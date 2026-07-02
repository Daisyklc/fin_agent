"""用 DeepSeek 离线标注标准答案，并与 Qwen 提交结果交叉对比。

仅用于 gold 构建与测试，不参与赛题正式推理。

前置：
  export DEEPSEEK_API_KEY=你的key
  # 可选：已有 evidence.json 时无 processed_data 也能用引用片段标注

用法：
    python -m script.annotate_gold --limit 5
    python -m script.annotate_gold --domain insurance
    python -m script.annotate_gold --reasoner          # 使用 deepseek-reasoner（更慢）
    python -m script.annotate_gold --out gold/deepseek_group_a_gold.csv
    python -m script.annotate_gold --compare answer.csv
"""

from __future__ import annotations

import sys
import json
import csv
import argparse
import logging
from datetime import datetime
from pathlib import Path

from config import settings
from agent.questions import load_questions
from agent.annotate import (
    DeepSeekAnnotator,
    load_evidence_json,
    compare_with_qwen,
    write_gold_csv,
)
from agent.deepseek_client import DeepSeekClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("annotate_gold")


def _load_qwen_preds(path: Path) -> dict[str, str]:
    preds: dict[str, str] = {}
    if not path.exists():
        return preds
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            qid = (row.get("qid") or "").strip()
            if qid and qid != "summary":
                preds[qid] = (row.get("answer") or "").strip()
    return preds


def main() -> int:
    ap = argparse.ArgumentParser(description="DeepSeek 离线标注 gold")
    ap.add_argument("--group", default="group_a")
    ap.add_argument("--domain", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--qids", default=None, help="逗号分隔的题号")
    ap.add_argument("--evidence", default=str(settings.OUTPUT_DIR / "evidence.json"))
    ap.add_argument("--compare", default=None, help="与 Qwen answer.csv 对比")
    ap.add_argument("--out", default=None, help="gold CSV 输出路径")
    ap.add_argument("--json-out", default=None, help="完整标注 JSON")
    ap.add_argument("--merge-gold", default=None, help="合并已有 gold（保留非空 answer）")
    ap.add_argument("--reasoner", action="store_true", help="使用 deepseek-reasoner")
    ap.add_argument("--top-k", type=int, default=8)
    args = ap.parse_args()

    if settings.deepseek_api_key_is_placeholder():
        logger.error(
            "未配置 DEEPSEEK_API_KEY。请执行：export DEEPSEEK_API_KEY=你的key"
        )
        return 2

    all_questions = load_questions(args.group, args.domain)
    questions = all_questions
    if args.qids:
        want = {x.strip() for x in args.qids.split(",") if x.strip()}
        questions = [q for q in all_questions if q.qid in want]
    if args.limit:
        questions = questions[: args.limit]

    model = settings.DEEPSEEK_REASONER_MODEL if args.reasoner else settings.DEEPSEEK_MODEL
    logger.info("DeepSeek 标注 %d 题，模型=%s", len(questions), model)

    evidence_log = load_evidence_json(Path(args.evidence))
    annotator = DeepSeekAnnotator(use_reasoner=args.reasoner, top_k=args.top_k)
    results = annotator.annotate_all(questions, evidence_log)

    # JSON 明细
    json_path = Path(args.json_out) if args.json_out else (
        settings.LOGS_DIR / f"deepseek_annotate_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    detail = {
        r.qid: {
            "answer": r.answer,
            "reason": r.reason,
            "evidence": r.evidence,
            "source": r.source,
            "tokens": annotator.client.tracker.by_qid.get(r.qid),
        }
        for r in results
    }
    # 序列化 token dataclass
    for qid, d in detail.items():
        tok = d.get("tokens")
        if tok is not None:
            d["tokens"] = {
                "prompt_tokens": tok.prompt_tokens,
                "completion_tokens": tok.completion_tokens,
                "total_tokens": tok.total_tokens,
            }
    json_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("标注明细: %s", json_path)

    # gold CSV
    gold_dir = settings.ROOT / "gold"
    out_csv = Path(args.out) if args.out else gold_dir / f"deepseek_{args.group}_gold.csv"
    merge_path = Path(args.merge_gold) if args.merge_gold else None
    write_gold_csv(out_csv, all_questions, results, merge_existing=merge_path)
    logger.info("Gold CSV: %s", out_csv)

    # token 汇总
    summary = annotator.client.tracker.summary()
    logger.info(
        "DeepSeek 总 Token: %d（prompt=%d, completion=%d）",
        summary.total_tokens, summary.prompt_tokens, summary.completion_tokens,
    )

    answered = sum(1 for r in results if r.answer)
    logger.info("成功标注: %d / %d", answered, len(results))

    # 与 Qwen 对比
    compare_path = Path(args.compare) if args.compare else settings.OUTPUT_DIR / "answer.csv"
    qwen_preds = _load_qwen_preds(compare_path)
    if qwen_preds:
        diffs = compare_with_qwen(results, qwen_preds)
        diff_path = settings.LOGS_DIR / "deepseek_vs_qwen.md"
        lines = [
            f"# DeepSeek vs Qwen 答案差异（{len(diffs)} 题）\n",
            f"DeepSeek 模型: {model}\n",
        ]
        for d in diffs:
            lines.append(f"## {d['qid']}")
            lines.append(f"- DeepSeek: **{d['deepseek']}**  |  Qwen: **{d['qwen']}**")
            if d["reason"]:
                lines.append(f"- DeepSeek 依据: {d['reason']}")
            lines.append("")
        diff_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("与 Qwen 不一致 %d 题，报告: %s", len(diffs), diff_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
