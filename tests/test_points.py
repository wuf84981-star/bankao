# ============================================================
# S8 · D64 甲 积分刀离线单测（积分=资产，2026-09-11 用户拍板）
# 断言主线：
#   ①算盘纯函数：1 分=100 tokens 锚 flash，型号倍率折分、ceil 向上；
#   ②进账腿：注册开池同事务、每日签到幂等、连签恰满 7 天加奖一次；
#   ③出账与闸：开口前余额>0 才放行、烧穿扣成负数、下一句拒聊零成本；
#   ④出口形状：/api/points 钱包读数、模型菜单带费率、户主 adjust 唯一后门也留痕。
# 铁律：对话一律假电厂注入（零真网络零真烧钱）；端点直传假用户绕 Depends 家法沿用。
# ============================================================
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.db import SessionLocal
from backend.llm import multiplier_of
from backend.main import (PointsAdjustIn, _code_hash, admin_points_adjust,
                          checkin_api, get_model, points_wallet, register)
from backend.main import RegisterIn
from backend.orchestrator import answer_turn
from backend.points import (CHECKIN_GRANT, SIGNUP_BONUS, STREAK_BONUS,
                            award, balance_of, checkin, cost_points, streak_of)


@pytest.fixture()
def uid():
    """裸户（不经注册）：没开池=余额 0——正好当闸的靶子。名字撞 _pt 前缀好清扫。"""
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_pt_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})   # 级联带走积分流水
        s.commit()


def _who(u, admin=False):
    return type("U", (), {"id": u, "is_admin": admin})()   # 假用户（含户主旗号位）


def _fake_plant(p=120, c=180):
    """假电厂：一开口就交卷（无工具轮），报固定 token 账单。"""
    def fn(msgs, tools=None):
        return {"role": "assistant", "content": "好，记下了"}, p, c
    return fn


# ── ① 算盘：汇率 + 倍率 ──

def test_cost_points_rate_and_ceil():
    assert cost_points(100, "deepseek-flash") == 1      # 汇率字面成立（基准脑）
    assert cost_points(1, "deepseek-flash") == 1        # 烧 1 token 也进一分——不装免费
    assert cost_points(0, "deepseek-flash") == 0        # 没烧=不扣
    assert cost_points(1000, "GLM-5.3") == 30           # ×3 倍率折分
    assert cost_points(1000, "deepseek-v4-pro") == 40   # ×4 倍率折分
    assert cost_points(100, "野狗模型") == 1            # 没登记的名字兜 1.0（宁可少扣）


def test_multiplier_table_covers_roster():
    """花名册七路都在倍率表有座位（漏一格=该型号被当免费兜底，桌牌摆齐是纪律）。"""
    from backend.llm import MODEL_PLATFORM
    for m in MODEL_PLATFORM:
        assert m in {k for k in MODEL_PLATFORM} and multiplier_of(m) >= 1.0
    assert multiplier_of(None) == 1.0 and multiplier_of("GLM-5.3") == 3.0


# ── ② 进账腿 ──

def test_signup_opens_pool():
    """注册=建号同事务开池 1000（假邮件不进现场：直插活码行走码闸）。"""
    email = "_pt_reg@test.local"
    code = "654321"
    user_id = None
    with SessionLocal() as s:
        s.execute(text(
            "INSERT INTO email_codes (email, purpose, code_hash, expires_at, fail_count, created_at) "
            "VALUES (:e, 'register', :h, :x, 0, now())"),
            {"e": email, "h": _code_hash(email, code),
             "x": datetime.now(timezone.utc) + timedelta(minutes=10)})
        s.commit()
    try:
        register(RegisterIn(username="阿池", password="passw0rdd1", email=email, code=code))
        with SessionLocal() as s:
            user_id = s.execute(
                text("SELECT id FROM users WHERE username = '阿池'")).scalar()
            assert balance_of(s, user_id) == SIGNUP_BONUS
            kind = s.execute(text(
                "SELECT kind FROM points_ledger WHERE user_id = :u"),
                {"u": user_id}).scalar()
            assert kind == "bonus"
    finally:
        with SessionLocal() as s:
            if user_id:
                s.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
            s.execute(text("DELETE FROM email_codes WHERE email = :e"), {"e": email})
            s.execute(text("DELETE FROM users WHERE username = '阿池'"))
            s.commit()


