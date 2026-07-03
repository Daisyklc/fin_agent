# DeepSeek 全量标注摘要

- 题目：100 题（A榜）
- 成功：100 / 100
- 空答案：[]
- 与 Qwen 一致：43 题（43%）
- 与 Qwen 不一致：57 题
- 总 Token（含 fin_a_001 重试）：约 359984

## 按领域一致率

| 领域 | 一致 | 不一致 |
|---|---|---|
| insurance | 14 | 6 |
| regulatory | 9 | 11 |
| financial_contracts | 8 | 12 |
| financial_reports | 5 | 15 |
| research | 7 | 13 |

## 产出
- `gold/deepseek_group_a_gold.csv`
- `logs/deepseek_annotate_full.json`
- `logs/deepseek_vs_qwen.md`

## 使用
```bash
python -m script.analyze --gold gold/deepseek_group_a_gold.csv --answer answer.csv
```
（将 deepseek 作 gold 代理可估算 Qwen 准确率约 43%）
