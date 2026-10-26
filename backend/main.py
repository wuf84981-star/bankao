# ============================================================
# 伴考后端 · 第一个真身（S1 骨架版）
# 现在只做两件事：证明自己活着（health）、把话原样弹回来（echo）
# S2 阶段这里会长出 function-call 循环，换成真脑子。
# ============================================================
import hashlib
import io
import json
import os
import re
import secrets
import smtplib
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.dialects.postgresql import to_tsvector

from backend.analytics import _track
from backend.auth import create_token, get_current_user, hash_password, verify_password
from backend.chunking import chunk_text
from backend.db import SessionLocal
from backend.jobs import scheduler, start_jobs
from backend.llm import DEFAULT_MODEL, MODEL_PLATFORM, chat_stream, key_ok, multiplier_of
from backend.mail import send_mail
from backend.models import (AnalyticsEvent, Chunk, Conversation, EmailCode,
                            Material, Message, PointsLedger, QQBinding, UsageLog, User)
from backend.orchestrator import (IMAGE_BUDGET_24H, DAILY_QUOTA, MAX_TOOL_ROUNDS,
                                  _get_or_create_conv, _image_budget, _system_for,
                                  answer_turn, image_turn)
from backend.parsing import parse_docx, parse_pdf, parse_text
from backend.points import (LOW_BALANCE_WARN, POINTS_EMPTY_MSG, SIGNUP_BONUS,
                            TOKENS_PER_POINT, award, balance_of, checkin as points_checkin,
                            spend, streak_of, today_spent)
from backend.qq import binding_for_user, gen_bind_code
from backend.search import search
from backend.short_memory import note_message, window_get, with_summary
from backend.teaching_track import teaching_eligible, teaching_events
from backend.tools import (MASTERY_LEVELS, cited_by_reply, model_for, run_tool,
                           tools_for)
from backend.zh_tokenizer import ts_input

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """开机挂调度器（S6 首刀 · D21 甲：进程内 APScheduler）——现编制表两单：
    03:00 清到期事件 + 每 5 分钟提醒派发；yield 后优雅收尾，测试/重启不留僵尸线程。
    调度器之前先补户主旗号：env 配了 BANKAO_ADMIN_EMAIL 而老户已存在（首刀抢跑的），
    幂等 UPDATE 一句抬上户主——不用删号重练。"""
    admin_email = _admin_email_from_env()
    if admin_email:
        with SessionLocal() as session:
            session.execute(User.__table__.update()
                            .where(User.email == admin_email)
                            .values(is_admin=True))
            session.commit()
    start_jobs()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="伴考 API", lifespan=lifespan)   # app 就是"接客总机"，所有路由都登记在它身上

# 跨域放行：前端 dev 在 5173、后端在 8000——浏览器规定"不同源"的调用
# 要先验通行证（CORS 预检）。开发期只放行本机前端这两个门牌；上云后收紧。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class EchoIn(BaseModel):
    """回声接口的入参契约：必须带 message 字段，否则 FastAPI 直接拒收 422"""
    message: str


# ---- 验证码腿常量（S8 首刀 · F-01 · 参数全 PRD 钉死，不发明） ----
CODE_TTL_MIN = 10          # 码 10 分钟过期
CODE_MAX_FAIL = 5          # 错 5 次作废重发
CODE_MAX_DAY = 10          # 单邮箱日限 10 条（AC①防轰炸）
CODE_COOLDOWN_SEC = 60     # 重发冷却（异常支「60s 后可重发」的正边）


def _clean_email(v: str) -> str:
    v = v.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
        raise ValueError("邮箱格式不对")
    return v


def _code_hash(email: str, code: str) -> str:
    """码不存明文：sha256(邮箱|码)——库被兜走，码也不裸奔（同密码 bcrypt 一个理由）"""
    return hashlib.sha256(f"{email}|{code}".encode("utf-8")).hexdigest()


# 邀请码字母表：剔掉 0/O、1/I 这类电话里说不清的易混形（S6 绑定码同款运维课）

def _admin_email_from_env() -> str:
    """户主旗号的根：.env 的 BANKAO_ADMIN_EMAIL（值不进对话/git），没配=谁都不是户主"""
    return os.environ.get("BANKAO_ADMIN_EMAIL", "").strip().lower()


def _check_password_strength(v: str) -> str:
    """PRD F-01 验收②：≥8 位且含字母含数字——注册与找回改密一本账规矩（D48 复用）"""
    if len(v) < 8 or not any(c.isdigit() for c in v) or not any(c.isalpha() for c in v):
        raise ValueError("密码需≥8位且同时包含字母和数字")
    return v


def _issue_code(s, email: str, purpose: str, subject: str, body: str) -> None:
    """发码共核（D48 找回腿第二用——注册/找回一套纪律，闸不抄第二份防漂移）：
    日限 → 60s 冷却 → 旧未用码作废 → 新码哈希进账 → 寄信（寄失败回滚零留账，
    日限额不被失败白吃）。账目按 purpose 各算各的（一邮箱两本限）。
    调用方负责成功后的 commit；闸内一切不合格当场 HTTPException。"""
    utc_now = datetime.now(timezone.utc)
    day_start = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = s.scalar(select(func.count()).select_from(EmailCode)
                     .where(EmailCode.email == email, EmailCode.purpose == purpose,
                            EmailCode.created_at >= day_start)) or 0
    if today >= CODE_MAX_DAY:
        raise HTTPException(status_code=429, detail="这个邮箱今天收码次数用完了，明天再来或换个邮箱")
    latest = s.scalar(select(EmailCode)
                      .where(EmailCode.email == email, EmailCode.purpose == purpose)
                      .order_by(EmailCode.id.desc()).limit(1))
    if latest is not None and utc_now - latest.created_at < timedelta(seconds=CODE_COOLDOWN_SEC):
        raise HTTPException(status_code=429, detail="刚发过了，等一分钟再发")
    # 新码出生即作废旧未用码（QQ 绑定码换绑同款规矩：一邮箱一 purpose 同时只活一条）
    for r in s.scalars(select(EmailCode).where(
            EmailCode.email == email, EmailCode.purpose == purpose,
            EmailCode.used_at.is_(None))).all():
        r.used_at = utc_now
    code = f"{secrets.randbelow(1000000):06d}"
    s.add(EmailCode(email=email, purpose=purpose, code_hash=_code_hash(email, code),
                    expires_at=utc_now + timedelta(minutes=CODE_TTL_MIN)))
    s.flush()   # 先进账再寄信；寄炸了 rollback 一并收回
    try:
        send_mail(email, subject, body.format(code=code, ttl=CODE_TTL_MIN))
    except smtplib.SMTPRecipientsRefused:
        # 邮局确认过：收件邮箱查无此号——信封写错，不是邮差罢工（真机 550 案换来的分话术）
        s.rollback()
        raise HTTPException(status_code=400,
                            detail="这个邮箱似乎不存在，对方服务器退了信——检查地址拼写再发一次")
    except Exception as e:
        s.rollback()
        raise HTTPException(status_code=503,
                            detail=f"邮件寄不出去（邮件腿没配好或 SMTP 故障）：{str(e)[:120]}")


def _pass_code_gates(s, email: str, purpose: str, code: str) -> EmailCode:
    """验证码三闸（有活码/没过期/哈希对，错满 5 次作废）——注册与找回共用：
    失败不白烧码（错满除外），全对也不在此盖消费章，留给调用方与建号/改密同一笔事务。"""
    utc_now = datetime.now(timezone.utc)
    row = s.scalar(select(EmailCode).where(
        EmailCode.email == email, EmailCode.purpose == purpose,
        EmailCode.used_at.is_(None)).order_by(EmailCode.id.desc()).limit(1))
    if row is None:
        raise HTTPException(status_code=400,
                            detail="没有可用的验证码（没发过、用过了或错满作废了），请重新发送")
    if row.expires_at < utc_now:
        row.used_at = utc_now          # 过期码盖章烧掉，不留悬账
        s.commit()
        raise HTTPException(status_code=400, detail="验证码已过期，重新发一条")
    if _code_hash(email, code.strip()) != row.code_hash:
        row.fail_count += 1
        burned = row.fail_count >= CODE_MAX_FAIL
        if burned:
            row.used_at = utc_now      # 错满 5 次当场作废（PRD 异常支）
        s.commit()
        raise HTTPException(status_code=400, detail="验证码不对" + (
            "，这条已作废，请重新发送" if burned
            else f"，还能再试 {CODE_MAX_FAIL - row.fail_count} 次"))
    return row


class CodeSendIn(BaseModel):
    """送码入参：只要邮箱。码永不在响应里露（回执只有到期分钟数）"""
    email: str

    @field_validator("email")
    @classmethod
    def email_rule(cls, v: str) -> str:
        return _clean_email(v)


class RegisterIn(BaseModel):
    """注册契约（D54 全拆邀请码 2026-09-10：F-04 退役，邮箱+验证码+密码三样齐即建号）。
    username 暂沿用邮箱串（S1 惯例，「独立用户名」欠账挂账）。"""
    username: str
    password: str
    email: str
    code: str

    @field_validator("password")
    @classmethod
    def password_rule(cls, v: str) -> str:
        return _check_password_strength(v)

    @field_validator("email")
    @classmethod
    def email_rule(cls, v: str) -> str:
        return _clean_email(v)


class LoginIn(BaseModel):
    """登录契约：只验格式不验强度（老密码可能不符合新规，照样得让人进门）"""
    username: str
    password: str


class ResetSendIn(BaseModel):
    """找回第一步入参：只要邮箱（回执只有到期分钟数，码永不露）"""
    email: str

    @field_validator("email")
    @classmethod
    def email_rule(cls, v: str) -> str:
        return _clean_email(v)


class ResetConfirmIn(BaseModel):
    """找回第二步入参：邮箱+重置码+新密码（强度与注册一本账）"""
    email: str
    code: str
    new_password: str

    @field_validator("email")
    @classmethod
    def email_rule(cls, v: str) -> str:
        return _clean_email(v)

    @field_validator("new_password")
    @classmethod
    def pwd_rule(cls, v: str) -> str:
        return _check_password_strength(v)


