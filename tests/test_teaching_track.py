# ============================================================
# S9·W5 教学轨分流/结算离线回归（teaching_track.py）
# 断言主线：五关全 AND（回滚旗=0 整轨消失、无料户不进、事务句不进）、
# 帧协议零发明（首帧 : ping、delta 键唯一、done 键集与事务轨逐项同构）、
# 流尾三本账同一事务（教练行+usage_logs+points_ledger）、
# 图腿炸了 error 帧零落账（BR-11）、thread_id=conv:{id} 形状、used_tools 恒空。
# 图腿全假件（build_graph/get_saver/_system_for/model_for 掉包）——不碰电厂。
# 测法仿 test_gaps：真 DB 造户造料，_tt 前缀尾清。
# ============================================================
import json
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy import text as sa_text

from backend import teaching_track as tt
from backend.db import SessionLocal
from backend.models import Chunk, Conversation, Material, Message, UsageLog, User
from test_admin import _make_user

_DATA = "data: "


def _uid(name: str) -> int:
    return _make_user(name, email=f"{name}@x.test")


def _seed(uid: int, with_chunk: bool) -> int:
    """造会话线（可带一个讲义块=「有材料户」），回 conv id。"""
    with SessionLocal() as s:
        if with_chunk:
            m = Material(user_id=uid, title="_tt 讲义", storage_path="_tt/x.txt",
                         file_type="txt", parse_status="ready")
            s.add(m)
            s.flush()
            s.add(Chunk(material_id=m.id, user_id=uid, seq=0,
                        content="基期量=现期量÷(1+增长率)"))
        conv = Conversation(user_id=uid, channel="web", title="_tt 线")
        s.add(conv)
        s.commit()
        return conv.id


def _conv(cid: int):
    with SessionLocal() as s:
        return s.get(Conversation, cid)


@pytest.fixture()
def cleanup():
    yield
    with SessionLocal() as s:
        s.execute(sa_text("DELETE FROM usage_logs WHERE user_id IN "
                          "(SELECT id FROM users WHERE username LIKE '_tt%')"))
        s.execute(sa_text("DELETE FROM points_ledger WHERE user_id IN "
                          "(SELECT id FROM users WHERE username LIKE '_tt%')"))
        s.execute(User.__table__.delete().where(User.username.like("_tt%")))
        s.commit()


class FakeGraph:
    """graph.stream 的替身：按剧本吐 (mode, payload)，遇异常原样炸——
    顺便把 state/config 留证给断言。"""
    def __init__(self, steps):
        self.steps = steps

    def stream(self, state, config=None, stream_mode=None):
        self.state = state
        self.cfg = config
        for st in self.steps:
            if isinstance(st, Exception):
                raise st
            yield st


def _wire(monkeypatch, steps) -> FakeGraph:
    g = FakeGraph(steps)
    monkeypatch.setattr(tt, "build_graph", lambda saver, session=None: g)
    monkeypatch.setattr(tt, "get_saver", lambda: None)
    monkeypatch.setattr(tt, "_system_for", lambda uid, s: "你是备考教练")
    monkeypatch.setattr(tt, "model_for", lambda s, uid: "deepseek-flash")
    return g


def _final(reply="我们一步步来", ptok=120, ctok=53, citations=None):
    return {"reply": reply, "ptok": ptok, "ctok": ctok,
            "citations": citations or [], "round_no": 1,
            "strategy": "socratic", "understood": False, "handoff": False}


def _events(uid, cid, user_msg="基期量怎么算", history=None):
    with SessionLocal() as s:
        return list(tt.teaching_events(user_id=uid, username="_tt 户",
                                       user_msg=user_msg, conv=_conv(cid),
                                       history=history or [], tool_session=s,
                                       today=date.today(), spent=0))


def _payload(frame: str) -> dict:
    assert frame.startswith(_DATA)
    return json.loads(frame[len(_DATA):])


# ── 五关分流（4 例）──

def test_eligible_teaching_question(cleanup):
    """默认旗开 + 有料 + 教学句 → True（进图资格的全部三关）。"""
    uid = _uid("_tt_t1")
    _seed(uid, with_chunk=True)
    with SessionLocal() as s:
        assert tt.teaching_eligible(s, uid, "基期量怎么算") is True


