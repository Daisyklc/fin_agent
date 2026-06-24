"""分领域 Prompt 构造。

要求模型输出严格 JSON：
  {"answer": "AB", "evidence": [{"doc_id": "...", "loc": "第X条/第N页", "quote": "..."}], "reason": "简短"}
"""

from __future__ import annotations

import re

from agent.questions import Question
from agent.retrieval import RetrievedChunk

# PDF 字体映射常引入私有区(PUA)字符与控制字符，清掉以免浪费 token / 干扰模型
_JUNK_RE = re.compile(r"[\ue000-\uf8ff\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize(text: str) -> str:
    return _JUNK_RE.sub("", text)

_FORMAT_HINT = {
    "mcq": "这是单选题，只有一个正确选项，answer 为单个大写字母（A/B/C/D）。",
    "multi": "这是多选题，可能有多个正确选项，answer 为多个大写字母按字母升序拼接且无分隔符（如 ABD）；漏选或多选均判错。",
    "tf": "这是判断题，answer 为单个大写字母，含义以选项为准（如 A=正确，B=错误）。",
}

_DOMAIN_GUIDE = {
    "insurance": (
        "你是保险条款分析专家。务必依据条款的触发条件与计算公式作答，"
        "区分身故保险金、现金价值、账户价值、已交保费、已领年金等概念，注意领取前后规则差异。"
    ),
    "regulatory": (
        "你是金融监管法规专家。必须严格依据给定法规条文作答，不得用常识替代条文。"
        "特别关注施行/生效日期、义务主体、时限（工作日/自然日）、比例阈值与法条优先级。"
    ),
    "financial_contracts": (
        "你是金融合同/债券条款分析专家。关注票面利率、发行规模、期限、信用评级、"
        "本息偿付与担保等权利义务关系。"
    ),
    "financial_reports": (
        "你是财务报表分析专家。准确提取并对比各期指标（营业收入、净利润、经营活动现金流量净额、"
        "研发投入占比、现金分红等），注意同比方向与口径一致性，逐项核对选项数值。"
    ),
    "research": (
        "你是行业研究分析专家。基于研报内容核验行业趋势、公司比较与结论，避免主观推断。"
    ),
}

SYSTEM_PROMPT = (
    "你是严谨的金融长文档问答系统。只能依据提供的【证据片段】作答，"
    "证据不足时也要选出最符合证据的答案，不要编造原文没有的事实。"
    "必须只输出一个 JSON 对象，不要输出多余文字。"
)


def build_user_prompt(q: Question, chunks: list[RetrievedChunk]) -> str:
    guide = _DOMAIN_GUIDE.get(q.domain, "")
    fmt = _FORMAT_HINT.get(q.answer_format, "")

    evidence_text = _build_evidence_text(chunks)
    options_text = "\n".join(f"{k}. {v}" for k, v in sorted(q.options.items()))

    return (
        f"{guide}\n\n"
        f"【题型说明】{fmt}\n\n"
        f"【问题】\n{q.question}\n\n"
        f"【选项】\n{options_text}\n\n"
        f"【证据片段】\n{evidence_text}\n\n"
        "请逐个选项核对证据后作答。只输出如下 JSON：\n"
        '{"answer": "选项字母", '
        '"evidence": [{"doc_id": "引用文档", "loc": "页码或条款", "quote": "关键原文(<=50字)"}], '
        '"reason": "一句话依据"}'
    )


def _build_evidence_text(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for i, c in enumerate(chunks, 1):
        loc = f"第{c.page}页" if c.page else ""
        tag = "【表格】" if c.is_table else ""
        head = f"[证据{i}] doc_id={c.doc_id} {loc} {tag}".strip()
        blocks.append(f"{head}\n{_sanitize(c.text)}")
    return "\n\n".join(blocks) if blocks else "（无可用证据）"


VERIFY_SYSTEM_PROMPT = (
    "你是严格的金融问答复核专家。请独立、批判性地核对一份初步答案是否正确，"
    "只依据提供的证据，不要默认初答正确。重点检查：选项与证据是否逐条对应、"
    "数值/日期/比例/时限是否准确、多选是否有漏选或多选。只输出一个 JSON 对象。"
)


def build_verify_prompt(
    q: Question, chunks: list[RetrievedChunk], initial_answer: str, initial_reason: str
) -> str:
    fmt = _FORMAT_HINT.get(q.answer_format, "")
    evidence_text = _build_evidence_text(chunks)
    options_text = "\n".join(f"{k}. {v}" for k, v in sorted(q.options.items()))
    return (
        f"【题型说明】{fmt}\n\n"
        f"【问题】\n{q.question}\n\n"
        f"【选项】\n{options_text}\n\n"
        f"【证据片段】\n{evidence_text}\n\n"
        f"【初步答案】{initial_answer}\n【初步依据】{initial_reason}\n\n"
        "请逐个选项独立复核，判断初步答案是否正确。只输出如下 JSON：\n"
        '{"answer": "你复核后认为正确的选项字母", '
        '"agree": true 或 false（是否与初步答案一致）, '
        '"confidence": "high"/"medium"/"low", '
        '"note": "复核要点(<=40字)"}'
    )
