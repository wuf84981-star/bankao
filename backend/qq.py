# ============================================================
# 伴考后端 · S6 三刀：QQ 通道件（F-34 · D23/D26/D27 甲案）
# 这份是 bot 容器的「纸面半」：绑定闸与对话转接都在此，对话本体
# 走 orchestrator.answer_turn——QQ 腿与网页腿同一颗编排心脏、同一份配额账。
# D23 甲：箱（NoneBot2+NapCat，B 段才立）import 复用本文件，直调函数，
# 不跨箱架 HTTP——共库同进程，故障隔离靠的是「bot 炸了 api 箱无损」而不是接口墙。
# ============================================================
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from backend.analytics import _track
from backend.models import QQBinding
from backend.orchestrator import answer_turn, image_turn

CODE_TTL_MIN = 10    # PRD F-34 验收①：6 位码 10 分钟有效
MAX_FAIL = 3         # PRD F-34 验收①：连错 3 次作废

# ── 通道整形：Markdown 底稿 → QQ 纯文本（S6 真机：QQ 私聊不渲染 MD，星号原样糊脸）──
# 「账记原稿、嘴说人话」：会话账里存的仍是完整 Markdown（网页照常渲染），
# 只有发往 QQ 的出口经过这里。纯函数、零 token、幂等（纯文本进=原样出）。
_MD_PATTERNS = [
    (re.compile(r"^```.*$", re.M), ""),                          # 代码块围栏行整行去
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), "（图片）"),            # 图片：url 在 QQ 无意义
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r"\1：\2"),          # 链接 → 文字：url
    (re.compile(r"\*\*\*(.+?)\*\*\*"), r"\1"),                    # 粗斜体
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),                        # 粗体
    (re.compile(r"__(.+?)__"), r"\1"),                            # 粗体（下划线形）
    (re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)"), r"\1"),           # 斜体（\w 界在中文里全落空，改防误吃连续星号）
    (re.compile(r"~~(.+?)~~"), r"\1"),                            # 删除线
    (re.compile(r"`([^`\n]+)`"), r"\1"),                          # 行内代码
    (re.compile(r"^#{1,6}\s*", re.M), ""),                        # 标题井号
    (re.compile(r"^>\s?", re.M), ""),                             # 引用尖括号
    (re.compile(r"^(\s*)[-*+]\s+", re.M), r"\1· "),               # 无序列表 → ·
    (re.compile(r"^\s*\|?[\s:|-]*---[\s:|-]*\|?\s*$", re.M), ""), # 表格分隔行整行去
    (re.compile(r"\s*\|\s*"), "　"),                              # 表格竖线 → 全角空格
]


def to_plain(text: str) -> str:
    """发往 QQ 前的 Markdown 整形：剥语法符号、信息一字不丢。幂等。"""
    for pat, rep in _MD_PATTERNS:
        text = pat.sub(rep, text)
    return text


GUIDE = ("你还没和伴考账号绑定。打开伴考网页 → 侧栏点「绑定 QQ」拿一个 6 位码，"
         "10 分钟内发给我就通了。")   # 未绑路人的指引话术：纯代码模板，零 token


def gen_bind_code(session, user_id: int) -> str:
    """网页端发绑定码（D27 甲：账号安全级动作只有网页这只手发起，
    QQ 端只有递码的手）。重发=重置本户行：旧码作废、旧 QQ 清空、状态翻回
    pending——新码出生那一刻起旧绑定即失效（换绑形状，一人一 QQ）。"""
    code = f"{secrets.randbelow(1000000):06d}"
    b = session.scalar(select(QQBinding).where(QQBinding.user_id == user_id))
    if b is None:
        b = QQBinding(user_id=user_id)
        session.add(b)
    b.bind_code = code
    b.status = "pending"
    b.fail_count = 0
    b.qq_number = None       # 发码时不知道哪个 QQ 会来绑——QQ 号绑成那刻才写，unique 不空占
    b.code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MIN)
    b.bound_at = None
    session.commit()
    return code


def binding_for_user(session, user_id: int) -> QQBinding | None:
    """查本户**绑成了**的行（提醒推送腿的「有嘴可张」判据）。"""
    return session.scalar(select(QQBinding).where(
        QQBinding.user_id == user_id, QQBinding.status == "bound",
        QQBinding.qq_number.is_not(None)))


