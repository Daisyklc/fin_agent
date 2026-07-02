"""DeepSeek 离线标注：检索证据 → 作答 → 与 Qwen 结果对比。

不参与赛题提交；产出供 gold 构建与交叉验证。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from config import settings
from agent.questions import Question
from agent.deepseek_client import DeepSeekClient, DeepSeekTracker
from agent.engine import FinanceAgent
from agent.postprocess import normalize_answer
from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from agent.retrieval import RetrievedChunk

logger = logging.getLogger("annotate")

ANNOTATE_SYSTEM_PROMPT = (
    SYSTEM_PROMPT
    + " 你正在协助构建标准答案集，请尽可能严谨、逐选项核对。"
)


@dataclass
class AnnotateResult:
    qid: str
    answer: str
    reason: str = ""
    evidence: list[dict] = field(default_factory=list)
    raw: str = ""
    source: str = "retrieval"  # retrieval | evidence_json


class DeepSeekAnnotator:
    def __init__(
        self,
        client: DeepSeekClient | None = None,
        top_k: int = 8,
        use_reasoner: bool = False,
    ) -> None:
        self.client = client or DeepSeekClient(
            model=settings.DEEPSEEK_REASONER_MODEL if use_reasoner else settings.DEEPSEEK_MODEL
        )
        self._retriever = FinanceAgent(top_k=top_k)

    def _chunks_from_evidence(self, q: Question, ev_items: list[dict]) -> list[RetrievedChunk]:
        chunks: list[RetrievedChunk] = []
        for i, e in enumerate(ev_items):
            quote = str(e.get("quote", "")).strip()
            if not quote:
                continue
            chunks.append(
                RetrievedChunk(
                    chunk_id=f"ev::{q.qid}::{i}",
                    doc_id=str(e.get("doc_id", "")),
                    domain=q.domain,
                    page=0,
                    text=quote,
                    is_table=False,
                    section_title=str(e.get("loc", "")),
                    score=0.0,
                )
            )
        return chunks

    def _pick_chunks(
        self, q: Question, evidence_log: dict | None
    ) -> tuple[list[RetrievedChunk], str]:
        chunks = self._retriever._retrieve(q)
        if chunks:
            return chunks, "retrieval"
        if evidence_log and q.qid in evidence_log:
            ev_items = evidence_log[q.qid].get("evidence") or []
            pseudo = self._chunks_from_evidence(q, ev_items)
            if pseudo:
                return pseudo, "evidence_json"
        return [], "none"

    def annotate_one(
        self, q: Question, evidence_log: dict | None = None
    ) -> AnnotateResult:
        chunks, source = self._pick_chunks(q, evidence_log)
        user_prompt = build_user_prompt(q, chunks)
        messages = [
            {"role": "system", "content": ANNOTATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        data = self.client.chat_json(messages, qid=q.qid)
        raw = str(data.get("answer", ""))
        return AnnotateResult(
            qid=q.qid,
            answer=normalize_answer(raw, q),
            reason=str(data.get("reason", "")),
            evidence=data.get("evidence", []) or [],
            raw=raw,
            source=source,
        )

    def annotate_all(
        self,
        questions: list[Question],
        evidence_log: dict | None = None,
    ) -> list[AnnotateResult]:
        out: list[AnnotateResult] = []
        for q in questions:
            try:
                out.append(self.annotate_one(q, evidence_log))
            except Exception as e:  # noqa: BLE001
                logger.error("%s 标注失败: %s", q.qid, e)
                out.append(AnnotateResult(qid=q.qid, answer="", source="error"))
        return out


def load_evidence_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def compare_with_qwen(
    results: list[AnnotateResult],
    qwen_preds: dict[str, str],
) -> list[dict]:
    """返回 DeepSeek 与 Qwen 答案不一致的题。"""
    diffs: list[dict] = []
    for r in results:
        qwen_ans = qwen_preds.get(r.qid, "")
        if r.answer and qwen_ans and r.answer != qwen_ans:
            diffs.append({
                "qid": r.qid,
                "deepseek": r.answer,
                "qwen": qwen_ans,
                "reason": r.reason,
            })
    return diffs


def write_gold_csv(
    path: Path,
    questions: list[Question],
    results: list[AnnotateResult],
    *,
    merge_existing: Path | None = None,
) -> Path:
    """写出 gold CSV；若已有 gold 且 answer 非空则保留人工填写值。"""
    import csv

    existing: dict[str, str] = {}
    if merge_existing and merge_existing.exists():
        with open(merge_existing, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                qid = (row.get("qid") or "").strip()
                ans = (row.get("answer") or "").strip()
                if qid and ans:
                    existing[qid] = ans

    res_map = {r.qid: r.answer for r in results}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["qid", "domain", "answer_format", "type", "answer", "question_brief", "source"])
        for q in questions:
            brief = q.question[:40].replace("\n", " ")
            ans = existing.get(q.qid) or res_map.get(q.qid, "")
            src = "manual" if q.qid in existing else "deepseek"
            w.writerow([q.qid, q.domain, q.answer_format, q.type, ans, brief, src])
    return path
