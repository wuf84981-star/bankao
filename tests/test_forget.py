# ============================================================
# S4 第四刀离线单测：forget_memory 控制权（BR-07 不得拒绝·物理删除）
# 核心断言=不对称闸：建点要确认、删除不拦删；多命中先列范围；
# 目标 id 也过票闸（编造别户 id 删不动）；不拒绝≠谎报删除
# ============================================================
import json

import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend.main import _system_for
from backend.tools import save_memory, update_mastery, query_memories, forget_memory


@pytest.fixture()
def uid():
    """临时户口（插完必 commit——三刀血写的保命符）"""
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_fgt_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
        s.commit()


def _ctx(s, u):
    return {"user_id": u, "session": s, "citations": []}


def _facts(s, u):
    return s.execute(text(
        "SELECT id, key FROM memory_facts WHERE user_id = :u ORDER BY id"),
        {"u": u}).all()


def test_single_hit_physically_deleted(uid):
    """唯一命中：必删且是物理删——行蒸发、注入消失（无软删标记可留）"""
    with SessionLocal() as s:
        save_memory({"category": "habit", "key": "数学印象",
                     "content": "自认数学差"}, _ctx(s, uid))
        assert "自认数学差" in _system_for(uid, s)
        r = forget_memory({"query": "数学差"}, _ctx(s, uid))
        assert "已删除 1 条" in r
        assert len(_facts(s, uid)) == 0                     # DELETE 不是 UPDATE 旗标
        assert "自认数学差" not in _system_for(uid, s)       # 下轮注入已无此账


def test_multi_hit_lists_then_confirmed_delete(uid):
    """多命中：先列候选一列不删；用户圈定后回传 ids 精确删一条留一条"""
    with SessionLocal() as s:
        save_memory({"category": "habit", "key": "学习时段", "content": "晚上效率高"}, _ctx(s, uid))
        save_memory({"category": "goal", "key": "学习目标", "content": "晚上挤时间学申论"}, _ctx(s, uid))
        r = json.loads(forget_memory({"query": "晚上"}, _ctx(s, uid)))
        assert len(r["多条相似命中"]) == 2
        assert len(_facts(s, uid)) == 2                     # 未确认=不落刀
        first = r["多条相似命中"][0]
        r2 = forget_memory({"query": "晚上", "memory_ids": [first["id"]]}, _ctx(s, uid))
        assert "已删除 1 条" in r2
        gone_key = first["内容"].split("] ")[1].split("：")[0]   # 从候选 label 抠出被删 key
        rest = _facts(s, uid)
        assert len(rest) == 1 and rest[0].key != gone_key        # 删所选、留另一条


def test_valid_delete_never_refused(uid):
    """BR-07：内容再"要紧"也不设判断闸——合法命中直删，无婉拒分支可走"""
    with SessionLocal() as s:
        save_memory({"category": "profile", "key": "紧急联系人",
                     "content": "家里老人生病需要照顾"}, _ctx(s, uid))
        r = forget_memory({"query": "紧急联系人"}, _ctx(s, uid))
        assert "已删除" in r and len(_facts(s, uid)) == 0


def test_zero_hit_honest_not_fake_delete(uid):
    """零命中：如实说没有——不拒绝≠谎报「删好了」（假删除比拒绝更伤信任）"""
    with SessionLocal() as s:
        r = forget_memory({"query": "根本没说过的东西"}, _ctx(s, uid))
        assert "没有任何" in r and "已删除" not in r


def test_forget_progress_keeps_node(uid):
    """删进度只删 mastery 行、节点保留（重报复用；PRD 反向引用语义）"""
    a = {"exam_type": "公务员考试", "create_node": True}
    with SessionLocal() as s:
        update_mastery({**a, "kp_name": "增长率", "level": "薄弱"}, _ctx(s, uid))
        r = forget_memory({"query": "增长率", "target": "progress"}, _ctx(s, uid))
        assert "已删除 1 条" in r
        assert s.execute(text("SELECT count(*) FROM knowledge_mastery WHERE user_id = :u"),
                         {"u": uid}).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM knowledge_nodes WHERE user_id = :u"),
                         {"u": uid}).scalar() == 1          # 节点没陪葬


def test_fabricated_foreign_id_deletes_nothing(uid):
    """越权门：乙户回传甲户条目 id——user_id 票闸兜底，甲行一根毛不掉"""
    with SessionLocal() as s:
        save_memory({"category": "profile", "key": "身份", "content": "甲的秘密"}, _ctx(s, uid))
        mine = _facts(s, uid)[0].id
        other = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_fgt_t2', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
        r = forget_memory({"query": "秘密", "memory_ids": [mine]}, _ctx(s, other))
        assert "没有删掉任何条目" in r
        assert len(_facts(s, uid)) == 1                     # 甲的账完好
        s.execute(text("DELETE FROM users WHERE username = '_fgt_t2'"))
        s.commit()


def test_query_memories_aggregates_progress(uid):
    """14.5 扩权：查账全貌=档案两组+学习进度组一次看全"""
    a = {"exam_type": "公务员考试", "create_node": True}
    with SessionLocal() as s:
        save_memory({"category": "habit", "key": "学习时段", "content": "晚上学"}, _ctx(s, uid))
        update_mastery({**a, "kp_name": "基期量", "level": "一般掌握"}, _ctx(s, uid))
        q = json.loads(query_memories({}, _ctx(s, uid)))
        assert q["你告诉过我的"][0]["项"] == "学习时段"
        assert q["学习进度"][0]["知识点"] == "基期量"
        assert q["学习进度"][0]["等级"] == "一般掌握"
