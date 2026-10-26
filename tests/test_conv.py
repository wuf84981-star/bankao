# ============================================================
# S7 五刀离线单测：会话历史管理（F-08 · D40/D41 甲）
# 断言主线：三面（列表/新建/删除）各归各位；列表按「最后消息时间」倒序（不信 updated_at）；
# 删除票闸=本户（D56 甲 2026-09-11 改形状：自家 QQ 线也可删，别人的/编的 404）；
# 定点 conv_id 假票拒在一切烧钱之前（电厂、OCR 都不许被叫，也不悄插垃圾行）；
# history 定点：不命中回空窗不回 404（不给探测会话存在性的探针）；
# D56 甲：QQ 线列表可见+定点可读、发送腿仍拒（看与写两把闸各管各的）。
# 铁律：电厂/OCR 腿全假件注入——真 key 在测试里出现一次就是烧用户的钱。
# 直调 route 函数传 SimpleNamespace 绕 Depends 的先例：test_image 借 main 纯函数。
# ============================================================
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.db import SessionLocal
from backend.main import conversation_delete, conversation_new, conversations_api, history
from backend.models import Message
from backend.orchestrator import answer_turn, image_turn
from test_image import _PNG   # 最小真 png 头——借四刀自备料
from test_qq import _chat     # 假电厂：(assistant, 10, 5)


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_conv_t', 'x', 'normal', now()) RETURNING id")).scalar()
        # D64 口粮：积分闸拦的是余额≤0 的户——本册验会话不验钱包，先开池再开口
        s.execute(text("INSERT INTO points_ledger (user_id, day, kind, amount, created_at) "
                       "VALUES (:u, current_date, 'bonus', 999999, now())"), {"u": u})
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})   # 级联带走一切
        s.commit()


# ── 三面与列表秩序 ──

def test_conv_three_faces_and_order(uid):
    """空账→两条新线→A 线聊一句→列表 A 先 B 后（排序键=A 的最后消息时间，
    不是 updated_at——插消息不动会话行）→删 B 只剩 A。"""
    ns = SimpleNamespace(id=uid)
    assert conversations_api(user=ns)["conversations"] == []
    a = conversation_new(user=ns)["id"]
    b = conversation_new(user=ns)["id"]
    assert a != b   # 新建=插行，不是一户一线
    with SessionLocal() as s:
        out = answer_turn(s, uid, "第一题错了", chat_fn=_chat, conv_id=a)
    assert out["conv_id"] == a   # 定点：消息落在指定的 A，没拐去最近的 B
    rows = conversations_api(user=ns)["conversations"]
    assert [r["id"] for r in rows] == [a, b]
    assert rows[0]["preview"] == "第一题错了"   # 预览=该线最后一条用户消息
    assert rows[0]["title"] == "新会话"
    assert rows[1]["preview"] == ""             # 空线也上列表，预览空串
    assert conversation_delete(b, user=ns) == {"deleted": b}
    assert [r["id"] for r in conversations_api(user=ns)["conversations"]] == [a]


def test_delete_ticket_gate_two_flavors(uid):
    """404 两张脸同话术：别人的行 / 编的 id——D56 甲（2026-09-11 拍）把旧第三张脸
    「本户 QQ 线」翻成正面：自家 QQ 线列表上架（行带 channel）、可删。"""
    ns = SimpleNamespace(id=uid)
    a = conversation_new(user=ns)["id"]
    with SessionLocal() as s:
        other = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_conv_t2', 'x', 'normal', now()) RETURNING id")).scalar()
        qq = s.execute(text(
            "INSERT INTO conversations (user_id, channel, title, updated_at) "
            "VALUES (:u, 'qq', 'QQ线', now()) RETURNING id"), {"u": uid}).scalar()
        s.commit()
    ns2 = SimpleNamespace(id=other)
    oa = conversation_new(user=ns2)["id"]
    try:
        for bad in (oa, 99999999):
            with pytest.raises(HTTPException) as e:
                conversation_delete(bad, user=ns)
            assert e.value.status_code == 404
        rows = conversations_api(user=ns)["conversations"]   # 混排：web a + 自家 qq
        assert {r["id"] for r in rows} == {a, qq}
        assert next(r for r in rows if r["id"] == qq)["channel"] == "qq"
        assert [r["id"] for r in conversations_api(user=ns2)["conversations"]] == [oa]
        # 别人的行原样在——404 是真拒，不是误删
        assert conversation_delete(qq, user=ns) == {"deleted": qq}   # 自家 QQ 线删得掉
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM users WHERE id = :o"), {"o": other})
            s.commit()


