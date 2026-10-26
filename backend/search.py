# ============================================================
# 检索（search.py）：问句 → 从chunks 仓库捞 top-k 相关块
#
# S9 改造：两条关键词腿 → 三腿合议。
# 原案（PRD 631）：向量 top20 ∪ pg_trgm top20 → RRF → top5。
# S9 补腿：pg_trgm 那条腿对中文按 UTF-8 字节剁三元组，实测「基期量怎么算」
# 对正题块 similarity 被稀释到 0.0275（阈值降到 0.01 才放行），事实上半废。
# 故加第三条腿：**jieba 分词 + PG 全文检索**（tsvector/GIN）——真能命中
# 「基期量」这种专名。pg_trgm 那条不删：它对英文与纯数字题号（"第729题"）
# 仍有价值，退居兜底位。
#
# 关键：rrf_fuse 本就吃「腿的列表」，腿数从2 变 3 是零代码改动——
# 融合骨架一个字没动，这是 S3 当年就选对的地方。
#
# 降级：向量腿空/异常 → 自动纯关键词并注明；关键词腿也空 → 如实报零命中。
# 隔离（D4）：三腿 SQL 全都硬带 user_id，隔离无法被绕过（PRD 13.6 条款2）。
# ============================================================
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.embedder import embed
from backend.zh_tokenizer import tsquery_from, ts_input

RRF_K = 60          # RRF 平滑常数（论文惯用值）：让第 1 名不至于碾压第 20 名
LEG_N = 20          # 每腿各捞 20（PRD 631）
TOP_K = 3           # 融合后取 3 注入 prompt（v2.11·D82 乙，2026-10-18 用户拍板：
                    # 票面杂乱归 cited_by_reply 票闸管（正文标几张摆几张），供给条数
                    # 跟秤走——评测 30 题实测 k=2 命中率跌一分（g23 答案块恰排第 3），
                    # k=3 零掉分，故供 3。账见 reports/eval-2026-10-18-goldsetv2-k2.md。
                    # /api/search 调试窗自带参数不受本常量影响，管理题的腿各走各的）
# D58「无相关资料」判定门槛：向量腿在线时,有向量分却低于此线的块不算相关。
# 0.30 是桌牌起点（中文语义块余弦相似的保守下沿），真机样本校准挂账——
# 错的方向是安全的：门槛偏高只会多判「无资料」（用户开开关可联网兜底、
# 关开关收到实话），不会喂垃圾。
REL_THRESHOLD = 0.30

# 向量腿：1-距离=相似度；只走已点火的 done 块
_VECTOR_SQL = """
    SELECT id, 1 - (embedding <=> CAST(:vec AS vector)) AS score
    FROM chunks
    WHERE user_id = :uid AND embed_status = 'done'
    ORDER BY embedding <=> CAST(:vec AS vector)
    LIMIT :n
"""

# S9 中文分词腿（S9 新增）：jieba 分词 → to_tsquery 匹配 → ts_rank_cd 排序。
# 为什么 ts_rank_cd 而非 plainto_tsquery：plainto 是 AND 语义，「基期量 怎么
# 算」三个词要求同块全有，讲义里没人这么写→ 候选清空。to_tsquery 显式给
# OR（tsquery_from 默认 OR），并集召回、靠 rank 排序，正是检索该有的分工。
# user_id 硬带（D4 铁律·隔离靠结构不靠自觉）；tsv 走 GIN，块数上万仍毫秒级。
_ZH_SQL = """
    SELECT id, ts_rank_cd(content_tsv, q) AS score
    FROM chunks, to_tsquery('simple', :q) q
    WHERE user_id = :uid AND content_tsv @@ q
    ORDER BY score DESC
    LIMIT :n
"""

