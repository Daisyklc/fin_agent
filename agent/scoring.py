"""评分核心：复用赛题公式。

  Accuracy   = Correct / Total
  TokenScore = max(0, min(1, (TokenBudget - TotalTokens) / TokenBudget))
  FinalScore = 100 * Accuracy * (0.7 + 0.3 * TokenScore)

答案比对规则（与赛题一致）：
  - mcq/tf：取首个有效字母比对。
  - multi：去重 + 升序后完全匹配，无部分分。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import settings
from agent.questions import Question

_LETTER_RE = re.compile(r"[A-Z]")


def canonical(ans: str, answer_format: str) -> str:
    """把答案串标准化，用于比对。"""
    if not ans:
        return ""
    letters = _LETTER_RE.findall(ans.upper())
    if not letters:
        return ""
    if answer_format == "multi":
        return "".join(sorted(set(letters)))
    return letters[0]


def is_correct(pred: str, gold: str, answer_format: str) -> bool:
    return canonical(pred, answer_format) == canonical(gold, answer_format) != ""


def token_score(total_tokens: int, budget: int = settings.TOKEN_BUDGET) -> float:
    if total_tokens is None or total_tokens <= 0:
        return 0.0
    return max(0.0, min(1.0, (budget - total_tokens) / budget))


def final_score(accuracy: float, total_tokens: int,
                budget: int = settings.TOKEN_BUDGET) -> float:
    ts = token_score(total_tokens, budget)
    return 100.0 * accuracy * (0.7 + 0.3 * ts)


@dataclass
class ScoreReport:
    total: int
    correct: int
    accuracy: float
    total_tokens: int
    token_score: float
    final_score: float


def score(
    questions: list[Question],
    preds: dict[str, str],
    gold: dict[str, str],
    total_tokens: int,
) -> ScoreReport:
    total = 0
    correct = 0
    for q in questions:
        if q.qid not in gold or gold[q.qid] == "":
            continue  # 未提供标准答案的题不计入
        total += 1
        if is_correct(preds.get(q.qid, ""), gold[q.qid], q.answer_format):
            correct += 1
    acc = correct / total if total else 0.0
    return ScoreReport(
        total=total,
        correct=correct,
        accuracy=acc,
        total_tokens=total_tokens,
        token_score=token_score(total_tokens),
        final_score=final_score(acc, total_tokens),
    )


# 官方公布的 baseline（基于 Qwen-plus 直接长文输入）
OFFICIAL_BASELINE = {
    "A": {"correct": 49, "total": 100, "accuracy": 0.49, "tokens": 2_991_883},
    "B": {"correct": 13, "total": 100, "accuracy": 0.13, "tokens": 3_884_045},
}
