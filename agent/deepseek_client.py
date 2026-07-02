"""DeepSeek 模型调用封装（OpenAI 兼容端点）。

仅用于离线标注、交叉验证与测试，不参与赛题正式提交推理。
申请 Key：https://platform.deepseek.com
"""

from __future__ import annotations

import time
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from config import settings

logger = logging.getLogger("deepseek_client")


@dataclass
class DeepSeekUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class DeepSeekTracker:
    """标注专用 token 统计（与赛题 GLOBAL_TRACKER 隔离）。"""
    by_qid: dict[str, DeepSeekUsage] = field(default_factory=dict)
    total_prompt: int = 0
    total_completion: int = 0

    def record(self, prompt: int, completion: int, *, qid: str | None = None) -> None:
        self.total_prompt += prompt
        self.total_completion += completion
        if qid:
            u = self.by_qid.setdefault(qid, DeepSeekUsage())
            u.prompt_tokens += prompt
            u.completion_tokens += completion

    def summary(self) -> DeepSeekUsage:
        return DeepSeekUsage(self.total_prompt, self.total_completion)


class DeepSeekClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        tracker: DeepSeekTracker | None = None,
    ) -> None:
        self.api_key = api_key or settings.DEEPSEEK_API_KEY
        self.base_url = base_url or settings.DEEPSEEK_BASE_URL
        self.model = model or settings.DEEPSEEK_MODEL
        self.tracker = tracker or DeepSeekTracker()
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if settings.deepseek_api_key_is_placeholder():
            raise RuntimeError(
                "尚未配置 DEEPSEEK_API_KEY。请设置环境变量或在 config/settings.py 中填入。"
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

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        qid: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> str:
        client = self._ensure_client()
        temperature = settings.DEFAULT_TEMPERATURE if temperature is None else temperature
        max_tokens = settings.DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens
        if json_mode:
            kwargs.setdefault("response_format", {"type": "json_object"})

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
                logger.warning("DeepSeek 调用失败(第%d次): %s，%ss 后重试", attempt, e, wait)
                time.sleep(wait)
        raise RuntimeError(f"DeepSeek 调用在 {settings.MAX_RETRIES} 次重试后仍失败: {last_err}")

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        qid: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """解析 JSON 输出。deepseek-reasoner 无 JSON mode 时从文本抽取。"""
        use_json_mode = self.model != settings.DEEPSEEK_REASONER_MODEL
        text = self.chat(messages, qid=qid, json_mode=use_json_mode, **kwargs)
        return _parse_json(text)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    cleaned = text.lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
    logger.error("无法解析 DeepSeek JSON 输出: %s", text[:200])
    return {}
