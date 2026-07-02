"""DeepSeek 客户端 JSON 解析单元测试（不调用真实 API）。"""

from __future__ import annotations

import unittest

from agent.deepseek_client import _parse_json


class TestDeepSeekParseJson(unittest.TestCase):
    def test_plain_json(self):
        data = _parse_json('{"answer": "A", "reason": "ok"}')
        self.assertEqual(data["answer"], "A")

    def test_fenced_json(self):
        data = _parse_json('```json\n{"answer": "AB"}\n```')
        self.assertEqual(data["answer"], "AB")

    def test_reasoner_tail_json(self):
        raw = "some thinking\n{\"answer\": \"B\"}"
        data = _parse_json(raw)
        self.assertEqual(data["answer"], "B")

    def test_embedded_json(self):
        data = _parse_json('结论如下：{"answer": "C", "reason": "x"} 结束')
        self.assertEqual(data["answer"], "C")


if __name__ == "__main__":
    unittest.main()
