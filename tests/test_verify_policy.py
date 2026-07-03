"""verify_policy 单元测试。"""

from __future__ import annotations

import unittest

from agent.questions import Question
from agent.verify_policy import should_verify, count_verify_targets


def _q(**kwargs) -> Question:
    base = dict(
        qid="t_001",
        domain="insurance",
        split="A",
        question="题干",
        options={"A": "a", "B": "b"},
        answer_format="mcq",
        type="事实查询",
        doc_ids=["1"],
    )
    base.update(kwargs)
    return Question(**base)


class TestVerifyPolicy(unittest.TestCase):
    def test_multi_always_verified(self):
        q = _q(answer_format="multi", type="事实查询")
        self.assertTrue(should_verify(q, "selective"))

    def test_regulatory_mcq_skipped_unless_tf(self):
        q = _q(domain="regulatory", answer_format="mcq", type="单选", doc_ids=["1"])
        self.assertFalse(should_verify(q, "selective"))

    def test_financial_cross_doc_mcq_verified(self):
        q = _q(
            domain="financial_reports",
            answer_format="mcq",
            type="单选题",
            doc_ids=["a", "b"],
        )
        self.assertTrue(should_verify(q, "selective"))

    def test_insurance_fact_query_skipped(self):
        q = _q(type="事实查询", answer_format="mcq")
        self.assertFalse(should_verify(q, "selective"))

    def test_insurance_calc_verified(self):
        q = _q(type="计算题", answer_format="mcq")
        self.assertTrue(should_verify(q, "selective"))

    def test_research_tf_verified(self):
        q = _q(domain="research", answer_format="tf", type="data_verification")
        self.assertTrue(should_verify(q, "selective"))

    def test_multi_doc_insurance_fact_skipped(self):
        q = _q(doc_ids=["1", "2", "3"], type="事实查询", answer_format="mcq")
        self.assertFalse(should_verify(q, "selective"))

    def test_count_targets(self):
        qs = [
            _q(qid="a", type="计算题"),
            _q(qid="b", type="事实查询"),
            _q(qid="c", answer_format="multi"),
        ]
        self.assertEqual(count_verify_targets(qs, "selective"), 2)
        self.assertEqual(count_verify_targets(qs, "all"), 3)
        self.assertEqual(count_verify_targets(qs, "off"), 0)


if __name__ == "__main__":
    unittest.main()
