# ============================================================
# S8 · D58 甲 联网兜底刀离线单测（Tavily + 用户开关，2026-09-11 拍板）
# 断言主线：三件套各守各层——
#   web_allowed=账（无行=关）；tools_for=在场性（关着 web_search 不进 schema）；
#   web_search handler=兜底闸（幻觉调用照拒）+ 故障转人话 + 「来自网络」声明随货。
# 铁律：Tavily 传输全程假 post/假函数注入——测试里出现一次真网络就是烧用户的钱。
# 端点直调传 SimpleNamespace 绕 Depends（先例 test_conv）；开户清户照 _xxx_t 家法。
# ============================================================
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend.main import WebSearchIn, get_websearch, set_websearch
from backend.tools import TOOLS, WEB_TOOLS, tools_for, web_allowed, web_search


def _names(tools):
    return [t["function"]["name"] for t in tools]


def _set_switch(uid, val):
    with SessionLocal() as s:
        n = s.execute(text(
            "UPDATE agent_settings SET web_search_enabled = :v WHERE user_id = :u"),
            {"v": val, "u": uid}).rowcount
        if not n:
            s.execute(text(
                "INSERT INTO agent_settings (user_id, web_search_enabled) VALUES (:u, :v)"),
                {"u": uid, "v": val})
        s.commit()


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_ws_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})   # 级联带走 settings 行
        s.commit()


# ── 账与在场性（开关的两块基石） ──

def test_no_row_means_off(uid):
    """新户没写过 agent_settings 行：web_allowed 读到 None → False——
    「默认关」不靠列默认值单独扛，无行也算关。"""
    assert web_allowed(SessionLocal(), uid) is False


def test_tools_for_presence_two_flavors(uid):
    """关：schema 里根本没 web_search（模型无从举手）；开：TOOLS+WEB_TOOLS 全量。
    这是「不触发外网查询」的执法现场——靠形状不靠 prompt。"""
    with SessionLocal() as s:
        assert "web_search" not in _names(tools_for(s, uid))
        assert _names(tools_for(s, uid)) == _names(TOOLS)
    _set_switch(uid, True)
    with SessionLocal() as s:
        assert _names(tools_for(s, uid)) == _names(TOOLS) + _names(WEB_TOOLS)


# ── handler 双闸与故障转人话 ──

def test_handler_refuses_when_closed_even_if_called(uid):
    """兜底闸：假想模型凭旧上下文幻觉调用——账上没开照样拒，且传输腿一次不许被叫。"""
    calls = []
    import backend.websearch as ws
    monkey = _Recorder(calls)
    old = ws.tavily_search
    ws.tavily_search = monkey
    try:
        with SessionLocal() as s:
            ctx = {"session": s, "user_id": uid, "citations": []}
            out = json.loads(web_search({"query": "考研报名时间"}, ctx))
        assert out["err"] == "closed"
        assert calls == []   # 拒在最便宜的一层，外网一根毛没碰
    finally:
        ws.tavily_search = old


def test_handler_happy_path_with_declaration(uid, monkeypatch):
    """开关开着：假 Tavily 回罐头 → 前 5 条转 hits（带 url、正文截 500）、
    「来自网络」rule 随货、answer 透传；citations 引用账一个字不记。"""
    canned = {"answer": "官方摘要", "results": [
        {"title": f"来源{i}", "url": f"https://example.com/{i}", "content": "长" * 600}
        for i in range(7)]}
    monkeypatch.setattr("backend.websearch.tavily_search",
                        lambda q, **kw: dict(canned))
    _set_switch(uid, True)
    with SessionLocal() as s:
        cites = []
        ctx = {"session": s, "user_id": uid, "citations": cites}
        out = json.loads(web_search({"query": "考研报名时间"}, ctx))
    assert out["found"] == 5
    assert out["hits"][0]["snippet"] == "长" * 500          # 截 500 防撑爆上下文
    assert "来自网络" in out["rule"]
    assert out["answer"] == "官方摘要"
    assert cites == []                                       # 网络货不进讲义引用账


