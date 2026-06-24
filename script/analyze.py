"""结果分析与 baseline 对照。

无 gold 时：输出答案分布、各领域/题型 token 消耗与召回情况。
有 gold 时：额外计算准确率、FinalScore、分项准确率、错题报告，并与官方 baseline 对照。

用法：
    python -m script.analyze                          # 读 answer.csv，自动探测 gold/
    python -m script.analyze --gold gold/group_a_gold.csv
    python -m script.analyze --answer answer.csv --evidence evidence.json
"""

from __future__ import annotations

import sys
import csv
import json
import argparse
from collections import defaultdict
from pathlib import Path

from config import settings
from agent.questions import load_questions, Question
from agent.scoring import (
    canonical, is_correct, token_score, final_score, OFFICIAL_BASELINE,
)


def load_answer_csv(path: Path) -> tuple[dict[str, str], dict[str, int], int]:
    """返回 (preds, per_qid_total_tokens, summary_total_tokens)。"""
    preds: dict[str, str] = {}
    qid_tokens: dict[str, int] = {}
    summary_total = 0
    if not path.exists():
        return preds, qid_tokens, summary_total
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            qid = (row.get("qid") or "").strip()
            if not qid:
                continue
            tot = int(row.get("total_tokens") or 0)
            if qid == "summary":
                summary_total = tot
                continue
            preds[qid] = (row.get("answer") or "").strip()
            qid_tokens[qid] = tot
    return preds, qid_tokens, summary_total