@app.get("/api/health")
def health():
    """存活探针：大门(S1 later)和人都靠它确认后端 breathable"""
    return {"status": "ok"}


@app.post("/api/register/send-code")
def register_send_code(body: CodeSendIn):
    """发码（F-01 · D52 甲）：已注册 409；四闸走共核 _issue_code——
    注册与找回共用一套闸纪律，不抄第二份防漂移（改了这忘改那=定时炸弹）。"""
    email = body.email
    with SessionLocal() as s:
        dup = s.scalar(select(User).where((User.email == email) | (User.username == email)))
        if dup is not None:
            raise HTTPException(status_code=409, detail="该邮箱已注册，去登录页直接登")
        _issue_code(s, email, "register", "伴考注册验证码",
                    "你的验证码是 {code}，{ttl} 分钟内有效。别把码转告任何人。")
        s.commit()
    return {"ok": True, "expires_in_min": CODE_TTL_MIN}


@app.post("/api/register")
def register(body: RegisterIn):
    """注册=验码放行（F-01 · D54 全拆邀请码）：查重不烧码 → 码过三闸走共核
    _pass_code_gates → 建号同事务盖码消费章 → 当场发证。没验证过邮箱的号根本生不出来——
    AC④「未验证不可登录」靠结构兑现，不靠登录时补查。"""
    utc_now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        if session.scalar(select(User).where(User.username == body.username)):
            raise HTTPException(status_code=409, detail="用户名已被占用")
        if session.scalar(select(User).where(User.email == body.email)):
            raise HTTPException(status_code=409, detail="该邮箱已注册，去登录页直接登")
        row = _pass_code_gates(session, body.email, "register", body.code)
        user = User(username=body.username, password_hash=hash_password(body.password),
                    email=body.email,
                    is_admin=bool(_admin_email_from_env()) and
                             body.email == _admin_email_from_env())   # 户主旗号：env 对上才盖
        session.add(user)
        session.flush()   # D64：先领自增 id——开池礼与建号同事务，不留「有号无礼」的悬账
        award(session, user.id, "bonus", SIGNUP_BONUS, "注册新手礼")   # D64 开池：1 分=100 tokens 的见面礼
        row.used_at = utc_now              # 一码一用：建号与盖章同一笔事务
        session.commit()
        session.refresh(user)   # commit 后回读自增 id
        _track(user.id, "sign_up_completed", channel="web")   # D55 埋点（首刀挂账在此回补）
        return {"token": create_token(user.id), "username": user.username}


# ---------- 找回密码（D48 甲 · 2026-09-10 拍：重发验证码式，purpose='reset' 列首刀预建今天用） ----------

@app.post("/api/reset/send-code")
def reset_send_code(body: ResetSendIn):
    """找回第一步：查无此户 400（不发信不烧钱），有户走共核 _issue_code 寄重置码。
    户口用 email|username 双条件找——老壳 email 列空但用户名就是邮箱串（S1 惯例），
    只查 email 会把老户锁在门外。"""
    email = body.email
    with SessionLocal() as s:
        user = s.scalar(select(User).where((User.email == email) | (User.username == email)))
        if user is None:
            raise HTTPException(status_code=400, detail="这个邮箱还没在伴考注册，查无此户")
        _issue_code(s, email, "reset", "伴考重置密码验证码",
                    "你的验证码是 {code}，{ttl} 分钟内有效。如果不是你本人申请重置，请忽略这封信。")
        s.commit()
    return {"ok": True, "expires_in_min": CODE_TTL_MIN}


@app.post("/api/reset/confirm")
def reset_confirm(body: ResetConfirmIn):
    """找回第二步：码过三闸（共核）→ 换密码哈希与盖码消费章同一笔事务——
    要么都成要么都不成，没有「码烧了密没改」的悬账。
    边界备案：改密不吊销已发 token（JWT 无状态，旧票到期前仍有效）——
    要「强制下线」得另造黑名单账，挂账未做。"""
    utc_now = datetime.now(timezone.utc)
    email = body.email
    with SessionLocal() as s:
        user = s.scalar(select(User).where((User.email == email) | (User.username == email)))
        if user is None:
            raise HTTPException(status_code=400, detail="这个邮箱还没在伴考注册，查无此户")
        row = _pass_code_gates(s, email, "reset", body.code)
        user.password_hash = hash_password(body.new_password)
        row.used_at = utc_now              # 一码一用：改密与盖章同一笔事务
        s.commit()
        _track(user.id, "password_reset_completed")   # D55 埋点：找回闭环最后一步
    return {"ok": True}


# ---------- 管理页（D49 甲户主钥匙在岗；D54 2026-09-10：F-04 邀请码整体退役，
# 码账三端点随拆，本页只剩用户清单） ----------

