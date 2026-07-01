"""检索 Query 构造：从题干/选项抽取高信息量词，增强 BM25 召回。

合规：纯规则抽取，不调用 embedding；可选 Qwen 扩展在 engine 层另行处理。
"""

from __future__ import annotations

import re

from agent.questions import Question

# 题干/选项中常见金融产品、机构、指标名（用于 query 补强）
_ENTITY_PATTERNS = [
  r"平安[\u4e00-\u9fa5A-Za-z0-9·]+",
  r"国寿[\u4e00-\u9fa5A-Za-z0-9·]+",
  r"众安[\u4e00-\u9fa5A-Za-z0-9·]+",
  r"太保[\u4e00-\u9fa5A-Za-z0-9·]+",
  r"比亚迪|宁德时代|天阳科技",
  r"fc_text_\d+|text\d+",
  r"annual_[a-z0-9_]+",
  r"pack2_text\d+",
  r"strict_v3_[a-z0-9_]+",
  r"strict_csrc_\d+",
  r"《[^》]{2,40}》",
]
_ENTITY_RE = re.compile("|".join(_ENTITY_PATTERNS), re.IGNORECASE)

# 金融合同/债券常见要素
_BOND_TERMS_RE = re.compile(
  r"票面利率|发行规模|信用评级|债项评级|主体评级|到期日|担保|偿付|AAA|AA\+|A\+"
)
_NUM_WITH_UNIT_RE = re.compile(
  r"\d+(?:\.\d+)?(?:%|万|亿|元|倍|日|个月|年|工作日|自然日)"
)


def extract_entities(text: str) -> list[str]:
  """从文本抽取实体/专有名词，去重保序。"""
  seen: set[str] = set()
  out: list[str] = []
  for m in _ENTITY_RE.finditer(text):
    t = m.group(0).strip()
    if t and t not in seen:
      seen.add(t)
      out.append(t)
  return out


def build_retrieval_query(q: Question, *, repeat_question: int = 2) -> str:
  """构造检索 query：题干加权重复 + 选项 + 实体 + 数值。"""
  parts: list[str] = [q.question] * repeat_question
  parts.extend(q.options.values())

  entities = extract_entities(q.question + " " + " ".join(q.options.values()))
  if entities:
    parts.extend(entities)

  # 题目显式引用的 doc_id 也加入 query（A 榜多文档对比题常见）
  for did in q.doc_ids:
    parts.append(did)
    # fc_text_002 类写法与 text02 文件名可能不一致，两种都试
    m = re.search(r"(?:fc_)?text[_]?(\d+)", did, re.I)
    if m:
      parts.append(f"text{int(m.group(1)):02d}")

  bond_hits = _BOND_TERMS_RE.findall(q.question + " " + " ".join(q.options.values()))
  parts.extend(bond_hits)

  nums = _NUM_WITH_UNIT_RE.findall(q.question + " " + " ".join(q.options.values()))
  # 数值去重，避免选项里重复数字淹没 BM25
  seen_num: set[str] = set()
  for n in nums:
    if n not in seen_num:
      seen_num.add(n)
      parts.append(n)

  return " ".join(parts)
