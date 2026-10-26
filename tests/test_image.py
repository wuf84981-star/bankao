# ============================================================
# S7 四刀离线单测：拍照汇报（F-09 · D36~D39 甲）
# 断言主线：三重校验只放真图（改名假图/MIME 错位/越界全拦）；EXIF 剥净；
# image_turn 合成链（转写进大脑、原图不进上下文、运费独立入账）；
# 低置信程序执法（全不可读零电厂轮）；张数闸 24h≤4 拦在 OCR 之前（拒的图不烧钱不落账）；
# QQ 腿带图走同一颗 image_turn、未绑带图一毛钱不烧。
# 铁律：OCR 腿全程假件注入——真 qwen-vl 在测试里出现一次就是烧用户的钱。
# ============================================================
import io
from datetime import date

import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend.main import _sniff_image, _strip_meta
from backend.models import Conversation, Message
from backend.ocr import looks_unclear
from backend.orchestrator import IMAGE_BUDGET_24H, _image_budget, image_turn
from backend.qq import gen_bind_code, handle_qq_event
from test_qq import _chat   # 假电厂：(assistant, 10, 5)——复用免重造

# 各格式的最小真头（魔数部分），正文塞随机字节足够过纯函数
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"\x00" * 24


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_img_t', 'x', 'normal', now()) RETURNING id")).scalar()
        # D64 口粮：积分闸排在 OCR 运费之前——本册验图腿，先开池免得被闸外拦
        s.execute(text("INSERT INTO points_ledger (user_id, day, kind, amount, created_at) "
                       "VALUES (:u, current_date, 'bonus', 999999, now())"), {"u": u})
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})   # 级联带走一切
        s.commit()


def _ocr_fn(canned="第一题选 B，解析见材料第 3 页"):
    """假 OCR 腿：记每跳收到的 data/url，回 canned + 100+50 票运费。"""
    calls: list[dict] = []

    def fn(data=None, url=None):
        calls.append({"data": data, "url": url})
        return (canned, 100, 50)
    return fn, calls


# ── 三重校验与剥敏（main.py 纯函数段）──

def test_sniff_triple_gate():
    """正件放行；改名假图、MIME 错位、越界、不收格式各拦各的。"""
    assert _sniff_image(_PNG, "题.png", "image/png") == ("png", "image/png", None)
    assert _sniff_image(_JPG, "a.jpg", "image/jpeg")[0] == "jpeg"
    assert _sniff_image(_WEBP, "a.webp", "image/webp")[0] == "webp"
    # exe 改名 .png：后缀对、魔数不对 → 拦
    fmt, code, msg = _sniff_image(b"MZ\x90\x00" + b"\x00" * 32, "virus.png", "image/png")
    assert fmt is None and code == 415 and "三重校验" in msg
    # 真 png 但声明 jpeg：MIME↔魔数错位 → 拦
    assert _sniff_image(_PNG, "a.png", "image/jpeg")[1] == 415
    # gif 压根不收
    assert _sniff_image(_PNG, "a.gif", "image/png")[1] == 415
    # 越界：哪怕头是真的也先量斤两（413 在内容核对之前）
    assert _sniff_image(_PNG + b"\x00" * 10 * 1024 * 1024, "big.png", "image/png")[1] == 413


def test_strip_meta_removes_exif_and_rejects_garbage():
    """重编码剥 EXIF（PRD 880）：带元数据的真 jpeg 出去后账上干干净净；坏字节当场炸。"""
    from PIL import Image
    im = Image.new("RGB", (8, 8), (200, 30, 30))
    exif = im.getexif()
    exif[0x0112] = 6                       # Orientation：随便钉一个真实标签当证据
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)
    data = buf.getvalue()
    assert Image.open(io.BytesIO(data)).getexif()[0x0112] == 6   # 进场时确实带着
    out = _strip_meta(data, "jpeg")
    re_im = Image.open(io.BytesIO(out))
    assert re_im.format == "JPEG" and re_im.size == (8, 8)
    assert not dict(re_im.getexif()), "EXIF 没剥净"
    with pytest.raises(Exception):
        _strip_meta(b"not an image at all", "png")   # 路由靠这炸换 422 人话


def test_looks_unclear_program_gate():
    """低置信判定程序执法：空/【没看清】即不可信，正常转写放行。"""
    assert looks_unclear("") and looks_unclear("   ")
    assert looks_unclear("第二题【没看清】看不清题干")
    assert not looks_unclear("第三题选 C")


# ── image_turn 合成链（假 OCR + 假电厂）──

def test_image_turn_transcribes_and_books_freight(uid):
    """图+一句话：转写进合并消息、运费(150)先落账、大脑吃文本、回复照常回。"""
    fn, calls = _ocr_fn()
    ref = {"kind": "file", "path": f"chat/{uid}/t.png", "mime": "image/png", "size": 40}
    with SessionLocal() as s:
        out = image_turn(s, uid, text="这题我又栽了", images=[{"data": _PNG, "ref": ref}],
                         chat_fn=_chat, ocr_fn=fn)
        assert "收到" in out["reply"]
        assert "[拍照汇报·图转写1]" in out["message"] and "第一题选 B" in out["message"]
        assert "这题我又栽了" in out["message"]          # 用户的字排最前
        assert out["ocr"] == {"images": 1, "usable": 1}
        assert calls == [{"data": _PNG, "url": None}]    # 原图只到 ocr_fn 这一跳
        # 账：user 行存合并文本+image_refs；运费 150 + 电厂 15 同天入账
        row = s.execute(text(
            "SELECT content, image_refs FROM messages m JOIN conversations c "
            "ON m.conversation_id = c.id WHERE c.user_id = :u AND m.role = 'user'"),
            {"u": uid}).one()
        assert "拍照汇报" in row.content and "第一题选 B" in row.content
        assert row.image_refs[0]["kind"] == "file"      # web 账形：{kind:'file',…}
        assert s.scalar(text("SELECT sum(tokens) FROM usage_logs WHERE user_id = :u "
                             "AND day = :d"), {"u": uid, "d": date.today()}) == 165
        assert _image_budget(s, uid, "web") == 1


