# ============================================================
# 伴考后端 · D64 甲 积分账本心脏（2026-09-11 用户拍板）
# 积分=资产：进=注册赠送+每日签到（充值已砍，在线支付随 D51 押后），出=对话消耗。
# 汇率 1 积分 = 100 tokens，锚在基准脑 deepseek-flash 上；其他型号按
# llm.py 的 MODEL_MULTIPLIER 折算——贵模型烧真钱多、扣分多（差别计费）。
# 余额不存列、只从 points_ledger 流水加总导出（usage_logs 同立场：审计可复算）。
# 本文件是「钱规矩」的唯一真源：改价/改赠送=动下面几行常量，业务代码零动。
# import 方向纪律：points 只依赖 llm/models（下层），谁都不许倒挂进来。
# ============================================================
from datetime import date, timedelta
from math import ceil

from sqlalchemy import func, select

from backend.llm import multiplier_of
from backend.models import PointsLedger

# ── 全部桌牌一处立齐（2026-09-11 用户拍板；真金白银上线前可再校）──
TOKENS_PER_POINT = 100    # 汇率：1 积分 = 100 tokens（基准脑口径）
SIGNUP_BONUS = 1000       # 注册开池：新手礼 1000 分（≈10 万 tokens 的免费额度体感）
CHECKIN_GRANT = 200       # 每日签到：+200 分（≈2 万 tokens，日常轻聊够用一天）
STREAK_DAYS = 7           # 连签里程碑天数
STREAK_BONUS = 100        # 连签恰满 7 天那天加奖（第 8 天起不再加，断签重新攒——「+1 次」不循环）
LOW_BALANCE_WARN = 50     # 侧栏卡红字告警线：余额 ≤ 此数提个醒（闸拦人之前先自收着）

POINTS_EMPTY_MSG = "积分用完啦——去侧栏「每日签到」领今天的口粮，就能继续聊～"


def cost_points(tokens: int, model: str | None) -> int:
    """把一轮烧掉的 tokens 换算成扣分明细（真金白银腿的算盘）：
    ceil 向上取整——烧了 1 token 也不装免费；倍率听 llm.py 花名册隔壁那张表。"""
    if tokens <= 0:
        return 0
    return ceil(tokens / TOKENS_PER_POINT * multiplier_of(model))


def balance_of(session, user_id: int) -> int:
    """余额唯一来源：流水加总（可负——后账式：开口前查 >0 放行，烧穿扣成负、下一句才拦）。
    一分子都没有的户=0 分（拒聊人话由调用方说，本函数只报账）。"""
    return session.scalar(
        select(func.coalesce(func.sum(PointsLedger.amount), 0))
        .where(PointsLedger.user_id == user_id)) or 0


def today_spent(session, user_id: int) -> int:
    """今日已消耗多少积分（侧栏卡展示用，回正数）。"""
    neg = session.scalar(
        select(func.coalesce(func.sum(PointsLedger.amount), 0))
        .where(PointsLedger.user_id == user_id,
               PointsLedger.kind == "consume",
               PointsLedger.day == date.today())) or 0
    return -neg


def award(session, user_id: int, kind: str, amount: int, note: str | None = None,
          day: date | None = None) -> PointsLedger:
    """进账共核（注册礼/签到/连签奖/户主发放全走这一扇门）：
    只 add 行不 commit——由调用方同事务签发（开户与开池同生共死，不留「有号无礼」悬账）。"""
    row = PointsLedger(user_id=user_id, day=day or date.today(),
                       kind=kind, amount=amount, note=note)
    session.add(row)
    return row


def spend(session, user_id: int, tokens: int, model: str | None,
          day: date | None = None) -> int:
    """消耗落账（answer_turn 与流式尾记账处调用，与 usage_logs 流水同 commit）：
    凭据行写清型号/倍率/tokens——将来对账不用翻模型猜。返回本轮扣分数。"""
    cost = cost_points(tokens, model)
    if cost <= 0:
        return 0
    session.add(PointsLedger(user_id=user_id, day=day or date.today(), kind="consume",
                             amount=-cost,
                             note=f"消耗 · {model or '默认'} ×{multiplier_of(model):g} · {tokens} tokens"))
    return cost


def streak_of(session, user_id: int, today: date | None = None) -> tuple[int, bool]:
    """(连签天数, 今天签没签)——连签不存列、从 checkin 流水回溯重算（单一真源：
    少一个可被写歪的状态位）。起点：今天签了从今天往回串，没签从昨天往回串
    （「连签 3 天，今天还没签」的提示语据此能算对）。"""
    today = today or date.today()
    days = {r[0] for r in session.execute(
        select(PointsLedger.day).where(
            PointsLedger.user_id == user_id, PointsLedger.kind == "checkin",
            PointsLedger.day <= today)).all()}
    signed_today = today in days
    cur = today if signed_today else today - timedelta(days=1)
    streak = 0
    while cur in days:
        streak += 1
        cur -= timedelta(days=1)
    return streak, signed_today


def checkin(session, user_id: int) -> dict:
    """每日签端正身：幂等闸（今日已有 checkin 行即拒，一秒连点两次也只领一份）→
    落 +200 → 连签恰满 7 天再落 +100（奖在 streak 行，账目分得清哪笔是什么）。
    只 add 不 commit——路由层签发（响应里的余额才准）。"""
    today = date.today()
    already = session.scalar(
        select(func.count()).select_from(PointsLedger)
        .where(PointsLedger.user_id == user_id,
               PointsLedger.kind == "checkin",
               PointsLedger.day == today)) or 0
    if already:
        return {"ok": False, "granted": 0, "streak": 0}
    award(session, user_id, "checkin", CHECKIN_GRANT, "每日签到", today)
    session.flush()   # 让 streak_of 看得见刚落进行（今天的份要算进串里）
    streak, _ = streak_of(session, user_id, today)
    granted = CHECKIN_GRANT
    if streak == STREAK_DAYS:   # 恰满：只在第 7 天加奖一次，第 8 天起不加（见常量注）
        award(session, user_id, "streak", STREAK_BONUS, f"连签满 {STREAK_DAYS} 天奖励", today)
        granted += STREAK_BONUS
    return {"ok": True, "granted": granted, "streak": streak}
