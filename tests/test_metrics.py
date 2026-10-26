# ============================================================
# 评测指标纯函数离线测（test_metrics.py）
# W2 秤的自检：已知榜单喂已知期望，数字必须逐一对上。
# 全离线零 DB 零网络——真腿跑分在 run_retrieval_eval.py，pytest 外。
# ============================================================
import pytest

from backend.evals.metrics import evaluate, gap_flag, mrr, recall_at_k


# ── recall@k ──

def test_recall_full_hit_and_miss():
    """全命中=1；榜里没有期望=0；空期望=-1 哨兵不参评。"""
    assert recall_at_k([7, 3, 9], {7, 3, 9}, k=3) == 1.0
    assert recall_at_k([1, 2, 3], {8, 9}, k=3) == 0.0
    assert recall_at_k([1, 2], set(), k=2) == -1.0


def test_recall_partial_and_window():
    """半命中算比例；k 窗外的命中不算——秤只称前 k 名。"""
    assert recall_at_k([5, 1, 2, 3], {5, 3}, k=3) == 0.5   # 3 在第 4 名，窗外
    assert recall_at_k([5, 1, 2, 3], {5, 3}, k=5) == 1.0   # 放宽到 5 就全进窗


# ── mrr ──

def test_mrr_first_hit_position():
    """倒数排名认第一个命中：第 1 名=1.0，第 3 名=1/3；无命中=0；空期望=-1。"""
    assert mrr([8, 2, 1], {8}) == 1.0
    assert mrr([4, 2, 8], {8}) == pytest.approx(1 / 3)
    assert mrr([4, 2], {8, 9}) == 0.0
    assert mrr([1], set()) == -1.0


def test_mrr_only_first_hit_counts():
    """第二个命中不加分——MRR 考的是「最快摸到」。"""
    assert mrr([3, 7, 1], {3, 7}) == 1.0


# ── gap_flag ──

def test_gap_flag_three_states():
    """三口径逐字钉死：None=zero、低于线=weak、达标=正常（''）。"""
    assert gap_flag(None, 0.60) == "zero"
    assert gap_flag(0.45, 0.60) == "weak"
    assert gap_flag(0.60, 0.60) == ""    # 踩线算达标（严格小于才 weak）


# ── evaluate 汇总 ──

def _gold(*pairs):
    return [{"id": i, "question": f"题{i}", "expect_ids": e} for i, e in pairs]


def test_evaluate_mismatch_raises():
    """题数与跑分组数对不上=账错了，必须炸给人看。"""
    with pytest.raises(ValueError):
        evaluate(_gold(("a", {1})), [[1], [2]])


def test_evaluate_mixes_hit_and_unscored():
    """期望集空的题剔除出分母；命中/半命中/脱靶各占一位，均值可手算。"""
    gold = _gold(("a", {1}), ("b", {2, 3}), ("c", set()))
    runs = [[1, 9], [5, 2, 3], [1, 2]]      # a 全中；b 两个期望在第2、3名 recall=1；c 不参评
    r = evaluate(gold, runs, k=3)
    assert r["n"] == 2                       # c 被剔除
    assert r["recall@k"] == 1.0
    assert r["hit_rate"] == 1.0
    assert r["mrr"] < 1.0                    # b 的第一个命中在第 2 名，MRR 拉低


def test_evaluate_accept_map_tolerates_neighbor():
    """核心块没进榜但它的邻块进了=算得分（切块劈开知识点不冤枉）；
    分母仍按核心块数——邻块不许撑分母（首跑实锤的假低病根）。"""
    a = {"id": "a", "question": "q", "expect_ids": {9}, "accept_map": {9: {8, 9, 10}}}
    r = evaluate([a], [[8, 77, 76]], k=3)
    assert r["recall@k"] == 1.0 and r["mrr"] == 1.0
    r2 = evaluate([dict(a, accept_map={9: {9}})], [[8, 77, 76]], k=3)
    assert r2["recall@k"] == 0.0 and r2["hit_rate"] == 0.0


def test_evaluate_all_unscored_returns_zero_structure():
    """全是不参评题时给零结构而不是除零爆炸。"""
    r = evaluate(_gold(("a", set())), [[]])
    assert r == {"n": 0, "recall@k": 0.0, "mrr": 0.0, "hit_rate": 0.0, "items": []}