def _require_admin(user: User) -> None:
    """户主闸：非旗号户一律 403——钥匙形状 D49 甲，认票不认脸"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="管理页只认户主——你的号没这面旗")


@app.get("/api/admin/users")
def admin_user_list(user: User = Depends(get_current_user)):
    """用户清单（原 D53 验收⑤，D54 后为管理页独苗）：全体注册户。
    来源列随邀请码退役——全天下只剩「邮箱注册」一种来源，无需再区分。"""
    _require_admin(user)
    with SessionLocal() as session:
        users = session.scalars(select(User).order_by(User.id)).all()
        bals = dict(session.execute(                      # D64：余额全从流水加总，一条聚合查齐
            select(PointsLedger.user_id, func.sum(PointsLedger.amount))
            .group_by(PointsLedger.user_id)).all())
        return {"items": [{
            "id": u.id, "username": u.username, "email": u.email,
            "is_admin": u.is_admin,
            "balance": bals.get(u.id, 0),   # D64 钱包列：没账的户=0（老户注册礼补发归户主 adjust）
            "created_at": u.created_at.isoformat() if u.created_at else None,
        } for u in users]}


@app.get("/api/admin/gaps")
def admin_gaps(user: User = Depends(get_current_user)):
    """S9·W3 知识缺口清单：用户问了、讲义答不上/只擦边的题——户主补弹药的本子。
    kind 两档：zero=查无（top_score 空）、weak=擦边（低于登记线 GAP_WEAK）。
    只翻最近 50 笔，按时间倒序（ix_knowledge_gaps_user_created 同向）。"""
    _require_admin(user)
    from backend.gaps import GAP_WEAK
    with SessionLocal() as session:
        rows = session.execute(text(
            "SELECT g.id, g.user_id, u.username, g.question, g.top_score, "
            "g.channel, g.created_at "
            "FROM knowledge_gaps g LEFT JOIN users u ON u.id = g.user_id "
            "ORDER BY g.created_at DESC LIMIT 50")).all()
    return {"items": [{
        "id": r[0], "user_id": r[1], "username": r[2], "question": r[3],
        "top_score": r[4], "channel": r[5],
        "kind": "zero" if r[4] is None else ("weak" if r[4] < GAP_WEAK else ""),
        "created_at": r[6].isoformat() if r[6] else None,
    } for r in rows]}


@app.get("/api/admin/stats")
def admin_stats(user: User = Depends(get_current_user)):
    """用量面板（D55 甲 · PRD 十一章）：event 逐项计数+最近发生时间，
    外加「近 7 天开口户数 / 总户数」——周活跃主料。只聚合不吐明细行，
    账本上的 props 原样不上页（隐私口径的第二道：页上也只给数不给事）。"""
    _require_admin(user)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    with SessionLocal() as session:
        rows = session.execute(
            select(AnalyticsEvent.event, func.count(), func.max(AnalyticsEvent.created_at))
            .group_by(AnalyticsEvent.event)
            .order_by(func.count().desc())
        ).all()
        weekly_active = session.scalar(
            select(func.count(func.distinct(AnalyticsEvent.user_id)))
            .where(AnalyticsEvent.event == "chat_message_sent",
                   AnalyticsEvent.created_at >= week_ago)
        ) or 0
        total_users = session.scalar(select(func.count(User.id))) or 0
    return {
        "events": [{
            "event": e, "count": c,
            "last_at": t.isoformat() if t else None,
        } for e, c, t in rows],
        "weekly_active": weekly_active,
        "total_users": total_users,
    }


class PointsAdjustIn(BaseModel):
    user_id: int
    amount: int
    note: str | None = None


@app.post("/api/admin/points/adjust")
def admin_points_adjust(body: PointsAdjustIn, user: User = Depends(get_current_user)):
    """D64 户主手动发放/扣减：也走 points_ledger 这扇门（kind=adjust）——
    没有「后台直改数字」的第二扇门，每一笔发放都留痕可审计（余额永远是流水加总）。
    老户（开池制前注册的）没吃过注册礼，户主可在此补发。"""
    _require_admin(user)
    if body.amount == 0:
        raise HTTPException(422, "调整数得是非零整数：正数加、负数减")
    with SessionLocal() as session:
        if session.get(User, body.user_id) is None:
            raise HTTPException(404, "查无此户")
        award(session, body.user_id, "adjust", body.amount,
              (body.note or "").strip() or "户主手动调整")
        session.commit()
        bal = balance_of(session, body.user_id)   # 同上家法：先签后读，回执余额才含本笔
    return {"user_id": body.user_id, "balance": bal}


@app.post("/api/login")
def login(body: LoginIn):
    """登录=验票发证：用户名错/密码错回同一句 401，不泄露"哪一半错了" """
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == body.username))
        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="用户名或密码不正确")
        _track(user.id, "login_completed", channel="web")   # D55 埋点：进门动作
        return {"token": create_token(user.id), "username": user.username}


@app.get("/api/me")
def me(user: User = Depends(get_current_user)):
    """验票窗口：告诉我"我是谁"——前端接上后靠它确认登录态（S8 二刀起带户主旗号，
    侧栏「管理」入口认这个位）"""
    return {"username": user.username, "is_admin": user.is_admin}


@app.get("/api/quota")
def quota(user: User = Depends(get_current_user)):
    """配额窗口：今日已用/剩余——侧栏额度卡的数从此有真源（补 F-35① 的显示半截）"""
    with SessionLocal() as session:
        spent = session.scalar(
            select(func.sum(UsageLog.tokens))
            .where(UsageLog.user_id == user.id, UsageLog.day == date.today())
        ) or 0
    return {"spent": spent, "remaining": max(DAILY_QUOTA - spent, 0), "limit": DAILY_QUOTA}


# ── D64 甲 2026-09-11（积分=资产，充值已砍、在线支付随 D51 押后）：钱包读数 + 每日签到 ──

@app.get("/api/points")
def points_wallet(user: User = Depends(get_current_user)):
    """积分口袋：余额=流水加总、今日已耗、签到态——侧栏积分卡数字的唯一真源。"""
    with SessionLocal() as session:
        bal = balance_of(session, user.id)
        spent_pt = today_spent(session, user.id)
        streak, signed = streak_of(session, user.id)
    return {"balance": bal, "today_spent": spent_pt, "streak": streak,
            "checked_in_today": signed, "warn": bal <= LOW_BALANCE_WARN,
            "tokens_per_point": TOKENS_PER_POINT}


@app.post("/api/checkin")
def checkin_api(user: User = Depends(get_current_user)):
    """每日签到：幂等闸在 points.checkin()（一秒连点也只领一份）——
    今日已签回 409 人话；成功回口粮明细（含连签奖与最新余额）。"""
    with SessionLocal() as session:
        out = points_checkin(session, user.id)
        if not out["ok"]:
            raise HTTPException(409, "今天的签到已经领过啦，明天再来～")
        session.commit()
        # 家法 autoflush=False：余额必须 commit 之后再读——先读会把刚落账的口粮读瞎
        bal = balance_of(session, user.id)
    _track(user.id, "checkin_done", channel="web")   # D55 埋点：签到也是活跃信号
    return {"granted": out["granted"], "streak": out["streak"], "balance": bal}


class WebSearchIn(BaseModel):
    enabled: bool


@app.get("/api/settings/websearch")
def get_websearch(user: User = Depends(get_current_user)):
    """D58 联网开关读数：无行=从没开过=关（默认关写进数据，不靠 prompt 自觉）。"""
    with SessionLocal() as session:
        val = session.scalar(text(
            "SELECT web_search_enabled FROM agent_settings WHERE user_id = :u"),
            {"u": user.id})
    return {"enabled": bool(val)}


@app.post("/api/settings/websearch")
def set_websearch(body: WebSearchIn, user: User = Depends(get_current_user)):
    """D58 联网开关落账：开=零命中时 note 引导模型调 web_search；关=web_search
    压根不进 schema（模型无从举手），与旧版行为逐字相同。upsert 照命名系统家法。"""
    with SessionLocal() as session:
        updated = session.execute(text(
            "UPDATE agent_settings SET web_search_enabled = :v WHERE user_id = :u"),
            {"v": body.enabled, "u": user.id}).rowcount
        if not updated:
            session.execute(text(
                "INSERT INTO agent_settings (user_id, web_search_enabled) VALUES (:u, :v)"),
                {"u": user.id, "v": body.enabled})
        session.commit()
    return {"enabled": body.enabled}


class TeachingModeIn(BaseModel):
    enabled: bool


@app.get("/api/settings/teaching")
def get_teaching(user: User = Depends(get_current_user)):
    """D81 挂招牌刀：教学轨用户开关读数——无行/NULL=从没动过=开
    （默认档与 teaching_track.user_teaching_on 同一判据，两处不许打架）。"""
    with SessionLocal() as session:
        val = session.scalar(text(
            "SELECT teaching_mode FROM agent_settings WHERE user_id = :u"),
            {"u": user.id})
    return {"enabled": val is not False}


@app.post("/api/settings/teaching")
def set_teaching(body: TeachingModeIn, user: User = Depends(get_current_user)):
    """D81 挂招牌刀：教学轨用户开关落账。关=本户考点问题全走事务轨直答
    （行为回到 S9 上教学图之前）；env 总闸仍是运维一票，用户闸只裁自己。
    upsert 照命名系统家法。"""
    with SessionLocal() as session:
        updated = session.execute(text(
            "UPDATE agent_settings SET teaching_mode = :v WHERE user_id = :u"),
            {"v": body.enabled, "u": user.id}).rowcount
        if not updated:
            session.execute(text(
                "INSERT INTO agent_settings (user_id, teaching_mode) VALUES (:u, :v)"),
                {"u": user.id, "v": body.enabled})
        session.commit()
    return {"enabled": body.enabled}


@app.get("/api/settings/feynman")
def get_feynman(user: User = Depends(get_current_user)):
    """D89 费曼加招：意愿闸读数——无行/NULL=从没动过=开
    （默认档与 teaching_track.user_feynman_on 同一判据，两处不许打架）。"""
    with SessionLocal() as session:
        val = session.scalar(text(
            "SELECT feynman_mode FROM agent_settings WHERE user_id = :u"),
            {"u": user.id})
    return {"enabled": val is not False}


@app.post("/api/settings/feynman")
def set_feynman(body: TeachingModeIn, user: User = Depends(get_current_user)):
    """D89：费曼开关落账（body 形与 teaching 同款 {enabled}，复用不重抄）。
    关=教学轨里不用「你讲我听」这招；大门（teaching_mode）关了本闸无从生效。
    upsert 照命名系统家法。"""
    with SessionLocal() as session:
        updated = session.execute(text(
            "UPDATE agent_settings SET feynman_mode = :v WHERE user_id = :u"),
            {"v": body.enabled, "u": user.id}).rowcount
        if not updated:
            session.execute(text(
                "INSERT INTO agent_settings (user_id, feynman_mode) VALUES (:u, :v)"),
                {"u": user.id, "v": body.enabled})
        session.commit()
    return {"enabled": body.enabled}


class ModelIn(BaseModel):
    model: str


@app.get("/api/settings/model")
def get_model(user: User = Depends(get_current_user)):
    """D60 花名册+可用性+当前选模：没钥匙的平台照列（available=false，前端灰显），
    用户配齐 .env 重建容器后自动点亮——清单是真源，不是藏掖。"""
    with SessionLocal() as session:
        cur = model_for(session, user.id)
    return {"current": cur, "default": DEFAULT_MODEL,
            "models": [{"id": m, "platform": MODEL_PLATFORM[m], "available": key_ok(m),
                        "multiplier": multiplier_of(m)}   # D64：换脑子时看见的就是费率
                       for m in MODEL_PLATFORM]}


@app.post("/api/settings/model")
def set_model(body: ModelIn, user: User = Depends(get_current_user)):
    """D60 选模落账：认花名册+平台有钥匙才收（拒脏账在后端，菜单灰显只是体贴）。
    下次开口即换新脑子——网页/QQ/流式/出题判分全线同源（都查这一本账）。"""
    m = body.model.strip()
    if m not in MODEL_PLATFORM:
        raise HTTPException(422, "这个型号不在花名册里——下拉菜单里挑一个")
    if not key_ok(m):
        raise HTTPException(422, "该平台还没配钥匙（.env 补对应 KEY 并重建容器后才能选它，"
                                 "或先换回已点亮的型号）")
    with SessionLocal() as session:
        updated = session.execute(text(
            "UPDATE agent_settings SET model_choice = :v WHERE user_id = :u"),
            {"v": m, "u": user.id}).rowcount
        if not updated:
            session.execute(text(
                "INSERT INTO agent_settings (user_id, model_choice) VALUES (:u, :v)"),
                {"u": user.id, "v": m})
        session.commit()
    return {"model": m}


# D61 甲 2026-09-11（设置页人设接真腿）：命名/人设/自定义描述/提醒时点一页四账，
# 与聊天口 set_agent_name、set_remind_time 写的是同列——两路一本账，页面所见即真相。
PERSONAS = {"strict", "senior", "buddy", "custom"}   # 前端四张卡的值（PRD 3.1 F-07）


class ProfileIn(BaseModel):
    name: str | None = None
    persona: str | None = None
    custom_prompt: str | None = None
    remind_time: str | None = None


@app.get("/api/settings/profile")
def get_profile(user: User = Depends(get_current_user)):
    """无行=全是默认：人设读侧兜 senior（与 _system_for 同规则，两处不打架）。"""
    with SessionLocal() as session:
        row = session.execute(text(
            "SELECT agent_name, persona, custom_prompt, remind_time "
            "FROM agent_settings WHERE user_id = :u"), {"u": user.id}).first()
    return {"name": row[0] if row else None,
            "persona": (row[1] if row and row[1] else "senior"),
            "custom_prompt": row[2] if row else None,
            "remind_time": row[3] if row else None}


@app.post("/api/settings/profile")
def set_profile(body: ProfileIn, user: User = Depends(get_current_user)):
    """字段级可选：None=这格没改（不碰账）；空串=清空该项（写 NULL）。
    校验拦在落账前——脏名、野人设、怪时间都进不了库。"""
    cols: dict[str, object] = {}
    if body.name is not None:
        nm = body.name.strip()
        if len(nm) > 8:
            raise HTTPException(422, "教练名字最长 8 个字")
        cols["agent_name"] = nm or None
    if body.persona is not None:
        if body.persona not in PERSONAS:
            raise HTTPException(422, "人设只有四种：严师 / 学长学姐 / 搭子 / 自定义")
        cols["persona"] = body.persona
    if body.custom_prompt is not None:
        cp = body.custom_prompt.strip()
        if len(cp) > 500:
            raise HTTPException(422, "自定义描述最长 500 字")
        cols["custom_prompt"] = cp or None
    if body.remind_time is not None:
        rt = body.remind_time.strip()
        if rt and not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", rt):
            raise HTTPException(422, "提醒时点要 HH:MM 形状，比如 19:30")
        cols["remind_time"] = rt or None
    if not cols:
        raise HTTPException(422, "没有要保存的内容")
    with SessionLocal() as session:
        sets = ", ".join(f"{k} = :{k}" for k in cols)   # 列名出自函数内常量，非用户串
        n = session.execute(text(
            f"UPDATE agent_settings SET {sets} WHERE user_id = :u"),
            {**cols, "u": user.id}).rowcount
        if not n:
            keys = ", ".join(cols)
            vals = ", ".join(f":{k}" for k in cols)
            session.execute(text(
                f"INSERT INTO agent_settings (user_id, {keys}) VALUES (:u, {vals})"),
                {**cols, "u": user.id})
        session.commit()
    return get_profile(user)


@app.post("/api/qq/bind-code")
def qq_bind_code(user: User = Depends(get_current_user)):
    """发起 QQ 绑定（D27 甲：账号安全级动作只长网页这只手——QQ 端只有递码的份）：
    发 6 位码，10 分钟有效，去 QQ 发给伴考即通；重发即换绑（旧码旧 QQ 同时作废）。"""
    with SessionLocal() as session:
        code = gen_bind_code(session, user.id)
    return {"code": code, "expires_min": 10}


@app.get("/api/qq/binding")
def qq_binding(user: User = Depends(get_current_user)):
    """绑定状态窗口：前端按钮据此显示「已绑 xxxxx」或「绑定/换绑 QQ」。
    pending 且码还活着时一并回码——刷新页面不丢刚拿到的码。
    D65：三态统一带 bot_number（加好友指路的号，读 env BOT_QQ，没配=None 前端藏指路块）——
    号码只在后端账上记一处，前端不抄第二份死字符串（写死的状态声明必过期）。"""
    bot_qq = os.environ.get("BOT_QQ") or None
    with SessionLocal() as session:
        b = binding_for_user(session, user.id)
        if b:
            return {"status": "bound", "qq_number": b.qq_number, "bot_number": bot_qq}
        p = session.scalar(select(QQBinding).where(
            QQBinding.user_id == user.id, QQBinding.status == "pending"))
        if p and p.code_expires_at and p.code_expires_at > datetime.now(timezone.utc):
            return {"status": "pending", "code": p.bind_code, "bot_number": bot_qq}
        return {"status": "none", "qq_number": None, "bot_number": bot_qq}


@app.get("/api/history")
def history(user: User = Depends(get_current_user), limit: int = 100,
            conv_id: int | None = None, before_id: int | None = None):
    """回显窗口（S3 插曲 · S6 三刀修串道）：最近**网页**会话的消息正序递回——
    前端挂页渲染，刷新不丢对话。QQ 会话出现后必须按 channel 过滤，
    否则网页历史会捞到 QQ 那头的对话（两渠道各走各的道，PRD 14.6）。
    五刀（F-08）：带 conv_id 定点读指定线。不命中（别人的/编的/QQ 线）一律回空窗
    ——不 404，免得这接口变成探测别人会话 id 存在性的探针。
    六刀（用户真机反馈「切会话等太久」）：带 before_id 往回翻页——多取一行当探针
    判「还有更早页」，响应每行带 id（前端稳定 key+游标都靠它）。limit 默认 100 原样，
    旧调用零影响。七刀：缺省落线改「最后活跃线」（同侧栏尺子），响应带 conv_id。"""
    with SessionLocal() as session:
        if conv_id is not None:
            # D56 甲：定点「看」放行 QQ 线（本户行仍是票闸；只读由前端执法，
            # 发送腿照旧只认 web 线——看与写的闸门各管各的）
            conv = session.scalar(
                select(Conversation).where(
                    Conversation.id == conv_id,
                    Conversation.user_id == user.id,
                    Conversation.channel.in_(("web", "qq"))))
            cid = conv.id if conv else None
        else:
            # 七刀（用户真机「刷新没回到在聊的线」）：缺省落线=最后活跃线。
            # 排序三级：①空线让位（用户心智：没开口的「新会话」还不算对话，
            # 不许堵门——实测新线 updated_at 能晚于老线最后发言，光比时间会翻车）
            # ②有货线里比最后活动时间（有消息看消息时间、空线看 updated_at，
            # 同侧栏尺子）③平局看 id。不再按最大 id 落线。
            cid = session.execute(text(
                "SELECT c.id FROM conversations c "
                "WHERE c.user_id = :u AND c.channel = 'web' "
                "ORDER BY EXISTS (SELECT 1 FROM messages m "
                "                  WHERE m.conversation_id = c.id) DESC, "
                "         COALESCE((SELECT max(m.created_at) FROM messages m "
                "                   WHERE m.conversation_id = c.id), c.updated_at) DESC, "
                "         c.id DESC LIMIT 1"), {"u": user.id}).scalar()
        if cid is None:
            return {"messages": [], "has_more": False, "conv_id": None}
        q = select(Message).where(Message.conversation_id == cid)
        if before_id is not None:
            q = q.where(Message.id < before_id)
        rows = list(session.scalars(
            q.order_by(Message.id.desc()).limit(limit + 1)   # 多取一行探尾，不改 count 查询
        ).all())
    has_more = len(rows) > limit
    rows = rows[:limit][::-1]   # 探针行先扔再倒转（超出的那行是更旧的，砍头）
    return {"messages": [{"id": r.id, "role": r.role, "text": r.content,
                          "citations": r.citations} for r in rows],
            "has_more": has_more, "conv_id": cid}   # 七刀：带回落线号，前端回填后发送不串道


MAX_PDF_BYTES = 50 * 1024 * 1024   # PRD F-19 验收②：单文件 ≤50MB（用户级总容量 500MB 归管理页 S7）

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/data/uploads")   # 原件仓库（D5 甲案：compose 挂 ./data/uploads）


def _extract(data: bytes, name: str) -> tuple[str, int | None]:
    """字节流→干净文本的公用件（parse/ingest 两边共用的验伤台）：
    .pdf=印刷指令单交 PyMuPDF 重放（回页数）；.txt/.md=字符流解码即用（无页可数，pages=None）；
    .docx=python-docx 读段落+表格（pages=None——Word 的「页」是排版算出来的，不可靠不硬凑）。
    坏文件从这抛 415/422 人话，调用方不用各自写护栏。"""
    low = name.lower()
    if low.endswith(".pdf"):
        try:
            text, pages = parse_pdf(data)
        except Exception:
            # 加密、损坏、假 PDF（改名的别的文件）全从这漏出来——回人话不回栈
            raise HTTPException(status_code=422, detail="PDF 读不动：可能加密或已损坏")
        return text, pages
    if low.endswith((".txt", ".md")):
        return parse_text(data), None   # 解码自带三级容错，进得来就出得去，不炸
    if low.endswith(".docx"):
        try:
            return parse_docx(data), None
        except Exception:
            # .doc 老二进制改名骗闸、加密 docx、半截 zip 全走这条人话
            raise HTTPException(status_code=422, detail="Word 读不动：可能加密、损坏，或是 2007 前的老 .doc（另存为 .docx 再传）")
    raise HTTPException(status_code=415, detail="本刀接 PDF/TXT/MD/Word 四种：图片、网页链接等后续刀再装")


@app.post("/api/parse")
async def parse(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """解析窗口（S3 边 A→P）：纯体检窗口收文件 → 回页数/字数/切块数/前 600 字预览。
    不落库——入库是 /api/ingest 的活；留着它，排障时能分清"读不动"还是"存不进"。
    护栏：验票（Depends）→ 大小 → 后缀分流 → PDF 读不动（后三道搬进 _extract 公用）。"""
    data = await file.read()   # UploadFile 是流：整只吞进内存（≤50MB 护栏兜底）
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 50MB 上限（PRD F-19）")
    text, pages = _extract(data, file.filename or "")
    result = {"chars": len(text), "chunks": len(chunk_text(text)), "preview": text[:600]}
    if pages is not None:
        result["pages"] = pages
    return result


@app.post("/api/ingest")
async def ingest(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """入库窗口（S3 边 E→V · D4/D5 甲案）：解析→切块→原件落盘→双表写。
    两段式入库的存字半段：chunks 以 embed_status=pending 入仓、坐标列留空——
    存字不要 key，点火刀（配齐 key 后扫 pending 回填）再来清 embedding 那笔账。
    快速失败不留行：413/415/422 全发生在落库之前，materials 里只见成功者
    （parse_status 的 failed 态留给将来的异步解析/点火回填失败写）。"""
    data = await file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 50MB 上限（PRD F-19）")
    name = file.filename or "untitled"
    text, pages = _extract(data, name)          # 先验伤：坏文件不配占户口
    chunks = chunk_text(text)
    with SessionLocal() as session:
        m = Material(user_id=user.id, title=name, storage_path="",
                     file_type=Path(name).suffix.lstrip(".").lower() or "bin",
                     parse_status="parsing")
        session.add(m)
        session.flush()   # 先领自增 id——落盘路径以它为名（echo 领 id 同款形状）
        # 原件落盘：uploads/{user_id}/{材料id}_{清洗后文件名}；清洗掉 / \ 等防路径穿越
        safe = re.sub(r"[^\w.\-]+", "_", name)[-80:]
        path = Path(UPLOAD_DIR) / str(user.id) / f"{m.id}_{safe}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)   # 先落盘再 commit：commit 炸了只多一只孤儿文件，行不会指向空头
        m.storage_path = str(path)
        m.parse_status = "ready"
        for seq, c in enumerate(chunks):
            # S9：分词在入库这一跳就做掉（jieba 在本进程，与向量点火同套家法——
            # 分词权在代码侧，DB 只存结果）。为什么必须在这做、不能等点火刀：
            # content_tsv 空着的块在分词腿里等于不存在，新传的资料会「传了却搜不到」，
            # 直到谁跑一次回填为止。点火刀只管 embedding，两笔账各走各的时机。
            # to_tsvector('simple', 分词串)：PG 侧只按空白切词项、不二次分词，
            # 词边界是 jieba 定的——'simple' 配置不做中文分词，这正是我们要的。
            tok = ts_input(c)
            session.add(Chunk(material_id=m.id, user_id=user.id, seq=seq,
                              content=c, token_count=len(c),
                              content_tokenized=tok or None,
                              content_tsv=to_tsvector(tok, language="simple") if tok else None))
        session.commit()   # 户口+原件+K 块一个事务：同生共死（原子性第四次当法）
        mid = m.id
    result = {"material_id": mid, "status": "ready",
              "chars": len(text), "chunks": len(chunks)}
    if pages is not None:
        result["pages"] = pages
    return result


@app.get("/api/materials")
def materials_api(user: User = Depends(get_current_user)):
    """资料真账列表（八刀 D46 甲——用户真机戳穿页面钉着三条演示假卡）：
    本户材料按入库倒序，行带块数/已点火坐标数——点火没点火一眼对账。
    大小读磁盘真值（表里没存 size 列，stat 一把比加列迁移便宜）；
    原件丢失（磁盘被手清等）size 回 None，前端显「—」，不编造重量。"""
    with SessionLocal() as session:
        rows = session.execute(text(
            "SELECT m.id, m.title, m.exam_type, m.parse_status, m.parse_error, "
            "       m.storage_path, "
            "       (SELECT count(*) FROM chunks c WHERE c.material_id = m.id) AS n_chunks, "
            "       (SELECT count(*) FROM chunks c WHERE c.material_id = m.id "
            "        AND c.embedding IS NOT NULL) AS n_vec "
            "FROM materials m WHERE m.user_id = :u ORDER BY m.id DESC"),
            {"u": user.id}).all()
    out = []
    for r in rows:
        try:
            size = Path(r.storage_path).stat().st_size if r.storage_path else None
        except OSError:
            size = None
        out.append({"id": r.id, "title": r.title,
                    "exam": r.exam_type or "通用",
                    "size": size, "status": r.parse_status,
                    "reason": r.parse_error,
                    "chunks": r.n_chunks, "vectors": r.n_vec})
    return {"materials": out}


# ── 记忆页真账三面（S7 九刀 · D47 甲：用户真机戳穿整页 INITIAL 道具）──

class FactIn(BaseModel):
    """确认/遗忘的入参形状：fact id 单/多皆可。"""
    id: int | None = None
    ids: list[int] = []


@app.get("/api/memories")
def memories_api(user: User = Depends(get_current_user)):
    """五本账聚合成展示形状（页签数字=真条数）：
    profile=考试档案+已确认事实；pending=未确认推测（BR-02 的门面）；
    kp=节点带掌握度小票；error=错误模式（含已克服旗）；event=时效事件。
    id 加表前缀防串页（m 前缀行才有确认/删除按钮，剥 m 交票）。"""
    out: list[dict] = []
    with SessionLocal() as session:
        for r in session.execute(text(
            "SELECT id, exam_type, exam_date, target_desc, is_primary "
            "FROM exam_profiles WHERE user_id = :u "
            "ORDER BY is_primary DESC, id"), {"u": user.id}).all():
            t = f"{r.exam_type} · 考试日 {r.exam_date}"
            if r.target_desc:
                t += f"——{r.target_desc}"
            out.append({"id": f"p{r.id}", "cat": "profile", "text": t,
                        "source": "明确",
                        "meta": "主考档案" if r.is_primary else "辅考",
                        # D87：结构化档案票——编辑框填名字/日期用真值，不拆 text 拼串
                        "pf": {"pid": r.id, "name": r.exam_type,
                               "date": str(r.exam_date)}})
        for r in session.execute(text(
            "SELECT id, category, key, content, confirmed FROM memory_facts "
            "WHERE user_id = :u ORDER BY confirmed, id"), {"u": user.id}).all():
            out.append({"id": f"m{r.id}",
                        "cat": "pending" if not r.confirmed else "profile",
                        "text": r.content,
                        "source": "推测" if not r.confirmed else "明确",
                        "meta": None if r.confirmed
                              else f"[{r.category}] {r.key} · 确认后生效（BR-02）"})
        for r in session.execute(text(
            "SELECT k.id, k.name, "
            "(SELECT string_agg(m.level || '（置信 ' || m.confidence || '）', '；') "
            " FROM knowledge_mastery m WHERE m.kp_ref = k.id) AS ms, "
            # D85：结构化进度票——页面改档要拿 mastery 真 id，text 那串给人看、
            # msj 这列给按钮用（一列两职必打架，各给各的）
            "(SELECT json_agg(json_build_object('mid', m.id, 'level', m.level, "
            " 'exam', m.exam_type) ORDER BY m.id) "
            " FROM knowledge_mastery m WHERE m.kp_ref = k.id) AS msj "
            "FROM knowledge_nodes k WHERE k.user_id = :u "
            "ORDER BY k.id"), {"u": user.id}).all():
            out.append({"id": f"k{r.id}", "cat": "kp",
                        "text": f"{r.name}：{r.ms}" if r.ms else f"{r.name}（还没进度账）",
                        "source": "明确", "meta": None, "ms": r.msj or []})
        for r in session.execute(text(
            "SELECT id, category, description, count, resolved FROM error_patterns "
            "WHERE user_id = :u ORDER BY resolved, id"), {"u": user.id}).all():
            out.append({"id": f"x{r.id}", "cat": "error", "text": r.description,
                        "source": "明确",
                        "meta": f"[{r.category}] 错题账沉淀 {r.count} 次"
                                + (" · 已克服" if r.resolved else "")})
        for r in session.execute(text(
            "SELECT id, content, start_at, end_at FROM life_events "
            "WHERE user_id = :u ORDER BY id"), {"u": user.id}).all():
            out.append({"id": f"e{r.id}", "cat": "event", "text": r.content,
                        "source": "明确",
                        "meta": f"到期 · {r.end_at} 自动消失（BR-03）"})
    return {"memories": out}


@app.post("/api/memories/confirm")
def memory_confirm_api(body: FactIn, user: User = Depends(get_current_user)):
    """网页版 BR-02 确认=升格翻列：inferred→user_stated + confirmed=true，
    与模型侧「用户亲口确认后同 key 重存」落账效果等价。
    只收本户行；不中回 404 人话（不报「是谁的」）。"""
    if body.id is None:
        raise HTTPException(422, detail="要确认哪条——得给条目号")
    with SessionLocal() as session:
        got = session.execute(text(
            "UPDATE memory_facts SET confirmed = true, source = 'user_stated', "
            "updated_at = now() WHERE id = :i AND user_id = :u "
            "RETURNING id"), {"i": body.id, "u": user.id}).scalar()
        session.commit()
    if got is None:
        raise HTTPException(404, detail="这条记忆不存在或不是你的")
    return {"confirmed": got}


@app.post("/api/memories/forget")
def memory_forget_api(body: FactIn, user: User = Depends(get_current_user)):
    """网页版 BR-07 遗忘：物理 DELETE——tools.forget_memory 的 HTTP 孪生，
    不问模型、不得拒绝；票闸只删本户行，混进别人的 id 静默出局（回执只数真删的）。"""
    if not body.ids:
        return {"deleted": []}
    q = text("DELETE FROM memory_facts WHERE user_id = :u AND id IN :ids "
             "RETURNING id").bindparams(bindparam("ids", expanding=True))
    with SessionLocal() as session:
        deleted = session.execute(q, {"u": user.id, "ids": body.ids}).scalars().all()
        session.commit()
    return {"deleted": list(deleted)}


@app.get("/api/search")
def search_api(q: str, user: User = Depends(get_current_user), top_k: int = 5):
    """检索调试窗口（S3 边 V→A）：问句 → 两腿捞料 RRF 合议 → 回 top-k 块。
    引用作答刀接进 chat 前，先用这只眼睛看清"捞得对不对"——
    块文、双腿名次、降级人话全透明，出 bug 分得清是捞错还是喂坏。"""
    with SessionLocal() as session:
        return search(session, q, user.id, top_k=min(max(top_k, 1), 20))


@app.get("/api/chunks/{chunk_id}")
def chunk_api(chunk_id: int, user: User = Depends(get_current_user)):
    """引用小票溯源（真机反馈「第 23 块，哪里的 23 块」）：凭 id 取回那块讲义原文。
    只读腿不碰检索；结构闸照旧家法——user_id 不是本户一律「查无此块」，
    别人的块存在与否都不向你泄密。"""
    with SessionLocal() as session:
        row = session.execute(
            select(Chunk.id, Chunk.material_id, Chunk.seq, Chunk.content,
                   Material.title)
            .join(Material, Chunk.material_id == Material.id)
            .where(Chunk.id == chunk_id, Chunk.user_id == user.id)
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="这块不在你名下（查无此块）")
    return {"chunk_id": row.id, "material_id": row.material_id, "seq": row.seq,
            "title": row.title, "content": row.content}


@app.post("/api/echo")
def echo(body: EchoIn, user: User = Depends(get_current_user)):
    """回声：先验通行证再办事，两句对话记在真用户名下（demo 户口退役）"""
    reply = body.message
    with SessionLocal() as session:
        conv = session.scalar(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.id.desc())
        )
        if conv is None:
            conv = Conversation(user_id=user.id, title="回声试线")
            session.add(conv)
            session.flush()   # 先领到自增 id，消息才有得挂
        session.add(Message(conversation_id=conv.id, role="user",
                            content=body.message, token_count=len(body.message)))
        session.add(Message(conversation_id=conv.id, role="assistant",
                            content=reply, token_count=len(reply)))
        session.commit()   # 一个事务：会话+两句消息同生共死——原子性本尊
    return {"reply": reply, "from": "bankao-backend", "saved": True, "username": user.username}


class ChatIn(BaseModel):
    """真聊天入参：形状照 EchoIn，换个脑子不换门面。
    conv_id（F-08 五刀）：可选定点票——指哪条会话聊哪条；None=随后端最近线。"""
    message: str
    conv_id: int | None = None


# SYSTEM_PROMPT 与组装器 _system_for 已于 S6 三刀搬去 backend/orchestrator.py
# ——网页腿与将来的 QQ 腿（bot 容器 import 复用）共用同一颗编排心脏。


def _sse(obj: dict) -> str:
    """把一个 dict 包成一条 SSE 事件（协议形状：data: JSON，结尾空一行）"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


