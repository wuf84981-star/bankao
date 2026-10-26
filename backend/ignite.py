# ============================================================
# 点火刀（ignite.py）：扫库里 pending 块 → 电厂变坐标 → 翻 done
# D7 甲案形态：独立命令而非后台常驻——`uv run python -m backend.ignite`
# 配好 key 跑一次全库点亮，新传的再跑一次（定时化与 PRD 840"定时重试3次"
# 的生产形态欠账归 S7）。运费按 PRD 625 记 material 主人名下 usage_logs。
# 失败单位=材料：一只材料电厂故障→它的块全保持 pending 等下趟，不拖垮一库。
# ============================================================
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import SessionLocal
from backend.embedder import EMBED_MODEL, embed
from backend.zh_tokenizer import ts_input


def ignite_all(session: Session, only: list[int] | None = None) -> dict:
    """点亮所有 pending 块（only=材料 id 白名单：单测边界闸，防假电厂污染真材料）。
    战报 {"materials", "chunks", "tokens", "failed":[材料id…]}。
    RuntimeError（电厂没通电）整场向上抛——CLI 接住回人话；
    单材料故障记入 failed 继续下一只（一挂鞭不成全库哑）。"""
    report = {"materials": 0, "chunks": 0, "tokens": 0, "failed": []}
    # S9：点火刀顺手补分词列（content_tsv 为空的老块）。
    # 为什么捎在这把刀里做：点火刀本就是「新块入库后的补账工具」，
    # 分词腿与向量腿共用同一次「扫库补账」的时机，分开跑等于让运营跑两遍全库。
    # 迁移已回填过存量，这把刀只兜迁移之后新增又漏分词的块（S9 双保险）。
    zh_backfilled = 0
    where = "WHERE c.embed_status = 'pending'"
    params: dict = {}
    if only:
        where += " AND c.material_id = ANY(:only)"
        params["only"] = list(only)
    # 分词腿补账：不限 pending——有些块向量已 done 但分词列空着
    # （迁移后新增、或当时 jieba 故障），它们同样检索不到。
    zh_rows = session.execute(text(
        "SELECT id, content FROM chunks "
        "WHERE content_tsv IS NULL ORDER BY id")).fetchall()
    for r in zh_rows:
        tok = ts_input(r.content or "")
        if not tok:      # 全虚词/全停用词：不进索引，靠另两腿兜
            continue
        session.execute(text(
            "UPDATE chunks SET content_tokenized = :tok, "
            "content_tsv = to_tsvector('simple', :tok) WHERE id = :id"
        ), {"tok": tok, "id": r.id})
        zh_backfilled += 1
    mats = session.execute(text(f"""
        SELECT DISTINCT c.material_id, m.user_id
        FROM chunks c JOIN materials m ON m.id = c.material_id
        {where}
        ORDER BY c.material_id
    """), params).all()
    for mid, owner_id in mats:
        rows = session.execute(text(
            "SELECT id, content FROM chunks "
            "WHERE material_id = :mid AND embed_status = 'pending' ORDER BY id"
        ), {"mid": mid}).all()
        try:
            vectors, tokens = embed([r.content for r in rows])
        except RuntimeError:
            raise   # 缺 key 不是某只材料的错，是全场没电——让 CLI 说人话
        except Exception:
            report["failed"].append(mid)
            continue   # 没写过一笔，库里这些块仍 pending，下趟重来
        for r, vec in zip(rows, vectors):
            session.execute(text(
                "UPDATE chunks SET embedding = CAST(:v AS vector), embed_status = 'done' "
                "WHERE id = :id"
            ), {"v": "[" + ",".join(map(str, vec)) + "]", "id": r.id})
        session.execute(text(
            "UPDATE materials SET embedding_model = :em WHERE id = :mid"
        ), {"em": EMBED_MODEL, "mid": mid})   # 向量户口：这批是谁家模型嵌的（PRD 13.6 条款3）
        if tokens:   # 端点没报 usage 就不立空账——不虚报也不自欺
            session.execute(text(
                "INSERT INTO usage_logs (user_id, day, tokens, created_at) "
                "VALUES (:u, :d, :t, now())"
            ), {"u": owner_id, "d": date.today(), "t": tokens})
        session.commit()   # 材料粒度事务：点亮一只结一只，失败不连坐
        report["materials"] += 1
        report["chunks"] += len(rows)
        report["tokens"] += tokens
    if zh_backfilled:
        session.commit()   # 分词补账与向量点火同事务边界（材料粒度已结，这里补一次）
        report["zh_backfilled"] = zh_backfilled
    return report


def main() -> None:
    """CLI 入口：uv run python -m backend.ignite"""
    with SessionLocal() as session:
        try:
            r = ignite_all(session)
        except RuntimeError as e:
            print(f"点不着火：{e}")
            raise SystemExit(1)
    tail = f"；{len(r['failed'])} 只材料故障仍 pending，等下趟 {r['failed']}" if r["failed"] else ""
    print(f"点火战报：{r['materials']} 份材料 / {r['chunks']} 块拿到坐标，"
          f"运费 {r['tokens']} tokens{tail}")
    if r.get("zh_backfilled"):
        print(f"分词腿补账：{r['zh_backfilled']} 块已建tsvector（中文关键词检索现已可命中）")


if __name__ == "__main__":
    main()
