"""答案规范化与 answer.csv 生成。

格式要求：
  - 单选(mcq)/判断(tf)：单个大写字母（取首个有效）。
  - 多选(multi)：多个大写字母，去重 + 升序，无分隔符，如 ABC。
  - answer.csv 首行为 summary（含 token 统计），其余每行为各题。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from agent.questions import Question
from agent.token_tracker import TokenTracker

_LETTER_RE = re.compile(r"[A-Z]")


def normalize_answer(raw: str, q: Question) -> str:
    """把模型原始输出规范化为合法答案字母串。"""
    if not raw:
        return ""
    text = raw.upper()
    valid = set(q.valid_letters)
    letters = [c for c in _LETTER_RE.findall(text) if c in valid]
    if not letters:
        return ""

    if q.answer_format == "multi":
        return "".join(sorted(set(letters)))
    # mcq / tf：取首个有效字母
    return letters[0]


def write_answer_csv(
    path: Path,
    questions: list[Question],
    answers: dict[str, str],
    tracker: TokenTracker,
) -> Path:
    usage = {q.qid: (
        tracker.usage_for(q.qid).prompt_tokens,
        tracker.usage_for(q.qid).completion_tokens,
        tracker.usage_for(q.qid).total_tokens,
    ) for q in questions}
    return write_answer_csv_rows(path, questions, answers, usage)


def write_answer_csv_rows(
    path: Path,
    questions: list[Question],
    answers: dict[str, str],
    qid_usage: dict[str, tuple[int, int, int]],
) -> Path:
    """用显式的 per-qid token 映射写出 answer.csv（合并多次运行时使用）。"""
    sp = sum(u[0] for u in qid_usage.values())
    sc = sum(u[1] for u in qid_usage.values())
    st = sum(u[2] for u in qid_usage.values())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["qid", "answer", "prompt_tokens", "completion_tokens", "total_tokens"])
        w.writerow(["summary", "", sp, sc, st])
        for q in questions:
            p, c, t = qid_usage.get(q.qid, (0, 0, 0))
            w.writerow([q.qid, answers.get(q.qid, ""), p, c, t])
    return path