# ── 定点票闸：拒在一切烧钱之前 ──

def test_pin_gate_burns_nothing(uid):
    """假 conv_id 进 answer_turn/image_turn：电厂、OCR 一只都不许被叫（tripwire 即炸）、
    不悄插垃圾会话行、消息零行、运费零笔——D41 甲「票闸排在钱的次序最前」。"""
    def tripwire(*a, **k):
        raise AssertionError("电厂被叫了——假票不配烧一分钱")

    def ocr_tripwire(*a, **k):
        raise AssertionError("OCR 腿被叫了——conv 闸在图片闸之前")

    ns = SimpleNamespace(id=uid)
    conversation_new(user=ns)
    with SessionLocal() as s:
        out = answer_turn(s, uid, "你好", chat_fn=tripwire, conv_id=999999)
        assert out["err"] == "conv"
        out2 = image_turn(s, uid, text="看图", images=[{
            "data": _PNG, "ref": {"kind": "file", "path": "x.png",
                                  "mime": "image/png", "size": len(_PNG)},
        }], chat_fn=tripwire, ocr_fn=ocr_tripwire, conv_id=999999)
        assert out2["err"] == "conv"
        assert s.execute(text(
            "SELECT count(*) FROM conversations WHERE user_id = :u"),
            {"u": uid}).scalar() == 1   # 只有新建那一条，没被伪造行污染
        assert s.execute(text(
            "SELECT count(*) FROM messages m JOIN conversations c "
            "ON m.conversation_id = c.id WHERE c.user_id = :u"), {"u": uid}).scalar() == 0
        assert s.execute(text(
            "SELECT count(*) FROM usage_logs WHERE user_id = :u"),
            {"u": uid}).scalar() == 0


def test_chat_lands_pinned_not_latest(uid):
    """有更新的 B 线在场，定点投递仍落 A——「随后端最近线」只是缺省，不是强制。"""
    ns = SimpleNamespace(id=uid)
    a = conversation_new(user=ns)["id"]
    b = conversation_new(user=ns)["id"]
    with SessionLocal() as s:
        answer_turn(s, uid, "B线的垫话", chat_fn=_chat, conv_id=b)   # B 现在是最近线
        out = answer_turn(s, uid, "回A补一句", chat_fn=_chat, conv_id=a)
    assert out["conv_id"] == a
    with SessionLocal() as s:
        mb = s.execute(text(
            "SELECT count(*) FROM messages WHERE conversation_id = :c"),
            {"c": b}).scalar()
        ma = s.execute(text(
            "SELECT count(*) FROM messages WHERE conversation_id = :c"),
            {"c": a}).scalar()
    assert mb == 2 and ma == 2   # 各线各账，A 的两句没串进 B


# ── history 定点 ──

def test_history_pinned(uid):
    """定点读指定线；空线空窗；假 id 也空窗（404 会泄露存在性）；不指定=最近线。"""
    ns = SimpleNamespace(id=uid)
    a = conversation_new(user=ns)["id"]
    b = conversation_new(user=ns)["id"]
    with SessionLocal() as s:
        answer_turn(s, uid, "落在B线", chat_fn=_chat, conv_id=b)
    assert history(user=ns, conv_id=a)["messages"] == []
    hb = history(user=ns, conv_id=b)["messages"]
    assert [m["text"] for m in hb] == ["落在B线", "收到，已记在你名下。"]
    assert history(user=ns, conv_id=999999)["messages"] == []
    hd = history(user=ns)["messages"]           # 缺省=最近线 B
    assert hd and hd[0]["text"] == "落在B线"


