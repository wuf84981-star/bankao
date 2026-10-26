# ============================================================
# 知识缺口账（backend/gaps.py）—— S9 · W3 刀（2026-10-11）
# 「讲义里查不到的题」的旁路账本：写账的资格只有两问——
# 零命中（zero）？有命中但向量最高分低于登记线（weak）？
# 立场三条（施工图钉死）：
# ① 写消费端（tools.search_materials、W5 教学图检索节点），
#    不写 search() 核心——/api/search 调试窗狂问不许污染账；
# ② 自吞异常：这本旁账永不拖垮答题正线，写失败就 silently 走人；
# ③ 24h 幂等：同户同题一天只记一笔，狂刷不胀账。
# 两线两职不许混：闸线 REL_THRESHOLD=0.30 裁「能不能喂教练」，
# 本文件的登记线裁「要不要进待补账」；与 knowledge_mastery
# .confidence（0~100 整数）更是两个币种。
# ============================================================
from sqlalchemy import text

from backend.db import SessionLocal
from backend.models import KnowledgeGap

# 登记线：向量腿最高分低于它才进账（0.60 沿用桌牌起点，评测刀校准挂账——
# W2 报告 eval-2026-10-11-goldsetv2 的阈值平表管的是闸线，这条线归后续样本）
GAP_WEAK = 0.60


def record_gap(user_id: int, question: str, top_vec: float | None,
               channel: str = "web") -> bool:
    """记一笔知识缺口。top_vec=None ⇒ zero（查无）；低于登记线 ⇒ weak（擦边）。
    返回是否真落了行。达标分（>= GAP_WEAK）不落账直接 False。
    一切异常自吞返回 False——旁账的身份决定它没有炸别人的权力。"""
    try:
        q = (question or "").strip()[:500]
        if not q:
            return False
        if top_vec is not None and top_vec >= GAP_WEAK:
            return False          # 这题讲义答得上，不是缺口
        with SessionLocal() as s:
            dup = s.execute(text(
                "SELECT 1 FROM knowledge_gaps "
                "WHERE user_id = :u AND question = :q "
                "AND created_at > now() - interval '24 hours' LIMIT 1"
            ), {"u": user_id, "q": q}).first()
            if dup:
                return False      # 24h 同题已记过，不重复胀账
            s.add(KnowledgeGap(user_id=user_id, question=q,
                               top_score=None if top_vec is None
                                       else round(float(top_vec), 4),
                               channel=channel))
            s.commit()
            return True
    except Exception:
        return False