def handle_qq_event(session, qq_number: str, text: str, *, chat_fn=None,
                    images: list[dict] | None = None, ocr_fn=None) -> str:
    """QQ 侧消息总入口（B 段的 bot 收到私聊就调它，回话原样发回 QQ）：
    ①已绑 QQ → 对话走 answer_turn（channel='qq'——会话与网页分家，脑子与配额同源）；
      带图（S7 四刀 F-09 · D38 甲）→ 走 image_turn：图 url 直接喂 qwen-vl 转写、
      零下载零落盘（原图本就躺 Tencent 云上，二次落盘是假动作），张数闸与网页同口；
    ②未绑 + 恰 6 位数字 → 认码链（pending / 10 分钟 / 错 3 次作废 / 一号一主）；
    ③未绑 + 普通文本 → 指引话术（不配进模型：生面孔烧不了电厂的电，也不占配额——
      未绑户带图同样吃这条规矩，OCR 的钱一分离，脸没认之前不烧）。
    返回值就是要发回 QQ 的那句话。"""
    text = text.strip()
    now = datetime.now(timezone.utc)
    # 一号一主（PRD F-34②）：这 QQ 绑给谁，就跟谁说话——码校验挡在门外的只是不认得的脸
    b = session.scalar(select(QQBinding).where(
        QQBinding.qq_number == qq_number, QQBinding.status == "bound"))
    if b:
        if re.fullmatch(r"\d{6}", text):
            # 一号一主（PRD F-34②）：这 QQ 已有主，别人的码休想从这里拐走绑定——
            # 换绑的正确路径只在网页：原账号重新发码=旧绑定即刻失效，此后 QQ 才换新主。
            other = session.scalar(select(QQBinding).where(
                QQBinding.bind_code == text, QQBinding.status == "pending",
                QQBinding.user_id != b.user_id))
            if other:
                return "这个 QQ 已经绑定了别的伴考账号。换绑请到原账号的网页端操作。"
        if images:   # 认了脸才配烧 OCR 的钱（图与字拼一条消息进同一颗大脑）
            out = image_turn(session, b.user_id, text=text, images=images,
                             channel="qq", chat_fn=chat_fn, ocr_fn=ocr_fn)
            img = True
        else:
            out = answer_turn(session, b.user_id, text, channel="qq", chat_fn=chat_fn)
            img = False
        if "err" not in out:   # D55 埋点：QQ 腿开口也进同一本账，渠道分属性
            _track(b.user_id, "chat_message_sent", channel="qq", with_image=img)
        return out.get("reply") or out.get("msg", "出了点小状况，稍后再试。")
    if not re.fullmatch(r"\d{6}", text):
        return GUIDE
    b = session.scalar(select(QQBinding).where(
        QQBinding.bind_code == text, QQBinding.status == "pending"))
    if b and b.code_expires_at and b.code_expires_at < now:
        b.status = "invalid"
        b.bind_code = None
        session.commit()
        return "这个码过期啦（10 分钟有效）。回网页重新拿一个。"
    if b:
        b.qq_number = qq_number
        b.status = "bound"
        b.bind_code = None      # 一次性：绑成即清码，账上不留过期钥匙
        b.bound_at = now
        session.commit()
        return ("绑定成功！从现在起你跟我说的一切，都走你的伴考大脑——"
                "和网页端记得同一件事，也共用同一份每日配额。")
    # 码没对上：有活着的 pending 行就在「最近发的那行」记次错——错 3 次作废的秤。
    # （首刀简化：不做「谁的 QQ 试谁的码」的归属配对，误伤路径最坏是重拿一次码。）
    p = session.scalar(select(QQBinding).where(
        QQBinding.status == "pending").order_by(QQBinding.id.desc()))
    if p:
        p.fail_count += 1
        if p.fail_count >= MAX_FAIL:
            p.status = "invalid"
            p.bind_code = None
            session.commit()
            return "连续 3 次码不对，这个码作废了。请回网页重新获取。"
        session.commit()
    return "没认出的这个码。请核对网页上那 6 位数字，或者回网页重新拿一个。"


def push_via_onebot(qq_number: str, text: str) -> bool:
    """经 OneBot HTTP 推一条私聊（D26 甲「账是本、QQ 是嘴」的推送方）：
    环境没配（ONEBOT_API_URL 缺席）或任何故障（超时/拒收/断网）一律回 False 不抛——
    提醒本体已落会话账，QQ 这条腿只是补送达，绝不能反过来把提醒拖成失败。
    B 段接 NapCat 时配置：ONEBOT_API_URL / ONEBOT_API_TOKEN。"""
    url = os.environ.get("ONEBOT_API_URL", "")
    if not url:
        return False
    text = to_plain(text)   # 所有发 QQ 的路（聊天回话/提醒/补推）唯一收口：嘴说人话
    token = os.environ.get("ONEBOT_API_TOKEN", "")
    uid: object = int(qq_number) if qq_number.isdigit() else qq_number
    try:
        r = httpx.post(f"{url.rstrip('/')}/send_private_msg",
                       json={"user_id": uid, "message": text},
                       headers={"Authorization": f"Bearer {token}"} if token else {},
                       timeout=10)
        r.raise_for_status()
        data = r.json()
        # OneBot11 惯例：retcode==0 或 status in (ok, async) 都算收下
        return data.get("retcode") == 0 or data.get("status") in ("ok", "async")
    except Exception:
        return False
