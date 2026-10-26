# ============================================================
# S4 首刀离线单测：真开发库 + 临时户口（无网络无模型，纯验档案机械件）
# 验：首场自动主考、晋级降旧主、坏日期人话零写入、同型 upsert 不立双胎、
#     get_current_time 带倒计时、DB 部分唯一索引兜底闸（俩主考必炸）
# ============================================================
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import SessionLocal
from backend.tools import save_exam_profile, get_current_time


@pytest.fixture()
def uid():
    """临时户口，用完即删（CASCADE 连档案一起清）"""
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_exam_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()   # 不 commit 户口就是鬼号——别的会话根本看不见它
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
        s.commit()


def _ctx(s, u):
    return {"user_id": u, "session": s, "citations": []}


def _future(days):
    return (date.today() + timedelta(days=days)).isoformat()


def test_first_exam_auto_primary(uid):
    """库里没考试：模型没传 is_primary 也自动升主考（判断收在后端，不劳模型）"""
    with SessionLocal() as s:
        r = save_exam_profile({"exam_type": "公务员考试", "exam_date": _future(90)}, _ctx(s, uid))
        assert "主考" in r and "还剩 90 天" in r
        row = s.execute(text(
            "SELECT is_primary, exam_date FROM exam_profiles WHERE user_id = :u"),
            {"u": uid}).one()
        assert row.is_primary is True


def test_promote_demotes_old_primary(uid):
    """第二场带 is_primary=true：旧主考让位，全场仍恰有一主——PRD 658 唯一时刻恰一"""
    with SessionLocal() as s:
        save_exam_profile({"exam_type": "公务员考试", "exam_date": _future(90)}, _ctx(s, uid))
        save_exam_profile({"exam_type": "事业单位考试", "exam_date": _future(30),
                           "is_primary": True}, _ctx(s, uid))
        old, new = s.execute(text(
            "SELECT is_primary FROM exam_profiles WHERE user_id = :u ORDER BY id"),
            {"u": uid}).all()
        assert (old.is_primary, new.is_primary) == (False, True)


def test_db_gate_rejects_two_primary(uid):
    """DB 兜底闸：绕过写入端直接硬插俩主考，部分唯一索引必须炸——代码有 bug 也无处藏"""
    with SessionLocal() as s:
        save_exam_profile({"exam_type": "公务员考试", "exam_date": _future(90)}, _ctx(s, uid))
        with pytest.raises(IntegrityError):
            s.execute(text(
                "INSERT INTO exam_profiles (user_id, exam_type, exam_date, is_primary, "
                "weekly_reserved_minutes, status, created_at) "
                "VALUES (:u, '硬闯考试', :d, true, 0, 'in-progress', now())"),
                {"u": uid, "d": _future(10)})
        s.rollback()


def test_bad_date_human_no_write(uid):
    """坏日期：回人话给模型自纠，库里零行——验伤不留行第四次当法"""
    with SessionLocal() as s:
        r = save_exam_profile({"exam_type": "公务员考试", "exam_date": "12月4号"}, _ctx(s, uid))
        assert "YYYY-MM-DD" in r
        r2 = save_exam_profile({"exam_type": "公务员考试", "exam_date": "2020-01-01"}, _ctx(s, uid))
        assert "已过去" in r2   # 过去日期也是人话（说岔年份重灾区）
        n = s.execute(text("SELECT count(*) FROM exam_profiles WHERE user_id = :u"),
                      {"u": uid}).scalar()
        assert n == 0


def test_upsert_same_type_no_twins(uid):
    """同 exam_type 再说一遍：更新而非立双胎（模型复述同话的防重）"""
    with SessionLocal() as s:
        save_exam_profile({"exam_type": "公务员考试", "exam_date": _future(90)}, _ctx(s, uid))
        save_exam_profile({"exam_type": "公务员考试", "exam_date": _future(200)}, _ctx(s, uid))
        rows = s.execute(text(
            "SELECT exam_date, is_primary FROM exam_profiles WHERE user_id = :u"),
            {"u": uid}).all()
        assert len(rows) == 1 and rows[0].exam_date == date.fromisoformat(_future(200))
        assert rows[0].is_primary is True   # 没明说主辅的更新：角色原样保留（改日期≠挪主考）


def test_get_time_with_countdown(uid):
    """转正件：ctx 带 session 时倒计时随表出来，主辅标注齐"""
    with SessionLocal() as s:
        save_exam_profile({"exam_type": "公务员考试", "exam_date": _future(88)}, _ctx(s, uid))
        out = get_current_time({}, _ctx(s, uid))
        assert "还剩 88 天" in out and "主考" in out
        # 清掉档案再看空话术（引导模型去登记的路径）
        s.execute(text("DELETE FROM exam_profiles WHERE user_id = :u"), {"u": uid})
        s.commit()
    with SessionLocal() as s:
        out2 = get_current_time({}, _ctx(s, uid))
        assert "还没有登记" in out2
