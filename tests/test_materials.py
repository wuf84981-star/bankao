# ============================================================
# S7 八刀离线单测：资料真账列表（D46 甲 · 用户真机戳穿三条演示假卡）
# 断言主线：新户空表；行带块数/已点火坐标数（点火对账靠它）；exam NULL→"通用"；
# 磁盘原件丢失 size 回 None（不编造重量）；user_id 闸——别人户的账不可见。
# 零模型零 OCR 零烧钱：纯 SQL 直调 route 函数（SimpleNamespace 绕 Depends 先例）。
# fixture 用 try/finally 自清（六刀技术账的正面教材：失败轮也要扫地出门）。
# ============================================================
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend.main import materials_api
from backend.models import Chunk, Material


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_mat_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    try:
        yield u
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
            s.commit()   # 级联带走材料/块——无论测试过没过都执行


def test_materials_shape_and_fire_ledger(uid):
    """空户→插 1 材料 3 块→列表行形 correct（exam NULL=通用、vectors=0）
    →手工给 1 块钉上坐标→vectors 翻 1（点火进度对得上账）；
    storage_path 指不存在的文件→size=None 不编重量。"""
    ns = SimpleNamespace(id=uid)
    assert materials_api(user=ns)["materials"] == []
    with SessionLocal() as s:
        m = Material(user_id=uid, title="行测讲义.pdf",
                     storage_path="/nonexistent/dir/9_行测讲义.pdf",
                     file_type="pdf", parse_status="ready", exam_type=None)
        s.add(m)
        s.flush()
        s.add_all([Chunk(material_id=m.id, user_id=uid, seq=i,
                         content="工程问题" * 5, token_count=20)
                   for i in range(3)])
        s.commit()
        mid = m.id
    r0 = materials_api(user=ns)["materials"][0]
    assert r0["title"] == "行测讲义.pdf" and r0["exam"] == "通用"
    assert r0["status"] == "ready" and r0["reason"] is None
    assert r0["chunks"] == 3 and r0["vectors"] == 0
    assert r0["size"] is None            # 磁盘没这文件——宁可「—」不造假 4.2MB
    # 点一块的火：坐标列非空就该被数进 vectors
    vec = "[" + ",".join(["0.01"] * 1024) + "]"
    with SessionLocal() as s:
        s.execute(text("UPDATE chunks SET embedding = CAST(:v AS vector), "
                       "embed_status = 'done' "
                       "WHERE material_id = :m AND seq = 0"),
                  {"v": vec, "m": mid})
        s.commit()
    r0 = materials_api(user=ns)["materials"][0]
    assert r0["chunks"] == 3 and r0["vectors"] == 1


def test_materials_user_gate(uid):
    """另一户直调：看不见本户的行（user_id 硬过滤，列表不例外）。"""
    with SessionLocal() as s:
        other = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_mat_t2', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    try:
        with SessionLocal() as s:
            s.add(Material(user_id=uid, title="我的账", storage_path="",
                           file_type="txt", parse_status="ready"))
            s.commit()
        assert len(materials_api(user=SimpleNamespace(id=uid))["materials"]) == 1
        assert materials_api(user=SimpleNamespace(id=other))["materials"] == []
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM users WHERE id = :o"), {"o": other})
            s.commit()


# ── 甲案小刀：引用小票溯源接口 GET /api/chunks/{id}（真机反馈「第几块，哪里的」）──

def test_chunk_api_traceable(uid):
    """本户凭票取块：讲义名/序位/块全文原样还——用户看得懂「哪里」靠的就是这块原文。"""
    from backend.main import chunk_api
    with SessionLocal() as s:
        m = Material(user_id=uid, title="常识判断.md", storage_path="_mat/x.md",
                     file_type="md", parse_status="ready")
        s.add(m)
        s.flush()
        c = Chunk(material_id=m.id, user_id=uid, seq=22,
                  content="基期量=现期量÷(1+增长率)", token_count=10)
        s.add(c)
        s.commit()
        cid = c.id
    out = chunk_api(cid, user=SimpleNamespace(id=uid))
    assert out["chunk_id"] == cid and out["seq"] == 22
    assert out["title"] == "常识判断.md" and "基期量" in out["content"]