# ── S7 五刀：会话历史管理（F-08 · PRD P0·Phase1 · D40/D41 甲）──
# 三面（列表/新建/删除）+ history 定点回显 + chat/stream/image 的 conv_id 透传。
# 地基早备好：conversations 无「一户一线」唯一约束、title/context_summary 预建列——
# 本刀只是开门。AC① 滚动摘要按 D41 甲挂账（等真实长会话当标本，不闭眼调参）。

def _conv_list(session, uid: int) -> list[dict]:
    """本户全部会话线（web+QQ，时间倒序）。排序键=该线最后一条消息的时间——
    坑在 updated_at 的 onupdate：插消息不动会话行，它根本不会跳，不信它。
    次键 id 与 history 缺省落线写死同一把尺子（平局不各选各）。
    D56 甲（2026-09-11 用户拍）：QQ 线也上架、行带 channel——渠道闸历来防的是
    「写入/缺省落线串道」，从今起只继续防写入，不再拦「看」。"""
    rows = session.execute(text(
        "SELECT c.id, c.title, c.channel, "
        "COALESCE((SELECT max(m.created_at) FROM messages m "
        "          WHERE m.conversation_id = c.id), c.updated_at) AS last_at, "
        "(SELECT m.content FROM messages m WHERE m.conversation_id = c.id "
        " AND m.role = 'user' ORDER BY m.id DESC LIMIT 1) AS preview "
        "FROM conversations c WHERE c.user_id = :u "
        "ORDER BY last_at DESC, c.id DESC"), {"u": uid}).all()
    return [{"id": r.id, "title": r.title, "channel": r.channel,
             "last_at": r.last_at.isoformat() if r.last_at else None,
             "preview": (r.preview or "")[:60]} for r in rows]


