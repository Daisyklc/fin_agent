"""Qwen 系列模型调用封装（OpenAI 兼容端点）。

所有对模型的调用都应经过这里，以保证 token 被统一计入 GLOBAL_TRACKER。
推理问答阶段只允许 Qwen 系列模型；禁用 embedding 模型（本封装不提供 embed 接口）。
"""

from __future__ import annotations

import time
import json
import logging
from typing import Any

from config import settings
from agent.token_tracker import GLOBAL_TRACKER, TokenTracker

logger = logging.getLogger("qwen_client")


class QwenClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        tracker: TokenTracker | None = None,
    ) -> None:
        self.api_key = api_key or settings.API_KEY
        self.base_url = base_url or settings.BASE_URL
        self.model = model or settings.MODEL_NAME
        self.tracker = tracker or GLOBAL_TRACKER
        self._client = None  # 延迟初始化，未填 key 时也能 import

    # -------------------------------------------------------------- #
    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if settings.api_key_is_placeholder():
            raise RuntimeError(
                "尚未配置 DASHSCOPE_API_KEY。请设置环境变量或在 config/settings.py 中填入 API_KEY。"
            )
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("缺少依赖 openai，请先 `pip install openai`。") from e
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=settings.REQUEST_TIMEOUT,
        )
        return self._client

    # -------------------------------------------------------------- #
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        qid: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        """发起一次对话补全，返回文本内容；token 自动计入 tracker。"""
        client = self._ensure_client()
        temperature = settings.DEFAULT_TEMPERATURE if temperature is None else temperature
        max_tokens = settings.DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens

        last_err: Exception | None = None
        for attempt in range(1, settings.MAX_RETRIES + 1):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    self.tracker.record(
                        getattr(usage, "prompt_tokens", 0),
                        getattr(usage, "completion_tokens", 0),
                        qid=qid,
                    )
                return resp.choices[0].message.content or ""
            except Exception as e:  # noqa: BLE001
                last_err = e
                wait = min(2 ** attempt, 10)
                logger.warning("Qwen 调用失败(第%d次): %s，%ss 后重试", attempt, e, wait)
                time.sleep(wait)
        raise RuntimeError(f"Qwen 调用在 {settings.MAX_RETRIES} 次重试后仍失败: {last_err}")

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        qid: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """要求模型输出 JSON，并解析为 dict。解析失败返回 {}。"""
        kwargs.setdefault("response_format", {"type": "json_object"})
        text = self.chat(messages, qid=qid, **kwargs)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            cleaned = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                logger.error("无法解析模型 JSON 输出: %s", text[:200])
                return {}
