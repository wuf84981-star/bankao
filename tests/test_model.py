# ============================================================
# S8 · D60 甲 模型切换刀离线单测（七路花名册 + 每户选模，2026-09-11 拍板）
# 断言主线：路由表是唯一真源——
#   resolve_model/platform_of=名字归一；key_ok=env 实时读（monkeypatch 全控，
#   不信环境现值）；model_for=账（无行=默认，脏账兜默认）；
#   chat_once=按型号路由到对应平台客户端（假客户端塞 _clients 缓存，零真网络）；
#   answer_turn 默认电厂路线收本户账（注入假电厂不感知，旧签名照活）。
# 端点直调传 SimpleNamespace 绕 Depends（先例 test_conv/_ws_t 家法）。
# ============================================================
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text

import backend.llm as llm
import backend.orchestrator as orch
from backend.db import SessionLocal
from backend.llm import DEFAULT_MODEL, MODEL_PLATFORM, key_ok, platform_of, resolve_model
from backend.main import ModelIn, get_model, set_model
from backend.tools import model_for


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_md_t', 'x', 'normal', now()) RETURNING id")).scalar()
        # D64 口粮：answer_turn 有了积分闸——本册验选模绑账，先开池再开口
        s.execute(text("INSERT INTO points_ledger (user_id, day, kind, amount, created_at) "
                       "VALUES (:u, current_date, 'bonus', 999999, now())"), {"u": u})
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})   # 级联带走 settings 行
        s.commit()


def _set_model(uid, val):
    with SessionLocal() as s:
        n = s.execute(text(
            "UPDATE agent_settings SET model_choice = :v WHERE user_id = :u"),
            {"v": val, "u": uid}).rowcount
        if not n:
            s.execute(text(
                "INSERT INTO agent_settings (user_id, model_choice) VALUES (:u, :v)"),
                {"u": uid, "v": val})
        s.commit()


# ── 纯函数：名字归一与钥匙判定 ──

def test_resolve_model_three_flavors():
    """认账原样走；None 与不认的名兜默认——脏账不炸电厂。"""
    assert resolve_model("GLM-5.2") == "GLM-5.2"
    assert resolve_model(None) == DEFAULT_MODEL
    assert resolve_model("gpt-9-不存在的") == DEFAULT_MODEL


def test_platform_of_routes_roster():
    assert platform_of("deepseek-flash") == "deepseek"
    assert platform_of("qwen3.8-max") == "dashscope"   # 2026-09-12 换真 ID：百炼货架名是小写
    assert platform_of("GLM-5.3") == "zhipu"
    assert platform_of("野名") == platform_of(DEFAULT_MODEL)   # 错名兜向最熟的脑