@app.get("/api/conversations")
def conversations_api(user: User = Depends(get_current_user)):
    with SessionLocal() as session:
        return {"conversations": _conv_list(session, user.id)}


@app.post("/api/conversations")
def conversation_new(user: User = Depends(get_current_user)):
    """新对话=插一行——_get_or_create_conv 取最近，新行即新主场；
    老线原地封存可回看（记忆/题目账本就不挂会话，天然不受影响）。"""
    with SessionLocal() as session:
        c = Conversation(user_id=user.id, channel="web", title="新会话")
        session.add(c)
        session.commit()
        return {"id": c.id, "title": c.title}


@app.delete("/api/conversations/{cid}")
def conversation_delete(cid: int, user: User = Depends(get_current_user)):
    """F-08 AC②：只删展示记录（messages 外键 CASCADE 跟走），记忆库/错题账一分不动。
    票闸=本户——D56 甲：自家 QQ 线也可删（看与删都是展示面动作，不碰渠道写入）；
    别人的行与编的行同答 404。"""
    with SessionLocal() as session:
        hit = session.execute(text(
            "DELETE FROM conversations WHERE id = :i AND user_id = :u "
            "RETURNING id"), {"i": cid, "u": user.id}).first()
        session.commit()
    if hit is None:
        raise HTTPException(status_code=404, detail="会话不存在或不是你的")
    return {"deleted": cid}


