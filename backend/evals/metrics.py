# ============================================================
# 评测指标（evals/metrics.py）：检索质量的那杆秤——纯函数
# 零 DB 零网络零电厂，pytest 直接喂已知榜单验（家法：真网络
# 永不进测试；跑真腿在 run_retrieval_eval.py，pytest 之外）。
# 为什么要有这文件：S9 前所有检索参数（REL_THRESHOLD=0.30、
# TOP_K=5、RRF_K=60）都是桌牌拍脑袋，改分块/换阈值没有数字
# 就不知道是进步还是退步——先造秤，再动刀。
# ============================================================


def recall_at_k(ranked_ids: list[int], expect_ids: set[int], k: int = 5) -> float:
    """前 k 名里命中了几个期望块 ÷ 期望块总数。
    期望集空=这题没法评，返回 -1.0 让汇总层剔除（不混 0 分污染均值）。"""
    if not expect_ids:
        return -1.0
    hits = sum(1 for cid in ranked_ids[:k] if cid in expect_ids)
    return hits / len(expect_ids)


def mrr(ranked_ids: list[int], expect_ids: set[int], k: int = 20) -> float:
    """倒数排名：第一个命中的名次越靠前分越高（第1名=1.0，第3名≈0.33）。
    前 k 名内无命中记 0。同 recall_at_k，空期望集返回 -1.0 不参评。"""
    if not expect_ids:
        return -1.0
    for rank, cid in enumerate(ranked_ids[:k], start=1):
        if cid in expect_ids:
            return 1.0 / rank
    return 0.0


def gap_flag(top_vec_score: float | None, threshold_weak: float) -> str:
    """这次问答该不该进「知识缺口」账（与线上 gaps.py 同一把尺的口径源）：
    zero=向量腿没分（没点火/零命中）；weak=有分但低于登记线；''=正常。
    只裁口径不写库——写库在 gaps.py，指标层不碰账本。"""
    if top_vec_score is None:
        return "zero"
    if top_vec_score < threshold_weak:
        return "weak"
    return ""


def evaluate(gold: list[dict], runs: list[list[int]], k: int = 5) -> dict:
    """汇总一整套金标准的成绩单。
    gold 每条：{"id": 题号, "question": 问句, "expect_ids": set[int],
                可选 "accept_map": {核心块: 可接受块集合(含自身与邻块)}}
    runs  与 gold 同序：每题的检索命中榜（chunk id 有序表）
    判分口径（2026-10-11 首跑实锤后修订）：分母只算**核心期望块**，
    某个核心块只要它自己或它的邻块（accept_map）进了前 k 就算得分——
    邻块容错只宽判分、不撑分母，否则期望集被膨胀成 recall 假低。
    返回 recall@k / MRR / 命中率——剔除期望集空的题（-1.0 哨兵）。"""
    if len(gold) != len(runs):
        raise ValueError(f"金标准 {len(gold)} 题与跑分 {len(runs)} 组对不上数")
    scored = []
    for g, ranked in zip(gold, runs):
        expect = set(g["expect_ids"])
        if not expect:
            continue   # 没法评的题不进分母
        accept = g.get("accept_map") or {e: {e} for e in expect}
        top = set(ranked[:k])
        got = {e for e in expect if top & accept.get(e, {e})}
        first = next((rank for rank, cid in enumerate(ranked[:k], 1)
                      for e in expect if cid in accept.get(e, ())), None)
        scored.append({
            "id": g["id"],
            "recall": len(got) / len(expect),
            "mrr": 1.0 / first if first else 0.0,
            "hit": bool(got),
        })
    n = len(scored)
    if not n:
        return {"n": 0, "recall@k": 0.0, "mrr": 0.0, "hit_rate": 0.0, "items": []}
    return {
        "n": n,
        "k": k,
        "recall@k": round(sum(s["recall"] for s in scored) / n, 4),
        "mrr": round(sum(s["mrr"] for s in scored) / n, 4),
        "hit_rate": round(sum(1 for s in scored if s["hit"]) / n, 4),
        "items": scored,
    }
