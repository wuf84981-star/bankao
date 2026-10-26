# ============================================================
# 切块边（chunking.py）：解析边的整根长文 → 可检索的小块
# 规矩照 PRD 12.2（D3 甲案拍板）：标题层级先切 + 400~800 token
# 滑动窗口（重叠 15%）。离线没有 DeepSeek 的 tokenizer，用字数近似
# （中文约 1 字≈1 token 量级），通关前校准——边界已记账。
# S3 校准已清（2026-09-07，cl100k 替身词表）：纯中文≈0.9~1.1 token/字，
# 400~800 字块对中文/混合安全；英文≈0.25 token/字（英文密集材料会顶预算，
# 真值等千问 tokenizer 实用复核——账挂 key 后）。
# 纯函数：进文本出块表，零碰库零碰电厂，pytest 直接喂已知文本验。
# ============================================================
import re

TARGET = 600    # 攒到约 600 字封块（块长理想中位）
HARD = 800      # 单块硬上限（PRD 400~800 的顶）
OVERLAP = 0.15  # 强切缝线：相邻切片复读 15%（PRD 定值）


def _slide(text: str) -> list[str]:
    """把超长文本硬切成 ≤HARD 的切片，相邻片头尾复读 OVERLAP 比例——
    缝线：关键句正好被劈在刀口上时，两半各自都还带着完整句。"""
    if len(text) <= HARD:
        return [text]
    step = int(HARD * (1 - OVERLAP))   # 每次前进一步，上一步的尾巴留在下一片里
    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        chunks.append(text[i:i + HARD])
        if i + HARD >= n:
            break
        i += step
    return chunks


def chunk_text(text: str) -> list[str]:
    """长文 → 块列表。三段逻辑：
    ① 空行分自然段；② Markdown 标题(#) 是硬边界——见标题先封上块，
    标题归新块开头（块自带章节上下文，检索命中后引用能报出家门）；
    ③ 攒到 TARGET 封块，超 HARD 交给 _slide 强切（唯一需要缝线的地方）。"""
    chunks: list[str] = []
    buf = ""
    for raw in re.split(r"\n\s*\n", text):
        para = raw.strip()
        if not para:
            continue
        # 硬边界：遇到标题行，把手里的块先封掉（标题不孤立成块，垫到新块头）
        if para.startswith("#") and buf:
            chunks.append(buf)
            buf = ""
        # 超长段：先封旧账，整段强切，最后一小截留作下轮起头
        if len(para) > HARD:
            if buf:
                chunks.append(buf)
                buf = ""
            sliced = _slide(para)
            chunks.extend(sliced[:-1])
            buf = sliced[-1]
            continue
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) >= TARGET:
            chunks.append(candidate)
            buf = ""
        else:
            buf = candidate
    if buf:
        chunks.append(buf)
    return chunks