@app.post("/api/chat")
def chat(body: ChatIn, user: User = Depends(get_current_user)):
    """真脑子第一刀（S6 三刀起内脏搬进 orchestrator.answer_turn，QQ 腿共用同颗心）：
    本路由只剩翻译职责——err 字典换 HTTP 码，回执原样上菜。/api/echo 仍留对照组。"""
    with SessionLocal() as session:
        out = answer_turn(session, user.id, body.message, conv_id=body.conv_id)
        if "err" in out:
            raise HTTPException(
                status_code=429 if out["err"] in ("quota", "points")
                else 404 if out["err"] == "conv" else 502, detail=out["msg"])
    _track(user.id, "chat_message_sent", channel="web")   # D55 埋点：开口即活（周活跃主料）
    return {"reply": out["reply"], "from": "deepseek-chat", "saved": True,
            "username": user.username, "remaining": out["remaining"],
            "notice": out["notice"],
            "balance": out["balance"],   # D64：开口后的钱包余额（前端积分卡就地刷新）
            "used_tools": out["used_tools"],   # 本句动用过哪几只手——空列表=纯嘴答
            "citations": out["citations"],   # 结构化出处：正文 [N] 只是标注，账在这
            "conv_id": out["conv_id"]}   # 五刀：消息实际落在哪条线——前端拿它回填 activeConv


# ── S7 四刀：拍照汇报·网页入口（F-09 · D37 甲 · PRD 880 三重校验家规）──

MAX_IMAGE_BYTES = 10 * 1024 * 1024   # F-09① 单图 ≤10MB
_IMG_KINDS = {".png": ("png", "image/png"), ".jpg": ("jpeg", "image/jpeg"),
              ".jpeg": ("jpeg", "image/jpeg"), ".webp": ("webp", "image/webp")}


def _sniff_image(data: bytes, filename: str, mime: str):
    """三重校验纯函数（PRD 880）：扩展名/MIME/魔数三者**互相一致**才放行——
    改名的假图（把 exe 后缀改 .png）过不了魔数，声明 image/png 的 txt 过不了
    MIME↔魔数对齐。返回 (fmt, mime, None) 或 (None, http码, 人话)。"""
    ext = os.path.splitext(filename.lower())[1]
    if len(data) > MAX_IMAGE_BYTES:
        return None, 413, "单图超过 10MB 上限（F-09①）"
    if ext not in _IMG_KINDS:
        return None, 415, "拍照汇报收 png/jpg/jpeg/webp 四种，其余不接"
    fmt, want_mime = _IMG_KINDS[ext]
    magic = {"png": data[:8] == b"\x89PNG\r\n\x1a\n",
             "jpeg": data[:3] == b"\xff\xd8\xff",
             "webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP"}[fmt]
    if mime != want_mime or not magic:
        return None, 415, "扩展名/MIME/魔数对不上号——这不是它声称的那张图（PRD 880 三重校验）"
    return fmt, mime, None


