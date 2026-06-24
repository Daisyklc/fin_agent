"""文档登记表：doc_id ↔ 原始文件路径 ↔ 标题。

doc_id 规则（实测）：
  - financial_reports / financial_contracts / research / insurance：
        doc_id == 文件名去扩展名（大小写不敏感，兼容 .PDF/.pdf）。
  - regulatory：
        * strict_v3_xxx_...  → raw/regulatory/txt/<doc_id>.txt（精确同名）
        * strict_csrc_NNN    → raw/regulatory/html/csrc_{NNNN}.html
"""

from __future__ import annotations

import re
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path

from config import settings

logger = logging.getLogger("doc_registry")

_DOC_EXTS = {".pdf", ".txt", ".html", ".htm"}
_CSRC_RE = re.compile(r"^strict_csrc_(\d+)$", re.IGNORECASE)


@dataclass
class DocEntry:
    doc_id: str
    domain: str
    path: str
    ext: str


class DocRegistry:
    def __init__(self) -> None:
        # stem(小写) -> DocEntry
        self._by_stem: dict[str, DocEntry] = {}
        # csrc 编号(int) -> DocEntry
        self._csrc_by_num: dict[int, DocEntry] = {}
        self._build()

    def _build(self) -> None:
        for domain in settings.DOMAINS:
            domain_dir = settings.RAW_DIR / domain
            if not domain_dir.exists():
                continue
            for path in domain_dir.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in _DOC_EXTS:
                    continue
                stem = path.stem
                entry = DocEntry(
                    doc_id=stem,
                    domain=domain,
                    path=str(path),
                    ext=path.suffix.lower(),
                )
                self._by_stem.setdefault(stem.lower(), entry)
                m = re.match(r"^csrc_(\d+)$", stem, re.IGNORECASE)
                if m:
                    self._csrc_by_num[int(m.group(1))] = entry
        logger.info("DocRegistry 载入 %d 个文件", len(self._by_stem))

    # -------------------------------------------------------------- #
    def resolve(self, doc_id: str) -> DocEntry | None:
        """把题目里的 doc_id 解析到具体文件。"""
        key = doc_id.strip().lower()
        if key in self._by_stem:
            return self._by_stem[key]

        # regulatory: strict_csrc_NNN → csrc_{NNNN}.html
        m = _CSRC_RE.match(doc_id.strip())
        if m:
            num = int(m.group(1))
            if num in self._csrc_by_num:
                return self._csrc_by_num[num]

        # 去掉 strict_ 前缀再试一次
        if key.startswith("strict_"):
            stripped = key[len("strict_"):]
            if stripped in self._by_stem:
                return self._by_stem[stripped]

        logger.warning("未能解析 doc_id: %s", doc_id)
        return None

    def all_entries(self) -> list[DocEntry]:
        return list(self._by_stem.values())

    def entries_for_domain(self, domain: str) -> list[DocEntry]:
        return [e for e in self._by_stem.values() if e.domain == domain]

    def dump(self, path: Path | None = None) -> Path:
        """导出登记表为 JSON，便于核查映射。"""
        path = path or (settings.PROCESSED_DIR / "doc_registry.json")
        data = [asdict(e) for e in self._by_stem.values()]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


_REGISTRY: DocRegistry | None = None


def get_registry() -> DocRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = DocRegistry()
    return _REGISTRY