def test_history_cursor_pages(uid):
    """六刀游标：25 条一屏装不下——首页 12 条最新、before_id 逐页往回、
    翻到剩 1 条时 has_more=False（探针行：limit+1 多取一行判尾）。"""
    ns = SimpleNamespace(id=uid)
    a = conversation_new(user=ns)["id"]
    with SessionLocal() as s:
        for i in range(25):
            s.add(Message(conversation_id=a, role="user",
                          content=f"第{i}句", token_count=4))
        s.commit()
    p1 = history(user=ns, limit=12, conv_id=a)
    assert len(p1["messages"]) == 12 and p1["has_more"] is True
    assert p1["messages"][-1]["text"] == "第24句"       # 正序：最新在尾
    assert p1["messages"][0]["text"] == "第13句"
    p2 = history(user=ns, limit=12, conv_id=a, before_id=p1["messages"][0]["id"])
    assert len(p2["messages"]) == 12 and p2["has_more"] is True
    assert p2["messages"][-1]["text"] == "第12句"       # 页缝无重叠无空洞
    p3 = history(user=ns, limit=12, conv_id=a, before_id=p2["messages"][0]["id"])
    assert [m["text"] for m in p3["messages"]] == ["第0句"]
    assert p3["has_more"] is False
    # 行行带 id：前端稳定 key 与下一页游标都靠它
    assert all(isinstance(m["id"], int) for m in p1["messages"])


def test_history_default_lands_most_active(uid):
    """七刀真机案：老线聊过话后又建空新线（id 更大）——刷新缺省落线必须回
    有动静的老线，不是新建的空线（旧规则取最大 id 才会落空）。空线一旦
    自己开口，落线才切过去。响应带 conv_id：前端回填线号，发送不串道。"""
    ns = SimpleNamespace(id=uid)
    a = conversation_new(user=ns)["id"]
    with SessionLocal() as s:
        answer_turn(s, uid, "老线的话", chat_fn=_chat, conv_id=a)
    b = conversation_new(user=ns)["id"]              # 空新线，id 比 a 大
    h = history(user=ns)
    assert h["conv_id"] == a                          # 落活跃老线，不落最大 id 空线
    assert h["messages"][0]["text"] == "老线的话"
    assert h["has_more"] is False
    with SessionLocal() as s:
        answer_turn(s, uid, "新线开口", chat_fn=_chat, conv_id=b)
    assert history(user=ns)["conv_id"] == b           # b 活动了才轮得到它
    d = conversation_new(user=ns)["id"]               # 再建空线，创建时间最新
    assert history(user=ns)["conv_id"] == b           # 空线不堵门（updated_at 再晚也不抢）
    # 定点读空线照旧空窗，但也要带线号（前端要把 activeConv 钉在指定线上）
    assert history(user=ns, conv_id=a)["conv_id"] == a


def test_qq_line_read_not_write(uid):
    """D56 甲的分闸边界：自家 QQ 线定点**读**放行（消息回得来、空线带线号）、
    别人的 QQ 线照旧空窗（本户票闸不松）；**写**腿原样铁面——answer_turn 拿
    QQ 线 id 当定点票=假票，拒在电厂被叫之前（看与写两把闸各管各的）。"""
    ns = SimpleNamespace(id=uid)
    with SessionLocal() as s:
        qq = s.execute(text(
            "INSERT INTO conversations (user_id, channel, title, updated_at) "
            "VALUES (:u, 'qq', 'QQ线', now()) RETURNING id"), {"u": uid}).scalar()
        s.add(Message(conversation_id=qq, role="user", content="QQ上的话",
                      token_count=5))
        other = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_conv_t3', 'x', 'normal', now()) RETURNING id")).scalar()
        oqq = s.execute(text(
            "INSERT INTO conversations (user_id, channel, title, updated_at) "
            "VALUES (:u, 'qq', '别人的QQ线', now()) RETURNING id"), {"u": other}).scalar()
        s.commit()
    try:
        hq = history(user=ns, conv_id=qq)
        assert [m["text"] for m in hq["messages"]] == ["QQ上的话"]   # 读面开门
        assert hq["conv_id"] == qq
        assert history(user=ns, conv_id=oqq)["messages"] == []      # 别人的仍空窗

        def tripwire(*a, **k):
            raise AssertionError("电厂被叫了——QQ 线 id 在网页发送腿不配当票")
        with SessionLocal() as s:
            out = answer_turn(s, uid, "网页想插话", chat_fn=tripwire, conv_id=qq)
        assert out["err"] == "conv"                                 # 写面照旧铁面
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM users WHERE id = :o"), {"o": other})
            s.commit()
