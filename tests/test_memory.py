# ============================================================
# S4 第二刀离线单测：真库+临时户口，验档案三只手与组装器注入闸
# 核心断言=BR-02 轻版闭环：inferred 可存但休眠（不注入），
# 亲口确认后以 user_stated 重存同 key 升格生效——全走 upsert 零新机制
# ============================================================
import json

import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend.main import _system_for
from backend.tools import save_memory, query_memories, set_agent_name


@pytest.fixture()
def uid():
    """临时户口（首刀验过的保命形：插完必 commit，否则就是鬼号）"""
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_mem_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
        s.commit()


def _ctx(s, u):
    return {"user_id": u, "session": s, "citations": []}


def test_user_stated_lands_and_injects(uid):
    """亲口说：落库 confirmed=t，下一轮组装器注入真账"""
    with SessionLocal() as s:
        r = save_memory({"category": "profile", "key": "身份",
                         "content": "2026届应届生"}, _ctx(s, uid))
        assert "已记下" in r
        row = s.execute(text(
            "SELECT confirmed, source FROM memory_facts WHERE user_id = :u"),
            {"u": uid}).one()
        assert (row.confirmed, row.source) == (True, "user_stated")
        assert "[profile] 身份：2026届应届生" in _system_for(uid, s)


def test_inferred_dormant_flagged_not_effective(uid):
    """推测：可存但必休眠——confirmed 后端强制 false；注入挂【待确认】旗
    露面（血案修订：隐身给假升格留窟窿），但绝不进【生效真账】段"""
    with SessionLocal() as s:
        r = save_memory({"category": "habit", "key": "学习时段",
                         "content": "可能偏好夜间学习", "source": "inferred"}, _ctx(s, uid))
        assert "未生效" in r
        out = _system_for(uid, s)
        assert "推测待确认" in out and "学习时段" in out        # 露面带旗
        eff = out.split("【档案·推测待确认")[0]                  # 旗前=生效段
        assert "学习时段" not in eff                            # 生效段绝不收它
        q = json.loads(query_memories({}, _ctx(s, uid)))
        assert q["我推测待确认的"][0]["项"] == "学习时段"   # 查询里以【推测】组露面


def test_confirm_promotes_via_upsert(uid):
    """用户亲口确认后模型以 user_stated 重存同 key：一行不增、自动升格进注入"""
    with SessionLocal() as s:
        save_memory({"category": "habit", "key": "学习时段",
                     "content": "可能偏好夜间学习", "source": "inferred"}, _ctx(s, uid))
        save_memory({"category": "habit", "key": "学习时段",
                     "content": "偏好夜间学习", "source": "user_stated"}, _ctx(s, uid))
        rows = s.execute(text(
            "SELECT confirmed, content FROM memory_facts WHERE user_id = :u"),
            {"u": uid}).all()
        assert len(rows) == 1 and rows[0].confirmed is True
        assert "[habit] 学习时段：偏好夜间学习" in _system_for(uid, s)


def test_bad_input_human_no_write(uid):
    """坏 category/空 key/野 source：人话回且不留行——验伤不留行第五次当法"""
    with SessionLocal() as s:
        assert "只认" in save_memory({"category": "秘法", "key": "k", "content": "v"}, _ctx(s, uid))
        assert "不能为空" in save_memory({"category": "profile", "key": "", "content": "v"}, _ctx(s, uid))
        assert "只认" in save_memory({"category": "profile", "key": "k", "content": "v",
                                      "source": "神谕"}, _ctx(s, uid))
        n = s.execute(text("SELECT count(*) FROM memory_facts WHERE user_id = :u"),
                      {"u": uid}).scalar()
        assert n == 0


def test_agent_name_upsert_single_row(uid):
    """起名：一户一行，改两次不立双胎；注入段带自称指令"""
    with SessionLocal() as s:
        set_agent_name({"name": "小知"}, _ctx(s, uid))
        out = _system_for(uid, s)
        assert "起名『小知』" in out
        set_agent_name({"name": "阿知"}, _ctx(s, uid))
        rows = s.execute(text("SELECT agent_name FROM agent_settings WHERE user_id = :u"),
                         {"u": uid}).all()
        assert len(rows) == 1 and rows[0].agent_name == "阿知"


def test_isolation_two_users(uid):
    """隔离：乙户查账看不到甲户的一字（D4 老规延伸进记忆表族）"""
    with SessionLocal() as s:
        save_memory({"category": "profile", "key": "身份", "content": "甲的秘密"}, _ctx(s, uid))
        other = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_mem_t2', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
        q = json.loads(query_memories({}, _ctx(s, other)))
        assert q["你告诉过我的"] == []
        assert "甲的秘密" not in _system_for(other, s)
        s.execute(text("DELETE FROM users WHERE username = '_mem_t2'"))
        s.commit()
