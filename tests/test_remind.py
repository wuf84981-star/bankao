# ============================================================
# S6 二刀离线单测：每日提醒（F-33 · D24 三甲：落会话账/30分钟窗/模板拼文案）
# 核心断言=系统第一次自己开口：到点读账发提醒（不烧模型）、补偿窗内可补、
# 超窗当天跳过、同日绝不重发（防重发查送达账 remind_on 戳，零新增状态位）。
# tick 扫全表——每次调用必带 only=[测试户]（ignite 白名单闸同款），
# 否则拿开发库里的真账号开刀（真数据污染血案预防）。
# 台件借 test_plan：TODAY/_setup/_activated/_ctx 原样上岗。
# ============================================================
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend.jobs import DEFAULT_REMIND, run_reminder_tick
from backend.main import _system_for
from backend.tools import set_remind_time
from test_plan import TODAY, _activated, _ctx, _setup


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_remind_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
        s.commit()


def _tick(u, hh, mm):
    """直喂时刻的派发（now=今天 hh:mm，白名单只罩测试户）"""
    return run_reminder_tick(datetime.combine(TODAY, time(hh, mm)), only={u})


def _reminders(s, u):
    return s.execute(text(
        "SELECT m.content, c.title FROM messages m "
        "JOIN conversations c ON m.conversation_id = c.id "
        "WHERE c.user_id = :u AND m.remind_on IS NOT NULL ORDER BY m.id"),
        {"u": u}).all()


def test_set_remind_gates_and_lands(uid):
    """改时点的手：坏格式全拒、好格式归一化落账（针尖带【】验注入段，不吃 SYSTEM_PROMPT 字样）"""
    with SessionLocal() as s:
        c = _ctx(s, uid)
        assert "HH:MM" in set_remind_time({"time": "九点"}, c)
        assert "合法钟点" in set_remind_time({"time": "25:00"}, c)
        assert "合法钟点" in set_remind_time({"time": "9:70"}, c)
        assert s.scalar(text("SELECT remind_time FROM agent_settings WHERE user_id = :u"),
                        {"u": uid}) is None            # 拒收不落账
        r = set_remind_time({"time": "9:05"}, c)
        assert "09:05" in r
        assert s.scalar(text("SELECT remind_time FROM agent_settings WHERE user_id = :u"),
                        {"u": uid}) == "09:05"
        out = _system_for(uid, s)
        assert "【每日提醒·账】" in out and "09:05" in out
    with SessionLocal() as s:
        # 摘掉时点=没上过户：默认口径也照实进账（模型答『几点提醒』不抓瞎）
        s.execute(text("UPDATE agent_settings SET remind_time = NULL WHERE user_id = :u"),
                  {"u": uid})
        s.commit()
        assert f"{DEFAULT_REMIND}（默认，未设置过）" in _system_for(uid, s)


def test_tick_due_once_and_reentry(uid):
    """到点发一条：任务清单进会话账、防重发戳同日只一枚；没到点安静"""
    with SessionLocal() as s:
        _setup(s, uid)
        _activated(s, uid)
        set_remind_time({"time": "20:00"}, _ctx(s, uid))
    assert _tick(uid, 19, 59) == 0                       # 差一分钟不开口
    assert _tick(uid, 20, 0) == 1
    assert _tick(uid, 20, 5) == 0                        # 防重入：查送达账不查状态位
    with SessionLocal() as s:
        rows = _reminders(s, uid)
        assert len(rows) == 1 and "每日提醒" in rows[0].content
        assert "刷20题并复盘(60分)" in rows[0].content   # AC①具体任务非空喊
        assert "距考试 40 天" in rows[0].content
        # 提醒真进了历史面：role=assistant 正常一行，回显通道天然可查
        assert s.scalar(text(
            "SELECT role FROM messages m JOIN conversations c ON m.conversation_id = c.id "
            "WHERE c.user_id = :u AND m.remind_on = :d"), {"u": uid, "d": TODAY}) == "assistant"


def test_tick_window_edge_and_skip(uid):
    """补偿窗：+30 分钟整点内补发（重启错过的档），+31 分今天翻篇"""
    with SessionLocal() as s:
        _setup(s, uid)
        _activated(s, uid)
        set_remind_time({"time": "20:00"}, _ctx(s, uid))
    assert _tick(uid, 20, 31) == 0                       # 超窗：宁缺勿半夜扰
    assert _tick(uid, 20, 30) == 1                       # 窗闭界含：PRD 30 分钟口径


def test_tick_care_and_orphan_household(uid):
    """AC②两分支：无计划的孤儿户（提醒自己开窝）与计划全 done 的休整日，都发轻量关心"""
    assert _tick(uid, 20, 0) == 1                        # 从没聊过的户（默认 20:00）
    with SessionLocal() as s:
        rows = _reminders(s, uid)
        assert "今天没排任务" in rows[0].content and "分)" not in rows[0].content
        assert rows[0].title == "每日提醒"               # 会话是提醒自开的
        n = s.scalar(text("SELECT count(*) FROM conversations WHERE user_id = :u"),
                     {"u": uid})
        assert n == 1
        _setup(s, uid)
        _activated(s, uid)
        s.execute(text("UPDATE plan_items SET status = 'done' WHERE user_id = :u"),
                  {"u": uid})
        s.execute(text("DELETE FROM messages WHERE remind_on IS NOT NULL "
                       "AND conversation_id IN (SELECT id FROM conversations "
                       "WHERE user_id = :u)"), {"u": uid})   # 摘戳验第二分支（只摘本户）
        s.commit()
    assert _tick(uid, 20, 0) == 1
    with SessionLocal() as s:
        assert "今天没排任务" in _reminders(s, uid)[-1].content


def test_tick_respects_custom_time(uid):
    """时点真的吃账：21:30 户在 20:00 档必须安静"""
    with SessionLocal() as s:
        _setup(s, uid)
        _activated(s, uid)
        set_remind_time({"time": "21:30"}, _ctx(s, uid))
    assert _tick(uid, 20, 0) == 0
    assert _tick(uid, 21, 45) == 1
    # 明日同日可再发：戳按天等值判，昨天那枚不挡今天（跨天=换日账）
    with SessionLocal() as s:
        s.execute(text("UPDATE messages SET remind_on = :y WHERE remind_on = :d "
                       "AND id IN (SELECT m.id FROM messages m "
                       "JOIN conversations c ON m.conversation_id = c.id "
                       "WHERE c.user_id = :u)"),
                  {"y": TODAY - timedelta(days=1), "d": TODAY, "u": uid})
        s.commit()
    assert _tick(uid, 21, 45) == 1
