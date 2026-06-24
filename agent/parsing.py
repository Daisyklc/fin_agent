"""文档解析：PDF / HTML / TXT → 结构化文本块。

预处理阶段，允许使用非 Qwen 工具（pdfplumber/bs4 等）做解析与版面/表格还原。
输出的块尽量保留页码、章节/条款标题与表格，供后续检索与压缩使用。
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

from agent.doc_registry import DocEntry

logger = logging.getLogger("parsing")


@dataclass
class Block:
    """一个文本块（一页正文、或一张表格）。"""
    doc_id: str
    domain: str
    page: int                # 1-based；非 PDF 记 0
    text: str
    is_table: bool = False
    section_title: str = ""


# ---------------------------------------------------------------------- #
# 编码检测（监管 txt 多为 GBK/UTF-8）
# ---------------------------------------------------------------------- #
def _read_text_file(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-8", "gb18030", "gbk", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


# ---------------------------------------------------------------------- #
# 各格式解析
# ---------------------------------------------------------------------- #
def _table_to_text(table: list[list]) -> str:
    """把 pdfplumber 提取的表格转成可读文本（管道分隔，保留行列关系）。"""
    rows = []
    for row in table or []:
        cells = ["" if c is None else str(c).replace("\n", " ").strip() for c in row]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def parse_pdf(entry: DocEntry) -> list[Block]:
    import pdfplumber

    blocks: list[Block] = []
    with pdfplumber.open(entry.path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as e:  # noqa: BLE001
                logger.warning("%s 第%d页文本抽取失败: %s", entry.doc_id, i, e)
                text = ""
            if text.strip():
                blocks.append(Block(entry.doc_id, entry.domain, i, text.strip()))

            try:
                tables = page.extract_tables() or []
            except Exception:  # noqa: BLE001
                tables = []
            for t in tables:
                ttext = _table_to_text(t)
                if ttext.strip():
                    blocks.append(
                        Block(entry.doc_id, entry.domain, i, ttext, is_table=True)
                    )
    return blocks


def parse_html(entry: DocEntry) -> list[Block]:
    from bs4 import BeautifulSoup

    html = _read_text_file(entry.path)
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # 表格单独成块
    blocks: list[Block] = []
    for tbl in soup.find_all("table"):
        rows = []
        for tr in tbl.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            blocks.append(
                Block(entry.doc_id, entry.domain, 0, "\n".join(rows),
                      is_table=True, section_title=title)
            )
        tbl.decompose()

    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    if text.strip():
        blocks.insert(0, Block(entry.doc_id, entry.domain, 0, text.strip(),
                               section_title=title))
    return blocks


def parse_txt(entry: DocEntry) -> list[Block]:
    text = _read_text_file(entry.path)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return [Block(entry.doc_id, entry.domain, 0, text)] if text else []


def parse_doc(entry: DocEntry) -> list[Block]:
    try:
        if entry.ext == ".pdf":
            return parse_pdf(entry)
        if entry.ext in (".html", ".htm"):
            return parse_html(entry)
        if entry.ext == ".txt":
            return parse_txt(entry)
    except Exception as e:  # noqa: BLE001
        logger.error("解析失败 %s (%s): %s", entry.doc_id, entry.path, e)
        return []
    logger.warning("未支持的扩展名: %s", entry.ext)
    return []