def test_eligible_no_materials(cleanup):
    """无料户一票否——检索腿空转的教学轨比事务轨更贫。"""
    uid = _uid("_tt_t2")
    _seed(uid, with_chunk=False)
    with SessionLocal() as s:
        assert tt.teaching_eligible(s, uid, "基期量怎么算") is False


def test_eligible_task_sentence(cleanup):
    """有料也拦事务句（intent 一票否决词表在分流门外再证一次）。"""
    uid = _uid("_tt_t3")
    _seed(uid, with_chunk=True)
    with SessionLocal() as s:
        assert tt.teaching_eligible(s, uid, "帮我排个计划") is False


def test_rollback_flag_kills_track(cleanup, monkeypatch):
    """TEACHING_TRACK_ENABLED=0 → 满配句也 False：回滚=分流处一行 if。"""
    monkeypatch.setenv("TEACHING_TRACK_ENABLED", "0")
    uid = _uid("_tt_t4")
    _seed(uid, with_chunk=True)
    with SessionLocal() as s:
        assert tt.teaching_eligible(s, uid, "基期量怎么算") is False


def test_user_switch_gates_track(cleanup):
    """D81 挂招牌刀三态：无行=从没动过=开；关=回事务轨直答；再开=回图。
    用户闸在 env 总闸之后、材料闸之前——意愿闸不越运维闸。"""
    uid = _uid("_tt_t13")
    _seed(uid, with_chunk=True)
    with SessionLocal() as s:
        assert tt.user_teaching_on(s, uid) is True
        assert tt.teaching_eligible(s, uid, "基期量怎么算") is True
        s.execute(sa_text("INSERT INTO agent_settings (user_id, teaching_mode) "
                          "VALUES (:u, false)"), {"u": uid})
        s.commit()
        assert tt.user_teaching_on(s, uid) is False
        assert tt.teaching_eligible(s, uid, "基期量怎么算") is False
        s.execute(sa_text("UPDATE agent_settings SET teaching_mode = true "
                          "WHERE user_id = :u"), {"u": uid})
        s.commit()
        assert tt.teaching_eligible(s, uid, "基期量怎么算") is True


def test_teaching_settings_api_roundtrip(cleanup):
    """端点与分流闸读写同一本账（单一真相源）：POST false 后 GET 关、
    user_teaching_on 同判 False；无行户 GET=开。"""
    from backend.main import TeachingModeIn, get_teaching, set_teaching
    uid = _uid("_tt_t14")
    ns = SimpleNamespace(id=uid)
    assert get_teaching(user=ns)["enabled"] is True
    set_teaching(TeachingModeIn(enabled=False), user=ns)
    assert get_teaching(user=ns)["enabled"] is False
    with SessionLocal() as s:
        assert tt.user_teaching_on(s, uid) is False
    set_teaching(TeachingModeIn(enabled=True), user=ns)
    assert get_teaching(user=ns)["enabled"] is True


def test_feynman_settings_api_roundtrip(cleanup):
    """D89 费曼闸：端点与 user_feynman_on 读写同一本账（单一真相源），
    三态与大门同法——无行=从没动过=开；POST false 后 GET 与读闸同 False。"""
    from backend.main import TeachingModeIn, get_feynman, set_feynman
    uid = _uid("_tt_t15")
    ns = SimpleNamespace(id=uid)
    assert get_feynman(user=ns)["enabled"] is True
    with SessionLocal() as s:
        assert tt.user_feynman_on(s, uid) is True
    set_feynman(TeachingModeIn(enabled=False), user=ns)
    assert get_feynman(user=ns)["enabled"] is False
    with SessionLocal() as s:
        assert tt.user_feynman_on(s, uid) is False
    set_feynman(TeachingModeIn(enabled=True), user=ns)
    assert get_feynman(user=ns)["enabled"] is True


# ── 帧协议与流尾结算（3 例）──

