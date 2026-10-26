# ============================================================
# 检索合议离线单测：RRF 是纯名次算术，不碰库不碰网（能力库「单元测试」卡适用区）
# 两腿 SQL 与降级编排走真机断言（正门 curl），不在此列
# ============================================================
from backend.search import RRF_K, rrf_fuse


def test_consensus_beats_single_leg():
    """共识王胜单科状元：两腿都第 2（2/62）应压过单腿第 1（1/61）——
    RRF 的存在理由：只有一腿看好它，不如两腿都给面子"""
    fused = rrf_fuse([[10], [20, 10]], top_k=5)
    assert fused[0][0] == 10
    assert fused[1][0] == 20
    assert fused[0][1] > fused[1][1]


def test_double_first_wins():
    """两腿共同的第 1 名：分数应为两份 1/(60+1)，稳坐合议榜首"""
    fused = rrf_fuse([[7, 8], [7, 9]], top_k=5)
    assert fused[0][0] == 7
    assert fused[0][1] == round(2 / (RRF_K + 1), 6)


def test_top_k_cut_and_stable_order():
    """截断到 top_k；同分按 id 升序（结果可复现，不随 dict 插入序抖）"""
    fused = rrf_fuse([[5, 3, 1, 2, 4, 6]], top_k=3)
    assert [cid for cid, _ in fused] == [5, 3, 1]
    # 造一个真同分：2 号块两腿第 1；8、9 各只在向量腿第 2——同分靠 id 升序定序
    tied = rrf_fuse([[2, 8], [2, 9]], top_k=5)
    assert tied[0][0] == 2 and tied[1][0] == 8 and tied[2][0] == 9   # 8、9 同分，id 升序


def test_empty_boards():
    """两腿全空：合不出东西，回空表——上层走「无命中」防幻觉分支"""
    assert rrf_fuse([[], []]) == []


# ── D58 相关度闸（fused_gate 纯函数）：「讲义里没有」的判定地基 ──

def test_gate_drops_low_similarity():
    """向量腿在线：有向量分却低于门槛的块剔除——名次要得再高也不算相关"""
    from backend.search import REL_THRESHOLD, fused_gate
    fused = [(1, 0.032), (2, 0.031)]
    vec = {1: 0.82, 2: REL_THRESHOLD - 0.01}
    assert fused_gate(fused, vec, vec_live=True) == [(1, 0.032)]


def test_gate_passes_keyword_only_hits():
    """只在关键词腿露面的块（向量榜没有它=拿不到相似度）放行——
    词面证据是降级期主力，闸无权因「没分」而杀"""
    from backend.search import fused_gate
    fused = [(7, 0.03), (8, 0.028)]
    assert fused_gate(fused, {7: 0.9}, vec_live=True) == fused


def test_gate_offline_leg_no_filter():
    """向量腿离线/零命中：没有相似度可考时不设防，原样放行（维持降级现状）"""
    from backend.search import fused_gate
    fused = [(1, 0.03), (2, 0.02)]
    assert fused_gate(fused, {}, vec_live=False) == fused
    assert fused_gate(fused, {1: 0.01}, vec_live=False) == fused
