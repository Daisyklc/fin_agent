"""从 DeepSeek vs Qwen 分歧题中筛选优先人工复核清单。

用法：
    python -m script.prioritize_review
    python -m script.prioritize_review --top 20
"""

from __future__ import annotations

import csv
import json
import argparse
from collections import Counter
from pathlib import Path

from config import settings
from agent.questions import load_questions

HIGH_RISK = {
    "ins_a_003", "ins_a_007", "ins_a_016", "reg_a_006", "reg_a_012",
    "reg_a_017", "fc_a_007", "res_a_006",
}

HINTS = {
    "res_a_006": "核对「除客户资金杠杆」是否改变判断",
    "ins_a_003": "补偿型总额上限 vs 分险种加总",
    "reg_a_012": "C项「不披露分红原因」限定条件",
    "reg_a_017": "C项是法条还是案例意见",
    "fc_a_007": "两家文档评级/要素逐项核对",
    "ins_a_007": "B项贷款比例是否有条款依据",
}

FIELDS = [
    "priority", "qid", "domain", "format", "deepseek", "qwen", "score",
    "tags", "lean", "review_hint", "question", "verify_note", "ds_reason",
]


def _score_row(qid, q, d_ans, w_ans, ev, reason) -> tuple[int, list[str], str, str]:
    verified = ev.get("verified", False)
    agree = ev.get("agree", True)
    confidence = ev.get("confidence", "")
    initial = ev.get("initial_answer", "")
    note = ev.get("verify_note", "")

    score, tags = 0, []
    if qid in HIGH_RISK:
        score += 30
        tags.append("高风险题")
    if verified and not agree:
        score += 25
        tags.append("Qwen复核不一致")
    if confidence == "low":
        score += 15
        tags.append("Qwen低置信")
    if q.domain in ("financial_reports", "research"):
        score += 12
        tags.append("弱项领域")
    elif q.domain == "financial_contracts":
        score += 8
    if q.answer_format == "multi":
        score += 10
        tags.append("多选")
    sym = len(set(d_ans) ^ set(w_ans))
    score += sym * 5
    if sym >= 2:
        tags.append(f"差{sym}项")
    if any(k in reason for k in ("无法", "不确定", "无证据", "未提及", "常识")):
        score += 8
        tags.append("DS存疑")
    if verified and initial and initial != w_ans:
        score += 10
        tags.append("verify改答")

    hint = HINTS.get(qid, "")
    if not hint:
        if q.domain == "financial_reports":
            hint = "核对报表数值与同比方向"
        elif q.domain == "research":
            hint = "注意否定词与时间口径"
        elif q.answer_format == "multi":
            hint = "逐选项核对防漏选"

    lean = "待人工"
    if qid in HIGH_RISK and verified and not agree and confidence == "high":
        lean = "倾向Qwen(verify)"
    if "DS存疑" in tags and "Qwen复核不一致" not in tags:
        lean = "倾向Qwen"
    if qid == "res_a_006":
        lean = "待人工(否定词)"

    return score, tags, hint, lean, note


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--annotate", default=str(settings.LOGS_DIR / "deepseek_annotate_full.json"))
    ap.add_argument("--answer", default=str(settings.OUTPUT_DIR / "answer.csv"))
    ap.add_argument("--evidence", default=str(settings.OUTPUT_DIR / "evidence.json"))
    args = ap.parse_args()

    questions = {q.qid: q for q in load_questions()}
    data = json.loads(Path(args.annotate).read_text(encoding="utf-8"))
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    qwen: dict[str, str] = {}
    with open(args.answer, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            qid = (row.get("qid") or "").strip()
            if qid and qid != "summary":
                qwen[qid] = (row.get("answer") or "").strip()

    rows = []
    for qid, ds in data.items():
        q = questions[qid]
        d_ans, w_ans = ds.get("answer", ""), qwen.get(qid, "")
        if not d_ans or d_ans == w_ans:
            continue
        reason = ds.get("reason", "")
        score, tags, hint, lean, note = _score_row(qid, q, d_ans, w_ans, evidence.get(qid, {}), reason)
        rows.append({
            "qid": qid, "domain": q.domain, "format": q.answer_format,
            "deepseek": d_ans, "qwen": w_ans, "score": score,
            "tags": "|".join(tags), "review_hint": hint, "lean": lean,
            "question": q.question[:80].replace("\n", " "),
            "verify_note": note[:120], "ds_reason": reason[:180],
        })

    rows.sort(key=lambda x: (-x["score"], x["qid"]))
    for i, r in enumerate(rows, 1):
        r["priority"] = i

    gold_dir = settings.ROOT / "gold"
    gold_dir.mkdir(exist_ok=True)
    top_n = rows[: args.top]

    for name, subset in [
        (f"review_priority_top{args.top}.csv", top_n),
        ("review_priority_all57.csv", rows),
    ]:
        with open(gold_dir / name, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(subset)

    lines = [
        f"# 分歧题优先复核清单（Top {args.top} / 共 {len(rows)} 题）\n",
        "## 已确认一致（跳过重核）\n",
        "- `reg_a_006`：B = B",
        "- `ins_a_016`：CD = CD\n",
        f"## Top {args.top}\n",
        "| # | 题号 | 领域 | DS | Qwen | 分 | 倾向 | 复核要点 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in top_n:
        lines.append(
            f"| {r['priority']} | {r['qid']} | {r['domain']} | **{r['deepseek']}** "
            f"| **{r['qwen']}** | {r['score']} | {r['lean']} | {r['review_hint']} |"
        )

    lines += ["\n## 领域分布\n", "| 领域 | 分歧 |", "|---|---|"]
    c = Counter(r["domain"] for r in rows)
    for dom in ["financial_reports", "research", "financial_contracts", "regulatory", "insurance"]:
        lines.append(f"| {dom} | {c[dom]} |")

    lines.append("\n## 逐题详情\n")
    for r in top_n:
        lines.append(f"### {r['priority']}. {r['qid']}")
        lines.append(f"- DS **{r['deepseek']}** vs Qwen **{r['qwen']}** | {r['lean']}")
        lines.append(f"- 题干: {r['question']}")
        if r["verify_note"]:
            lines.append(f"- Qwen复核: {r['verify_note']}")
        lines.append(f"- DS依据: {r['ds_reason']}")
        lines.append("")

    report = settings.LOGS_DIR / f"review_priority_top{args.top}.md"
    report.write_text("\n".join(lines), encoding="utf-8")

    print(f"分歧题 {len(rows)} 道，已输出 Top {args.top}:")
    print(f"  {gold_dir / f'review_priority_top{args.top}.csv'}")
    print(f"  {gold_dir / 'review_priority_all57.csv'}")
    print(f"  {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