def test_handler_leg_failure_to_human_words(uid, monkeypatch):
    """外联故障（缺 key/超时/配额尽都算）：转 err=web 人话，绝不外包炸主流程。"""
    def boom(q, **kw):
        raise RuntimeError("没配钥匙")
    monkeypatch.setattr("backend.websearch.tavily_search", boom)
    _set_switch(uid, True)
    with SessionLocal() as s:
        out = json.loads(web_search({"query": "x"}, {"session": s, "user_id": uid,
                                                     "citations": []}))
    assert out["err"] == "web" and "没配钥匙" in out["note"]


# ── 零命中 note 的开关两版（D59 乙 2026-09-11 用户改口径：两条兜底路同挂开关） ──

def test_zero_hit_note_two_flavors(uid):
    """关着：只回『知识库无相关资料』实话，既不提联网也不给常识兜底；
    开着：常识兜底（PRD 632 老规矩）+ web_search 第二条路都在。"""
    from backend.tools import search_materials
    with SessionLocal() as s:
        ctx = {"session": s, "user_id": uid, "citations": []}
        off = json.loads(search_materials({"query": "库中必无的词_9xz"}, ctx))
    assert off["found"] == 0
    assert "知识库无相关资料" in off["note"]
    assert "通用知识回答" not in off["note"] and "web_search" not in off["note"]
    _set_switch(uid, True)
    with SessionLocal() as s:
        ctx = {"session": s, "user_id": uid, "citations": []}
        on = json.loads(search_materials({"query": "库中必无的词_9xz"}, ctx))
    assert on["found"] == 0 and "web_search" in on["note"] and "通用知识" in on["note"]


def test_system_prompt_bound_when_closed(uid):
    """D59 源头立法：关着开关的人，system 每轮带【回答边界】段——防的是
    模型压根不调检索、直接凭常识答考点那条路（提示语只在零命中现场说话，够不着这里）。"""
    from backend.orchestrator import _system_for
    with SessionLocal() as s:
        off = _system_for(uid, s)
        _set_switch(uid, True)
        on = _system_for(uid, s)
    assert "【回答边界·数据库真账】" in off and "知识库无相关资料" in off
    assert "【回答边界·数据库真账】" not in on


# ── 传输层本体：钥匙与假 post ──

class _Recorder:
    """假 tavily_search：记调用不干活"""
    def __init__(self, calls):
        self.calls = calls
    def __call__(self, q, **kw):
        self.calls.append(q)
        return {"results": []}


def test_tavily_needs_key(monkeypatch):
    """没 TAVILY_API_KEY：开口就是人话 RuntimeError——且绝不出网。"""
    from backend.websearch import tavily_search
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        tavily_search("test")


def test_tavily_transmit_shape(monkeypatch):
    """假 post 顶上：验 Bearer 头、payload 形状（basic+include_answer）、回包直通。
    真 httpx 一次不进测试——出现一次真网络就是烧用户的钱。"""
    from backend.websearch import TAVILY_URL, tavily_search
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-fake-key")
    seen = {}
    def fake_post(url, **kw):
        seen["url"] = url
        seen["kw"] = kw
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"answer": "a", "results": [{"url": "u"}]})
    out = tavily_search("考研时间", post=fake_post)
    assert seen["url"] == TAVILY_URL
    assert seen["kw"]["headers"]["Authorization"] == "Bearer tvly-fake-key"
    assert seen["kw"]["json"] == {"query": "考研时间", "max_results": 5,
                                  "search_depth": "basic", "include_answer": True}
    assert out["answer"] == "a"


# ── 端点读写往返（前端那只手的全景） ──

def test_endpoint_roundtrip(uid):
    """无行读=关；POST 开→读到开；再 POST 关→读到关。直调 route 绕票闸。"""
    ns = SimpleNamespace(id=uid)
    assert get_websearch(user=ns) == {"enabled": False}
    assert set_websearch(WebSearchIn(enabled=True), user=ns) == {"enabled": True}
    assert get_websearch(user=ns) == {"enabled": True}
    assert set_websearch(WebSearchIn(enabled=False), user=ns) == {"enabled": False}
    assert get_websearch(user=ns) == {"enabled": False}