def test_frames_shape_and_settlement(cleanup, monkeypatch):
    cite = [{"chunk_id": 11, "material_id": 3, "title": "讲义A", "seq": 2,
             "ref": 1}]
    steps = [("custom", {"delta": "我们"}),
             ("custom", {"delta": "一步步来[ref 1]"}),   # 正文标注了票才留（D79 甲）
             ("values", _final(reply="我们一步步来[ref 1]", citations=cite))]
    g = _wire(monkeypatch, steps)
    uid = _uid("_tt_t5")
    cid = _seed(uid, with_chunk=True)
    frames = _events(uid, cid)
    assert frames[0] == ": ping\n\n"                 # 心跳同款
    deltas = [_payload(f) for f in frames[1:-1]]
    assert all(set(d) == {"delta"} for d in deltas)  # delta 帧键唯一，一帧不发明
    assert "".join(d["delta"] for d in deltas) == "我们一步步来[ref 1]"
    done = _payload(frames[-1])["done"]
    # done 键集与事务轨逐项同构——前端 fly 只认这套契约：
    assert set(done) == {"remaining", "notice", "balance", "points_spent",
                         "used_tools", "username", "conv_id", "citations"}
    assert done["used_tools"] == []                  # 教学轨不调工具：恒空是立场
    assert done["citations"] == cite and done["conv_id"] == cid
    assert done["points_spent"] == 2                 # 173 tokens ×1 倍率 ceil → 2 分
    assert done["balance"] == -2                     # 白户烧穿（后账式，下一句才拦）
    # 检查点续存钥匙的形状：一条会话线一个线程
    assert g.cfg["configurable"]["thread_id"] == f"conv:{cid}"
    assert g.state["system"] == "你是备考教练"       # 人设真源两轨同脑
    assert g.state["model"] == "deepseek-flash"
    # 流尾三本账（教练行+流水+积分）都落定：
    with SessionLocal() as s:
        row = s.scalars(select(Message).where(
            Message.conversation_id == cid, Message.role == "assistant")).one()
        assert row.content == "我们一步步来[ref 1]" and row.token_count == 53
        assert row.citations == cite
        assert s.scalar(select(func.sum(UsageLog.tokens))
                        .where(UsageLog.user_id == uid)) == 173


def test_history_passed_through_and_summary(cleanup, monkeypatch):
    """W6 接线形状：main 交纯 dict 窗（window_get 产物），teaching_events 直搬
    进图状态不转手；context_summary 由 with_summary 拼进 system——教学轨同享摘要。"""
    g = _wire(monkeypatch, [("values", _final())])
    uid = _uid("_tt_t6")
    cid = _seed(uid, with_chunk=True)
    with SessionLocal() as s:
        conv = s.get(Conversation, cid)
        conv.context_summary = json.dumps(
            {"until_id": 9, "text": "聊过基期量两轮", "model": "q", "at": "t"},
            ensure_ascii=False)
        s.commit()
    frames = _events(uid, cid, history=[{"role": "user", "content": "你好"}])
    assert g.state["history"] == [{"role": "user", "content": "你好"}]
    assert "前情摘要" in g.state["system"] and "聊过基期量两轮" in g.state["system"]
    assert _payload(frames[-1])["done"]["points_spent"] > 0


def test_teaching_system_swaps_raise_hand_clause(cleanup):
    """真机漏案钉（2026-10-12）：人设「考点问题必须先调 search_materials」
    与教学轨 tools=None 打架，qwen 遵命又无处举手，就把整句工具调用 XML
    吐进正文。双钉：①锚串必须仍在 orchestrator 原句里（人设被改而锚没跟=
    replace 静默失手，漏案复发）；②教学轨 system 里旧令绝迹、新令在场。"""
    from backend.orchestrator import SYSTEM_PROMPT
    assert tt._TEACH_TOOL_OLD in SYSTEM_PROMPT
    uid = _uid("_tt_t10")
    cid = _seed(uid, with_chunk=True)
    with SessionLocal() as s:
        sys_txt = tt._teaching_system(uid, s, _conv(cid))
    assert tt._TEACH_TOOL_OLD not in sys_txt
    assert "先调用 search_materials" not in sys_txt
    assert tt._TEACH_TOOL_NEW in sys_txt