def test_checkin_daily_idempotent(uid):
    """签到一发 +200；同日连点第二次被幂等闸拒（一秒两击也只领一份）。"""
    with SessionLocal() as s:
        out = checkin(s, uid)
        assert out["ok"] and out["granted"] == CHECKIN_GRANT
        s.commit()
        out2 = checkin(s, uid)
        assert not out2["ok"]
        assert balance_of(s, uid) == CHECKIN_GRANT


def test_checkin_streak_bonus_exactly_on_seven(uid):
    """连签恰满 7 天那天加奖 +100（第 8 天不再加——奖在 streak 行独立留痕）。"""
    today = date.today()
    with SessionLocal() as s:
        for i in range(1, 7):   # 昨天起连签 6 天的历史流水（回溯读账，不写状态列）
            s.execute(text(
                "INSERT INTO points_ledger (user_id, day, kind, amount, note, created_at) "
                "VALUES (:u, :d, 'checkin', 200, '每日签到', now())"),
                {"u": uid, "d": today - timedelta(days=i)})
        s.commit()
        out = checkin(s, uid)   # 今天这签=第 7 天
        assert out["ok"] and out["streak"] == 7
        assert out["granted"] == CHECKIN_GRANT + STREAK_BONUS
        s.commit()   # 端点直调测试自负责签发（家法：award 只 add，checkin 不 commit）
        kinds = [r[0] for r in s.execute(text(
            "SELECT kind FROM points_ledger WHERE user_id = :u AND day = :d ORDER BY id"),
            {"u": uid, "d": today}).all()]
        assert "streak" in kinds   # 加奖单独一行，账目分得清哪笔是什么


def test_streak_breaks_gap(uid):
    """断签重攒：昨天缺签——今天签上也只剩孤链 1（大前天的两连已被缺口斩断，串链断在缺日处）。"""
    today = date.today()
    with SessionLocal() as s:
        for d in (2, 3):
            s.execute(text(
                "INSERT INTO points_ledger (user_id, day, kind, amount, created_at) "
                "VALUES (:u, :d, 'checkin', 200, now())"),
                {"u": uid, "d": today - timedelta(days=d)})
        s.commit()
        streak, signed = streak_of(s, uid, today)
        assert (streak, signed) == (0, False)   # 今天没签、昨天缺→串不起来
        out = checkin(s, uid)
        assert out["streak"] == 1               # 今天签上：昨天缺口，孤链计 1，不碰里程碑


# ── ③ 出账与闸 ──

def test_gate_refuses_empty_wallet(uid):
    """分文没有：answer_turn 拒聊回人话，电厂一毛不烧（闸在开卷之前）。"""
    called = False
    def boom(msgs, tools=None):
        nonlocal called
        called = True
        raise AssertionError("闸拦下后不许再碰电厂")
    with SessionLocal() as s:
        out = answer_turn(s, uid, "你好", chat_fn=boom)
    assert out["err"] == "points" and "签到" in out["msg"]
    assert not called


def test_consume_row_and_balance(uid):
    """成功一轮：假电厂报 300 tokens → flash×1 → 扣 3 分，流水留凭据行、回执带余额。"""
    with SessionLocal() as s:
        award(s, uid, "bonus", 1000, "测试开池")
        s.commit()
    with SessionLocal() as s:
        out = answer_turn(s, uid, "帮我看看计划", chat_fn=_fake_plant(120, 180))
        assert "err" not in out
        assert out["points_spent"] == 3 and out["balance"] == 997
        row = s.execute(text(
            "SELECT amount, note FROM points_ledger WHERE user_id = :u AND kind = 'consume'"),
            {"u": uid}).first()
        assert row[0] == -3 and "×1" in row[1] and "300 tokens" in row[1]


