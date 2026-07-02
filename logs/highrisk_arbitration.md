# 高风险题三方对照（Qwen verify vs DeepSeek）

> 生成时间：20260702  
> DeepSeek 模型：`deepseek-chat`（8题）+ `deepseek-reasoner`（3题补跑）  
> 证据来源：`evidence.json` 引用片段（无 `processed_data`，检索未启用）

## 汇总

| 题号 | Qwen(verify) | DeepSeek | 一致 | 建议 |
|---|---|---|---|---|
| ins_a_003 | A（复核认为错） | **D** | ❌ | 人工核：题干已给复发类型/免赔额，D 可能过保守；补偿型上限需查条款 |
| ins_a_007 | BC | AC | ❌ | 人工核：B 是否有证据支持贷款比例 |
| ins_a_016 | CD | （空） | ❌ | 证据不足；需补检索 doc 9/10 施救费用条款 |
| reg_a_006 | B | **B** | ✅ | 可采信 B（较高风险**以上** vs 高风险） |
| reg_a_012 | ABCD | ABD | ❌ | 人工核：C「不披露分红原因」限定条件 |
| reg_a_017 | AB | ABC | ❌ | 人工核：C 是否为法规规定还是申辩意见 |
| fc_a_007 | A | ABD | ❌ | 人工核：B/D 是否有 text02/text14 依据 |
| res_a_006 | B | **A** | ❌ | 人工核：「除客户资金杠杆」是否改变陈述真伪 |

**一致 1/8**，DeepSeek 与 Qwen 直接不一致 **6/8**（另 1 题 DeepSeek 未作答）。

Token 消耗：chat 批 4492 + reasoner 批 3623 ≈ **8115**

---

## 逐题详情

### ins_a_003 [insurance] — 医疗险合计赔付

- **Qwen**：A（合计 13.5 万）
- **Qwen 复核**：认为违反补偿型原则，初答错，但未改答案
- **DeepSeek**：**D**（无法确定，因众安条款证据不足）
- **分析**：题干已写明「免赔额 0、形态学复发」，DeepSeek 可能因 `evidence.json` 未收录众安条款而保守选 D。A/B/C 选项数值完全相同（均为 13.5 万），若补偿型「总额不超过自费 5 万」成立，则三选项同错——需回原文核实。

### ins_a_007 [insurance] — 保单贷款

- **Qwen**：BC
- **DeepSeek**：AC
- **分歧点**：B（国寿增益宝贷款比例）是否有条款支持；DeepSeek 称 B 无证据

### ins_a_016 [insurance] — 施救费用上限

- **Qwen**：CD
- **DeepSeek**：（空）证据未提及施救费用
- **分析**：Qwen 引用了 doc 9/10 车险条款，但 `evidence.json` 给 DeepSeek 的引用片段可能不完整 → **放入 raw 数据后重跑检索可解**

### reg_a_006 [regulatory] — 判断题 ✅

- **Qwen**：B
- **DeepSeek**：B
- **依据**：法规为「较高风险**以上**」存量客户，题干「高风险」表述不精确 → 整体判错

### reg_a_012 [regulatory] — 公司治理多选

- **Qwen**：ABCD
- **DeepSeek**：ABD（排除 C）
- **分歧点**：C 是否要求「具备条件而不分红」才须披露原因

### reg_a_017 [regulatory] — 治理与处罚时效

- **Qwen**：AB
- **DeepSeek**：ABC（多选 C）
- **分歧点**：C 是法条还是案例申辩意见

### fc_a_007 [financial_contracts] — 债券文档对比

- **Qwen**：A
- **DeepSeek**：ABD
- **分歧点**：B（发行规模上限）、D（违约条款）是否在两家文档中均成立

### res_a_006 [research] — 券商杠杆判断

- **Qwen**：B（错误）
- **DeepSeek**：A（正确），认为「除」字不改变含义
- **分析**：这是典型否定词题；Qwen verify 认为题干漏「除」致概念错误。DeepSeek 与 Qwen verify **立场相反**，**必须人工读 pack2_text10 原文**

---

## 建议下一步

1. **立即可写入 gold 候选**：`reg_a_006=B`（双方一致）
2. **优先人工复核**：`res_a_006`、`ins_a_003`、`fc_a_007`
3. **补数据后重跑**：将 `raw/` 放入并 `python -m script.parse_docs`，再跑  
   `python -m script.annotate_gold --qids ins_a_016,fc_a_007 --compare answer.csv`
4. **额度允许时**：对分歧题用 `--reasoner` 二次标注（注意 reasoner 需优化 JSON 解析）

## 命令备忘

```bash
# 仅高风险 8 题
python -m script.annotate_gold --qids ins_a_003,ins_a_007,ins_a_016,reg_a_006,reg_a_012,reg_a_017,fc_a_007,res_a_006 --compare answer.csv

# 有 raw 数据后
python -m script.parse_docs
python -m script.annotate_gold --qids ins_a_016,ins_a_003 --compare answer.csv
```
