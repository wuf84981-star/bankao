# ============================================================
# S9·W3 知识缺口账回归（gaps.record_gap 旁路 + admin 端点 + tools 接线）
# 断言主线：zero/weak 两档落账、登记线卡达标分（0.60 恰达线不记）、
# 24h 幂等不胀账、空题不落、record_gap 自吞异常永不炸答题、
# channel 随行、admin_gaps 户主闸+两档 kind、
# search_materials 零命中接线（无材料户 done_count=0 跳过 embed——全离线安全）。
# 测法仿 test_admin：直接调端点函数，假户主/平民主动作；_gp_t 前缀尾清。
# ============================================================
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy import text as sa_text

from backend import gaps
from backend.db import SessionLocal
from backend.gaps import GAP_WEAK, record_gap
from backend.main import admin_gaps
from backend.models import KnowledgeGap, User
from backend.tools import search_materials
from test_admin import _get_user, _make_user


@pytest.fixture()
def cleanup():
    yield
    with SessionLocal() as s:
        s.execute(sa_text("DELETE FROM knowledge_gaps WHERE user_id IN "
                          "(SELECT id FROM users WHERE username LIKE '_gp_t%')"))
        s.execute(User.__table__.delete().where(User.username.like("_gp_t%")))
        s.commit()


def _rows(uid: int):
    with SessionLocal() as s:
        return s.scalars(select(KnowledgeGap).where(
            KnowledgeGap.user_id == uid).order_by(KnowledgeGap.id)).all()


def _uid(name: str) -> int:
    return _make_user(name, email=f"{name}@x.test")


def test_zero_row_written(cleanup):
    """top_vec=None ⇒ zero：讲义查无，top_score 空着落账。"""
    uid = _uid("_gp_t1")
    assert record_gap(uid, "这道题讲义根本没有", None) is True
    r = _rows(uid)[0]
    assert r.top_score is None and r.channel == "web"


def test_weak_row_written(cleanup):
    """有分但低于登记线 ⇒ weak：分数原样存（四舍五入 4 位）。"""
    uid = _uid("_gp_t2")
    assert record_gap(uid, "擦边题", 0.451234) is True
    assert _rows(uid)[0].top_score == pytest.approx(0.4512)


def test_strong_score_not_recorded(cleanup):
    """达标分不落账：恰在线（0.60）算答得上——登记线语义是「低于才记」。"""
    uid = _uid("_gp_t3")
    assert record_gap(uid, "讲义答得上的题", GAP_WEAK) is False
    assert record_gap(uid, "讲义答得上的题", 0.9) is False
    assert _rows(uid) == []


def test_just_below_line_recorded(cleanup):
    """贴线下方必须记（边界别写成闭区间把擦边漏掉）。"""
    uid = _uid("_gp_t4")
    assert record_gap(uid, "刚好擦边", 0.5999) is True
    assert len(_rows(uid)) == 1


def test_idempotent_24h(cleanup):
    """同户同题 24h 内只一笔：狂刷不胀账（零命中反复问最典型）。"""
    uid = _uid("_gp_t5")
    assert record_gap(uid, "再问一次也一样", None) is True
    assert record_gap(uid, "  再问一次也一样  ", None) is False   # strip 后同题
    assert len(_rows(uid)) == 1


def test_blank_question_not_recorded(cleanup):
    uid = _uid("_gp_t6")
    assert record_gap(uid, "   ", None) is False
    assert record_gap(uid, "", 0.1) is False
    assert _rows(uid) == []


def test_swallows_db_failure(cleanup):
    """旁账身份：DB 炸了也只回 False——绝不把异常甩进答题正线。"""
    uid = _uid("_gp_t7")

    def boom(*a, **kw):
        raise RuntimeError("库断了")
    monkey_result = None
    original = gaps.SessionLocal
    gaps.SessionLocal = boom
    try:
        monkey_result = record_gap(uid, "任性问题", None)
    finally:
        gaps.SessionLocal = original
    assert monkey_result is False


def test_channel_carried(cleanup):
    """渠道随行（web/qq）：Conversation 同谱，户主看哪条触点在缺粮。"""
    uid = _uid("_gp_t8")
    assert record_gap(uid, "QQ 侧的题", 0.2, channel="qq") is True
    assert _rows(uid)[0].channel == "qq"


def test_admin_gaps_owner_and_gate(cleanup):
    """户主闸双形状：平民 403；户主见两档 kind（zero/weak）。"""
    boss = _make_user("_gp_t9_boss", email="_gp_t9_boss@x.test", admin=True)
    peon = _uid("_gp_t9_peon")
    record_gap(peon, "查无的题", None)
    record_gap(peon, "擦边的题", 0.45)
    with pytest.raises(HTTPException) as e:
        admin_gaps(user=_get_user(peon))
    assert e.value.status_code == 403 and "户主" in e.value.detail
    items = admin_gaps(user=_get_user(boss))["items"]
    mine = {i["question"]: i for i in items if i["user_id"] == peon}
    assert mine["查无的题"]["kind"] == "zero"
    assert mine["擦边的题"]["kind"] == "weak"
    assert mine["查无的题"]["username"] == "_gp_t9_peon"


def test_search_materials_zero_hit_writes_gap(cleanup):
    """消费端接线实锤：无材料户（done_count=0 跳过 embed，全离线安全）
    调 search_materials 零命中 → 账上落一笔 zero；再调幂等不增行。
    写在消费端不写 search() 核心——/api/search 调试窗不污染这本账。"""
    uid = _uid("_gp_t10")
    with SessionLocal() as s:
        ctx = {"user_id": uid, "session": s, "citations": [], "channel": "web"}
        out = json.loads(search_materials({"query": "这道题讲义里肯定没有"}, ctx))
        assert out["found"] == 0
        out2 = json.loads(search_materials({"query": "这道题讲义里肯定没有"}, ctx))
        assert out2["found"] == 0
    rows = _rows(uid)
    assert len(rows) == 1 and rows[0].top_score is None
