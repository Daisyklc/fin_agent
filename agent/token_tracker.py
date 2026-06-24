"""Token 统计中间件。

评分要求在 answer.csv 中提交 prompt_tokens / completion_tokens / total_tokens，
且必须覆盖回答全过程的所有 Qwen API 调用（检索、压缩、判断、生成、自检）。

用法：
    tracker = TokenTracker()
    with tracker.scope("ins_a_001"):
        ... qwen_client.chat(...) ...   # 调用内部自动累加到当前 scope
    tracker.summary()                   # 全局汇总
"""

from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += int(prompt or 0)
        self.completion_tokens += int(completion or 0)
        self.calls += 1


class TokenTracker:
    """线程安全的分桶 token 计数器。按 qid 分组，同时维护全局总量。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_qid: dict[str, Usage] = defaultdict(Usage)
        self._global = Usage()
        self._current_qid: str | None = None

    @contextmanager
    def scope(self, qid: str):
        """进入某道题的计数上下文。"""
        prev = self._current_qid
        self._current_qid = qid
        try:
            yield self._by_qid[qid]
        finally:
            self._current_qid = prev

    def record(self, prompt_tokens: int, completion_tokens: int, qid: str | None = None) -> None:
        target = qid or self._current_qid
        with self._lock:
            self._global.add(prompt_tokens, completion_tokens)
            if target is not None:
                self._by_qid[target].add(prompt_tokens, completion_tokens)

    def usage_for(self, qid: str) -> Usage:
        return self._by_qid.get(qid, Usage())

    def summary(self) -> Usage:
        return self._global

    def per_qid(self) -> dict[str, Usage]:
        return dict(self._by_qid)


# 进程级全局单例，供 qwen_client 自动累加。
GLOBAL_TRACKER = TokenTracker()