def test_chunk_api_gates_two_flavors(uid):
    """结构闸两味全是 404 同一句：别人的真块号不承认真伪、无主的假号直接查无。"""
    from fastapi import HTTPException
    from backend.main import chunk_api
    with SessionLocal() as s:
        m = Material(user_id=uid, title="私有讲义", storage_path="_mat/p.md",
                     file_type="md", parse_status="ready")
        s.add(m)
        s.flush()
        c = Chunk(material_id=m.id, user_id=uid, seq=0, content="机密", token_count=2)
        s.add(c)
        s.commit()
        cid = c.id
    with SessionLocal() as s:
        thief = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_mat_thief', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    try:
        with pytest.raises(HTTPException) as ei:
            chunk_api(cid, user=SimpleNamespace(id=thief))    # 偷号：不泄存在性
        assert ei.value.status_code == 404
        with pytest.raises(HTTPException):
            chunk_api(10 ** 9, user=SimpleNamespace(id=uid))   # 无主假号
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM users WHERE id = :u"), {"u": thief})
            s.commit()


# ── D84 资料删除腿：DELETE /api/materials/{id}（PRD 1151 AC②兑现）──

def test_material_delete_cascades_chunks_and_disk(uid, tmp_path):
    """删一份：materials 行没、chunks 被 CASCADE 整体带走（不留孤儿索引）、
    磁盘原件跟着扫掉（不留孤儿文件）。"""
    from backend.main import material_delete
    f = tmp_path / "讲义.md"   # pytest 自带临时目录，失败轮也不留渣
    f.write_text("基期量", encoding="utf-8")
    with SessionLocal() as s:
        m = Material(user_id=uid, title="讲义.md", storage_path=str(f),
                     file_type="md", parse_status="ready")
        s.add(m)
        s.flush()
        s.add_all([Chunk(material_id=m.id, user_id=uid, seq=i,
                         content="x", token_count=1) for i in range(2)])
        s.commit()
        mid = m.id
    assert material_delete(mid, user=SimpleNamespace(id=uid)) == \
        {"id": mid, "status": "deleted"}
    with SessionLocal() as s:
        assert s.execute(text("SELECT count(*) FROM materials "
                              "WHERE id=:i"), {"i": mid}).scalar() == 0
        assert s.execute(text("SELECT count(*) FROM chunks "
                              "WHERE material_id=:i"), {"i": mid}).scalar() == 0
    assert not f.exists()          # 原件也扫干净——盘账两清


def test_material_delete_ticket_gate_same_404(uid):
    """两味 404 同一句：别人材料的真号、无主的假号——票闸不泄存在。"""
    from fastapi import HTTPException
    from backend.main import material_delete
    with SessionLocal() as s:
        m = Material(user_id=uid, title="我的账", storage_path="",
                     file_type="txt", parse_status="ready")
        s.add(m)
        s.commit()
        mid = m.id
        thief = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_mat_del_thief', 'x', 'normal', now()) RETURNING id"
        )).scalar()
        s.commit()
    try:
        with pytest.raises(HTTPException) as ei:
            material_delete(mid, user=SimpleNamespace(id=thief))
        assert ei.value.status_code == 404
        with pytest.raises(HTTPException) as ei2:
            material_delete(10 ** 9, user=SimpleNamespace(id=uid))
        assert ei2.value.status_code == 404
        with SessionLocal() as s:   # 偷不动：本户行原地完好
            assert s.execute(text("SELECT count(*) FROM materials "
                                  "WHERE id=:i"), {"i": mid}).scalar() == 1
    finally:
        with SessionLocal() as s:
            s.execute(text("DELETE FROM users WHERE id=:t"), {"t": thief})
            s.commit()


def test_material_delete_survives_missing_file(uid):
    """磁盘原件早被手清（storage_path 指空）——账照删不误，脏盘不拦账腿。"""
    from backend.main import material_delete
    with SessionLocal() as s:
        m = Material(user_id=uid, title="丢片.pdf",
                     storage_path="/nonexistent/dir/9_丢片.pdf",
                     file_type="pdf", parse_status="ready")
        s.add(m)
        s.commit()
        mid = m.id
    assert material_delete(mid, user=SimpleNamespace(id=uid))["status"] == "deleted"