def test_citations_mouth_over_ledger(cleanup, monkeypatch):
    """D79 甲案（嘴账对齐）：检索命中 3 块，正文只标 [ref 2]→done 与落库只留那张；
    正文零标注（嘴说没找到）→票面整空，账不替嘴撒谎。"""
    cites = [{"chunk_id": 10 + i, "material_id": 3, "title": "讲义A",
              "seq": i, "ref": i + 1} for i in range(3)]
    _wire(monkeypatch, [("values", _final(reply="先看这步[ref 2]",
                                         citations=cites))])
    uid = _uid("_tt_t11")
    cid = _seed(uid, with_chunk=True)
    done = _payload(_events(uid, cid)[-1])["done"]
    assert done["citations"] == [cites[1]]
    with SessionLocal() as s:
        row = s.scalars(select(Message).where(
            Message.conversation_id == cid, Message.role == "assistant")).one()
        assert row.citations == [cites[1]]
    _wire(monkeypatch, [("values", _final(reply="资料中未找到相关内容",
                                         citations=cites))])
    uid2 = _uid("_tt_t12")
    cid2 = _seed(uid2, with_chunk=True)
    done2 = _payload(_events(uid2, cid2)[-1])["done"]
    assert done2["citations"] == []
    with SessionLocal() as s:
        row2 = s.scalars(select(Message).where(
            Message.conversation_id == cid2,
            Message.role == "assistant")).one()
        assert row2.citations is None     # 空账不落空 JSON——与零命中户同形


def test_safety_round_settles_zero_cost(cleanup, monkeypatch):
    """拦下句也走完整流尾（固定话术+零账单）：行落库、积分不动。"""
    fixed = "生命最要紧——先拨打 12355"
    g = _wire(monkeypatch, [("custom", {"delta": fixed}),
                            ("values", _final(reply=fixed, ptok=0, ctok=0,
                                              citations=None))])
    uid = _uid("_tt_t7")
    cid = _seed(uid, with_chunk=True)
    frames = _events(uid, cid)
    done = _payload(frames[-1])["done"]
    assert done["points_spent"] == 0 and done["balance"] == 0
    assert done["citations"] == []
    with SessionLocal() as s:
        row = s.scalars(select(Message).where(
            Message.conversation_id == cid, Message.role == "assistant")).one()
        assert row.content == fixed and row.citations is None
        assert s.scalar(select(func.count(UsageLog.id))
                        .where(UsageLog.user_id == uid)) == 1  # 流水 0 行照落，账实相符


# ── 故障面（2 例）──

def test_graph_error_frame_zero_settlement(cleanup, monkeypatch):
    """图腿中途炸：error 帧收场、半句不落库（BR-11 对教学轨同样成立）。"""
    _wire(monkeypatch, [("custom", {"delta": "半句"}), RuntimeError("电厂炸了")])
    uid = _uid("_tt_t8")
    cid = _seed(uid, with_chunk=True)
    frames = _events(uid, cid)
    assert set(_payload(frames[-1])) == {"error"}
    with SessionLocal() as s:
        n = s.scalar(select(func.count(Message.id)).where(
            Message.conversation_id == cid, Message.role == "assistant"))
        assert n == 0
        assert s.scalar(select(func.count(UsageLog.id))
                        .where(UsageLog.user_id == uid)) == 0


def test_error_keeps_user_row_only(cleanup, monkeypatch):
    """D67 家法复刻：用户行进门已落（main 侧），教学轨炸了它独活、教练行无。
    本测在 track 函数外补插用户行，模拟 main 分叉前的进门账。"""
    _wire(monkeypatch, [ValueError("开局就炸")])
    uid = _uid("_tt_t9")
    cid = _seed(uid, with_chunk=True)
    with SessionLocal() as s:
        s.add(Message(conversation_id=cid, role="user", content="基期量怎么算",
                      token_count=7))
        s.commit()
    frames = _events(uid, cid)
    # ping 已发（进门帧），随后第一颗数据帧就是 error：
    assert frames[0] == ": ping\n\n" and set(_payload(frames[1])) == {"error"}
    with SessionLocal() as s:
        assert s.scalar(select(func.count(Message.id)).where(
            Message.conversation_id == cid, Message.role == "user")) == 1
        assert s.scalar(select(func.count(Message.id)).where(
            Message.conversation_id == cid, Message.role == "assistant")) == 0
