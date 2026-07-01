"""评估 B 榜文档级召回质量（无需答案 gold）。

思路：A 榜题目自带真实 doc_ids。把它当成"盲测"——忽略 doc_ids，在整个领域内做
文档级召回，再用真实 doc_ids 作为 gold，统计 Recall@k 与"全命中率"。
这样无需 B 榜标准答案即可量化检索效果，为 B 榜调参提供依据。

前置：先运行 `python -m script.parse_docs --all` 解析全部文档。

用法：
    python -m script.eval_retrieval
    python -m script.eval_retrieval --domain regulatory --ks 3,5,8,10
"""

from __future__ import annotations

import sys
import argparse
from collections import defaultdict

from config import settings
from agent.questions import load_questions
from agent.doc_registry import get_registry
from agent.retrieval import BM25Retriever, load_domain_chunks
from agent.query_builder import build_retrieval_query


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="group_a")
    ap.add_argument("--domain", default=None)
    ap.add_argument("--ks", default="3,5,8,10", help="评估的 top_docs 取值")
    args = ap.parse_args()

    ks = [int(x) for x in args.ks.split(",")]
    max_k = max(ks)
    reg = get_registry()

    domains = [args.domain] if args.domain else settings.DOMAINS
    # 缓存每个领域的检索器，避免重复构建
    retrievers: dict[str, BM25Retriever] = {}
    chunk_counts: dict[str, int] = {}
    for dom in domains:
        chunks = load_domain_chunks(dom)
        chunk_counts[dom] = len(chunks)
        retrievers[dom] = BM25Retriever(chunks) if chunks else None

    questions = load_questions(args.group, args.domain)

    # 把题目真实 doc_ids 解析成统一的 doc_id（文件 stem），与检索结果可比
    def norm_ids(ids: list[str]) -> set[str]:
        out = set()
        for d in ids:
            e = reg.resolve(d)
            out.add(e.doc_id if e else d)
        return out

    per_dom_recall = defaultdict(lambda: {k: [] for k in ks})
    per_dom_fullhit = defaultdict(lambda: {k: [] for k in ks})

    for q in questions:
        r = retrievers.get(q.domain)
        if r is None:
            continue
        gold = norm_ids(q.doc_ids)
        if not gold:
            continue
        query = build_retrieval_query(q)
        ranked_docs = [d for d, _ in r.recall_documents(query, top_docs=max_k)]
        for k in ks:
            topk = set(ranked_docs[:k])
            hit = len(gold & topk)
            per_dom_recall[q.domain][k].append(hit / len(gold))
            per_dom_fullhit[q.domain][k].append(1.0 if gold <= topk else 0.0)

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0

    print("=" * 72)
    print("B 榜文档召回评估（用 A 榜真实 doc_ids 作 gold）")
    print(f"评估 k = {ks}")
    print("=" * 72)
    header = f"{'领域':<20}{'文档数':>7}{'题数':>6}" + "".join(f"  R@{k:<3}/全@{k:<3}" for k in ks)
    print(header)

    all_recall = {k: [] for k in ks}
    all_full = {k: [] for k in ks}
    for dom in domains:
        n_docs = len(reg.entries_for_domain(dom))
        n_q = len(per_dom_recall[dom][ks[0]])
        cells = ""
        for k in ks:
            rec = avg(per_dom_recall[dom][k])
            full = avg(per_dom_fullhit[dom][k])
            all_recall[k] += per_dom_recall[dom][k]
            all_full[k] += per_dom_fullhit[dom][k]
            cells += f"  {rec:>5.2f}/{full:>5.2f}"
        print(f"{dom:<20}{n_docs:>7}{n_q:>6}{cells}")

    print("-" * 72)
    cells = ""
    for k in ks:
        cells += f"  {avg(all_recall[k]):>5.2f}/{avg(all_full[k]):>5.2f}"
    print(f"{'总体':<20}{'':>7}{len(all_recall[ks[0]]):>6}{cells}")
    print("\n说明：R@k=平均文档召回率，全@k=该题全部真实文档都进 top-k 的比例。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
