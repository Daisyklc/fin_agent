"""query_builder 单元测试。"""

from __future__ import annotations

import unittest

from agent.questions import Question
from agent.query_builder import build_retrieval_query, extract_entities


class TestQueryBuilder(unittest.TestCase):
    def _q(self, **kwargs) -> Question:
        base = dict(
            qid="t_001",
            domain="insurance",
            split="A",
            question="李某投保平安e生保",
            options={"A": "选项甲", "B": "选项乙"},
            answer_format="mcq",
            type="计算题",
            doc_ids=["5", "6"],
        )
        base.update(kwargs)
        return Question(**base)

    def test_extract_entities_insurance(self):
        text = "平安智盈金生与国寿增益宝对比"
        ents = extract_entities(text)
        self.assertTrue(any("平安" in e for e in ents))
        self.assertTrue(any("国寿" in e for e in ents))

    def test_build_query_includes_doc_ids(self):
        q = self._q()
        query = build_retrieval_query(q)
        self.assertIn("5", query)
        self.assertIn("6", query)
        self.assertIn(q.question, query)

    def test_fc_text_alias(self):
        q = self._q(
            domain="financial_contracts",
            doc_ids=["fc_text_002", "fc_text_014"],
            question="对比两份文档",
        )
        query = build_retrieval_query(q)
        self.assertIn("text02", query)


if __name__ == "__main__":
    unittest.main()
