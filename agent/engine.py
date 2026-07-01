"""单题 Agent 流水线：检索 → 组装上下文 → Qwen 推理 → 规范化答案 + 证据。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from config import settings
from agent.questions import Question
from agent.qwen_client import QwenClient
from agent.token_tracker import TokenTracker, GLOBAL_TRACKER
from agent.retrieval import BM25Retriever, RetrievedChunk, load_chunks, load_domain_chunks
from agent.query_builder import build_retrieval_query
from agent.verify_policy import should_verify
from agent.prompts import (
    SYSTEM_PROMPT, build_user_prompt, VERIFY_SYSTEM_PROMPT, build_verify_prompt,
)
from agent.postprocess import normalize_answer

logger = logging.getLogger("engine")


@dataclass
class QAResult:
    qid: str
    answer: str
    evidence: list[dict] = field(default_factory=list)
    reason: str = ""
    raw: str = ""
    # 自洽验证相关
    verified: bool = False
    initial_answer: str = ""
    agree: bool = True
    confidence: str = ""
    verify_note: str = ""

    @property
    def high_risk(self) -> bool:
        """复核与初答不一致、或复核置信度低，视为高风险题。"""
        return self.verified and (not self.agree or self.confidence == "low")


class FinanceAgent:
    def __init__(
        self,
        client: QwenClient | None = None,
        tracker: TokenTracker | None = None,
        top_k: int = 8,
        top_docs: int = 8,
        verify: bool = False,
        verify_mode: str | None = None,
    ) -> None:
        self.client = client or QwenClient()
        self.tracker = tracker or GLOBAL_TRACKER
        self.top_k = top_k
        self.top_docs = top_docs
        self.enable_verify = verify
        self.verify_mode = verify_mode or settings.VERIFY_MODE

    def _retrieve(self, q: Question) -> list[RetrievedChunk]:
        chunks, _ = self._retrieve_with_cands(q)
        return chunks

    def _retrieve_with_cands(self, q: Question) -> tuple[list[RetrievedChunk], list[str]]:
        query = build_retrieval_query(q)
        doc_boost = {d.lower() for d in q.doc_ids}
        if q.doc_ids:
            # A 榜：限定在题目给的 doc_ids
            chunks = load_chunks(q.doc_ids, q.domain)
            if not chunks:
                logger.warning("%s 无可用 chunk（文档可能未解析）", q.qid)
                return [], []
            retriever = BM25Retriever(chunks)
            if len(q.doc_ids) > 1:
                return (
                    retriever.search_balanced(
                        query, top_k=self.top_k, per_doc=2, doc_boost=doc_boost),
                    q.doc_ids,
                )
            return retriever.search(query, top_k=self.top_k, doc_boost=doc_boost), q.doc_ids
        # B 榜：无 doc_ids → 全领域两阶段检索（先文档召回，再段落）
        chunks = load_domain_chunks(q.domain)
        if not chunks:
            logger.warning("%s 无可用 chunk（领域文档可能未解析）", q.qid)
            return [], []
        retriever = BM25Retriever(chunks)
        return retriever.search_two_stage(
            query, top_docs=self.top_docs, top_k=self.top_k, per_doc=2, doc_boost=doc_boost)

    def answer(self, q: Question) -> QAResult:
        with self.tracker.scope(q.qid):
            chunks = self._retrieve(q)
            user_prompt = build_user_prompt(q, chunks)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            data = self.client.chat_json(
                messages, qid=q.qid, max_tokens=settings.DEFAULT_MAX_TOKENS
            )

            raw_answer = str(data.get("answer", ""))
            norm = normalize_answer(raw_answer, q)
            reason = str(data.get("reason", ""))
            result = QAResult(
                qid=q.qid,
                answer=norm,
                evidence=data.get("evidence", []) or [],
                reason=reason,
                raw=raw_answer,
            )

            if self.enable_verify and should_verify(q, self.verify_mode):
                self._verify(q, chunks, result)
            return result

    def _verify(self, q: Question, chunks, result: QAResult) -> None:
        """独立复核：不一致时采用复核答案并标记高风险。token 计入同一题。"""
        vp = build_verify_prompt(q, chunks, result.answer, result.reason)
        messages = [
            {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
            {"role": "user", "content": vp},
        ]
        data = self.client.chat_json(messages, qid=q.qid, max_tokens=settings.DEFAULT_MAX_TOKENS)
        v_ans = normalize_answer(str(data.get("answer", "")), q)
        agree = bool(data.get("agree", True))
        confidence = str(data.get("confidence", ""))
        result.verified = True
        result.initial_answer = result.answer
        result.agree = agree
        result.confidence = confidence
        result.verify_note = str(data.get("note", ""))
        # 复核给出有效答案且不一致时，采用复核答案
        if v_ans and v_ans != result.answer:
            result.answer = v_ans
            result.agree = False
        elif not agree and v_ans and v_ans == result.answer:
            # 模型声称不同意但答案未变：标记不一致，保留初答供人工关注
            result.agree = False
        elif not agree and not v_ans:
            result.agree = False
            if confidence == "low":
                result.confidence = "low"
