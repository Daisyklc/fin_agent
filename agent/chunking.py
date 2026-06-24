"""把解析得到的 Block 切成检索单元 Chunk。

策略：
  - 表格块整体保留（数值上下文不可拆断）。
  - 正文块优先按结构边界（第X条 / 第X章 / 编号标题）切分；
    过长再按字符窗口 + 重叠滑动，避免切断条款。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from agent.parsing import Block

# 结构边界：法规条款、章节、合同条款等
_STRUCT_RE = re.compile(
    r"(?=(?:第[一二三四五六七八九十百零〇\d]+[条章节款项编]"
    r"|^\s*\d+[\.、]\s"
    r"|^\s*（[一二三四五六七八九十]+）))",
    re.MULTILINE,
)

# 条款编号抽取（用于检索加权与证据定位）
_CLAUSE_RE = re.compile(r"第[一二三四五六七八九十百零〇\d]+条")


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    domain: str
    page: int
    text: str
    is_table: bool
    section_title: str
    clauses: list[str]


def _split_by_structure(text: str) -> list[str]:
    parts = [p.strip() for p in _STRUCT_RE.split(text) if p and p.strip()]
    return parts if parts else [text.strip()]


def _window_split(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out, start = [], 0
    while start < len(text):
        end = start + size
        out.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return out


def chunk_blocks(
    blocks: list[Block],
    *,
    max_chars: int = 1200,
    overlap: int = 150,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    counter = 0

    def _emit(b: Block, text: str) -> None:
        nonlocal counter
        text = text.strip()
        if not text:
            return
        chunks.append(
            Chunk(
                doc_id=b.doc_id,
                chunk_id=f"{b.doc_id}::c{counter:04d}",
                domain=b.domain,
                page=b.page,
                text=text,
                is_table=b.is_table,
                section_title=b.section_title,
                clauses=_CLAUSE_RE.findall(text),
            )
        )
        counter += 1

    for b in blocks:
        if b.is_table:
            # 表格整体保留；超长则按窗口切（极少见）
            for piece in _window_split(b.text, max_chars * 3, overlap):
                _emit(b, piece)
            continue

        for seg in _split_by_structure(b.text):
            if len(seg) <= max_chars:
                _emit(b, seg)
            else:
                for piece in _window_split(seg, max_chars, overlap):
                    _emit(b, piece)

    return chunks


def chunk_to_dict(c: Chunk) -> dict:
    return asdict(c)
