# ============================================================
# 金标准候选题铺设（evals/build_gold_candidates.py）
# W2 评测刀的第一步：从**真实语料**铺候选，人（用户）定稿。
# 原则：题目只许问库里真有的词——词典专名若语料里根本没有
# （如本地无「基期量」块），铺进来也评不了，宁缺毋滥。
# 产出：markdown 候选清单打到 stdout（重定向存 goldset_draft.md），
# 每题带：专名 / 建议问法 / 命中块 id（含材料与段序）/ 内容摘要。
# 定稿后手抄进 goldset.yaml——铺题是弹药厂，不是扣扳机的人。
# 跑法（容器内，本机 5432 被野进程抢听的绕行路）：
#   docker compose cp backend/evals backend:/app/backend/evals
#   docker compose exec -T backend sh -c \
#     '/app/.venv/bin/python -m backend.evals.build_gold_candidates'
# ============================================================
import argparse
import re

from sqlalchemy import text

from backend.db import SessionLocal
from backend.zh_tokenizer import CUSTOM_WORDS

_CJK = re.compile(r"^[一-鿿]{3,}$")   # 候选词门槛：纯中文、≥3 字（单双字太泛不配当考题眼）

# 问法模板按词类粗选——数量类问"怎么算"，概念类问"是什么"，
# 其余兜"怎么理解"。只是建议稿，定稿时人来改腔调。
_CALC_HINTS = ("增长", "量", "率", "比", "倍", "数", "和定", "整除", "同余")


def _suggest(term: str) -> str:
    if any(h in term for h in _CALC_HINTS):
        return f"{term}怎么算"
    if term.endswith(("问题", "原理", "定律", "命题", "推理")):
        return f"{term}是什么"
    return f"{term}怎么理解"


def main(uid: int) -> None:
    with SessionLocal() as s:
        rows = s.execute(text(
            "SELECT id, material_id, seq, content_tokenized, content FROM chunks "
            "WHERE user_id = :u AND embed_status = 'done'"
        ), {"u": uid}).fetchall()
    if not rows:
        print(f"户 {uid} 无 done 块，评测跑不了——先换 uid 或先点火")
        return

    # 词 → 命中块列表：分词列直接 split（ts_input 空格连接，无需再分词）
    df: dict[str, list[tuple]] = {}
    for cid, mid, seq, tok, content in rows:
        frag = (content or "").replace("\n", " ").strip()[:20]
        for w in set((tok or "").split()):
            df.setdefault(w, []).append((cid, mid, seq, frag))

    # 候选池 = 词典专名∩语料 + 语料稀有专名（df 2~4：跨块可区分又不泛；
    # df=1 的一次词噪声大——随机三字串也混在里面，人工定稿看不动，剔除）
    dict_set = set(CUSTOM_WORDS)
    in_dict = [(w, df[w]) for w in CUSTOM_WORDS if w in df]
    extras = sorted(((w, v) for w, v in df.items()
                     if w not in dict_set and _CJK.fullmatch(w) and 2 <= len(v) <= 4),
                    key=lambda kv: len(kv[1]))[:60]
    pool = sorted(in_dict, key=lambda kv: len(kv[1])) + extras

    skipped = [w for w in CUSTOM_WORDS if w not in df]
    print(f"# 金标准候选清单（户 {uid}，done 块 {len(rows)} 个）\n")
    print(f"词典专名在语料中有命中：{len(in_dict)} 个；语料稀有词补充：{len(extras)} 个（只留跨 2~4 块的词，df=1 噪声词已剔）\n")
    print(f"⚠️ 词典里有、语料里没有（不配出题）：{'、'.join(skipped)}\n")
    print("| 专名 | 建议问法 | 命中块 id | 所在材料/段 | 内容摘要 |")
    print("|---|---|---|---|---|")
    for w, hits in pool:
        ids = ",".join(str(h[0]) for h in hits)
        loc = "；".join(f"材料{h[1]}第{h[2]}段" for h in hits[:3])
        print(f"| {w} | {_suggest(w)} | {ids} | {loc} | {hits[0][3]} |")
    print("\n定稿方式：勾保留题、改问法，回我一声，我抄成 goldset.yaml。")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="从真实语料铺金标准候选题")
    p.add_argument("--uid", type=int, default=6289, help="出题取材的租户 id")
    main(p.parse_args().uid)