def _strip_meta(data: bytes, fmt: str) -> bytes:
    """重编码剥 EXIF（PRD 880 隐私家规：照片元数据里的 GPS 一行都不许进仓库）。
    重编码顺手兼作「真可解码图」验尸——坏图死在 PIL open/load，OCR 通道不背这锅。"""
    from PIL import Image           # 首用 import：工具箱不为枕头拖重量
    im = Image.open(io.BytesIO(data))
    im.load()
    if fmt == "jpeg" and im.mode not in ("RGB", "L"):
        im = im.convert("RGB")      # JPEG 藏不住透明通道，alpha 就地剥离
    buf = io.BytesIO()
    im.save(buf, format={"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}[fmt])
    return buf.getvalue()


@app.post("/api/chat/image")
async def chat_image(file: UploadFile = File(...), text: str = Form(""),
                     conv_id: str = Form(""),
                     user: User = Depends(get_current_user)):
    """拍照汇报（F-09）：图+可选一句话 → 三道闸 → 剥敏落私有目录 → image_turn
    （OCR 转写→文本进大脑，原图永不进模型上下文——9.1 的代码化）。
    张数闸（24h ≤4）在 image_turn 内统一执法（QQ 腿同闸口），这里预检一次是为了
    **拦下的图不落盘**——先落盘再拒绝会留一堆无主孤儿文件。
    五刀：conv_id 表单参（FormData 无类型，字符串收、整数验）——空=随后端最近线。"""
    cid: int | None = None
    if conv_id.strip():
        if not conv_id.strip().isdigit():
            raise HTTPException(status_code=422, detail="会话编号得是数字")
        cid = int(conv_id.strip())
    data = await file.read()
    fmt, mime_or_code, err = _sniff_image(data, file.filename or "",
                                          file.content_type or "")
    if err:
        raise HTTPException(status_code=mime_or_code, detail=err)
    try:
        data = _strip_meta(data, fmt)
    except Exception:
        raise HTTPException(status_code=422, detail="图读不动：已损坏或不是真正的图片")
    with SessionLocal() as session:
        if _image_budget(session, user.id, "web") + 1 > IMAGE_BUDGET_24H:
            return {"reply": f"网页端 24 小时内最多收 {IMAGE_BUDGET_24H} 张照片，"
                             "先消化手头这几张，或直接用文字说～",
                    "saved": False, "rejected": "image_budget"}
        d = Path(UPLOAD_DIR) / "chat" / str(user.id)
        d.mkdir(parents=True, exist_ok=True)
        rel = f"chat/{user.id}/{uuid.uuid4().hex}.{fmt.replace('jpeg', 'jpg')}"
        (Path(UPLOAD_DIR) / rel).write_bytes(data)   # 随机名：防穿越也防互相踩
        out = image_turn(session, user.id, text=text, images=[{
            "data": data, "ref": {"kind": "file", "path": rel, "mime": mime_or_code,
                                  "size": len(data)}}], channel="web", conv_id=cid)
    if out.get("rejected") == "image_budget":
        # 竞态兜网：路由预检放行、门内闸拦下（同秒 QQ 腿又交一张）——
        # 该分支回执没有 conv_id 等账目键，原样转成与预检同形的拒绝
        return {"reply": out["reply"], "saved": False, "rejected": "image_budget"}
    if "err" in out:
        raise HTTPException(status_code=429 if out["err"] in ("quota", "points")
                            else 404 if out["err"] == "conv" else 502,
                            detail=out["msg"])
    _track(user.id, "chat_message_sent", channel="web", with_image=True)   # D55 埋点：带图开口
    return {"reply": out["reply"], "transcription": out.get("message"),
            "ocr": out.get("ocr"), "remaining": out["remaining"],
            "notice": out["notice"], "balance": out.get("balance"), "used_tools": out["used_tools"],
            "citations": out["citations"], "saved": True,
            "conv_id": out["conv_id"]}   # 五刀：前端拿它回填 activeConv


@app.post("/api/chat/stream")
def chat_stream_api(body: ChatIn, user: User = Depends(get_current_user)):
    """第四刀·流式（SSE）：边生成边回吐，前端打字机效果。
    查配额/取历史在进门时同步做完（429 等还能走正常 HTTP 拒绝），
    电厂循环+教练行落库进生成器；最终 reply 之外的中间轮次不转发 delta（防举手轮噪音）。
    D67 甲：用户行改随进门先落账——你说的话不该等教练回完才算说过
    （2026-09-12 断案：流中途被刷新掐死时收尾 commit 永不到站，问答整对蒸发；
    用户行不参与计费，先落不违 BR-11 记账原子性——教练行照旧流尾原子落）。
    /api/chat 原样保留当对照组：流式坏了退回整包模式排障。"""
    with SessionLocal() as session:
        today = date.today()
        spent = session.scalar(
            select(func.sum(UsageLog.tokens))
            .where(UsageLog.user_id == user.id, UsageLog.day == today)
        ) or 0
        if spent >= DAILY_QUOTA:
            raise HTTPException(status_code=429,
                                detail="今日 200 万 token 预算用完啦，明天零点自动回血～")
        if balance_of(session, user.id) <= 0:   # D64 积分闸：流式腿与 answer_turn 同闸同话术
            raise HTTPException(status_code=429, detail=POINTS_EMPTY_MSG)
        # 五刀（F-08）：conv_id 定点——编的/别人的/QQ 线一律 404，不开流不落账不烧电
        conv = _get_or_create_conv(session, user.id, conv_id=body.conv_id)
        if conv is None:
            raise HTTPException(status_code=404,
                                detail="这个会话不存在或不是你的——刷新侧栏重新选一个？")
        # S9·W6：取窗走热缓存腿；未命中回落原 PG select（行为逐字等于旧代码）。
        # 先取完历史再挂用户行——顺序反了会把本句重复喂给电厂
        history = window_get(session, conv.id)
        # D67 甲：用户行进门先落账（闸全过了才走到这，拒聊的句一个字不落）
        session.add(Message(conversation_id=conv.id, role="user",
                            content=body.message, token_count=len(body.message)))
        session.commit()   # 会话行+用户行先落定；教练行+流水+积分在流尾另一个 commit
        note_message(conv.id, "user", body.message)   # W6：进门句已落账就添窗（不等流尾）
    user_msg = body.message
    username = user.username
    user_id = user.id

    def events():
        # 工具专用会话：生成器活多久它活多久（外层的 with 早已关门，
        # search_materials 捞库得有活会话可用）；finally 保证弃疗也不漏账本把手
        tool_session = SessionLocal()
        ctx = {"user_id": user_id, "session": tool_session, "citations": []}
        try:
            # S9·W5 教学轨分叉（五关全 AND，任何失手一字不差回旧路；
            # 回滚旗 TEACHING_TRACK_ENABLED=0 → teaching_eligible 恒 False）
            if teaching_eligible(tool_session, user_id, user_msg):
                yield from teaching_events(user_id=user_id, username=username,
                                           user_msg=user_msg, conv=conv,
                                           history=history,
                                           tool_session=tool_session,
                                           today=today, spent=spent)
                return
            # 组上下文：system + 会话窗近20条 + 本句——与 /api/chat 完全同源
            msgs = [{"role": "system",
                     "content": with_summary(_system_for(user_id, tool_session), conv)}]
            msgs += history   # 纯 dict（W6 窗形状）直喂；教学轨拿的也是同一份
            msgs.append({"role": "user", "content": user_msg})
            ptok = ctok = 0
            used_tools: list[str] = []
            tools = tools_for(tool_session, user_id)   # D58：与 answer_turn 同一家法——开关定工具在场性
            model = model_for(tool_session, user_id)   # D60 选模；D64：扣分倍率按它折
            reply = ""
            try:
                for _ in range(MAX_TOOL_ROUNDS):
                    # 心跳帧（2026-09-12 断线案）：SSE 注释帧，前端解析只认 data: 行、
                    # 见不着它；但每一轮开跑前线上动一下，配合大门 300s 耐心，
                    # 「模型在想、工具在跑」的静默期不再被当成断线
                    yield ": ping\n\n"
                    call_msg: dict = {}
                    for ev in chat_stream(msgs, tools=tools, model=model):   # D60：本户选模随行
                        kind = ev[0]
                        if kind == "delta":
                            yield _sse({"delta": ev[1]})   # 字直接往浏览器转
                        else:
                            call_msg, p, c = ev[1], ev[2], ev[3]
                            ptok += p
                            ctok += c
                    msgs.append(call_msg)
                    if not call_msg.get("tool_calls"):
                        reply = call_msg["content"]
                        break
                    # 举手轮：静默执行工具，不向前端吐字（查资料这事不该演给用户看）
                    for tc in call_msg["tool_calls"]:
                        fn = tc["function"]
                        used_tools.append(fn["name"])
                        msgs.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": run_tool(fn["name"], fn["arguments"], ctx)})
                else:
                    yield _sse({"error": "模型连续调用工具未收敛，6 轮封顶已截断"})
                    return
            except Exception as e:
                # 流式腿留声（2026-09-12，与 orchestrator 同药方）：昨天 Qwen 404 悬案
                # 教做人——吞异常不吭声，排障全靠箱内重放。半句不落库的规矩不变，声必须留
                print(f"[chat_stream] 电厂故障 {type(e).__name__}: {str(e)[:280]}", flush=True)
                yield _sse({"error": "模型电厂暂时故障，稍后再试"})
                return   # 半句不落库（BR-11 对流式同样成立：走到这没记账就是没扣）
            # D82 甲（2026-10-18 用户拍板·事务轨补票闸）：票面以嘴为准，
            # 与教学轨同一函数——检索摆几块是供给，正文标几块才是承诺
            cited = cited_by_reply(ctx["citations"], reply)
            with SessionLocal() as session:
                # D67 甲：用户行已随进门落账，流尾只收教练行——别补第二份（同话落两遍就是双胎账）
                session.add(Message(conversation_id=conv.id, role="assistant",
                                    content=reply, token_count=ctok,
                                    citations=cited or None))   # 引用账落库
                session.add(UsageLog(user_id=user_id, day=today, tokens=ptok + ctok))
                cost = spend(session, user_id, ptok + ctok, model, today)   # D64：与 token 流水同笔事务
                session.commit()
                note_message(conv.id, "assistant", reply)   # W6：教练句落库添窗（写路只添不删）
                balance = balance_of(session, user_id)
            _track(user_id, "chat_message_sent", channel="web")   # D55 埋点：流式腿同账
            remaining = DAILY_QUOTA - spent - ptok - ctok
            notice = (f"积分余额只剩 {balance}——记得签到续口粮，省着点用"   # D64 资产命门优先播报
                      if balance <= LOW_BALANCE_WARN
                      else (f"今日剩余配额约 {max(remaining, 0)} token（不足 10%）"
                            if remaining < DAILY_QUOTA * 0.1 else None))
            yield _sse({"done": {"remaining": remaining, "notice": notice,
                                 "balance": balance, "points_spent": cost,
                                 "used_tools": used_tools, "username": username,
                                 "conv_id": conv.id,   # 五刀：前端回填 activeConv
                                 "citations": cited}})
        finally:
            tool_session.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )   # 最后一行是 Nginx 的通关令：关响应级缓冲，SSE 才不被大门扣到攒够才放行


# ============================================================
# D83 计划页换真（2026-10-18，用户拍板「乙」）：计划页四腿（三读一写）
# 真账 S5 就睡在库里（plans/plan_items；generate/activate/report_check_in
# 聊天腿全在用）——缺的只是网页这扇门。隔离老规矩：user_id 从登录票来
# 不从参数来；写腿票闸=query 形状照抄 report_check_in（本户 active 计划
# 才有资格），别人的/归档版的一律 404 不泄存在（/api/chunks 同法）。
# ============================================================

@app.get("/api/plan/summary")
def plan_summary(user: User = Depends(get_current_user)):
    """页头总账：主考档案（倒计时真值，治 42/87 打架案）+ 计划状态
    （active/draft 横幅）。主考=exam_profiles.is_primary（F-41 一主一辅）。"""
    with SessionLocal() as session:
        prof = session.execute(text(
            "SELECT exam_type, exam_date FROM exam_profiles "
            "WHERE user_id = :u AND is_primary LIMIT 1"),
            {"u": user.id}).first()
        exam = None if prof is None else {"name": prof.exam_type,
                                          "date": str(prof.exam_date)}
        active = draft = None
        if prof:
            a = session.execute(text(
                "SELECT id, version, start_date FROM plans "
                "WHERE user_id = :u AND exam_type = :e AND status = 'active'"),
                {"u": user.id, "e": prof.exam_type}).first()
            active = None if a is None else {
                "id": a.id, "version": a.version, "start_date": str(a.start_date)}
            d = session.execute(text(
                "SELECT p.id, p.version, count(i.id) AS n FROM plans p "
                "LEFT JOIN plan_items i ON i.plan_id = p.id "
                "WHERE p.user_id = :u AND p.exam_type = :e AND p.status = 'draft' "
                "GROUP BY p.id, p.version ORDER BY p.version DESC LIMIT 1"),
                {"u": user.id, "e": prof.exam_type}).first()
            draft = None if d is None else {
                "id": d.id, "version": d.version, "items": d.n}
    return {"exam": exam, "active": active, "draft": draft}


@app.get("/api/plan/calendar")
def plan_calendar(month: str, user: User = Depends(get_current_user)):
    """月账：active 计划逐日聚合（total/done）——格子色块与小圆点的数据源。
    month=YYYY-MM；partial 不算完成（页上诚实口径：勾了 done 才算）。
    无 active 计划=空账，格子全白，横幅另行指路激活。"""
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(status_code=400, detail="month 须是 YYYY-MM")
    with SessionLocal() as session:
        rows = session.execute(text(
            "SELECT i.date, count(*) AS total, "
            "       count(*) FILTER (WHERE i.status = 'done') AS done "
            "FROM plan_items i JOIN plans p ON p.id = i.plan_id "
            "WHERE i.user_id = :u AND p.status = 'active' "
            "  AND to_char(i.date, 'YYYY-MM') = :m "
            "GROUP BY i.date ORDER BY i.date"),
            {"u": user.id, "m": month}).all()
    return {"month": month,
            "days": [{"date": str(r.date), "total": r.total, "done": r.done}
                     for r in rows]}


@app.get("/api/plan/day")
def plan_day(date: str, user: User = Depends(get_current_user)):
    """某日详情：active 计划当日任务清单（带 status）——当日视图的腿。"""
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date 须是 YYYY-MM-DD")
    with SessionLocal() as session:
        rows = session.execute(text(
            "SELECT i.id, i.subject, i.task_desc, i.est_minutes, i.kind, i.status "
            "FROM plan_items i JOIN plans p ON p.id = i.plan_id "
            "WHERE i.user_id = :u AND i.date = :d AND p.status = 'active' "
            "ORDER BY i.id"),
            {"u": user.id, "d": d}).all()
    return {"date": date, "items": [
        {"id": r.id, "subject": r.subject, "task": r.task_desc,
         "est_minutes": r.est_minutes, "kind": r.kind, "status": r.status}
        for r in rows]}


class PlanCheckIn(BaseModel):
    done: bool


@app.post("/api/plan/item/{item_id}/check")
def plan_item_check(item_id: int, body: PlanCheckIn,
                    user: User = Depends(get_current_user)):
    """打卡的页面门（F-23 写腿第二扇门）：勾=done、回勾=pending。
    聊天腿的「完成是历史事实」管的是模型的手，不锁本人——误勾可撤。
    来源态限闸：勾只从 pending/partial 起（done 再勾=幂等报现账）；
    撤只从 done 起（partial 是口述账，页面不动它）。done_note 不抹：
    partial 升 done 保留原话，撤勾留痕归流水思维之外的最小改动。"""
    with SessionLocal() as session:
        row = session.execute(text(
            "SELECT i.status FROM plan_items i JOIN plans p ON p.id = i.plan_id "
            "WHERE i.id = :i AND i.user_id = :u AND p.status = 'active'"),
            {"i": item_id, "u": user.id}).first()
        if row is None:
            raise HTTPException(status_code=404, detail="这条不在你名下（查无此任务）")
        if body.done:
            if row.status in ("pending", "partial"):
                session.execute(text(
                    "UPDATE plan_items SET status = 'done', completed_at = now() "
                    "WHERE id = :i"), {"i": item_id})
                session.commit()
                return {"id": item_id, "status": "done"}
            return {"id": item_id, "status": row.status}
        if row.status == "done":
            session.execute(text(
                "UPDATE plan_items SET status = 'pending', completed_at = NULL "
                "WHERE id = :i"), {"i": item_id})
            session.commit()
            return {"id": item_id, "status": "pending"}
        return {"id": item_id, "status": row.status}


# ── 资料删除腿（D84，2026-10-18，兑现 PRD 1151 AC②「删除资料连带删除全部
#    chunks 与向量，不留孤儿索引」——承诺挂着一实现，这刀开门）──

@app.delete("/api/materials/{mid}")
def material_delete(mid: int, user: User = Depends(get_current_user)):
    """物理删（BR-07 同族家法：本人删自己的东西，不留尸不软删）。
    DELETE ... RETURNING 先拿正身与 storage_path——查无行一律 404 同一句话，
    别人的号与无主的号不分辨（/api/chunks 同款，不泄存在）；
    行删落账后才扫磁盘原件：扫不动就自吞（文件早被手清=磁盘真相，
    不为它拒账）——点火刀「commit 炸只多一只孤儿文件」的镜像：
    孤儿文件脏盘，不脏账。chunks（文字+向量+分词列）由表形 CASCADE 一次带走，
    AC②「不留孤儿索引」写死在 S3 的 FK 上，这里清账不用管向量腿。"""
    with SessionLocal() as s:
        row = s.execute(text(
            "DELETE FROM materials WHERE id = :i AND user_id = :u "
            "RETURNING storage_path"), {"i": mid, "u": user.id}).first()
        if row is None:
            raise HTTPException(status_code=404, detail="查无这份资料")
        s.commit()
        path = row.storage_path
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass   # 盘上扫不掉不拦账的腿
    return {"id": mid, "status": "deleted"}


# ── 记忆修改腿（D85，2026-10-18，F-13 P0 欠条兑现——AC②「页面编辑与指令
#    编辑等效落库」：聊天一句话改记忆 S4 就通，页面这扇门今天补上）──

class FactEdit(BaseModel):
    """事实条目就地改：只动 content（key/category 是账名与归属，改它们=换账，
    正门是「删掉旧的+聊天里说新的」，这里不开那个口子）。"""
    id: int
    content: str


@app.post("/api/memories/fact")
def memory_fact_edit_api(body: FactEdit, user: User = Depends(get_current_user)):
    """UPDATE content 并同翻升格列——你亲手改的字=你明确说的（BR-02 同 shape，
    与 confirm/模型侧重存三扇门落进同一本账）。空文/超长 422 拦在门口；
    查无行 404 与 confirm 同句式（不泄存在）。"""
    content = body.content.strip()
    if not content:
        raise HTTPException(422, detail="内容不能空着——要它消失请用「删掉」")
    if len(content) > 2000:
        raise HTTPException(422, detail="这条太长了——记忆条目限 2000 字以内")
    with SessionLocal() as s:
        got = s.execute(text(
            "UPDATE memory_facts SET content = :c, source = 'user_stated', "
            "confirmed = true, updated_at = now() "
            "WHERE id = :i AND user_id = :u RETURNING id"),
            {"c": content, "i": body.id, "u": user.id}).scalar()
        s.commit()
    if got is None:
        raise HTTPException(404, detail="这条记忆不存在或不是你的")
    return {"edited": got}


class MasteryEdit(BaseModel):
    id: int
    level: str


@app.post("/api/memories/mastery")
def memory_mastery_edit_api(body: MasteryEdit, user: User = Depends(get_current_user)):
    """掌握度页面换档：五档枚举与 tools.MASTERY_LEVELS 单源共账（不抄第二花名册）；
    越档 422。你页面上亲手点的档=亲口说的，confidence 钉满 100（user_stated 同族）；
    模型侧 update_mastery 的闸照旧，两扇门管的是同一本账。"""
    if body.level not in MASTERY_LEVELS:
        raise HTTPException(422, detail=f"档位只认 {'/'.join(MASTERY_LEVELS)}")
    with SessionLocal() as s:
        got = s.execute(text(
            "UPDATE knowledge_mastery SET level = :l, confidence = 100 "
            "WHERE id = :i AND user_id = :u RETURNING id"),
            {"l": body.level, "i": body.id, "u": user.id}).scalar()
        s.commit()
    if got is None:
        raise HTTPException(404, detail="这条进度账不存在或不是你的")
    return {"edited": got}


class ProfileEdit(BaseModel):
    """考试档案就地改（D87，用户拍板「我要的就是每一条都能改」）：只动
    exam_type/exam_date——主/辅角色是「换主考」的语义，正门在聊天腿
    （save_exam_profile 先降级再晋级），页面不开这道口子。"""
    id: int
    exam_type: str
    exam_date: str


@app.post("/api/memories/profile")
def memory_profile_edit_api(body: ProfileEdit, user: User = Depends(get_current_user)):
    """档案改名字/改日期落真账；日期格式闸在门口（假日期不落库——侧栏/日历/
    便利贴三处读同一真源，D83 治的三数打架病不许从这扇门复发）。
    **改日期的诚实账**：已排计划不会自动挪（PRD 143 重算链未建，挂账），
    回执里带 replan=true 时前端指路「跟教练说重排计划」。查无行 404 同族句式。"""
    name = body.exam_type.strip()
    if not name:
        raise HTTPException(422, detail="考试名字不能空着")
    if len(name) > 32:
        raise HTTPException(422, detail="考试名字限 32 字以内")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.exam_date.strip()):
        raise HTTPException(422, detail="日期得是 2026-11-25 这样的日子")
    try:
        new_date = date.fromisoformat(body.exam_date.strip())
    except ValueError:
        raise HTTPException(422, detail="这个日子不存在——查查收历再填")
    with SessionLocal() as s:
        row = s.execute(text(
            "SELECT exam_date FROM exam_profiles "
            "WHERE id = :i AND user_id = :u"),
            {"i": body.id, "u": user.id}).first()
        if row is None:
            raise HTTPException(404, detail="这份档案不存在或不是你的")
        replan = row.exam_date != new_date   # 只有日期真挪了才提重排
        if replan:
            got = s.execute(text(
                "UPDATE exam_profiles SET exam_type = :t, exam_date = :d "
                "WHERE id = :i AND user_id = :u RETURNING id"),
                {"t": name, "d": new_date, "i": body.id, "u": user.id}).scalar()
        else:
            got = s.execute(text(
                "UPDATE exam_profiles SET exam_type = :t "
                "WHERE id = :i AND user_id = :u RETURNING id"),
                {"t": name, "i": body.id, "u": user.id}).scalar()
        s.commit()
    return {"edited": got, "replan": replan}


