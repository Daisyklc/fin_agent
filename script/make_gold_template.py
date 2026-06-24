"""生成标准答案(gold)模板，供人工填写后做准确率与错题分析。

A 榜官方不提供标准答案，可借此自建小规模校验集：填写你已核对确认的题目答案，
留空的题目不计入准确率统计。

用法：
    python -m script.make_gold_template                 # 全部领域 → gold/group_a_gold.csv
    python -m script.make_gold_template --domain insurance
"""

from __future__ import annotations

import sys
import csv
import argparse

from config import settings
from agent.questions import load_questions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="group_a")
    ap.add_argument("--domain", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    questions = load_questions(args.group, args.domain)
    gold_dir = settings.ROOT / "gold"
    gold_dir.mkdir(exist_ok=True)
    out = args.out or (gold_dir / f"{args.group}_gold.csv")

    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["qid", "domain", "answer_format", "type", "answer", "question_brief"])
        for q in questions:
            brief = q.question[:40].replace("\n", " ")
            w.writerow([q.qid, q.domain, q.answer_format, q.type, "", brief])

    print(f"已生成 gold 模板: {out}（共 {len(questions)} 行）")
    print("请在 answer 列填入标准答案（mcq/tf 单字母，multi 多字母如 ABD），留空的题不计分。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
