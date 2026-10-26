# ============================================================
# S6 首刀离线单测：时效事件链（F-15/F-26 · D22 甲减量往返 · D25 甲豁免）
# 核心断言=「自动算、不自动落」：create 只落事件不碰计划；apply 要预览后的点头、
# 防重入、mock/sprint 豁免；restore 只回滚没被再动过的行（手改不被覆盖）；
# 事件行会被 03:00 物理删，但「结束次日提恢复」的真值活在 change_logs 里。
# 台件全借 test_plan：EXAM/TODAY/_setup/_activated 原样上岗（新活找旧件）。
# ============================================================
import re
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend.jobs import clean_expired_events
from backend.main import _system_for
from backend.tools import (apply_life_event, create_life_event, edit_plan_item,
                           forget_life_event, restore_plan_items, _half)
from test_plan import EXAM, TODAY, _activated, _ctx, _setup


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_life_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
        s.commit()


def _eid(out: str) -> int:
    """回执里抠 event_id（格式变体只认这一处）"""
    return int(re.search(r"event_id=(\d+)", out).group(1))


def test_half_rule():
    assert _half(120) == 60 and _half(45) == 25 and _half(47) == 25
    assert _half(10) == 5 and _half(5) == 5   # 下限 5 分钟：减无可减也留一口气


def _evt(s, u, start, end, content="去杭州出差三天"):
    """create 直调小件（票闸上下文照旧）"""
    return create_life_event({"content": content, "start_date": str(start),
                              "end_date": str(end)}, _ctx(s, u))


def test_create_gates_reject_and_leave_nothing(uid):
    """三关拒收且一行不落：倒置、过去、超界、坏格式——模型的算术由工具闸复检"""
    with SessionLocal() as s:
        c = _ctx(s, uid)
        assert "日期倒置" in _evt(s, uid, TODAY + timedelta(days=5), TODAY + timedelta(days=3))
        assert "就已经结束了" in _evt(s, uid, TODAY - timedelta(days=4), TODAY - timedelta(days=2))
        assert "超过 90 天" in _evt(s, uid, TODAY, TODAY + timedelta(days=95))
        r = create_life_event({"content": "x", "start_date": "下周三",
                               "end_date": str(TODAY)}, c)
        assert "YYYY-MM-DD" in r
        assert s.scalar(text("SELECT count(*) FROM life_events WHERE user_id = :u"),
                        {"u": uid}) == 0
        # content 空也拒（在日期关之前先验）
        assert "不能空" in create_life_event({"start_date": str(TODAY),
                                              "end_date": str(TODAY)}, c)


def test_create_preview_touches_no_plan(uid):
    """登记≠减量：事件落账、预览带逐日数字、计划 est 一字没动（D22 甲的定盘星）"""
    with SessionLocal() as s:
        _setup(s, uid)
        _activated(s, uid)
        r = _evt(s, uid, TODAY + timedelta(days=5), TODAY + timedelta(days=7))
        assert "减量预览" in r and "event_id=" in r and "→" in r
        assert "rule" in r   # 回执自带规矩行：征询话术钉在账上
        eid = _eid(r)
        row = s.execute(text("SELECT applied_at, content FROM life_events WHERE id = :i"),
                        {"i": eid}).first()
        assert row.applied_at is None and row.content == "去杭州出差三天"
        est = s.scalar(text("SELECT min(est_minutes) FROM plan_items WHERE user_id = :u"),
                       {"u": uid})
        assert est == 60   # _good_days 的 60 分钟原样——预览只是预览


