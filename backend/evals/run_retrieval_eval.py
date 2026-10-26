# ============================================================
# 检索跑分器（evals/run_retrieval_eval.py）——真腿、真钱、pytest 外
# W2 评测刀的心脏。家法：真网络永不进测试，本脚本手动单发跑，
# 20 题 embed 一次批量拿坐标（几分钱，不进 usage_logs），
# 参数扫描只重走融合与闸（零运费）——embed 与参数解耦是省钱关键。
# 三腿调用与 search() 线上同一批函数同一姿势（含 SET LOCAL 阈值），
# 扫 REL_THRESHOLD × TOP_K 出校准表，报告打 stdout（重定向存 reports/）。
# 跑法（容器内，绕本机 5432 抢听）：
#   docker compose cp backend/evals backend:/app/backend/evals
#   docker compose exec -T backend sh -c \
#     '/app/.venv/bin/python -m backend.evals.run_retrieval_eval' \
#     > backend/evals/reports/eval-xxx.md
# ============================================================
import sys
import datetime
from pathlib import Path

import yaml
from sqlalchemy import text

from backend.db import SessionLocal
from backend.embedder import embed
from backend.zh_tokenizer import tsquery_from
from backend import search as search_mod
from backend.search import _VECTOR_SQL, _ZH_SQL, _KEYWORD_SQL, LEG_N
from backend.evals.metrics import evaluate

GOLD_PATH = Path(__file__).parent / "goldset.yaml"
THRESHOLDS = [0.20, 0.25, 0.30, 0.35, 0.40]   # 施工图校准网格
TOP_KS = [2, 3, 5, 8]   # D82 甲（2026-10-18）补 k=2 实测点：桌牌已降到 2，秤上得有账


def log(msg: str) -> None:
    """进度走 stderr——stdout 留给报告本体，重定向才干净。"""
    print(msg, file=sys.stderr)


def neighbor_expand(session, ids: set[int]) -> set[int]:
    """期望集扩邻块（施工图定的容错）：同材料 seq±1 也算命中。
    切块会把一条知识点劈两半，苛求正中一块是冤枉检索。"""
    if not ids:
        return ids
    rows = session.execute(text(
        "SELECT material_id, seq FROM chunks WHERE id = ANY(:ids)"
    ), {"ids": list(ids)}).fetchall()
    out = set(ids)
    for mid, seq in rows:
        nbrs = session.execute(text(
            "SELECT id FROM chunks WHERE material_id = :m AND seq IN (:a, :b)"
        ), {"m": mid, "a": seq - 1, "b": seq + 1}).fetchall()
        out |= {r[0] for r in nbrs}
    return out


def leg_boards(session, uid: int, qvec, question: str):
    """三腿各捞 20——与 search() 逐句同姿势（含降级形状：zh 腿缺席不炸）。
    返回 (向量榜, 向量分dict, zh榜, 关键词榜)。"""
    vec_rows = session.execute(text(_VECTOR_SQL), {
        "vec": search_mod._to_vec_str(qvec), "uid": uid, "n": LEG_N}).all()
    board_v = [r.id for r in vec_rows]
    scores_v = {r.id: round(float(r.score), 4) for r in vec_rows}
    zh_q = tsquery_from(question)
    board_z: list[int] = []
    if zh_q:
        try:
            board_z = [r.id for r in session.execute(
                text(_ZH_SQL), {"q": zh_q, "uid": uid, "n": LEG_N}).all()]
        except Exception:
            pass
    session.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.01"))
    board_k = [r.id for r in session.execute(
        text(_KEYWORD_SQL), {"q": question, "uid": uid, "n": LEG_N}).all()]
    return board_v, scores_v, board_z, board_k


def score_at(gold: list[dict], boards: list, th: float, k: int) -> dict:
    """一套(阈值,取数)参数下的整套跑分：融合与闸用线上同一对函数。"""
    old = search_mod.REL_THRESHOLD
    search_mod.REL_THRESHOLD = th
    try:
        runs = []
        for board_v, scores_v, board_z, board_k in boards:
            fused = search_mod.rrf_fuse([board_v, board_z, board_k], top_k=k)
            gated = search_mod.fused_gate(fused, scores_v, vec_live=bool(board_v))
            runs.append([cid for cid, _ in gated])
        return evaluate(gold, runs, k=k)
    finally:
        search_mod.REL_THRESHOLD = old


def main() -> None:
    data = yaml.safe_load(GOLD_PATH.read_text(encoding="utf-8"))
    uid = data["meta"]["uid"]

    with SessionLocal() as s:
        gold = []
        for it in data["items"]:
            core = set(it["expect_ids"])
            # 分母=核心块；邻块只进 accept_map 当容错（首跑实锤：
            # 把邻块混进期望集会虚增分母，recall 被秤自己冤枉成低）
            gold.append({"id": it["id"], "question": it["question"],
                         "expect_ids": core,
                         "accept_map": {e: neighbor_expand(s, {e}) for e in core}})
        log(f"[goldset] {len(gold)} 题（uid={uid}，期望集已扩邻块）")

        log("[embed] 批量拿坐标（本次唯一的真钱开销）…")
        qvecs, _ = embed([g["question"] for g in gold])

        boards = [leg_boards(s, uid, gv, g["question"]) for gv, g in zip(qvecs, gold)]

    # ── 校准表：阈值×取数网格逐档跑分 ──
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"# 检索评测报告（goldset {data['meta']['version']}，{len(gold)} 题）· {now}\n")
    print("| REL_THRESHOLD | TOP_K | recall@k | MRR | hit_rate |")
    print("|---|---|---|---|---|")
    results = {}
    for th in THRESHOLDS:
        for k in TOP_KS:
            r = score_at(gold, boards, th, k)
            results[(th, k)] = r
            # 现行桌牌标记随 D82 走：search.TOP_K=3（甲案试 2 掉分、乙案回 3）
            mark = " ←现行桌牌" if th == 0.30 and k == 3 else ""
            print(f"| {th:.2f} | {k} | {r['recall@k']:.3f} | {r['mrr']:.3f} "
                  f"| {r['hit_rate']:.3f} |{mark}")

    # 基线配置（现行桌牌）的失分明细——校准看趋势，改题看个案
    # （D82 乙：桌牌定在 k=3，明细档位跟着现行走）
    print("\n## 基线（th=0.30, k=3）失分明细\n")
    for g, item in zip(gold, results[(0.30, 3)]["items"]):
        if item["recall"] < 1.0:
            print(f"- {g['id']}「{g['question']}」 recall={item['recall']:.2f} "
                  f"mrr={item['mrr']:.2f} 期望块={sorted(g['expect_ids'])}")
    print("\n读法：recall@k 不降且 hit_rate 不跌的最高档阈值即候选桌牌；"
          "改常量须引用本报告文件名（写进 search.py 注释）。")


if __name__ == "__main__":
    main()
