# ============================================================
# S7 九刀离线单测：记忆页真账三面（D47 甲 · 用户真机戳穿整页 INITIAL 道具）
# 断言主线：读面五本账各归各页签（id 带表前缀防串页、推测行挂 pending+BR-02 旗）；
# confirm=翻列升格（pending 消失、profile 出现，与模型侧同 key 重存等价）；
# forget=物理删（BR-07 票闸——混进别人的 id 静默出局）。
# 零模型零烧钱：纯 SQL 直调 route 函数（SimpleNamespace 绕 Depends 先例）。
# fixture try/finally 自清（test_materials 正范）。
# ============================================================
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.db import SessionLocal
from backend.main import (FactIn, memories_api, memory_confirm_api,
                          memory_forget_api)
from backend.models import (ErrorPattern, ExamProfile, KnowledgeMastery,
                            KnowledgeNode, LifeEvent, MemoryFact, User)


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_mem_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    try:
        yield u
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
            s.commit()   # 级联带走五本账——无论测试过没过都执行


def _seed(u):
    """造一张五脏俱全的账：主考档案 1、推测 1、已确认事实 1、
    带进度节点 1、裸节点 1、错误模式 1、时效事件 1。返回关键 id。"""
    with SessionLocal() as s:
        prof = ExamProfile(user_id=u, exam_type="公考",
                           exam_date=date(2026, 11, 29), target_desc="上岸省厅")
        inferred = MemoryFact(user_id=u, category="habit", key="study_time",
                              content="感觉你常在晚上学习", source="inferred",
                              confirmed=False)
        stated = MemoryFact(user_id=u, category="goal", key="target",
                            content="目标行测 75+", source="user_stated",
                            confirmed=True)
        node1 = KnowledgeNode(user_id=u, exam_type="公考", name="工程问题")
        s.add_all([prof, inferred, stated, node1])
        s.flush()
        node2 = KnowledgeNode(user_id=u, exam_type="公考", name="资料分析")
        mas = KnowledgeMastery(user_id=u, exam_type="公考", kp_ref=node1.id,
                               level="薄弱", confidence=40)
        err = ErrorPattern(user_id=u, exam_type="公考", category="公式",
                           description="把基期看成现期", count=3)
        ev = LifeEvent(user_id=u, content="去杭州出差",
                       start_at=date(2026, 9, 15), end_at=date(2026, 9, 18))
        s.add_all([node2, mas, err, ev])
        s.commit()
        return {"inf": inferred.id, "stated": stated.id,
                "node1": node1.id, "node2": node2.id}


def test_memories_read_maps_five_ledgers(uid):
    """读面：五本账 → 各归各页签，前缀 id、来源旗、meta 文案全对。"""
    _seed(uid)
    rows = memories_api(user=SimpleNamespace(id=uid))["memories"]
    by_id = {r["id"]: r for r in rows}
    # 考试档案进 profile（明确源）
    assert len([k for k in by_id if k.startswith("p")]) == 1
    # 推测行挂 pending、已确认行挂 profile
    cats = {r["id"]: r["cat"] for r in rows}
    pend = [r for r in rows if r["cat"] == "pending"]
    assert len(pend) == 1 and pend[0]["source"] == "推测"
    assert "BR-02" in pend[0]["meta"]
    # 已确认事实与档案同页签、源为明确
    prof_rows = [r for r in rows if r["cat"] == "profile"]
    assert len(prof_rows) == 2 and all(r["source"] == "明确" for r in prof_rows)
    # kp：带进度票 vs 裸节点两样文案
    kp = {r["text"] for r in rows if r["cat"] == "kp"}
    assert any("薄弱" in t and "40" in t for t in kp)
    assert any("还没进度账" in t for t in kp)
    # error：错题账沉淀次数进 meta
    er = [r for r in rows if r["cat"] == "error"][0]
    assert er["text"] == "把基期看成现期" and "3 次" in er["meta"]
    # event：区间与自动失效旗
    ev = [r for r in rows if r["cat"] == "event"][0]
    assert ev["text"] == "去杭州出差" and "BR-03" in ev["meta"]
    assert len(rows) == 7   # 1+2+2+1+1，一行不多一行不少


def test_confirm_upgrades_then_moves_tab(uid):
    """confirm：翻列升格（inferred→user_stated + confirmed=true），
    pending 页签消失、profile 页签出现；重复确认可幂等；他户/不存在 → 404。"""
    ids = _seed(uid)
    ns = SimpleNamespace(id=uid)
    memory_confirm_api(body=FactIn(id=ids["inf"]), user=ns)
    with SessionLocal() as s:
        r = s.get(MemoryFact, ids["inf"])
        assert r.confirmed and r.source == "user_stated"
    cats = {r["id"]: r["cat"] for r in memories_api(user=ns)["memories"]}
    assert cats[f"m{ids['inf']}"] == "profile"        # 搬家了
    assert not [x for x in cats.values() if x == "pending"]
    memory_confirm_api(body=FactIn(id=ids["inf"]), user=ns)   # 再来一次不炸
    # 他户拿真 id 也confirm不动别人的账
    other = SimpleNamespace(id=uid + 99999)
    with pytest.raises(HTTPException) as e1:
        memory_confirm_api(body=FactIn(id=ids["stated"]), user=other)
    assert e1.value.status_code == 404
    with pytest.raises(HTTPException) as e2:
        memory_confirm_api(body=FactIn(id=999999), user=ns)
    assert e2.value.status_code == 404