def test_apply_roundtrip_exempt_reentry(uid):
    """apply：区间内 pending 减半、区间外与 mock 不动、留痕三要素、防重入闸"""
    with SessionLocal() as s:
        _setup(s, uid)
        pid, first_id = _activated(s, uid)
        d5 = TODAY + timedelta(days=5)
        # 区间内栽一条 mock（D25 甲：模考砍半=假模考，豁免）
        mock_id = s.scalar(text(
            "INSERT INTO plan_items (plan_id, user_id, date, subject, task_desc, "
            "est_minutes, kind, status) VALUES (:p, :u, :d, '行测', '全真模考', 180, "
            "'mock', 'pending') RETURNING id"), {"p": pid, "u": uid, "d": d5})
        r = _evt(s, uid, d5, TODAY + timedelta(days=7))
        eid = _eid(r)
        a = apply_life_event({"event_id": eid}, _ctx(s, uid))
        assert "已按预览减量" in a and "log_id=" in a
        log_id = int(re.search(r"log_id=(\d+)", a).group(1))
        assert s.scalar(text("SELECT est_minutes FROM plan_items WHERE id = :i"),
                        {"i": mock_id}) == 180          # 豁免条原地不动
        assert s.scalar(text("SELECT est_minutes FROM plan_items WHERE user_id = :u "
                             "AND date = :d AND kind = 'exercise'"),
                        {"u": uid, "d": d5}) == 30      # 60→30
        assert s.scalar(text("SELECT est_minutes FROM plan_items WHERE id = :i"),
                        {"i": first_id}) == 60          # 区间外（今天）不受牵连
        assert s.scalar(text("SELECT applied_at IS NOT NULL FROM life_events WHERE id = :i"),
                        {"i": eid})
        log = s.execute(text(
            "SELECT id, snapshot FROM plan_change_logs WHERE user_id = :u "
            "AND actor = 'life_event' ORDER BY id"), {"u": uid}).first()
        assert log.snapshot["phase"] == "apply" and log.snapshot["end_date"] == str(TODAY + timedelta(days=7))
        assert "已减过量" in apply_life_event({"event_id": eid}, _ctx(s, uid))   # 防重入


def test_restore_skips_touched_and_is_idempotent(uid):
    """恢复的手术刀：只回滚「之后没被再动过」的行；手改条跳过；二次调用无事可回"""
    with SessionLocal() as s:
        _setup(s, uid)
        pid, first_id = _activated(s, uid)
        d5, d6 = TODAY + timedelta(days=5), TODAY + timedelta(days=6)
        r = _evt(s, uid, d5, d6)
        eid = _eid(r)
        a = apply_life_event({"event_id": eid}, _ctx(s, uid))
        log_id = int(re.search(r"log_id=(\d+)", a).group(1))
        # 用户在 d6 那条上自己改过（走正门 edit 手，force 无需——60 分不超限）
        d6_item = s.scalar(text("SELECT id FROM plan_items WHERE plan_id = :p AND date = :d"),
                           {"p": pid, "d": d6})
        edit_plan_item({"item_id": d6_item, "est_minutes": 90,
                        "reason": "用户加量"}, _ctx(s, uid))
        out = restore_plan_items({"log_id": log_id}, _ctx(s, uid))
        assert "已恢复 1 条" in out and "1 条因用户已改动/已恢复而跳过" in out
        assert s.scalar(text("SELECT est_minutes FROM plan_items WHERE id = :i"),
                        {"i": d6_item}) == 90           # 手改不被覆盖（历史事实原则）
        assert s.scalar(text("SELECT est_minutes FROM plan_items WHERE plan_id = :p "
                             "AND date = :d"), {"p": pid, "d": d5}) == 60   # d5 回滚
        assert "没有可回滚" in restore_plan_items({"log_id": log_id}, _ctx(s, uid))
        assert s.scalar(text("SELECT count(*) FROM plan_change_logs WHERE user_id = :u "
                             "AND snapshot ->> 'phase' = 'restore'"), {"u": uid}) == 1
        assert "票闸" in restore_plan_items({"log_id": 999999}, _ctx(s, uid))


def test_forget_paths(uid):
    """忘事件不拒绝（F-15② 与 BR-07 同价值观）；减过再忘：账留下、log_id 递到手边"""
    with SessionLocal() as s:
        _setup(s, uid)
        _activated(s, uid)
        r = _evt(s, uid, TODAY + timedelta(days=5), TODAY + timedelta(days=7))
        eid = _eid(r)
        out = forget_life_event({"event_id": eid}, _ctx(s, uid))
        assert "已删除" in out
        assert s.scalar(text("SELECT count(*) FROM life_events WHERE id = :i"),
                        {"i": eid}) == 0
        assert "票闸" in forget_life_event({"event_id": eid}, _ctx(s, uid))   # 二次=没有此账
        # 已 apply 的事件：删账但计划不自动回滚，log_id 带出（区间错开：别把 d5 再砍一遍）
        r2 = _evt(s, uid, TODAY + timedelta(days=10), TODAY + timedelta(days=11))
        eid2 = _eid(r2)
        apply_life_event({"event_id": eid2}, _ctx(s, uid))
        out2 = forget_life_event({"event_id": eid2}, _ctx(s, uid))
        assert "未自动回滚" in out2 and "log_id=" in out2
        # 验的是 eid2 减过的 d10（30）没随事件删除被回滚——不是首刀那个从未 apply 的 d5（60）
        assert s.scalar(text("SELECT est_minutes FROM plan_items WHERE user_id = :u "
                             "AND date = :d"), {"u": uid, "d": TODAY + timedelta(days=10)}) == 30


