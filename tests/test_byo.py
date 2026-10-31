# ============================================================
# BYOK 自带钥匙离线单测（2026-10-31 用户拍板：积分消耗太快，接自己的 DeepSeek）
# 断言主线：
#   get_client=带钥现建临时客户端、不进平台缓存；own_key_for=只认 DeepSeek 平台；
#   answer_turn 带钥腿=api_key 下传电厂 + 积分零扣（consume 行都不该有）+ 余额闸旁路，
#   UsageLog 流水照记；check_deepseek_key=假 getter 四态（websearch 家法，零真触网）；
#   端点=掩码回显（永不带全文）/形状闸/清除/选模放宽。
# 端点直调传 SimpleNamespace 绕 Depends（test_model 家法）；数据库走真箱。
# ============================================================
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text

import backend.llm as llm
import backend.main as main
import backend.orchestrator as orch
from backend.db import SessionLocal
from backend.llm import check_deepseek_key, get_client
from backend.main import (ModelIn, OwnKeyIn, OwnKeyTestIn, get_model, get_ownkey,
                          set_model, set_ownkey)
# 注：验钥端点走 main.test_ownkey 属性调用——裸 import 会让 pytest 把端点当测试用例收集
from backend.tools import own_key_for

FAKE_KEY = "sk-abcdefgh12345678ij"


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_byo_t', 'x', 'normal', now()) RETURNING id")).scalar()
        # 口粮开池：验「带钥不扣分」先得有分可扣，扣没扣才看得出来
        s.execute(text("INSERT INTO points_ledger (user_id, day, kind, amount, created_at) "
                       "VALUES (:u, current_date, 'bonus', 999999, now())"), {"u": u})
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})   # 级联带走 settings 行
        s.commit()


def _set_key(uid, val, model=None):
    with SessionLocal() as s:
        if model:
            n = s.execute(text(
                "UPDATE agent_settings SET model_choice = :v WHERE user_id = :u"),
                {"v": model, "u": uid}).rowcount
            if not n:
                s.execute(text(
                    "INSERT INTO agent_settings (user_id, model_choice) VALUES (:u, :v)"),
                    {"u": uid, "v": model})
        n = s.execute(text(
            "UPDATE agent_settings SET own_deepseek_key = :v WHERE user_id = :u"),
            {"v": val, "u": uid}).rowcount
        if not n:
            s.execute(text(
                "INSERT INTO agent_settings (user_id, own_deepseek_key) VALUES (:u, :v)"),
                {"u": uid, "v": val})
        s.commit()


# ── 电厂层：带钥现建、不进缓存 ──

def test_get_client_own_key_bypasses_cache():
    """自带钥匙=临时客户端一把一建；平台缓存 _clients 一个字不添（串池=串账）。
    OpenAI 构造不碰网，零真网络。"""
    old = dict(llm._clients)
    try:
        c = get_client("deepseek-flash", api_key="  sk-mine-001  ")
        assert c.api_key == "sk-mine-001"          # strip 执法
        assert str(c.base_url).startswith("https://api.deepseek.com")
        assert "deepseek" not in llm._clients      # 没进缓存
        z = get_client("GLM-5.2", api_key="sk-mine-001")   # 非深平台带钥也按平台路由
        assert str(z.base_url).startswith("https://open.bigmodel.cn")
    finally:
        llm._clients.clear()
        llm._clients.update(old)


# ── 账层：own_key_for 平台闸 ──

def test_own_key_for_platform_gate(uid):
    """有行有钥且型号落 DeepSeek=给钥；非 DeepSeek 平台恒 None（钥匙不吃通义/智谱）；没行=None。"""
    assert own_key_for(SessionLocal(), uid, "deepseek-flash") is None
    _set_key(uid, FAKE_KEY)
    assert own_key_for(SessionLocal(), uid, "deepseek-flash") == FAKE_KEY
    assert own_key_for(SessionLocal(), uid, "deepseek-v4-pro") == FAKE_KEY
    assert own_key_for(SessionLocal(), uid, "qwen3.8-flash") is None
    assert own_key_for(SessionLocal(), uid, "GLM-5.2") is None


# ── 编排层：带钥免扣分 + 下传 + 闸旁路 ──

def test_answer_turn_byo_frees_points(uid, monkeypatch):
    """带钥腿：电厂收到 api_key=账上那把；真烧了 tokens 也一分不扣（无 consume 行）、
    余额纹丝不动；UsageLog 流水照记（账不能骗）。"""
    _set_key(uid, FAKE_KEY, model="deepseek-flash")
    caught = {}
    def fake_chat_once(messages, tools=None, model=None, api_key=None):
        caught["api_key"] = api_key
        return ({"role": "assistant", "content": "自家油真香"}, 300, 120)
    monkeypatch.setattr(orch, "chat_once", fake_chat_once)
    with SessionLocal() as s:
        before = s.execute(text(
            "SELECT coalesce(sum(amount),0) FROM points_ledger WHERE user_id = :u"),
            {"u": uid}).scalar()
        out = orch.answer_turn(s, uid, "用我自己的钥匙")
        consume = s.execute(text(
            "SELECT count(*) FROM points_ledger WHERE user_id = :u AND kind = 'consume'"),
            {"u": uid}).scalar()
        after = s.execute(text(
            "SELECT coalesce(sum(amount),0) FROM points_ledger WHERE user_id = :u"),
            {"u": uid}).scalar()
    assert caught["api_key"] == FAKE_KEY
    assert out["byo"] is True and out["points_spent"] == 0
    assert consume == 0 and before == after          # 一分没扣
    with SessionLocal() as s:
        tok = s.execute(text(
            "SELECT coalesce(sum(tokens),0) FROM usage_logs WHERE user_id = :u"),
            {"u": uid}).scalar()
    assert tok == 420                                # 流水照记 300+120


