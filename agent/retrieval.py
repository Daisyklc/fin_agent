"""检索：BM25 + 金融术语 / 条款号 / 数值加权。

合规说明：赛题禁用 embedding 模型做检索与推理。这里只用词面统计（BM25）
与规则加权，不涉及任何向量模型。query 关键词可由 Qwen 抽取（属允许范围），
但召回/排序本身由 BM25 完成。
"""

from __future__ import annotations

import re
import json
import logging
from dataclasses import dataclass

from config import settings

logger = logging.getLogger("retrieval")

# 金融领域高信息量词（命中给予加权）
_FIN_TERMS = [
    "营业收入", "营业总收入", "净利润", "归属于上市公司股东", "现金流量", "经营活动",
    "研发投入", "研发费用", "分红", "派息", "每股收益", "资产负债率", "毛利率",
    "保险金", "身故", "现金价值", "账户价值", "保费", "退保", "受益人", "保险责任",
    "免赔额", "等待期", "宽限期", "犹豫期", "保单贷款", "施救费用", "补偿", "报销",
    "施行", "生效", "工作日", "差异报告", "受益所有人", "尽职调查", "可疑交易",
    "较高风险", "高风险", "存量客户", "董事会", "股东大会",
    "票面利率", "发行规模", "信用评级", "债项评级", "主体评级", "到期", "本金", "利息", "担保",
    "股东大会", "特别决议", "独立董事", "募集资金",
    "杠杆", "净利率", "信创", "券商",
]
_FIN_RE = re.compile("|".join(map(re.escape, _FIN_TERMS)))
_CLAUSE_RE = re.compile(r"第[一二三四五六七八九十百零〇\d]+条")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    domain: str
    page: int
    text: str
    is_table: bool
    section_title: str
    score: float


def _tokenize(text: str) -> list[str]:
    import jieba
    toks = [t.strip() for t in jieba.lcut(text) if t.strip()]
    # 补充：条款号、数字作为独立 token，提升精确匹配
    toks += _CLAUSE_RE.findall(text)
    return toks


def load_chunks(doc_ids: list[str], domain: str | None = None) -> list[dict]:
    """从 processed_data 读取指定文档的 chunk。"""
    from agent.doc_registry import get_registry
    reg = get_registry()
    out: list[dict] = []
    seen_files = set()
    for did in doc_ids:
        entry = reg.resolve(did)
        if entry is None:
            continue
        fp = settings.PROCESSED_DIR / entry.domain / f"{entry.doc_id}.jsonl"
        if not fp.exists() or fp in seen_files:
            continue
        seen_files.add(fp)
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


def load_domain_chunks(domain: str) -> list[dict]:
    """加载整个领域的全部 chunk（B 榜全库检索用）。"""
    out: list[dict] = []
    dom_dir = settings.PROCESSED_DIR / domain
    if not dom_dir.exists():
        return out
    for fp in dom_dir.glob("*.jsonl"):
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


