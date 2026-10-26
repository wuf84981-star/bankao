# ============================================================
# S4 第三刀离线单测：知识进度两表+两手+四本账注入
# 核心断言=节点确认往返（不擅建）、根层双胎必炸（部分唯一闸·首刀纪律：
# 兜底闸必须真炸一次给用户看）、进度进注入（账上没有=没学过）
# ============================================================
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import SessionLocal
from backend.main import _system_for
from backend.tools import update_mastery, query_mastery, save_exam_profile


@pytest.fixture()
def uid():
    """临时户口（插完必 commit——不 commit 就是鬼号，前两刀血写的）"""
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_mas_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
        s.commit()


def _ctx(s, u):
    return {"user_id": u, "session": s, "citations": []}


def _count(s, u, table):
    return s.execute(text(
        f"SELECT count(*) FROM {table} WHERE user_id = :u"), {"u": u}).scalar()


def test_new_kp_needs_confirmation(uid):
    """首提知识点：无 create_node 只回人话零写入；用户确认后重调才建点落账"""
    with SessionLocal() as s:
        r = update_mastery({"kp_name": "基期量", "level": "一般掌握",
                            "exam_type": "公务员考试"}, _ctx(s, uid))
        assert "确认" in r and "create_node" in r
        assert _count(s, uid, "knowledge_nodes") == 0
        r2 = update_mastery({"kp_name": "基期量", "level": "一般掌握",
                             "exam_type": "公务员考试", "create_node": True}, _ctx(s, uid))
        assert "新建" in r2
        assert _count(s, uid, "knowledge_nodes") == 1
        assert _count(s, uid, "knowledge_mastery") == 1


def test_upsert_same_kp_single_row(uid):
    """同知识点再报：mastery 一行不增、等级改判、回执带原值（复述确认有据）"""
    a = {"kp_name": "增长率", "exam_type": "公务员考试"}
    with SessionLocal() as s:
        update_mastery({**a, "level": "初步了解", "create_node": True}, _ctx(s, uid))
        r = update_mastery({**a, "level": "薄弱"}, _ctx(s, uid))
        assert "更新" in r and "初步了解" in r   # 回执报出原等级
        assert _count(s, uid, "knowledge_mastery") == 1
        row = s.execute(text(
            "SELECT level, last_learned_at FROM knowledge_mastery WHERE user_id = :u"),
            {"u": uid}).one()
        assert row.level == "薄弱" and row.last_learned_at is not None


def test_root_twin_gate_blows(uid):
    """根层双胎必炸：绕过工具手插同名根节点，部分唯一闸必须拦（首刀纪律）"""
    ins = ("INSERT INTO knowledge_nodes (user_id, exam_type, name, source, sort, created_at) "
           "VALUES (:u, '公务员考试', '线程问题', 'user_edit', 0, now())")
    with SessionLocal() as s:
        s.execute(text(ins), {"u": uid})
        s.commit()
        with pytest.raises(IntegrityError):
            s.execute(text(ins), {"u": uid})
        s.rollback()
        assert _count(s, uid, "knowledge_nodes") == 1


def test_bad_input_human_no_write(uid):
    """坏 level/越界 confidence/空名/无档案无 exam_type：四式人话、两表零写入"""
    with SessionLocal() as s:
        assert "五档" in update_mastery({"kp_name": "x", "level": " mastered",
                                         "exam_type": "t"}, _ctx(s, uid))
        assert "0~100" in update_mastery({"kp_name": "x", "level": "薄弱",
                                          "confidence": 101, "exam_type": "t"}, _ctx(s, uid))
        assert "不能为空" in update_mastery({"kp_name": "", "level": "薄弱",
                                             "exam_type": "t"}, _ctx(s, uid))
        assert "考试档案" in update_mastery({"kp_name": "x", "level": "薄弱"}, _ctx(s, uid))
        assert _count(s, uid, "knowledge_nodes") == 0
        assert _count(s, uid, "knowledge_mastery") == 0


def test_default_primary_exam(uid):
    """不传 exam_type：进度自动挂主考账（判断收后端，首场=主考）"""
    future = (date.today() + timedelta(days=90)).strftime("%Y-%m-%d")
    with SessionLocal() as s:
        save_exam_profile({"exam_type": "事业单位考试", "exam_date": future}, _ctx(s, uid))
        update_mastery({"kp_name": "公文写作", "level": "初步了解", "create_node": True},
                       _ctx(s, uid))
        e = s.execute(text("SELECT exam_type FROM knowledge_mastery WHERE user_id = :u"),
                      {"u": uid}).one().exam_type
        assert e == "事业单位考试"


def test_query_weak_first_and_empty(uid):
    """查询腿：薄弱前置+置信升序；空账回 found=0 的人话（不编进度）"""
    a = {"exam_type": "公务员考试", "create_node": True}
    with SessionLocal() as s:
        assert '"found": 0' in query_mastery({}, _ctx(s, uid))
        update_mastery({**a, "kp_name": "数量关系", "level": "熟练", "confidence": 90}, _ctx(s, uid))
        update_mastery({**a, "kp_name": "资料分析", "level": "一般掌握", "confidence": 60}, _ctx(s, uid))
        update_mastery({**a, "kp_name": "判断推理", "level": "薄弱", "confidence": 20}, _ctx(s, uid))
        import json
        q = json.loads(query_mastery({}, _ctx(s, uid)))
        assert q["学习进度"][0]["知识点"] == "判断推理"   # 薄弱顶到第一
        assert [i["知识点"] for i in q["学习进度"]] == ["判断推理", "资料分析", "数量关系"]


def test_fourth_ledger_injection_and_isolation(uid):
    """四本账：进度行进注入（带真账旗）；乙户注入不见甲户一字"""
    a = {"exam_type": "公务员考试", "create_node": True}
    with SessionLocal() as s:
        update_mastery({**a, "kp_name": "基期量", "level": "薄弱",
                        "subject": "资料分析", "confidence": 30}, _ctx(s, uid))
        out = _system_for(uid, s)
        assert "【学习进度·数据库真账】" in out
        assert "[资料分析] 基期量：薄弱(30)" in out
        other = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_mas_t2', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
        assert "基期量" not in _system_for(other, s)
        s.execute(text("DELETE FROM users WHERE username = '_mas_t2'"))
        s.commit()
