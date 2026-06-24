"""对比两次运行的 answer.csv：答案变化、token 差异、按领域统计。

用法：
    python -m script.compare_runs --a answer_run1.csv --b answer.csv
"""

from __future__ import annotations

import sys
import csv
import argparse
from collections import defaultdict
from pathlib import Path

from agent.questions import load_questions


def _load(path: Path) -> tuple[dict[str, str], dict[str, int], int]:
    preds, toks, summary = {}, {}, 0
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            qid = (row.get("qid") or "").strip()
            if not qid:
                continue
            t = int(row.get("total_tokens") or 0)
            if qid == "summary":
                summary = t
                continue
            preds[qid] = (row.get("answer") or "").strip()
            toks[qid] = t
    return preds, toks, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="answer_run1.csv", help="旧结果")
    ap.add_argument("--b", default="answer.csv", help="新结果")
    args = ap.parse_args()

    a_preds, a_tok, a_sum = _load(Path(args.a))
    b_preds, b_tok, b_sum = _load(Path(args.b))
    qmap = {q.qid: q for q in load_questions("group_a")}

    changed = []
    for qid in sorted(set(a_preds) | set(b_preds)):
        if a_preds.get(qid) != b_preds.get(qid):
            changed.append(qid)

    by_dom = defaultdict(int)
    for qid in changed:
        by_dom[qmap[qid].domain if qid in qmap else "?"] += 1

    print("=" * 60)
    print(f"A(旧): {args.a}  总Token={a_sum:,}")
    print(f"B(新): {args.b}  总Token={b_sum:,}  (Δ={b_sum - a_sum:+,})")
    print("=" * 60)
    print(f"答案发生变化: {len(changed)} / {len(qmap)} 题")
    print("按领域:", dict(by_dom))
    print("-" * 60)
    for qid in changed:
        dom = qmap[qid].domain if qid in qmap else "?"
        print(f"  {qid:<12}[{dom:<18}] {a_preds.get(qid,''):<6} -> {b_preds.get(qid,'')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
