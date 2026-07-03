# 高风险题三方对照（检索重跑版）

> 生成时间：20260703  
> 数据：`raw/` 196 文件 + `processed_data/` 572 jsonl（已合并 main）  
> DeepSeek：`deepseek-chat`，证据来源：**BM25 检索**（非 evidence.json 片段）

## 汇总（vs 上次 evidence.json 版）

| 题号 | Qwen | DeepSeek(检索) | 一致 | 变化 |
|---|---|---|---|---|
| reg_a_006 | B | **B** | ✅ | 无变化 |
| **ins_a_016** | CD | **CD** | ✅ | **新增一致**（检索到 doc 9/10 车险条款） |
| ins_a_003 | A | D | ❌ | 仍分歧 |
| ins_a_007 | BC | AC | ❌ | 仍分歧 |
| reg_a_012 | ABCD | ABD | ❌ | 仍分歧（C 项） |
| reg_a_017 | AB | ABC | ❌ | 仍分歧（C 项） |
| fc_a_007 | A | ABD | ❌ | 仍分歧 |
| res_a_006 | B | A | ❌ | 仍分歧（「除」字） |

**一致 2/8**（上次 1/8）｜Token：**22,336**（有检索，prompt 显著增大）

## 关键改进

### ins_a_016 ✅ 已与 Qwen 一致
检索到 doc 9/10 特种车险条款，明确施救/修理期间费用补偿不超过保险金额，与 Qwen 答案 CD 一致。

### ins_a_003 仍选 D
检索到众安 doc 3 形态学复发条款，但认为赔付比例未明确；题干已给免赔额 0，A/B/C 选项数值相同（13.5 万），补偿型上限问题仍未解决。

### fc_a_007 DeepSeek 认为 A 错误
检索后指出 text02 仅为 A 级监管评级非 AAA，与 Qwen 仅选 A 矛盾；DeepSeek 选 ABD。

### res_a_006 仍与 Qwen 相反
DeepSeek 选 A（认为数据一致），Qwen verify 选 B（认为「除」字改变含义）。

## 可采信 gold 候选

| qid | answer | 置信度 |
|---|---|---|
| reg_a_006 | B | 高（双方一致） |
| ins_a_016 | CD | 高（双方一致，检索证实） |

## 命令

```bash
python -m script.annotate_gold --qids ins_a_003,ins_a_007,ins_a_016,reg_a_006,reg_a_012,reg_a_017,fc_a_007,res_a_006 --compare answer.csv
```
