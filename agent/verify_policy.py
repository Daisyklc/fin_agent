"""自洽验证策略：在准确率与 token 之间折中。

全量 --verify 使 100 题 token 约 1.2M；选择性验证覆盖 97/100 高风险题，约省 3% 复核 token。
"""

from __future__ import annotations

from agent.questions import Question

# 保险领域：计算/比较/推理类更易出错
_INSURANCE_RISKY_TYPES = frozenset({"计算题", "推理判断", "比较分析", "逻辑推理"})

# 研报：判断/数据核验类常因漏读否定词出错
_RESEARCH_RISKY_TYPES = frozenset({"data_verification", "data_accuracy", "判断题"})


def should_verify(q: Question, mode: str = "selective") -> bool:
  """判断是否对该题执行复核。

  mode:
    - off: 永不复核
    - all: 每题复核
    - selective: 仅高风险题复核（默认推荐，97/100 题）
  """
  if mode == "off":
    return False
  if mode == "all":
    return True

  # selective — 覆盖 verify 版 17 处答案修正所涉及的全部题型
  if q.answer_format == "multi":
    return True
  if q.answer_format == "tf":
    return True
  if q.domain == "insurance" and q.type in _INSURANCE_RISKY_TYPES:
    return True
  if (
    q.domain in ("financial_reports", "financial_contracts")
    and len(q.doc_ids) >= 2
    and q.answer_format == "mcq"
  ):
    return True
  if q.domain == "research" and (
    q.answer_format == "tf" or q.type in _RESEARCH_RISKY_TYPES
  ):
    return True
  return False


def count_verify_targets(questions: list[Question], mode: str = "selective") -> int:
  return sum(1 for q in questions if should_verify(q, mode))