def test_forget_physically_deletes_with_gate(uid):
    """forget：BR-07 物理删（行从库里真消失，不是打旗）；票闸——
    混进他户 id 静默出局、回执只数真删的；空清单直接空手回。"""
    ids = _seed(uid)
    ns = SimpleNamespace(id=uid)
    with SessionLocal() as s:
        thief = User(username="_mem_t2", password_hash="x", status="normal")
        s.add(thief)
        s.flush()
        loot = MemoryFact(user_id=thief.id, category="goal", key="k",
                          content="别人的账", source="user_stated",
                          confirmed=True)
        s.add(loot)
        s.commit()
        loot_id = loot.id
    try:
        r = memory_forget_api(
            body=FactIn(ids=[ids["inf"], ids["stated"], loot_id, 999999]),
            user=ns)
        assert sorted(r["deleted"]) == sorted([ids["inf"], ids["stated"]])
        with SessionLocal() as s:
            assert s.get(MemoryFact, ids["inf"]) is None          # 真没了
            assert s.get(MemoryFact, loot_id) is not None         # 别人的伤不到
        assert memories_api(user=ns)["memories"] == [
            x for x in memories_api(user=ns)["memories"]
            if not x["id"].startswith("m")]                       # m 前缀清零
        assert memory_forget_api(body=FactIn(ids=[]), user=ns)["deleted"] == []
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM users WHERE username = '_mem_t2'"))
            s.commit()


# ── D85 记忆修改腿：F-13 AC②「页面编辑与指令编辑等效落库」补页门 ──

def test_fact_edit_roundtrip_and_upgrades(uid):
    """改事实：content 换新 + 同翻升格列（亲手改=明确说，pending 行改完搬家
    profile）；空文 422 拦门口；他户/不存在 404 同句式。"""
    from backend.main import FactEdit, memory_fact_edit_api
    ids = _seed(uid)
    ns = SimpleNamespace(id=uid)
    memory_fact_edit_api(body=FactEdit(id=ids["inf"], content="我是早上学习的人"),
                         user=ns)
    with SessionLocal() as s:
        r = s.get(MemoryFact, ids["inf"])
        assert r.content == "我是早上学习的人"
        assert r.source == "user_stated" and r.confirmed   # 升格同 shape
    cats = {x["id"]: x["cat"] for x in memories_api(user=ns)["memories"]}
    assert cats[f"m{ids['inf']}"] == "profile"             # 改完自己搬进档案
    with pytest.raises(HTTPException) as e1:
        memory_fact_edit_api(body=FactEdit(id=ids["stated"], content="   "), user=ns)
    assert e1.value.status_code == 422
    with pytest.raises(HTTPException) as e2:
        memory_fact_edit_api(body=FactEdit(id=ids["stated"], content="x" * 2001), user=ns)
    assert e2.value.status_code == 422
    with pytest.raises(HTTPException) as e3:
        memory_fact_edit_api(body=FactEdit(id=ids["stated"], content="偷账"),
                             user=SimpleNamespace(id=uid + 99999))
    assert e3.value.status_code == 404


def test_mastery_edit_roundtrip_and_gates(uid):
    """页面换档：薄弱→熟练且 confidence 钉 100（亲口说的满信）；读面 text
    跟着变；越档 422、他户 404。"""
    from backend.main import MasteryEdit, memory_mastery_edit_api
    ids = _seed(uid)
    ns = SimpleNamespace(id=uid)
    with SessionLocal() as s:
        mid = s.execute(text("SELECT id FROM knowledge_mastery "
                             "WHERE user_id = :u"), {"u": uid}).scalar()
    memory_mastery_edit_api(body=MasteryEdit(id=mid, level="熟练"), user=ns)
    with SessionLocal() as s:
        r = s.get(KnowledgeMastery, mid)
        assert r.level == "熟练" and r.confidence == 100
    kp_texts = [x["text"] for x in memories_api(user=ns)["memories"] if x["cat"] == "kp"]
    assert any("熟练" in t and "100" in t for t in kp_texts)
    with pytest.raises(HTTPException) as e1:
        memory_mastery_edit_api(body=MasteryEdit(id=mid, level="天才"), user=ns)
    assert e1.value.status_code == 422
    with pytest.raises(HTTPException) as e2:
        memory_mastery_edit_api(body=MasteryEdit(id=mid, level="一般掌握"),
                                user=SimpleNamespace(id=uid + 99999))
    assert e2.value.status_code == 404


