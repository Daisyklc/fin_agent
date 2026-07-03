"""主入口：对题目运行 Agent，生成 answer.csv / evidence.json / 日志。

用法：
    python -m script.run --domain financial_reports     # 跑单个领域（MVP）
    python -m script.run                                 # 跑全部 A 榜
    python -m script.run --limit 3                       # 只跑前 3 题（联调）
    python -m script.run --dry-run                       # 不调模型，仅检索+组prompt，自检流水线
"""

from __future__ import annotations

import sys
import json
import argparse
import logging
from datetime import datetime

from config import settings
from agent.questions import load_questions
from agent.engine import FinanceAgent
from agent.token_tracker import GLOBAL_TRACKER
from agent.postprocess import write_answer_csv
from agent.prompts import build_user_prompt

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default=None, help="只跑某领域")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题")
    ap.add_argument("--group", default="group_a")
    ap.add_argument("--dry-run", action="store_true", help="不调用模型，仅验证检索与 prompt 组装")
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--top-docs", type=int, default=8, help="B榜文档级召回候选数")
    ap.add_argument("--verify", action="store_true",
                    help="开启自洽验证（默认 selective 模式，仅高风险题复核）")
    ap.add_argument("--verify-mode", default=None, choices=["off", "selective", "all"],
                    help="验证范围：selective=高风险题(默认), all=每题, off=关闭")
    ap.add_argument("--qids", default=None, help="只跑指定题目(逗号分隔)")
    ap.add_argument("--merge", action="store_true",
                    help="把本次结果合并进已有 answer.csv/evidence.json，而非全量覆盖")
    args = ap.parse_args()

    all_questions = load_questions(args.group, args.domain)
    questions = all_questions
    if args.qids:
        want = {x.strip() for x in args.qids.split(",") if x.strip()}
        questions = [q for q in all_questions if q.qid in want]
    if args.limit:
        questions = questions[: args.limit]
    logger.info("待作答题目: %d", len(questions))

    if args.dry_run:
        return _dry_run(questions, args.top_k)

    if settings.api_key_is_placeholder():
        logger.error("未配置 API Key，无法实际推理。可先用 --dry-run 验证流水线。")
        return 2

    verify_mode = args.verify_mode or (settings.VERIFY_MODE if args.verify else "off")
    if args.verify and verify_mode == "off":
        verify_mode = settings.VERIFY_MODE

    agent = FinanceAgent(
        top_k=args.top_k, top_docs=args.top_docs,
        verify=args.verify or verify_mode != "off",
        verify_mode=verify_mode,
    )
    from agent.verify_policy import count_verify_targets
    n_verify = count_verify_targets(questions, verify_mode) if (args.verify or verify_mode != "off") else 0
    if n_verify:
        logger.info("自洽验证模式=%s，将复核 %d/%d 题", verify_mode, n_verify, len(questions))

    answers: dict[str, str] = {}
    evidence_log: dict[str, dict] = {}
    high_risk: list[dict] = []

    try:
        from tqdm import tqdm
        iterator = tqdm(questions, desc="answering")
    except ImportError:
        iterator = questions

    for q in iterator:
        try:
            res = agent.answer(q)
        except Exception as e:  # noqa: BLE001
            logger.error("%s 作答失败: %s", q.qid, e)
            answers[q.qid] = ""
            continue
        answers[q.qid] = res.answer
        evidence_log[q.qid] = {
            "answer": res.answer,
            "reason": res.reason,
            "evidence": res.evidence,
            "tokens": GLOBAL_TRACKER.usage_for(q.qid).total_tokens,
        }
        if res.verified:
            evidence_log[q.qid].update({
                "verified": True,
                "initial_answer": res.initial_answer,
                "agree": res.agree,
                "confidence": res.confidence,
                "verify_note": res.verify_note,
            })
            if res.high_risk:
                high_risk.append({
                    "qid": q.qid, "domain": q.domain,
                    "initial": res.initial_answer, "final": res.answer,
                    "confidence": res.confidence, "note": res.verify_note,
                    "question": q.question,
                })

    csv_path = settings.OUTPUT_DIR / "answer.csv"
    ev_path = settings.OUTPUT_DIR / "evidence.json"

    if args.merge:
        out_questions, answers, qid_usage, evidence_log = _merge_with_existing(
            all_questions, answers, evidence_log, csv_path, ev_path)
        from agent.postprocess import write_answer_csv_rows
        write_answer_csv_rows(csv_path, out_questions, answers, qid_usage)
        final_total = sum(u[2] for u in qid_usage.values())
        answered = len(out_questions)
    else:
        write_answer_csv(csv_path, questions, answers, GLOBAL_TRACKER)
        final_total = GLOBAL_TRACKER.summary().total_tokens
        answered = len(answers)
    ev_path.write_text(json.dumps(evidence_log, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (settings.LOGS_DIR / f"run_{ts}.json").write_text(
        json.dumps(
            {"total_tokens": final_total,
             "this_run_tokens": GLOBAL_TRACKER.summary().total_tokens,
             "merged": bool(args.merge),
             "answered": answered},
            ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if args.verify or verify_mode != "off":
        hr_path = settings.LOGS_DIR / "highrisk_report.md"
        lines = [f"# 高风险题报告（{len(high_risk)} 题，复核不一致或低置信）\n"]
        for h in high_risk:
            if h["initial"] != h["final"]:
                flag = "答案被改"
            elif h["confidence"] == "low":
                flag = "低置信(答案未改)"
            else:
                flag = "复核存疑(答案未改)"
            lines.append(f"## {h['qid']} [{h['domain']}] ({flag})")
            lines.append(f"- 初答: **{h['initial']}** → 终答: **{h['final']}**  置信度: {h['confidence']}")
            lines.append(f"- 复核要点: {h['note']}")
            lines.append(f"- 题干: {h['question']}\n")
        hr_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("自洽验证: %d 题高风险，报告 %s", len(high_risk), hr_path)

    logger.info("完成（本次跑 %d 题）。answer.csv=%s", len(answers), csv_path)
    logger.info("总 Token: %d（预算 %d，TokenScore≈%.3f）",
                final_total, settings.TOKEN_BUDGET,
                max(0.0, min(1.0, (settings.TOKEN_BUDGET - final_total) / settings.TOKEN_BUDGET)))
    return 0


def _merge_with_existing(all_questions, new_answers, new_evidence, csv_path, ev_path):
    """把本次运行的子集结果合并进已有 answer.csv / evidence.json。"""
    import csv as _csv
    existing_ans: dict[str, str] = {}
    existing_usage: dict[str, tuple[int, int, int]] = {}
    if csv_path.exists():
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in _csv.DictReader(f):
                qid = (row.get("qid") or "").strip()
                if not qid or qid == "summary":
                    continue
                existing_ans[qid] = (row.get("answer") or "").strip()
                existing_usage[qid] = (
                    int(row.get("prompt_tokens") or 0),
                    int(row.get("completion_tokens") or 0),
                    int(row.get("total_tokens") or 0),
                )
    existing_ev = {}
    if ev_path.exists():
        existing_ev = json.loads(ev_path.read_text(encoding="utf-8"))

    answers: dict[str, str] = dict(existing_ans)
    usage: dict[str, tuple[int, int, int]] = dict(existing_usage)
    evidence = dict(existing_ev)
    for qid, ans in new_answers.items():
        answers[qid] = ans
        u = GLOBAL_TRACKER.usage_for(qid)
        usage[qid] = (u.prompt_tokens, u.completion_tokens, u.total_tokens)
        if qid in new_evidence:
            evidence[qid] = new_evidence[qid]
    return all_questions, answers, usage, evidence


def _dry_run(questions, top_k: int) -> int:
    """不调模型：验证检索能召回内容、prompt 能组装。"""
    from agent.engine import FinanceAgent
    agent = FinanceAgent(top_k=top_k)
    empty = 0
    for q in questions:
        chunks = agent._retrieve(q)
        prompt = build_user_prompt(q, chunks)
        if not chunks:
            empty += 1
        logger.info("[%s] 召回 %d 段，prompt %d 字", q.qid, len(chunks), len(prompt))
    logger.info("dry-run 完成：%d 题，其中 %d 题无召回。", len(questions), empty)
    return 0


if __name__ == "__main__":
    sys.exit(main())
