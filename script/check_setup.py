"""M0 自检脚本：验证目录、题目加载、doc_id → 文件映射是否健全。

用法（在项目根目录）：
    python -m script.check_setup
"""

from __future__ import annotations

import sys
from collections import Counter

from config import settings
from agent.questions import load_questions
from agent.doc_registry import get_registry


def main() -> int:
    print("=" * 60)
    print("项目根目录:", settings.ROOT)
    print("模型:", settings.MODEL_NAME, "| base_url:", settings.BASE_URL)
    print("API Key 状态:", "未配置（占位符）" if settings.api_key_is_placeholder() else "已配置")
    print("=" * 60)

    registry = get_registry()
    reg_path = registry.dump()
    print(f"文档登记表已导出: {reg_path}（共 {len(registry.all_entries())} 个文件）")
    for dom in settings.DOMAINS:
        print(f"  - {dom}: {len(registry.entries_for_domain(dom))} 个文件")

    print("-" * 60)
    questions = load_questions("group_a")
    print(f"加载题目: {len(questions)} 道")
    by_fmt = Counter(q.answer_format for q in questions)
    by_dom = Counter(q.domain for q in questions)
    print("  题型分布:", dict(by_fmt))
    print("  领域分布:", dict(by_dom))

    print("-" * 60)
    unresolved: list[tuple[str, str]] = []
    total_refs = 0
    for q in questions:
        for did in q.doc_ids:
            total_refs += 1
            if registry.resolve(did) is None:
                unresolved.append((q.qid, did))

    print(f"doc_id 引用总数: {total_refs}")
    if unresolved:
        print(f"[警告] {len(unresolved)} 个 doc_id 未能解析到文件:")
        for qid, did in unresolved[:30]:
            print(f"    {qid} -> {did}")
        if len(unresolved) > 30:
            print(f"    ... 其余 {len(unresolved) - 30} 个略")
        return 1

    print("[OK] 所有题目的 doc_id 均成功映射到原始文件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