def test_kp_rows_carry_structured_mastery(uid):
    """D85 读面补的 ms 列：带进度行给按钮用的真 id+档位+考试（页面换档的票根），
    裸节点行空数组——text 给人看、ms 给机器用，一列两职必打架所以分家。"""
    _seed(uid)
    rows = memories_api(user=SimpleNamespace(id=uid))["memories"]
    kp = {r["id"]: r for r in rows if r["cat"] == "kp"}
    with_progress = [r for r in kp.values() if r["ms"]]
    assert len(with_progress) == 1
    m0 = with_progress[0]["ms"][0]
    assert m0["level"] == "薄弱" and m0["exam"] == "公考" and isinstance(m0["mid"], int)
    assert all(r["ms"] == [] for r in kp.values() if r is not with_progress[0])


# ── D87 档案修改腿：用户拍板「我要的就是每一条都能改」──

def test_profile_edit_roundtrip_and_gates(uid):
    """改档案：换名（日期没挪 replan=False）、改日期（replan=True 指路重排）；
    空名/坏格式/假日子 422 拦门口；他户 404 同族句式。"""
    from backend.main import ProfileEdit, memory_profile_edit_api
    _seed(uid)
    ns = SimpleNamespace(id=uid)
    with SessionLocal() as s:
        pid = s.execute(text("SELECT id FROM exam_profiles "
                             "WHERE user_id = :u"), {"u": uid}).scalar()
    # 只改名：seed 日期 2026-11-29 原样填回 → replan 不报警
    r1 = memory_profile_edit_api(
        body=ProfileEdit(id=pid, exam_type="国家公务员考试",
                         exam_date="2026-11-29"), user=ns)
    assert r1["replan"] is False
    # 改日期：诚实账——旧计划不会自动挪，回执必须报警
    r2 = memory_profile_edit_api(
        body=ProfileEdit(id=pid, exam_type="国家公务员考试",
                         exam_date="2026-12-05"), user=ns)
    assert r2["replan"] is True
    with SessionLocal() as s:
        row = s.execute(text("SELECT exam_type, exam_date FROM exam_profiles "
                             "WHERE id = :i"), {"i": pid}).first()
        assert row.exam_type == "国家公务员考试" and row.exam_date == date(2026, 12, 5)
    # 读面 pf 票与 text 同步换真值
    rows = memories_api(user=ns)["memories"]
    p = [x for x in rows if x["id"] == f"p{pid}"][0]
    assert p["pf"] == {"pid": pid, "name": "国家公务员考试", "date": "2026-12-05"}
    assert "国家公务员考试" in p["text"] and "2026-12-05" in p["text"]
    # 三道 422：空名 / 形状不对 / 形状对但日子不存在
    for bad in [dict(exam_type="  ", exam_date="2026-12-05"),
                dict(exam_type="x", exam_date="2026-1-5"),
                dict(exam_type="x", exam_date="2026-11-31")]:
        with pytest.raises(HTTPException) as e:
            memory_profile_edit_api(body=ProfileEdit(id=pid, **bad), user=ns)
        assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e4:
        memory_profile_edit_api(
            body=ProfileEdit(id=pid, exam_type="偷档案", exam_date="2026-12-05"),
            user=SimpleNamespace(id=uid + 99999))
    assert e4.value.status_code == 404


def test_profile_delete_physically_with_primary_handoff(uid):
    """D88 档案遗忘门：删主考→剩行自动晋主（不许制造全户无主悬案）；
    删到全户空→promoted=False、读面 p 行清零；他户 404。
    无表外键锚档案（plans 只有 exam_type 文本冗余）——删行无连坐。"""
    from backend.main import memory_profile_delete_api
    _seed(uid)
    ns = SimpleNamespace(id=uid)
    with SessionLocal() as s:
        p1 = s.execute(text("SELECT id FROM exam_profiles "
                            "WHERE user_id = :u"), {"u": uid}).scalar()
        sub = ExamProfile(user_id=uid, exam_type="省考",
                          exam_date=date(2027, 3, 1), is_primary=False)
        s.add(sub)
        s.commit()
        p2 = sub.id
    # 先删主考：辅考自动晋主
    r = memory_profile_delete_api(pid=p1, user=ns)
    assert r == {"deleted": p1, "promoted": True}
    with SessionLocal() as s:
        assert s.get(ExamProfile, p2).is_primary   # 晋主了
    # 再删独苗主考：全户清空，无人可晋
    r2 = memory_profile_delete_api(pid=p2, user=ns)
    assert r2 == {"deleted": p2, "promoted": False}
    rows = memories_api(user=ns)["memories"]
    assert not [x for x in rows if x["id"].startswith("p")]
    with pytest.raises(HTTPException) as e:
        memory_profile_delete_api(pid=999999, user=ns)
    assert e.value.status_code == 404
