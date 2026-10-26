# ============================================================
# S8 还账刀离线单测：_extract 验伤台（Word 腿 2026-09-11 拍甲补装 · PRD 5.1.1 旧诺）
# 断言主线：四种形状各走各腿——PDF 重放回页数、TXT/MD 解码、.docx 段落+表格拼接、
# 形状外 415 话术带「四种」（旧话术「三种」当场作废钉死，防前端再对旧账）；
# 坏 docx（加密/假 zip/.doc 改名骗闸）422 人话指路「另存为 .docx」。
# 全离线零烧钱：docx/pdf 都在内存里现造现拆，不碰磁盘不碰网络。
# 历史自白：_extract 自 S3 首刀裸奔至今——本文件是它的第一份测试户口。
# ============================================================
import io

import pymupdf
import pytest
from docx import Document
from fastapi import HTTPException

from backend.main import _extract


def _make_docx() -> bytes:
    """内存里造一份真 .docx：两段正文+一张 2×2 表（讲义常见形状）。"""
    doc = Document()
    doc.add_paragraph("高频成语第一条：按图索骥。")
    doc.add_paragraph("第二条：差强人意是大体满意，不是不满意。")
    tbl = doc.add_table(rows=2, cols=2)
    tbl.cell(0, 0).text = "侃侃而谈"
    tbl.cell(0, 1).text = "GG ǎn ǎn"     # 故意留个拼音位
    tbl.cell(1, 0).text = "莘莘学子"
    tbl.cell(1, 1).text = "shēn shēn"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_pdf() -> bytes:
    buf = io.BytesIO()
    with pymupdf.open() as out:
        page = out.new_page()
        page.insert_text((72, 72), "Bankao PDF probe line")
        out.save(buf)
    return buf.getvalue()


def test_docx_paragraphs_and_tables_come_out():
    """Word 正腿：段落文字全在、表格行拼成「格 | 格」——对照表不再哑巴。
    pages=None：Word 的页是排版算出来的，不硬凑假页数。"""
    text, pages = _extract(_make_docx(), "语文讲义.docx")
    assert pages is None
    assert "按图索骥" in text and "差强人意" in text
    assert "侃侃而谈 | GG ǎn ǎn" in text
    assert "莘莘学子 | shēn shēn" in text


def test_fake_docx_points_the_way():
    """坏 Word（加密/损坏/老 .doc 改名骗闸同一条路）：422 人话，
    且话里必须指路「另存为 .docx」——拒了还要给出口。"""
    with pytest.raises(HTTPException) as e:
        _extract(b"this is not a zip", "伪装.docx")
    assert e.value.status_code == 422
    assert ".docx" in e.value.detail


def test_four_shapes_gate():
    """分流闸全景：pdf 回页数 1、txt 直读、形状外 415——
    415 话术钉死「PDF/TXT/MD/Word 四种」（前端 accept 就照这本账对）。"""
    text, pages = _extract(_make_pdf(), "probe.pdf")
    assert pages == 1 and "Bankao PDF probe line" in text
    assert _extract("第一条".encode("gbk"), "老讲义.txt")[0] == "第一条"
    with pytest.raises(HTTPException) as e:
        _extract(b"xx", "成绩单.xlsx")
    assert e.value.status_code == 415 and "四种" in e.value.detail