def test_image_turn_all_unclear_wakes_no_brain(uid):
    """全不可读且零文字：大脑一次都不叫醒，但图的事实进历史、引导话术出口。"""
    fn, _ = _ocr_fn("【没看清】")
    def never(msgs, tools=None):
        raise AssertionError("大脑不该被叫醒")
    with SessionLocal() as s:
        out = image_turn(s, uid, images=[{"data": _PNG}], chat_fn=never, ocr_fn=fn)
        assert "没看清" in out["reply"] and out["ocr"]["usable"] == 0
        assert s.scalar(text("SELECT count(*) FROM messages m JOIN conversations c "
                             "ON m.conversation_id = c.id WHERE c.user_id = :u "
                             "AND m.role = 'assistant'"), {"u": uid}) == 0
        # 运费照记——电是真烧了，没读出东西也不赖账
        assert s.scalar(text("SELECT sum(tokens) FROM usage_logs WHERE user_id = :u"),
                        {"u": uid}) == 150


def test_image_budget_gate_four_per_day(uid):
    """张数闸（AC① 24h ≤4）：第 4 张放行、第 5 张拦在 OCR 之前——拒的图零烧钱零落账。"""
    fn, calls = _ocr_fn()
    with SessionLocal() as s:
        conv = Conversation(user_id=uid, channel="web", title="闸测")
        s.add(conv)
        s.flush()
        for i in range(IMAGE_BUDGET_24H - 1):   # 垫 3 张有账的
            s.add(Message(conversation_id=conv.id, role="user", content=f"图{i}",
                          image_refs=[{"kind": "file", "path": f"chat/{uid}/x{i}.png"}]))
        s.commit()
        assert _image_budget(s, uid, "web") == 3
        out4 = image_turn(s, uid, images=[{"data": _PNG}], chat_fn=_chat, ocr_fn=fn)
        assert "收到" in out4["reply"] and len(calls) == 1   # 第 4 张走全链
        n_msgs = s.scalar(text("SELECT count(*) FROM messages WHERE conversation_id = :c"),
                          {"c": conv.id})
        out5 = image_turn(s, uid, images=[{"data": _PNG}], chat_fn=_chat, ocr_fn=fn)
        assert out5["rejected"] == "image_budget" and "4" in out5["reply"]
        assert len(calls) == 1                   # 第 5 张连 OCR 腿都没碰
        assert s.scalar(text("SELECT count(*) FROM messages WHERE conversation_id = :c"),
                        {"c": conv.id}) == n_msgs   # 拒的不记账
        # QQ 端分家：网页塞满不碍 QQ 腿收图（闸按端各算各的）
        assert _image_budget(s, uid, "qq") == 0


# ── QQ 腿接线（handle_qq_event 带图 → 同一颗 image_turn）──

def test_qq_bound_with_images_shares_brain(uid):
    """认了脸的 QQ 带图：url 直喂假 OCR 腿（零下载）、账落 qq 端。"""
    fn, calls = _ocr_fn()
    with SessionLocal() as s:
        code = gen_bind_code(s, uid)
        assert "绑定成功" in handle_qq_event(s, "70008", code)
        url = "http://qqcdn/pic.jpg"
        out = handle_qq_event(s, "70008", "帮我看看这道题",
                              images=[{"url": url, "ref": {"kind": "url", "url": url}}],
                              chat_fn=_chat, ocr_fn=fn)
        assert "收到" in out
        assert calls == [{"data": None, "url": url}]   # D38：url 直喂，零下载零落盘
        assert s.scalar(text(
            "SELECT count(*) FROM messages m JOIN conversations c "
            "ON m.conversation_id = c.id WHERE c.user_id = :u AND c.channel = 'qq' "
            "AND m.image_refs IS NOT NULL"), {"u": uid}) == 1


def test_qq_unbound_with_images_burns_nothing(uid):
    """未绑 + 带图：一毛 OCR 钱都不烧——脸没认之前，图和字同吃指引规矩。"""
    fn, calls = _ocr_fn()
    with SessionLocal() as s:
        out = handle_qq_event(s, "80009", "",
                              images=[{"url": "http://x/y.jpg",
                                       "ref": {"kind": "url", "url": "http://x/y.jpg"}}],
                              ocr_fn=fn)
        assert out.startswith("你还没和伴考账号绑定")
        assert calls == []
        assert s.scalar(text("SELECT count(*) FROM usage_logs WHERE user_id = :u"),
                        {"u": uid}) == 0   # 没烧电自然没账（count 空集是 0 不是 NULL）
