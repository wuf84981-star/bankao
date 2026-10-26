# ============================================================
# 点火刀离线单测：真开发库（5432 对宿主敞开）+ 假电厂（不联网不吃 key）
# 验的是机械件：done 翻转、坐标落列、户口写法、运费记账、故障不连坐
# 真机账（真电厂全库点亮+语义距离演示）挂 key 配置后清
# ============================================================
import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend import ignite


@pytest.fixture()
def stage():
    """临时户口 + 一份材料 + 三只 pending 块；用完即删（CASCADE 清全程）"""
    with SessionLocal() as s:
        uid = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_ignite_t', 'x', 'normal', now()) RETURNING id")).scalar()
        mid = s.execute(text(
            "INSERT INTO materials (user_id, title, storage_path, file_type, parse_status, created_at) "
            "VALUES (:u, '_t.md', '/dev/null', 'md', 'ready', now()) RETURNING id"),
            {"u": uid}).scalar()
        for seq in range(3):
            s.execute(text(
                "INSERT INTO chunks (material_id, user_id, seq, content, token_count, embed_status, created_at) "
                "VALUES (:m, :u, :s, :c, 10, 'pending', now())"),
                {"m": mid, "u": uid, "s": seq, "c": f"第{seq}块点火证物"})
        s.commit()
    yield uid, mid
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        s.commit()


def test_ignite_flips_all_and_books_freight(monkeypatch, stage):
    """假电厂点亮：三块全翻 done、坐标非空、材料写户口、运费进材料主人钱包"""
    uid, mid = stage
    monkeypatch.setattr(ignite, "embed",
                        lambda texts: ([[0.5] * 1024 for _ in texts], 42))
    # （1024 维不是随手写的：vector(1024) 列会当场拒收 4 维假坐标——维度绑库的第一道闸）
    with SessionLocal() as s:
        r = ignite.ignite_all(s, only=[mid])
        assert r["materials"] >= 1 and r["failed"] == []
        row = s.execute(text(
            "SELECT count(*) FILTER (WHERE embed_status='done' AND embedding IS NOT NULL) AS done, "
            "count(*) AS total FROM chunks WHERE material_id = :m"), {"m": mid}).one()
        assert (row.done, row.total) == (3, 3)
        em = s.execute(text("SELECT embedding_model FROM materials WHERE id = :m"),
                       {"m": mid}).scalar()
        assert em == ignite.EMBED_MODEL
        log = s.execute(text(
            "SELECT tokens FROM usage_logs WHERE user_id = :u AND tokens = 42"),
            {"u": uid}).scalar()
        assert log == 42   # 运费记在材料主人头上（PRD 625 同钱包）


def test_failed_material_keeps_pending(monkeypatch, stage):
    """电厂炸了：该材料零写入——块全 pending 等下趟，无运费假账"""
    uid, mid = stage
    def boom(texts):
        raise Exception("电厂抖动")
    monkeypatch.setattr(ignite, "embed", boom)
    with SessionLocal() as s:
        r = ignite.ignite_all(s, only=[mid])
        assert r["materials"] == 0 and mid in r["failed"]
        pend = s.execute(text(
            "SELECT count(*) FROM chunks WHERE material_id = :m AND embed_status = 'pending' "
            "AND embedding IS NULL"), {"m": mid}).scalar()
        assert pend == 3
        logs = s.execute(text("SELECT count(*) FROM usage_logs WHERE user_id = :u"),
                         {"u": uid}).scalar()
        assert logs == 0   # 没点着就不记账——BR-11 精神贯穿


def test_missing_key_raises_out(monkeypatch, stage):
    """缺 key 是全场没电：RuntimeError 一路上抛给 CLI 说人话，不是某材料 failed"""
    def nokey(texts):
        raise RuntimeError("DASHSCOPE_API_KEY 还没配置")
    monkeypatch.setattr(ignite, "embed", nokey)
    with pytest.raises(RuntimeError):
        with SessionLocal() as s:
            ignite.ignite_all(s, only=[stage[1]])
