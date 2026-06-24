"""朴素 baseline：直接把（截断的）整篇文档喂给 Qwen，不做检索排序。

用于复现/对照官方 baseline 思路。注意：长文直接输入 token 消耗很大，
默认对单题上下文做字符截断，并建议先用 --limit 小规模试跑。

用法：
    python -m script.run_baseline --domain financial_reports --limit 3
    python -m script.run_baseline --max-chars 40000 --limit 10
"""

from __future__ import annotations

import sys
import json
import argparse
import logging

from config import settings
from agent.questions import load_questions
from agent.qwen_client import QwenClient
from agent.token_tracker import TokenTracker
from agent.retrieval import load_chunks, load_domain_chunks
from agent.prompts import SYSTEM_PROMPT, _FORMAT_HINT
from agent.postprocess import normalize_answer, write_answer_csv

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("baseline")


def _full_context(q, max_chars: int) -> str:
    chunks = load_chunks(q.doc_ids, q.domain) if q.doc_ids else load_domain_chunks(q.domain)
    text = "\n".join(c["text"] for c in chunks)
    return text[:max_chars]


def _build_prompt(q, context: str) -> str:
    fmt = _FORMAT_HINT.get(q.answer_format, "")
    options = "\n".join(f"{k}. {v}" for k, v in sorted(q.options.items()))
    return (
        f"【题型说明】{fmt}\n\n【文档全文(可能被截断)】\n{context}\n\n"
        f"【问题】\n{q.question}\n\n【选项】\n{options}\n\n"
        '只输出 JSON：{"answer": "选项字母"}'
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default=None)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--group", default="group_a")
    ap.add_argument("--max-chars", type=int, default=50000, help="单题上下文字符上限")
    ap.add_argument("--out", default="answer_baseline.csv")
    args = ap.parse_args()

    if settings.api_key_is_placeholder():
        logger.error("未配置 API Key。")
        return 2

    questions = load_questions(args.group, args.domain)
    if args.limit:
        questions = questions[: args.limit]
    logger.info("baseline 作答题目: %d（max_chars=%d）", len(questions), args.max_chars)

    client = QwenClient()
    tracker = TokenTracker()
    answers: dict[str, str] = {}

    try:
        from tqdm import tqdm
        iterator = tqdm(questions, desc="baseline")
    except ImportError:
        iterator = questions

    for q in iterator:
        with tracker.scope(q.qid):
            ctx = _full_context(q, args.max_chars)
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_prompt(q, ctx)},
            ]
            try:
                data = client.chat_json(messages, qid=q.qid)
            except Exception as e:  # noqa: BLE001
                logger.error("%s 失败: %s", q.qid, e)
                answers[q.qid] = ""
                continue
            answers[q.qid] = normalize_answer(str(data.get("answer", "")), q)

    out_path = settings.OUTPUT_DIR / args.out
    write_answer_csv(out_path, questions, answers, tracker)
    s = tracker.summary()
    logger.info("baseline 完成。%s  总Token=%d  单题均=%d",
                out_path, s.total_tokens, s.total_tokens // max(1, len(questions)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