def test_key_ok_reads_env_live(monkeypatch):
    """env 实时读不缓存：空白值=没配（strip 执法）；换 key 即刻反映，不重启进程。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert key_ok("deepseek-flash") is False
    monkeypatch.setenv("DEEPSEEK_API_KEY", "   ")
    assert key_ok("deepseek-flash") is False
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    assert key_ok("deepseek-flash") is True
    assert key_ok("GLM-5.2") is False   # 智谱恒无（测试环境不许有真智谱 key 的账）


# ── 账：model_for（tools 家法同 web_allowed） ──

def test_model_for_no_row_uses_default(uid):
    """新户没落选模账 → DEFAULT_MODEL。默认只活在 llm.py 一处，不冻进历史行。"""
    assert model_for(SessionLocal(), uid) == DEFAULT_MODEL


def test_model_for_follows_ledger_and_sanitizes(uid):
    """落账跟账；库里躺着脏名（手改/换表残留）也读时兜默认，不炸现场。"""
    _set_model(uid, "deepseek-v4-pro")
    assert model_for(SessionLocal(), uid) == "deepseek-v4-pro"
    _set_model(uid, "gpt-9-不存在的")
    assert model_for(SessionLocal(), uid) == DEFAULT_MODEL   # 读时兜底，不炸现场


# ── 电厂路由：假客户端进 _clients 缓存，验 create 收的 model 名 ──

def _fake_platform(sink):
    """造一个「.chat.completions.create」形状的假平台客户端，记账每次呼叫。"""
    def create(**kw):
        sink.append(kw)
        msg = SimpleNamespace(content="ok", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2))
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_chat_once_routes_by_platform():
    """GLM 的呼叫落在 zhipu 假客户端、model 名原样透传；None 兜默认落 deepseek。
    烧哪家记哪家账的接线证据——全程零真网络（缓存里全是假件）。"""
    old = dict(llm._clients)
    sink_z, sink_d = [], []
    llm._clients.update({"zhipu": _fake_platform(sink_z), "deepseek": _fake_platform(sink_d)})
    try:
        out, ptok, ctok = llm.chat_once([{"role": "user", "content": "hi"}], model="GLM-5.2")
        assert (ptok, ctok) == (1, 2) and out["content"] == "ok"
        assert sink_z and sink_z[-1]["model"] == "GLM-5.2"
        assert not sink_d                       # 没串台
        llm.chat_once([{"role": "user", "content": "hi"}], model=None)
        assert sink_d and sink_d[-1]["model"] == DEFAULT_MODEL
    finally:
        llm._clients.clear()
        llm._clients.update(old)                # 清假件，不污染别的用例


# ── 编排层默认电厂绑账（QQ/网页两条线共用的心脏） ──

def test_answer_turn_binds_ledger_model(uid, monkeypatch):
    """不注入假电厂时，answer_turn 用真电厂路线 → chat_once 收到本户 model_choice。
    假 chat_once 无 tool_calls，一轮即收——循环形状照 test_conv 先例。"""
    _set_model(uid, "deepseek-v4-pro")
    caught = {}
    def fake_chat_once(messages, tools=None, model=None):
        caught["model"] = model
        return ({"role": "assistant", "content": "收到"}, 0, 0)
    monkeypatch.setattr(orch, "chat_once", fake_chat_once)
    with SessionLocal() as s:
        out = orch.answer_turn(s, uid, "换个脑子试试")
    assert caught["model"] == "deepseek-v4-pro"
    assert out["reply"] == "收到"


# ── 端点：菜单供给与后端执法 ──

def test_get_model_lists_full_roster(uid, monkeypatch):
    """菜单不藏掖：七路全列；没钥匙的 available=false（前端灰显的根据）。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    d = get_model(SimpleNamespace(id=uid))
    assert d["current"] == DEFAULT_MODEL and d["default"] == DEFAULT_MODEL
    assert [m["id"] for m in d["models"]] == list(MODEL_PLATFORM)
    by = {m["id"]: m for m in d["models"]}
    assert by["deepseek-flash"]["available"] is True
    assert by["GLM-5.2"]["available"] is False
    assert by["qwen3.8-max"]["platform"] == "dashscope"


def test_set_model_roundtrip(uid, monkeypatch):
    """存得进、读得出——key_ok 只查 env 不建客户端，所以假钥匙也能落账、零真网络。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    set_model(ModelIn(model="deepseek-v4-pro"), SimpleNamespace(id=uid))
    assert get_model(SimpleNamespace(id=uid))["current"] == "deepseek-v4-pro"


def test_set_model_rejects_off_roster(uid):
    with pytest.raises(HTTPException) as e:
        set_model(ModelIn(model="gpt-9"), SimpleNamespace(id=uid))
    assert e.value.status_code == 422 and "花名册" in e.value.detail


def test_set_model_rejects_keyless_platform(uid, monkeypatch):
    """菜单灰显只是体贴，拒存才是执法：智谱恒无钥匙，脏请求照样 422。"""
    monkeypatch.delenv("ZHIPU_API_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        set_model(ModelIn(model="GLM-5.3"), SimpleNamespace(id=uid))
    assert e.value.status_code == 422 and "钥匙" in e.value.detail
