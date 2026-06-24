"""打包 submission.zip，符合赛题要求的目录结构。

赛题要求（B 榜前 15 名提交）：
    submission.zip
    ├── answer.csv
    ├── evidence.json
    ├── processed_data/   # 清洗、切分、结构化后的长文本数据
    ├── agent/            # Agent 系统完整代码
    ├── script/           # 可复现运行脚本
    ├── logs/             # 实验记录
    ├── requirements.txt
    └── README.md
（总大小 ≤ 1GB）

用法：
    python -m script.make_submission                 # 默认用 answer.csv/evidence.json
    python -m script.make_submission --answer answer_verify.csv --evidence evidence_verify.json
"""

from __future__ import annotations

import sys
import zipfile
import argparse
from pathlib import Path

from config import settings

# 需要纳入的目录（代码 + 数据 + 配置）
INCLUDE_DIRS = ["agent", "script", "config", "processed_data", "logs"]
# 根目录单文件
INCLUDE_FILES = ["requirements.txt", "README.md", "方案设计.md"]
# 排除规则（路径片段）
EXCLUDE_PARTS = {"__pycache__", ".pyc", ".pyo"}
# logs 里只保留这些（避免把控制台大日志全打进去）
LOGS_KEEP_SUFFIX = (".json", ".md")

MAX_BYTES = 1024 ** 3  # 1GB


def _excluded(path: Path) -> bool:
    s = str(path)
    return any(part in s for part in EXCLUDE_PARTS)


def _iter_files():
    root = settings.ROOT
    for d in INCLUDE_DIRS:
        base = root / d
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or _excluded(p):
                continue
            if d == "logs" and p.suffix not in LOGS_KEEP_SUFFIX:
                continue
            yield p, p.relative_to(root)
    for f in INCLUDE_FILES:
        p = root / f
        if p.exists():
            yield p, Path(f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answer", default="answer.csv")
    ap.add_argument("--evidence", default="evidence.json")
    ap.add_argument("--out", default="submission.zip")
    args = ap.parse_args()

    root = settings.ROOT
    answer = root / args.answer
    evidence = root / args.evidence
    if not answer.exists():
        print(f"[错误] 找不到答案文件: {answer}")
        return 2

    out = root / args.out
    total = 0
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        # answer.csv / evidence.json 放到压缩包根，固定名
        zf.write(answer, "answer.csv")
        total += answer.stat().st_size
        count += 1
        if evidence.exists():
            zf.write(evidence, "evidence.json")
            total += evidence.stat().st_size
            count += 1
        for src, arc in _iter_files():
            zf.write(src, str(arc))
            total += src.stat().st_size
            count += 1

    zip_size = out.stat().st_size
    print(f"已生成 {out}")
    print(f"  打包文件数: {count}，原始总大小: {total/1024/1024:.1f} MB，压缩后: {zip_size/1024/1024:.1f} MB")
    print(f"  答案来源: {args.answer} / {args.evidence}")
    if total > MAX_BYTES:
        print("[警告] 原始大小超过 1GB，请精简后再提交！")
    else:
        print("  大小符合 ≤1GB 要求。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