# 关键词腿：pg_trgm 三元组；% 谓词吃 GIN 索引，阈值调低（中文语序碎块重合天然偏低）
# 注：% 运算符在 text() 源码里写单个——SQLAlchemy 方言会自动转义成 %%，手写双 % 会变四连炸库
_KEYWORD_SQL = """
    SELECT id, similarity(content, :q) AS score
    FROM chunks
    WHERE user_id = :uid AND content % :q
    ORDER BY score DESC
    LIMIT :n
"""

# 融合胜者回填详情：块身+出处（title 给引用跳回用）
_DETAIL_SQL = """
    SELECT c.id, c.material_id, m.title, c.seq, c.content, c.token_count
    FROM chunks c JOIN materials m ON m.id = c.material_id
    WHERE c.id = ANY(:ids)
"""


def rrf_fuse(rankings: list[list[int]], top_k: int = TOP_K) -> list[tuple[int, float]]:
    """多腿名次榜 → RRF 合议（纯函数，可离线单测）。
    rankings 每项是一条腿的 chunk id 有序榜（第 0 项=向量腿，第 1 项=关键词腿）。
    分数是两种货币不互认，只比名次：score = Σ 1/(RRF_K + 名次)；缺席腿零贡献。
    同分按 id 升序保证稳定。返回 [(chunk_id, rrf分)] 按分降序取 top_k。"""
    votes: dict[int, float] = {}
    for board in rankings:
        for rank, cid in enumerate(board, start=1):
            votes[cid] = votes.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    ranked = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(cid, round(score, 6)) for cid, score in ranked[:top_k]]


def fused_gate(fused: list[tuple[int, float]], vec_scores: dict[int, float],
               vec_live: bool) -> list[tuple[int, float]]:
    """D58 相关度闸（纯函数可测）：向量腿在线时,凡有向量分却低于门槛的块剔除；
    只有关键词腿命中的块放行（词面证据,降级期的主力）；向量腿离线/零命中不闸
    ——没有相似度可考时不设防,维持降级现状。"""
    if not vec_live or not vec_scores:
        return fused
    return [(cid, s) for cid, s in fused
            if vec_scores.get(cid, 1.0) >= REL_THRESHOLD]


def _to_vec_str(vec: list[float]) -> str:
    """python 列表 → pgvector 字面量 '[0.1,0.2,...]'"""
    return "[" + ",".join(map(str, vec)) + "]"