def test_answer_turn_byo_bypasses_empty_wallet(uid, monkeypatch):
    """零余额户：没钥匙=拒聊（旧闸逐字不变）；带钥匙=照常开口（自家油不欠平台）。"""
    def fake_chat_once(messages, tools=None, model=None, api_key=None):
        return ({"role": "assistant", "content": "穷也能聊"}, 10, 5)
    monkeypatch.setattr(orch, "chat_once", fake_chat_once)
    with SessionLocal() as s:
        poor = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_byo_poor', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    try:
        with SessionLocal() as s:
            out = orch.answer_turn(s, poor, "饿着肚子说话")
        assert out["err"] == "points"                 # 旧闸原样
        _set_key(poor, FAKE_KEY)
        with SessionLocal() as s:
            out = orch.answer_turn(s, poor, "现在呢")
        assert out.get("byo") is True and out["reply"] == "穷也能聊"
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM users WHERE id = :u"), {"u": poor})
            s.commit()


# ── 验钥腿：假 getter 四态，话术永不带钥匙本体 ──

def _resp(code, body=None):
    return SimpleNamespace(status_code=code, json=lambda: body or {})


def test_check_deepseek_key_four_states():
    good = _resp(200, {"balance_infos": [{"total_balance": "12.5"}]})
    ok, msg = check_deepseek_key(FAKE_KEY, getter=lambda *a, **k: good)
    assert ok and "12.5" in msg and FAKE_KEY not in msg
    ok, msg = check_deepseek_key(FAKE_KEY, getter=lambda *a, **k: _resp(401))
    assert not ok and "拒绝" in msg
    def boom(*a, **k):
        raise RuntimeError("连不上")
    ok, msg = check_deepseek_key(FAKE_KEY, getter=boom)
    assert not ok and "网络故障" in msg
    ok, msg = check_deepseek_key("   ")
    assert not ok and msg == "还没填钥匙"


# ── 端点：掩码回显 / 形状闸 / 清除 / 测试腿 / 菜单与选模放宽 ──

def test_set_ownkey_masks_never_shows_raw(uid):
    """回执与账上真值两清：库里存全文（拍板：熟人期明文），嘴上只给掩码。"""
    user = SimpleNamespace(id=uid)
    d = set_ownkey(OwnKeyIn(key=FAKE_KEY), user)
    assert d["configured"] is True
    assert FAKE_KEY not in str(d)                     # 回执里翻不出全文
    assert d["masked"] == f"sk-{'*' * (len(FAKE_KEY) - 7)}{FAKE_KEY[-4:]}"
    assert get_ownkey(user)["masked"] == d["masked"]
    with SessionLocal() as s:                          # 磁盘真值验一遍
        raw = s.execute(text("SELECT own_deepseek_key FROM agent_settings "
                             "WHERE user_id = :u"), {"u": uid}).scalar()
    assert raw == FAKE_KEY
    d2 = set_ownkey(OwnKeyIn(key=""), user)            # 空串=清除
    assert d2 == {"configured": False, "masked": None}


def test_set_ownkey_shape_gate(uid):
    user = SimpleNamespace(id=uid)
    with pytest.raises(HTTPException) as e:
        set_ownkey(OwnKeyIn(key="sk-坏 钥匙\n带控制符"), user)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        set_ownkey(OwnKeyIn(key="x" * 301), user)


def test_test_ownkey_endpoint(uid, monkeypatch):
    """不带 key=测账上存的；账上没钥=422。验钥本体另有假 getter 用例，这里只测腿。"""
    monkeypatch.setattr(main, "check_deepseek_key", lambda k: (True, "假的好"))
    with pytest.raises(HTTPException):                 # 还没存
        main.test_ownkey(OwnKeyTestIn(), SimpleNamespace(id=uid))
    _set_key(uid, FAKE_KEY)
    d = main.test_ownkey(OwnKeyTestIn(), SimpleNamespace(id=uid))
    assert d == {"ok": True, "msg": "假的好"}


def test_model_menu_byo_light_and_set_gate(uid, monkeypatch):
    """平台没 DEEPSEEK 钥匙：带自带钥后 DeepSeek 三路 available 点亮、byo=true；
    非深平台不吃这把钥；set_model 也随之放行（没 .env 也能选）。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    user = SimpleNamespace(id=uid)
    by = {m["id"]: m for m in get_model(user)["models"]}
    assert by["deepseek-flash"]["available"] is False and by["deepseek-flash"]["byo"] is False
    _set_key(uid, FAKE_KEY)
    by = {m["id"]: m for m in get_model(user)["models"]}
    assert by["deepseek-v4-pro"]["available"] is True and by["deepseek-v4-pro"]["byo"] is True
    assert by["GLM-5.2"]["available"] is False and by["GLM-5.2"]["byo"] is False
    set_model(ModelIn(model="deepseek-v4-pro"), user)  # 旧腿这步会 422，带钥放行
    assert get_model(user)["current"] == "deepseek-v4-pro"
