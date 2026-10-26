# ============================================================
# 切块器单元测试（伴考首例）：纯函数才配单测——输入输出确定、无外部依赖
# 跑法（宿主）：cd untitled && uv run --with pytest python -m pytest tests -q
# ============================================================
from backend.chunking import HARD, OVERLAP, TARGET, chunk_text


def test_empty():
    """空文本 → 零块，不炸"""
    assert chunk_text("") == []
    assert chunk_text("   \n\n  \n") == []


def test_short_text_one_chunk():
    """一段短文 → 恰好一块，原文不丢"""
    text = "这是一份很短的讲义，只有一段话。"
    out = chunk_text(text)
    assert out == [text]


def test_heading_is_hard_boundary():
    """两个章节标题 → 标题成为封块点，块数=章数，块头带自己的标题"""
    chap1 = "# 第一章 增长率\n\n" + "基期现期套路多。" * 50      # ~500字
    chap2 = "# 第二章 行程问题\n\n" + "相遇追及画个图。" * 50
    out = chunk_text(chap1 + "\n\n\n\n" + chap2)
    assert len(out) == 2
    assert out[0].startswith("# 第一章")
    assert out[1].startswith("# 第二章")   # 标题不孤立、垫在新块头


def test_slide_overlap_and_cap():
    """无段落结构的超长整坨 → 强切片：每片 ≤HARD，相邻片缝线=复读 15%"""
    text = "字" * 3000
    out = chunk_text(text)
    assert len(out) >= 4
    assert all(len(c) <= HARD for c in out)
    step = int(HARD * (1 - OVERLAP))
    # 整坨同字无法比对内容，换可定位文本再验缝线：
    import re as _re
    long_para = _re.sub(r"\s", "", ("甲乙丙丁" * 300))   # 1200 字可辨文本
    out2 = chunk_text(long_para)
    assert len(out2) >= 2
    tail = out2[0][-step:]
    assert out2[1].startswith(tail[:20])   # 下一片头部确实是上一片尾巴


def test_all_content_covered():
    """多段落攒块 → 每段完整落在某一块里，切完不吞字"""
    paras = [f"第{i}段内容。" + "填充文字用于凑长度。" * 40 for i in range(10)]
    text = "\n\n".join(paras)
    out = chunk_text(text)
    assert len(out) >= 2
    joined = "\n\n".join(out)
    for p in paras:
        assert p in joined          # 原文每一段都原样在块流里
    # 封块体量合理：除最后一块外都在 TARGET 附近起步
    assert all(len(c) >= TARGET or c is out[-1] for c in out)
