# ============================================================
# 解析边（parsing.py）：上传文件 → 纯文本文章
# PDF「印刷指令单」交 PyMuPDF 重放；TXT/MD 字符流解码；.docx 走 python-docx
# （段落+表格拼接）——S8 还账刀 2026-09-11 拍甲补上（PRD 5.1.1 旧诺）。
# 刀 = PyMuPDF（D2 拍板：PRD 12.2 hint 的 pypdf 被此决策推翻——
# 同为免费家族，PyMuPDF 的 C 引擎快一个量级，中文阅读序还原更稳）。
# import 名演变史：老账叫 fitz，1.28 起官方弃用、现名 pymupdf——用新名防未来拆桥
# ============================================================
import io

import pymupdf
from docx import Document


def parse_pdf(data: bytes) -> tuple[str, int]:
    """吃 PDF 字节（内存直接开，不落磁盘），回 (全文文本, 页数)。
    get_text 让引擎按坐标把每页文字重放成阅读顺序的文章流。"""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        pages = doc.page_count
        # 页间空一行隔开，保住「这页结束」的边界感
        text = "\n\n".join(page.get_text("text") for page in doc)
    return text, pages


def parse_text(data: bytes) -> str:
    """吃 TXT/MD 字节回文本——它们本就是字符流，唯一坎是编码：
    先按 UTF-8 严判（utf-8-sig 顺带罩住带 BOM 头的），不通再试 GBK
    （国产旧讲义常见），还不通就查一处补一个 ，垃圾进但不炸。"""
    for enc in ("utf-8-sig", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_docx(data: bytes) -> str:
    """吃 .docx 字节回纯文本（S8 还账刀 · 用户拍甲 2026-09-11：PRD 5.1.1 早承诺
    Word，此前 415 挡着）。python-docx 只认 OOXML（.docx），2007 前的 .doc 是
    另一套二进制——不收，前端 accept 同步归真。
    文档正文按体例走：段落是骨架，表格是附属——都读出来，表格每行拼成
    「单元格 | 单元格」一行（讲义里的对照表/生词表常见，切块后语义仍在）。
    内存直开不落盘（parse_pdf 同款姿势）；坏文件抛出去由 _extract 转人话。"""
    doc = Document(io.BytesIO(data))
    parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
    for tbl in doc.tables:
        for row in tbl.rows:
            line = " | ".join(c.text.strip() for c in row.cells)
            if line.strip(" |"):
                parts.append(line)
    return "\n".join(parts)