@app.delete("/api/memories/profile/{pid}")
def memory_profile_delete_api(pid: int, user: User = Depends(get_current_user)):
    """D88 档案遗忘门：物理删（BR-07 同族）。全 models 表族实查过——没有任何表
    外键锚 exam_profiles（plans 只存 exam_type 文本冗余，注释钉「以档案表为准」），
    删行结构安全。唯一的语义雷=删掉主考后全户无主——剩余行（id 最小者）自动晋主，
    与聊天腿 save_exam_profile 的「先降级再晋级」同族，页门不许制造没主的悬案。
    查无行 404 同族句式（不泄存在）。"""
    with SessionLocal() as s:
        row = s.execute(text(
            "DELETE FROM exam_profiles WHERE id = :i AND user_id = :u "
            "RETURNING is_primary"), {"i": pid, "u": user.id}).first()
        if row is None:
            raise HTTPException(404, detail="这份档案不存在或不是你的")
        promoted = False
        if row.is_primary:
            nxt = s.execute(text(
                "SELECT id FROM exam_profiles WHERE user_id = :u "
                "ORDER BY id LIMIT 1"), {"u": user.id}).scalar()
            if nxt is not None:
                s.execute(text("UPDATE exam_profiles SET is_primary = true "
                               "WHERE id = :i"), {"i": nxt})
                promoted = True
        s.commit()
    return {"deleted": pid, "promoted": promoted}