def search(session: Session, query: str, user_id: int,
           top_k: int = TOP_K) -> dict:
    """检索总编排：问句变坐标(尽力) → 三腿各捞 20 → RRF 合议 top5 → 回填详情。
    返回 {"results":[{id, material_id, title, seq, content, token_count,
                      rrf, ranks:{vector?, zh?, keyword?}}], "degraded": None|人话}。
    S9：三腿（向量 / jieba 分词 / pg_trgm），融合骨架零改动。"""
    if not query.strip():
        return {"results": [], "degraded": None}

    # ── 向量腿：先问库里有无可走的 done 块，再问电厂要坐标，两关任一过不去=降级 ──
    vec_board: list[int] = []
    vec_scores: dict[int, float] = {}   # D58：留着向量相似度给相关度闸用
    zh_board: list[int] = []            # S9：中文分词腿
    zh_scores: dict[int, float] = {}
    kw_board: list[int] = []            # pg_trgm 兜底腿（英文/题号仍靠它）
    degraded: str | None = None
    done_count = session.scalar(
        text("SELECT count(*) FROM chunks WHERE user_id = :uid AND embed_status = 'done'"),
        {"uid": user_id})
    if not done_count:
        degraded = "坐标未点火（库里无 done 块）——本次仅关键词腿"
    else:
        try:
            qvec, _tok = embed([query])   # 查询变坐标
            # 注：查询腿的运费入账欠着（等 key 点火后随校准刀小补——检索是读路径，账挂写路径先清）
            rows = session.execute(
                text(_VECTOR_SQL), {"vec": _to_vec_str(qvec[0]), "uid": user_id, "n": LEG_N}
            ).all()
            vec_board = [r.id for r in rows]
            vec_scores = {r.id: round(float(r.score), 4) for r in rows}
            if not vec_board:
                degraded = "向量腿零命中——仅关键词腿结果"
        except RuntimeError as e:
            # 电厂没通电（缺 key）：key 后置期的常客
            degraded = f"电厂未通电——仅关键词腿（{e}）"
        except Exception:
            # 超时、网络、维度不符……一切电厂故障都从这接住，绝不拖垮整次检索
            degraded = "向量腿故障——已降级纯关键词"

    # ── S9 中文分词腿：jieba 切词 → to_tsquery 走 GIN ──
    # 专名（基期量/隔年增长）靠 zh_tokenizer 的自定义词典保整词，
    # 停用词在那层就剔掉了，不进索引查询（省 GIN 空间也省误召回）。
    zh_q = tsquery_from(query)
    if zh_q:
        try:
            zh_rows = session.execute(
                text(_ZH_SQL), {"q": zh_q, "uid": user_id, "n": LEG_N}
            ).all()
            zh_board = [r.id for r in zh_rows]
            zh_scores = {r.id: round(float(r.score), 6) for r in zh_rows}
        except Exception:
            # 迁移未跑（content_tsv 列不存在）时降级：这条腿缺席，另两腿照走。
            # 不设 degraded 人话——用户不关心「分词索引没建」这种内部事，
            # 检索照常出结果时不必制造噪音。
            zh_board = []

    # ── pg_trgm 兜底腿：永远在场（英文、纯数字题号靠它）──
    # 真机验出的坑谱：pg_trgm 对中文按 UTF-8 字节剁三元组，长文对短句 similarity 被稀释
    # 到 0.0x 级（实测"基期量怎么算"对正题块仅 0.0275，默认阈值 0.3 永远零命中）——
    # 调到 0.01 放行中文场，排序仍按 similarity 降序，垃圾低分块自然沉底。
    # S9 后这条腿在中文场已被分词腿接管，退居兜底（英文/数字仍靠它）。
    session.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.01"))
    kw_rows = session.execute(
        text(_KEYWORD_SQL), {"q": query, "uid": user_id, "n": LEG_N}
    ).all()
    kw_board = [r.id for r in kw_rows]

    # ── 合议 + 相关度闸（D58）+ 回填 ──
    fused = fused_gate(rrf_fuse([vec_board, zh_board, kw_board], top_k=top_k),
                       vec_scores, vec_live=bool(vec_board))
    # top_vec：向量腿最高分（同闸币种，缺口账登记线用）；向量腿离线=缺省 None
    top_vec = round(max(vec_scores.values()), 4) if vec_scores else None
    if not fused:
        return {"results": [], "degraded": degraded, "top_vec": top_vec}
    kw_scores = {r.id: round(float(r.score), 4) for r in kw_rows}
    detail_rows = session.execute(
        text(_DETAIL_SQL), {"ids": [cid for cid, _ in fused]}
    ).all()
    by_id = {r.id: r for r in detail_rows}
    results = []
    for cid, rrf in fused:
        r = by_id.get(cid)
        if r is None:
            continue
        ranks: dict[str, int] = {}
        if cid in vec_board:
            ranks["vector"] = vec_board.index(cid) + 1
        if cid in zh_board:
            ranks["zh"] = zh_board.index(cid) + 1
        if cid in kw_board:
            ranks["keyword"] = kw_board.index(cid) + 1
        results.append({
            "id": cid, "material_id": r.material_id, "title": r.title,
            "seq": r.seq, "content": r.content, "token_count": r.token_count,
            "rrf": rrf, "ranks": ranks,
            "zh_score": zh_scores.get(cid),
            "keyword_score": kw_scores.get(cid),
        })
    return {"results": results, "degraded": degraded, "top_vec": top_vec}
