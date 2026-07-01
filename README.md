# 金融长文档问答 Agent

天池/阿里云「金融长文档问答」赛题方案实现。在 **500 万 token 预算**内，对保险条款、监管法规、金融合同、财务报表、行业研报五类长文档的选择题（单选/多选/判断）作答，并产出可追溯证据。

> 详细设计见 `方案设计.md`。
> 评分：`FinalScore = 100 * Accuracy * (0.7 + 0.3 * TokenScore)`，`TokenScore = max(0, min(1, (5e6 - TotalTokens)/5e6))`。

## 合规约束
- 推理问答阶段**只调用 Qwen 系列模型**（百炼/魔搭），**禁用任何 embedding 模型**。检索使用 BM25 + 规则加权（纯词面，无向量）。
- 解析阶段允许非 Qwen 工具（pdfplumber/bs4），其产物仅用于结构化，不直接作为答题结论。

## 目录结构
```
config/            # settings.py：API/模型/路径/预算
agent/             # 核心代码
  ├─ qwen_client.py    # Qwen 调用封装（自动累计 token）
  ├─ token_tracker.py  # Token 统计中间件（按 qid 分桶 + 全局汇总）
  ├─ doc_registry.py   # doc_id ↔ 文件路径 ↔ 标题 映射
  ├─ questions.py      # 题目加载
  ├─ parsing.py        # PDF/HTML/TXT → 结构化 Block
  ├─ chunking.py       # Block → 检索单元 Chunk（按条款/章节切分）
  ├─ retrieval.py      # BM25 + 金融术语/条款号/数值加权
  ├─ prompts.py        # 分领域 Prompt + 严格 JSON 输出约定
  ├─ engine.py         # 单题流水线：检索→组装→推理→规范化
  └─ postprocess.py    # 答案规范化 + answer.csv 生成
script/
  ├─ check_setup.py    # M0 自检：目录/题目/doc_id 映射
  ├─ parse_docs.py     # 解析全部/引用文档到 processed_data/
  └─ run.py            # 主入口：生成 answer.csv / evidence.json
processed_data/    # 解析后的结构化 chunk（*.jsonl）
logs/              # 每次运行的 token 与统计
raw/, questions/   # 原始数据集
```

## 快速开始
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key（任选其一）
#    a) 环境变量（推荐）
set DASHSCOPE_API_KEY=你的key        # Windows
export DASHSCOPE_API_KEY=你的key     # Linux/Mac
#    b) 直接改 config/settings.py 里的 API_KEY 占位符

# 3. 自检环境与映射
python -m script.check_setup

# 4. 解析文档（A 榜：仅题目引用的文档；B 榜加 --all）
python -m script.parse_docs

# 5. 运行（先小规模联调，再全量）
python -m script.run --dry-run                    # 不调模型，验证检索+prompt
python -m script.run --domain financial_reports   # 单领域
python -m script.run                              # 全部 A 榜 → answer.csv
```

## 产出
- `answer.csv`：首行 `summary`（token 统计）+ 每题答案与分项 token。
- `evidence.json`：每题答案、依据与引用证据（对应提交要求）。
- `logs/run_*.json`：本次运行的 token 总量与 TokenScore 估算。

## 当前进度
- [x] M0 工程脚手架、token 中间件、doc_id 映射（100 题 / 231 引用全部解析成功）
- [x] M1 文档解析切块（A榜引用 68 篇；全库 572 篇，1 篇扫描件无文本）
- [x] M2 BM25 + 金融术语加权检索（dry-run 100 题 0 漏召回）
- [x] M3 推理流水线打通，全量实跑：100/100，总 Token 635K，TokenScore 0.873
- [x] M4 均衡检索（多文档题保证每个文档都有证据）+ 全量重跑（13 题答案变化）
- [~] M5 错题分析与 token 压缩：选择性自洽验证（`--verify-mode selective`）+ 检索 query 增强 + 分领域 prompt 加固
- [x] M6 B 榜全库检索适配：两阶段（文档召回→段落），doc recall@8 全命中率 0.80

## 自洽验证（`python -m script.run --verify`）
每题在初答后再做一次独立复核（critic），逐选项核对证据：
- **`--verify-mode selective`（默认）**：仅对高风险题复核（多选、判断、保险计算/推理、财报/合同跨文档单选、研报数据核验），约 97/100 题。
- **`--verify-mode all`**：每题复核，token 约翻倍（100 题约 1.3M，TokenScore≈0.74）。
- 复核与初答**不一致**或**低置信** → 标记为高风险题，写入 `logs/highrisk_report.md`（含 初答→终答、置信度、复核要点）。
- 不一致时默认采用复核答案为终值；复核 prompt 要求 disagree 时必须给出不同于初答的正确选项。
- 建议：提交前用 selective verify 平衡准确率与 TokenScore；对 baseline 薄弱领域可改用 `--verify-mode all`。

## B 榜文档召回评估（`python -m script.eval_retrieval`）
用 A 榜真实 doc_ids 当 gold，模拟盲测测召回。总体 R@8=0.91 / 全命中@8=0.80。
弱项：insurance、financial_contracts（产品/债券名泛化），是后续优化重点。

## 评估与对比脚本
```bash
python -m script.make_gold_template     # 生成 gold 模板供人工填标准答案
python -m script.analyze                # 结果分析 + 错题报告 + baseline 对照（需 gold 才算准确率）
python -m script.compare_runs --a answer_run1.csv --b answer.csv   # 两次运行差异
python -m script.eval_retrieval         # B 榜文档召回 recall@k
python -m script.run_baseline --limit 5 # 朴素长文输入 baseline 对照
python -m script.make_submission        # 打包 submission.zip（≤1GB）
```

## 三个版本结果（A 榜 100 题）
| 版本 | 备份文件 | 总 Token | TokenScore | 说明 |
|---|---|---|---|---|
| run1 全局检索 | `answer_run1.csv` | 635,185 | 0.873 | 初版 |
| run2 均衡检索 | `answer_run2.csv` | 643,904 | 0.871 | 多文档题取证更均衡，13 题变化 |
| verify 自洽验证 | `answer_verify.csv` | 1,191,580 | 0.762 | 8 题高风险，5 处精确措辞纠正 |

当前 `answer.csv` = verify 版。提交版选择见对话说明（accuracy 主导 vs TokenScore）。
```
