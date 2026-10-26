# ============================================================
# D83 计划页换真离线单测（main.py plan 四腿：三读一写）
# 断言主线：summary 主考+active+draft 三本账、calendar 逐日聚合
# （partial 不算完成的诚实口径）、day 形状与参数格式闸、
# 打卡开关限闸与幂等、票闸 404 不泄存在（别人的/归档草案的都不可动）。
# 家法：ORM 直 add seed（Python 端 default 生效，raw SQL 会漏 NOT NULL 列——
# exam_profiles 前车之鉴）；直调 route 传 SimpleNamespace 绕 Depends（test_stream 先例）；
# users  CASCADE 带走全部种子。
# ============================================================
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.db import SessionLocal
from backend.main import (PlanCheckIn, plan_calendar, plan_day,
                          plan_item_check, plan_summary)
from backend.models import ExamProfile, Plan, PlanItem


def _ins_user(s, name):
    return s.execute(text(
        "INSERT INTO users (username, password_hash, status, created_at) "
        "VALUES (:n, 'x', 'normal', now()) RETURNING id"), {"n": name}).scalar()


@pytest.fixture()
def seed():
    """A 户：主考+active 计划（10-18 pending+done、10-19 partial）+两版草案
    （v1 空、v3 带 2 条）；B 户：什么都没有（票闸难家）。"""
    with SessionLocal() as s:
        ua = _ins_user(s, "_plan_a")
        ub = _ins_user(s, "_plan_b")
        s.add(ExamProfile(user_id=ua, exam_type="公务员考试",
                          exam_date=date(2026, 12, 31), is_primary=True))
        act = Plan(user_id=ua, exam_type="公务员考试", start_date=date(2026, 10, 1),
                   sprint_start_date=date(2026, 12, 1), status="active", version=2)
        d1 = Plan(user_id=ua, exam_type="公务员考试", start_date=date(2026, 10, 1),
                  sprint_start_date=date(2026, 12, 1), status="draft", version=1)
        d2 = Plan(user_id=ua, exam_type="公务员考试", start_date=date(2026, 10, 1),
                  sprint_start_date=date(2026, 12, 1), status="draft", version=3)
        s.add_all([act, d1, d2])
        s.flush()
        it1 = PlanItem(plan_id=act.id, user_id=ua, date=date(2026, 10, 18),
                       subject="行测", task_desc="资料分析 2 组", est_minutes=30,
                       kind="exercise")
        it2 = PlanItem(plan_id=act.id, user_id=ua, date=date(2026, 10, 18),
                       subject="申论", task_desc="真题精读 1 篇", est_minutes=40,
                       kind="review", status="done")
        it3 = PlanItem(plan_id=act.id, user_id=ua, date=date(2026, 10, 19),
                       subject="常识", task_desc="时政积累", est_minutes=20,
                       kind="new", status="partial", done_note="背了一半")
        dt1 = PlanItem(plan_id=d2.id, user_id=ua, date=date(2026, 10, 20),
                       subject="行测", task_desc="草案任务", est_minutes=10, kind="new")
        dt2 = PlanItem(plan_id=d2.id, user_id=ua, date=date(2026, 10, 21),
                       subject="行测", task_desc="草案任务二", est_minutes=10, kind="new")
        s.add_all([it1, it2, it3, dt1, dt2])
        s.commit()
        yield SimpleNamespace(ua=ua, ub=ub, act=act.id, it1=it1.id,
                              it2=it2.id, it3=it3.id, dt1=dt1.id)
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = ANY(:ids)"),
                  {"ids": [ua, ub]})
        s.commit()


def test_summary_three_ledgers(seed):
    """页头总账：主考真值 + active v2 + 草案取最高版（v3/2 条，v1 不入眼）。"""
    out = plan_summary(user=SimpleNamespace(id=seed.ua))
    assert out["exam"] == {"name": "公务员考试", "date": "2026-12-31"}
    assert out["active"]["version"] == 2
    assert out["draft"]["version"] == 3 and out["draft"]["items"] == 2