def test_inject_three_states(uid):
    """注入三态：无事件安静 / 未确认挂『要一句话』/ 已减量按减后口径 / 结束次日提恢复
    （恢复行=无状态一次性触发：end_date==昨天 只真一天）"""
    out0 = _sys(uid)
    # 注意针尖：SYSTEM_PROMPT 里就有「【生活事件】段」字样——只验注入段的账本抬头，别误伤规矩文
    assert "【生活事件·数据库真账】" not in out0
    with SessionLocal() as s:
        _setup(s, uid)
        _activated(s, uid)
        r = _evt(s, uid, TODAY, TODAY + timedelta(days=2))
        eid = _eid(r)
    assert "已登记但减量未经用户确认" in _sys(uid)
    with SessionLocal() as s:
        apply_life_event({"event_id": eid}, _ctx(s, uid))
    out = _sys(uid)
    assert "进行中" in out and "已减半" in out
    # 结束次日：把 apply 账的 end_date 拨到昨天验触发；拨远一天验熄灭
    with SessionLocal() as s:
        s.execute(text("UPDATE plan_change_logs SET snapshot = "
                       "jsonb_set(snapshot, '{end_date}', to_jsonb(CAST(:y AS text))) "
                       "WHERE user_id = :u AND actor = 'life_event' "
                       "AND snapshot ->> 'phase' = 'apply'"),
                  {"u": uid, "y": str(TODAY - timedelta(days=1))})
        s.execute(text("DELETE FROM life_events WHERE id = :i"), {"i": eid})   # 模拟 03:00 清账
        s.commit()
    out2 = _sys(uid)
    assert "已于昨日结束" in out2 and "log_id=" in out2
    with SessionLocal() as s:
        s.execute(text("UPDATE plan_change_logs SET snapshot = "
                       "jsonb_set(snapshot, '{end_date}', to_jsonb(CAST(:y AS text))) "
                       "WHERE user_id = :u AND actor = 'life_event'"),
                  {"u": uid, "y": str(TODAY - timedelta(days=2))})
        s.commit()
    assert "已于昨日结束" not in _sys(uid)


def _sys(uid):
    with SessionLocal() as s:
        return _system_for(uid, s)


def test_clean_expired_events(uid):
    """03:00 清理本体（函数可直喂日期，不等凌晨）：昨天到期的删、今天还活的留。
    到期条直栽 SQL——它「登记当天合法」，走 create 反被过去的闸拒（闸没错，栽法要对）。"""
    with SessionLocal() as s:
        yid = s.scalar(text(
            "INSERT INTO life_events (user_id, content, type, start_at, end_at, created_at) "
            "VALUES (:u, '已结束的旧事件', 'one_time', :a, :b, now()) RETURNING id"),
            {"u": uid, "a": TODAY - timedelta(days=2), "b": TODAY - timedelta(days=1)})
        t = _evt(s, uid, TODAY, TODAY + timedelta(days=1))
        tid = _eid(t)
        s.commit()
    assert clean_expired_events() >= 1
    with SessionLocal() as s:
        assert s.scalar(text("SELECT count(*) FROM life_events WHERE id = :i"), {"i": yid}) == 0
        assert s.scalar(text("SELECT count(*) FROM life_events WHERE id = :i"), {"i": tid}) == 1
        s.execute(text("UPDATE life_events SET end_at = :y WHERE id = :i"),
                  {"y": TODAY - timedelta(days=1), "i": tid})   # 把它也变成到期
        s.commit()
    assert clean_expired_events(TODAY) >= 1
    with SessionLocal() as s:
        assert s.scalar(text("SELECT count(*) FROM life_events WHERE id = :i"), {"i": tid}) == 0