def load_gold(path: Path) -> dict[str, str]:
    gold: dict[str, str] = {}
    if not path.exists():
        return gold
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            qid = (row.get("qid") or "").strip()
            ans = (row.get("answer") or "").strip()
            if qid and ans:
                gold[qid] = ans
    return gold


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "—"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answer", default=str(settings.OUTPUT_DIR / "answer.csv"))
    ap.add_argument("--evidence", default=str(settings.OUTPUT_DIR / "evidence.json"))
    ap.add_argument("--gold", default=None)
    ap.add_argument("--group", default="group_a")
    ap.add_argument("--report", default=None, help="错题报告输出路径(.md)")
    args = ap.parse_args()

    questions = load_questions(args.group)
    qmap: dict[str, Question] = {q.qid: q for q in questions}
    preds, qid_tokens, summary_total = load_answer_csv(Path(args.answer))

    evidence = {}
    ev_path = Path(args.evidence)
    if ev_path.exists():
        evidence = json.loads(ev_path.read_text(encoding="utf-8"))

    print("=" * 64)
    print(f"答案文件: {args.answer}")
    print(f"已作答题目: {len(preds)} / {len(questions)}")
    print(f"总 Token(summary): {summary_total:,}  TokenScore≈{token_score(summary_total):.3f}")
    print("=" * 64)

    # ---------- 无需 gold 的统计 ----------
    empty_ans = [qid for qid in qmap if not preds.get(qid)]
    print(f"空答案/缺失: {len(empty_ans)}")
    if empty_ans:
        print("  ", ", ".join(empty_ans[:20]), ("..." if len(empty_ans) > 20 else ""))

    print("-" * 64)
    print(f"{'领域':<20}{'题数':>6}{'已答':>6}{'平均Token':>12}")
    dom_tokens: dict[str, list[int]] = defaultdict(list)
    dom_total: dict[str, int] = defaultdict(int)
    dom_answered: dict[str, int] = defaultdict(int)
    for q in questions:
        dom_total[q.domain] += 1
        if preds.get(q.qid):
            dom_answered[q.domain] += 1
        if q.qid in qid_tokens:
            dom_tokens[q.domain].append(qid_tokens[q.qid])
    for dom in settings.DOMAINS:
        toks = dom_tokens.get(dom, [])
        avg = sum(toks) / len(toks) if toks else 0
        print(f"{dom:<20}{dom_total[dom]:>6}{dom_answered[dom]:>6}{avg:>12,.0f}")

    # ---------- gold 相关 ----------
    gold_path = Path(args.gold) if args.gold else (settings.ROOT / "gold" / f"{args.group}_gold.csv")
    gold = load_gold(gold_path)
    if not gold:
        print("-" * 64)
        print(f"[提示] 未找到已填写的 gold ({gold_path})，跳过准确率与错题分析。")
        print("       可运行 `python -m script.make_gold_template` 生成模板后填写。")
        return 0

    print("=" * 64)
    print(f"准确率分析（gold 覆盖 {len(gold)} 题）")
    print("=" * 64)

    overall_c = overall_t = 0
    by_dom = defaultdict(lambda: [0, 0])   # domain -> [correct, total]
    by_fmt = defaultdict(lambda: [0, 0])
    by_type = defaultdict(lambda: [0, 0])
    wrong: list[dict] = []

    for q in questions:
        if q.qid not in gold:
            continue
        overall_t += 1
        by_dom[q.domain][1] += 1
        by_fmt[q.answer_format][1] += 1
        by_type[q.type][1] += 1
        ok = is_correct(preds.get(q.qid, ""), gold[q.qid], q.answer_format)
        if ok:
            overall_c += 1
            by_dom[q.domain][0] += 1
            by_fmt[q.answer_format][0] += 1
            by_type[q.type][0] += 1
        else:
            ev = evidence.get(q.qid, {})
            wrong.append({
                "qid": q.qid, "domain": q.domain, "format": q.answer_format,
                "pred": canonical(preds.get(q.qid, ""), q.answer_format),
                "gold": canonical(gold[q.qid], q.answer_format),
                "question": q.question,
                "reason": ev.get("reason", ""),
                "evidence": ev.get("evidence", []),
            })

    acc = overall_c / overall_t if overall_t else 0.0
    fs = final_score(acc, summary_total)
    print(f"总体: {overall_c}/{overall_t}  准确率={_pct(overall_c, overall_t)}")
    print(f"FinalScore = 100 * {acc:.3f} * (0.7 + 0.3 * {token_score(summary_total):.3f}) = {fs:.2f}")

    print("-" * 64)
    print("按领域:")
    for dom in settings.DOMAINS:
        c, t = by_dom[dom]
        print(f"  {dom:<20} {c}/{t}  {_pct(c, t)}")
    print("按题型:")
    for fmt, (c, t) in sorted(by_fmt.items()):
        print(f"  {fmt:<20} {c}/{t}  {_pct(c, t)}")

    # ---------- baseline 对照 ----------
    print("=" * 64)
    print("与官方 baseline 对照（A 榜）")
    base = OFFICIAL_BASELINE["A"]
    base_fs = final_score(base["accuracy"], base["tokens"])
    print(f"{'':<10}{'准确率':>10}{'Token':>14}{'FinalScore':>14}")
    print(f"{'baseline':<10}{_pct(base['correct'], base['total']):>10}{base['tokens']:>14,}{base_fs:>14.2f}")
    print(f"{'ours':<10}{_pct(overall_c, overall_t):>10}{summary_total:>14,}{fs:>14.2f}")

    # ---------- 错题报告 ----------
    if wrong:
        report_path = Path(args.report) if args.report else (settings.LOGS_DIR / "error_report.md")
        lines = [f"# 错题报告（{len(wrong)} 题）\n"]
        for w in wrong:
            lines.append(f"## {w['qid']} [{w['domain']}/{w['format']}]")
            lines.append(f"- 预测: **{w['pred']}**  标准: **{w['gold']}**")
            lines.append(f"- 题干: {w['question']}")
            if w["reason"]:
                lines.append(f"- 模型依据: {w['reason']}")
            if w["evidence"]:
                lines.append("- 引用证据:")
                for e in w["evidence"]:
                    lines.append(f"    - [{e.get('doc_id','')} {e.get('loc','')}] {e.get('quote','')}")
            lines.append("")
        report_path.write_text("\n".join(lines), encoding="utf-8")
        print("-" * 64)
        print(f"错题报告已写入: {report_path}（{len(wrong)} 题）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
