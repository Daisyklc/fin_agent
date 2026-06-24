"""把原始文档解析、切块，输出到 processed_data/<domain>/<doc_id>.jsonl。

默认只解析被 A 榜题目引用的文档（加速开发）；加 --all 解析全部文档（B 榜需要）。

用法：
    python -m script.parse_docs                 # 仅题目引用到的文档
    python -m script.parse_docs --all           # 全部文档
    python -m script.parse_docs --domain insurance
"""

from __future__ import annotations

import sys
import json
import argparse
import logging

from config import settings
from agent.questions import load_questions
from agent.doc_registry import get_registry, DocEntry
from agent.parsing import parse_doc
from agent.chunking import chunk_blocks, chunk_to_dict

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("parse_docs")


def _referenced_doc_ids(domain: str | None) -> set[str]:
    qs = load_questions("group_a", domain)
    ids: set[str] = set()
    for q in qs:
        ids.update(q.doc_ids)
    return ids


def _targets(args) -> list[DocEntry]:
    reg = get_registry()
    if args.all:
        entries = reg.all_entries()
    else:
        ref_ids = _referenced_doc_ids(args.domain)
        entries = []
        seen = set()
        for did in ref_ids:
            e = reg.resolve(did)
            if e and e.path not in seen:
                entries.append(e)
                seen.add(e.path)
    if args.domain:
        entries = [e for e in entries if e.domain == args.domain]
    return entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="解析全部文档（含未被题目引用的）")
    ap.add_argument("--domain", default=None, help="只处理某个领域")
    ap.add_argument("--force", action="store_true", help="已存在也重新解析")
    args = ap.parse_args()

    entries = _targets(args)
    logger.info("待解析文档: %d 个", len(entries))

    try:
        from tqdm import tqdm
        iterator = tqdm(entries, desc="parsing")
    except ImportError:
        iterator = entries

    ok, empty, failed = 0, 0, 0
    for e in iterator:
        out_dir = settings.PROCESSED_DIR / e.domain
        out_dir.mkdir(parents=True, exist_ok=True)
        out_fp = out_dir / f"{e.doc_id}.jsonl"
        if out_fp.exists() and not args.force:
            ok += 1
            continue

        blocks = parse_doc(e)
        if not blocks:
            failed += 1
            logger.warning("无内容: %s", e.doc_id)
            continue

        chunks = chunk_blocks(blocks)
        if not chunks:
            empty += 1
            continue

        with open(out_fp, "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(chunk_to_dict(c), ensure_ascii=False) + "\n")
        ok += 1

    logger.info("完成: 成功=%d 空=%d 失败=%d", ok, empty, failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