def test_summary_no_profile(seed):
    """B 户无档案：三本账全 None——页面靠它显示引导，不报错。"""
    out = plan_summary(user=SimpleNamespace(id=seed.ub))
    assert out == {"exam": None, "active": None, "draft": None}


def test_calendar_roll_up(seed):
    """日账：10-18 三条里 done 只算 1（partial 不算完成）；10-19 done=0。"""
    out = plan_calendar(month="2026-10", user=SimpleNamespace(id=seed.ua))
    days = {d["date"]: d for d in out["days"]}
    assert days["2026-10-18"]["total"] == 2 and days["2026-10-18"]["done"] == 1
    assert days["2026-10-19"] == {"date": "2026-10-19", "total": 1, "done": 0}


def test_calendar_format_gate(seed):
    with pytest.raises(HTTPException) as ei:
        plan_calendar(month="2026/10", user=SimpleNamespace(id=seed.ua))
    assert ei.value.status_code == 400


def test_calendar_no_active_empty(seed):
    out = plan_calendar(month="2026-10", user=SimpleNamespace(id=seed.ub))
    assert out["days"] == []


def test_day_detail_and_gate(seed):
    items = plan_day(date="2026-10-18", user=SimpleNamespace(id=seed.ua))["items"]
    assert [i["id"] for i in items] == sorted(i["id"] for i in items)
    assert {"id": seed.it1, "subject": "行测", "task": "资料分析 2 组",
            "est_minutes": 30, "kind": "exercise", "status": "pending"} in items
    with pytest.raises(HTTPException) as ei:
        plan_day(date="10月18", user=SimpleNamespace(id=seed.ua))
    assert ei.value.status_code == 400


def _status(iid):
    with SessionLocal() as s:
        return s.execute(text("SELECT status, completed_at FROM plan_items "
                              "WHERE id = :i"), {"i": iid}).first()


def test_check_tick_and_undo(seed):
    """勾→done+盖时间戳；撤→pending+时间戳抹掉（本人的手，误勾可撤）。"""
    u = SimpleNamespace(id=seed.ua)
    assert plan_item_check(seed.it1, PlanCheckIn(done=True), user=u)["status"] == "done"
    row = _status(seed.it1)
    assert row.status == "done" and row.completed_at is not None
    assert plan_item_check(seed.it1, PlanCheckIn(done=False), user=u)["status"] == "pending"
    row = _status(seed.it1)
    assert row.status == "pending" and row.completed_at is None


def test_check_idempotent_and_partial(seed):
    """done 再勾/重撤都幂等报现账不动时间；partial 勾升 done、撤不动它
    （口述账页面不抹）。"""
    u = SimpleNamespace(id=seed.ua)
    again = plan_item_check(seed.it2, PlanCheckIn(done=True), user=u)
    assert again == {"id": seed.it2, "status": "done"}
    assert _status(seed.it2).status == "done"
    back = plan_item_check(seed.it3, PlanCheckIn(done=False), user=u)
    assert back["status"] == "partial" and _status(seed.it3).status == "partial"
    up = plan_item_check(seed.it3, PlanCheckIn(done=True), user=u)
    assert up["status"] == "done"


def test_check_ticket_gate(seed):
    """票闸：B 户勾 A 户任务 404；谁勾草案版任务也 404（active 才有门）。"""
    with pytest.raises(HTTPException) as ei:
        plan_item_check(seed.it1, PlanCheckIn(done=True), user=SimpleNamespace(id=seed.ub))
    assert ei.value.status_code == 404
    with pytest.raises(HTTPException) as ei2:
        plan_item_check(seed.dt1, PlanCheckIn(done=True), user=SimpleNamespace(id=seed.ua))
    assert ei2.value.status_code == 404