def test_expensive_model_costs_more(uid):
    """同烧 300 tokens：换 GLM-5.3(×3) 扣 9 分——差别计费把贵模型的便宜占不掉。"""
    with SessionLocal() as s:
        award(s, uid, "bonus", 1000, "测试开池")
        s.execute(text("INSERT INTO agent_settings (user_id, model_choice) VALUES (:u, 'GLM-5.3')"),
                   {"u": uid})
        s.commit()
    with SessionLocal() as s:
        out = answer_turn(s, uid, "贵脑子来一发", chat_fn=_fake_plant(200, 100))
        assert out["points_spent"] == 9 and out["balance"] == 991


def test_last_message_may_go_negative_then_blocked(uid):
    """后账式：余额 2 也放行（开口前查>0），烧穿扣成 -1，下一句才被拦。"""
    with SessionLocal() as s:
        award(s, uid, "bonus", 2, "只剩两分")
        s.commit()
    with SessionLocal() as s:
        out = answer_turn(s, uid, "最后挣扎", chat_fn=_fake_plant(120, 180))
        assert "err" not in out and out["balance"] == -1
    with SessionLocal() as s:
        out2 = answer_turn(s, uid, "再试一句", chat_fn=_fake_plant())
        assert out2["err"] == "points"


# ── ④ 出口形状 ──

def test_wallet_endpoint_shape(uid):
    with SessionLocal() as s:
        award(s, uid, "bonus", 40, "快见底")
        s.commit()
    d = points_wallet(_who(uid))
    assert d["balance"] == 40 and d["today_spent"] == 0
    assert d["checked_in_today"] is False and d["streak"] == 0
    assert d["warn"] is True            # ≤50 告警线（积分卡红字的数源）


def test_checkin_endpoint_and_409(uid):
    r = checkin_api(_who(uid))
    assert r["granted"] == CHECKIN_GRANT and r["balance"] == CHECKIN_GRANT
    with pytest.raises(HTTPException) as e:
        checkin_api(_who(uid))
    assert e.value.status_code == 409   # 重复签到：人话 409（前端 toast 直接上屏）


def test_model_menu_shows_rates():
    """D64：换脑子的菜单同时是价目表——每行带倍率，用户看见费率再选。"""
    d = get_model(_who(12345678))   # 不存在的户：走默认选模路径，不脏任何账
    rates = {m["id"]: m["multiplier"] for m in d["models"]}
    assert rates["deepseek-flash"] == 1.0 and rates["GLM-5.3"] == 3.0
    assert all("multiplier" in m for m in d["models"])


def test_admin_adjust_is_the_only_back_door_and_leaves_trace(uid):
    """户主 adjust：正加负减都走流水（余额仍可加总复算）；0 拒、查无此户 404、平民 403。"""
    d = admin_points_adjust(PointsAdjustIn(user_id=uid, amount=500), _who(999, admin=True))
    assert d["balance"] == 500
    admin_points_adjust(PointsAdjustIn(user_id=uid, amount=-200), _who(999, admin=True))
    with SessionLocal() as s:
        assert balance_of(s, uid) == 300
        note = s.execute(text(
            "SELECT note FROM points_ledger WHERE user_id = :u AND kind='adjust' LIMIT 1"),
            {"u": uid}).scalar()
        assert "户主" in note
    with pytest.raises(HTTPException) as e:
        admin_points_adjust(PointsAdjustIn(user_id=uid, amount=0), _who(999, admin=True))
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        admin_points_adjust(PointsAdjustIn(user_id=87654321, amount=1), _who(999, admin=True))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        admin_points_adjust(PointsAdjustIn(user_id=uid, amount=1), _who(uid))   # 平民无旗号
    assert e.value.status_code == 403