class BM25Retriever:
    def __init__(self, chunks: list[dict]):
        from rank_bm25 import BM25Okapi
        self.chunks = chunks
        self._tokenized = [_tokenize(c["text"]) for c in chunks]
        self._bm25 = BM25Okapi(self._tokenized) if chunks else None

    def _score_all(
        self, query: str, *, doc_boost: set[str] | None = None
    ) -> list[tuple[float, int]]:
        """对全部 chunk 打分（BM25 + 规则加权），返回按分降序的 (score, idx)。"""
        q_tokens = _tokenize(query)
        scores = self._bm25.get_scores(q_tokens)
        q_terms = set(_FIN_RE.findall(query))
        q_clauses = set(_CLAUSE_RE.findall(query))
        q_nums = set(_NUM_RE.findall(query))
        doc_boost = {d.lower() for d in (doc_boost or set())}

        boosted: list[tuple[float, int]] = []
        for i, c in enumerate(self.chunks):
            s = float(scores[i])
            text = c["text"]
            if q_terms and _FIN_RE.search(text):
                s += 1.5 * len(q_terms & set(_FIN_RE.findall(text)))
            if q_clauses and (set(c.get("clauses") or []) & q_clauses):
                s += 3.0
            if q_nums:
                s += 0.5 * len(q_nums & set(_NUM_RE.findall(text)))
            if c.get("is_table"):
                s += 0.3
            # 题目引用 doc_id 的 chunk 加权（跨文档对比题）
            if doc_boost and c.get("doc_id", "").lower() in doc_boost:
                s += 2.0
            boosted.append((s, i))
        boosted.sort(key=lambda x: x[0], reverse=True)
        return boosted

    def _to_chunk(self, score: float, idx: int) -> RetrievedChunk:
        c = self.chunks[idx]
        return RetrievedChunk(
            chunk_id=c["chunk_id"], doc_id=c["doc_id"], domain=c["domain"],
            page=c["page"], text=c["text"], is_table=c["is_table"],
            section_title=c.get("section_title", ""), score=round(score, 3),
        )

    def search(
        self, query: str, top_k: int = 8, *, doc_boost: set[str] | None = None
    ) -> list[RetrievedChunk]:
        if not self._bm25:
            return []
        return [
            self._to_chunk(s, i)
            for s, i in self._score_all(query, doc_boost=doc_boost)[:top_k]
        ]

    def recall_documents(
        self, query: str, top_docs: int = 3, topn_per_doc: int = 3
    ) -> list[tuple[str, float]]:
        """文档级召回（B 榜无 doc_ids 时用）。

        以每个文档命中最高的若干 chunk 分数之和作为文档得分，返回 top_docs 个候选。
        返回 [(doc_id, score), ...] 按分降序。
        """
        if not self._bm25:
            return []
        ranked = self._score_all(query, doc_boost=set())
        per_doc_scores: dict[str, list[float]] = {}
        for s, i in ranked:
            did = self.chunks[i]["doc_id"]
            per_doc_scores.setdefault(did, [])
            if len(per_doc_scores[did]) < topn_per_doc:
                per_doc_scores[did].append(s)
        doc_score = [(d, sum(v)) for d, v in per_doc_scores.items()]
        doc_score.sort(key=lambda x: x[1], reverse=True)
        return doc_score[:top_docs]

    def search_two_stage(
        self,
        query: str,
        top_docs: int = 3,
        top_k: int = 8,
        per_doc: int = 2,
        *,
        doc_boost: set[str] | None = None,
    ) -> tuple[list[RetrievedChunk], list[str]]:
        """两阶段检索：先文档召回，再在候选文档内做均衡段落检索。

        返回 (chunks, candidate_doc_ids)，candidate_doc_ids 便于评估文档召回质量。
        """
        cand = [d for d, _ in self.recall_documents(query, top_docs=top_docs)]
        cand_set = set(cand)
        ranked = [
            (s, i) for s, i in self._score_all(query, doc_boost=doc_boost)
            if self.chunks[i]["doc_id"] in cand_set
        ]
        chosen: list[int] = []
        chosen_set: set[int] = set()
        per_doc_count: dict[str, int] = {}
        for s, i in ranked:
            did = self.chunks[i]["doc_id"]
            if per_doc_count.get(did, 0) < per_doc:
                chosen.append(i); chosen_set.add(i)
                per_doc_count[did] = per_doc_count.get(did, 0) + 1
        for s, i in ranked:
            if len(chosen) >= top_k:
                break
            if i not in chosen_set:
                chosen.append(i); chosen_set.add(i)
        score_by_idx = {i: s for s, i in ranked}
        chosen = sorted(chosen, key=lambda i: score_by_idx[i], reverse=True)[:top_k]
        return [self._to_chunk(score_by_idx[i], i) for i in chosen], cand

    def search_balanced(
        self,
        query: str,
        top_k: int = 8,
        per_doc: int = 2,
        *,
        doc_boost: set[str] | None = None,
    ) -> list[RetrievedChunk]:
        """保证多文档覆盖：先给每个文档至少 per_doc 个名额，再用全局高分填满 top_k。

        跨文档对比题（如财报年度对比）需要每个引用文档都有证据入选，
        避免单个文档霸占 top-k 导致漏读其他文档。
        """
        if not self._bm25:
            return []
        ranked = self._score_all(query, doc_boost=doc_boost)
        chosen: list[int] = []
        chosen_set: set[int] = set()
        per_doc_count: dict[str, int] = {}

        # 第一轮：每个文档配额
        for s, i in ranked:
            did = self.chunks[i]["doc_id"]
            if per_doc_count.get(did, 0) < per_doc:
                chosen.append(i)
                chosen_set.add(i)
                per_doc_count[did] = per_doc_count.get(did, 0) + 1

        # 第二轮：全局高分填满剩余名额
        for s, i in ranked:
            if len(chosen) >= top_k:
                break
            if i not in chosen_set:
                chosen.append(i)
                chosen_set.add(i)

        # 按原始分数排序后截断
        score_by_idx = {i: s for s, i in ranked}
        chosen = sorted(chosen, key=lambda i: score_by_idx[i], reverse=True)[:top_k]
        return [self._to_chunk(score_by_idx[i], i) for i in chosen]
