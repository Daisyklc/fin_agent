"""校验 answer.csv 是否符合官方线上评测的提交格式。

依据赛题《四、提交格式》《五、评测指标》：
  - 表头：qid,answer,prompt_tokens,completion_tokens,total_tokens
  - 含 summary 行，提供 prompt/completion/total 的总消耗，且 total=prompt+completion
  - 单选(mcq)/判断(tf)：单个大写字母；多选(multi)：多个大写字母，去重+升序，无分隔符
  - 答案不能为空、不能含非法字符、不能越出该题选项范围
  - 每题 total_tokens 应等于 prompt+completion

用法：
    python -m script.validate_submission                 # 校验 answer.csv
    python -m script.validate_submission --answer answer_run2.csv
"""

from __future__ import annotations

import sys
import csv
import re
import argparse
from pathlib import Path

from config import settings
from agent.questions import load_questions

EXPECTED_HEADER = ["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"]
_LETTERS_ONLY = re.compile(r"^[A-Z]+$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answer", default="answer.csv")
    ap.add_argument("--group", default="group_a")
    args = ap.parse_args()

    path = settings.ROOT / args.answer
    if not path.exists():
        print(f"[FAIL] 找不到文件: {path}")
        return 2

    questions = {q.qid: q for q in load_questions(args.group)}
    errors: list[str] = []
    warnings: list[str] = []

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        print("[FAIL] 文件为空")
        return 2

    # 1) 表头
    header = [h.strip() for h in rows[0]]
    if header != EXPECTED_HEADER:
        errors.append(f"表头不符，应为 {EXPECTED_HEADER}，实际 {header}")

    # 2) 解析行
    summary = None
    seen: set[str] = set()
    per_q_total_sum = 0
    answered_qids: set[str] = set()

    for ln, row in enumerate(rows[1:], start=2):
        if len(row) != 5:
            errors.append(f"第{ln}行列数应为5，实际{len(row)}: {row}")
            continue
        qid, ans, p, c, t = [x.strip() for x in row]
        try:
            p, c, t = int(p), int(c), int(t)
        except ValueError:
            errors.append(f"第{ln}行 token 非整数: {row}")
            continue

        if qid == "summary":
            summary = (p, c, t)
            continue

        if qid in seen:
            errors.append(f"第{ln}行 qid 重复: {qid}")
        seen.add(qid)

        if t != p + c:
            errors.append(f"{qid}: total_tokens({t}) != prompt({p})+completion({c})")
        per_q_total_sum += t

        # 答案格式校验
        q = questions.get(qid)
        if q is None:
            warnings.append(f"{qid} 不在题库中（可能多余）")
            continue
        answered_qids.add(qid)
        valid = set(q.valid_letters)

        if ans == "":
            errors.append(f"{qid}: 答案为空（将判错）")
        elif not _LETTERS_ONLY.match(ans):
            errors.append(f"{qid}: 含非法字符或分隔符: '{ans}'")
        else:
            bad = [ch for ch in ans if ch not in valid]
            if bad:
                errors.append(f"{qid}: 选项越界 {bad}（合法 {sorted(valid)}）")
            if q.answer_format in ("mcq", "tf") and len(ans) != 1:
                errors.append(f"{qid}: {q.answer_format} 应为单字母，实际 '{ans}'")
            if q.answer_format == "multi":
                if list(ans) != sorted(set(ans)):
                    errors.append(f"{qid}: multi 答案需去重且升序: '{ans}'")

    # 3) summary 检查
    if summary is None:
        errors.append("缺少 summary 行（必须提供 token 消耗统计）")
    else:
        sp, sc, st = summary
        if st != sp + sc:
            errors.append(f"summary: total({st}) != prompt({sp})+completion({sc})")
        if st <= 0:
            errors.append("summary.total_tokens <= 0，TokenScore 将记 0")
        if st != per_q_total_sum:
            warnings.append(f"summary.total({st}) 与各题 total 之和({per_q_total_sum}) 不一致")

    # 4) 覆盖度
    missing = set(questions) - answered_qids
    if missing:
        errors.append(f"缺少 {len(missing)} 题: {sorted(missing)[:10]}{'...' if len(missing)>10 else ''}")

    # 输出
    print("=" * 60)
    print(f"校验文件: {path.name}")
    print(f"题库题数: {len(questions)}  已作答: {len(answered_qids)}")
    if summary:
        ts = max(0.0, min(1.0, (settings.TOKEN_BUDGET - summary[2]) / settings.TOKEN_BUDGET))
        print(f"summary total_tokens: {summary[2]:,}  TokenScore≈{ts:.3f}")
    print("=" * 60)
    if warnings:
        print(f"[警告] {len(warnings)} 条:")
        for w in warnings:
            print("  -", w)
    if errors:
        print(f"[FAIL] {len(errors)} 个错误:")
        for e in errors:
            print("  -", e)
        return 1
    print("[OK] answer.csv 符合官方提交格式要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
