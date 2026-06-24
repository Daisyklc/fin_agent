"""题目加载与数据结构。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from config import settings


@dataclass
class Question:
    qid: str
    domain: str
    split: str
    question: str
    options: dict[str, str]
    answer_format: str            # mcq | multi | tf
    type: str = ""
    doc_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        return cls(
            qid=d["qid"],
            domain=d.get("domain", ""),
            split=d.get("split", ""),
            question=d.get("question", ""),
            options=d.get("options", {}),
            answer_format=d.get("answer_format", ""),
            type=d.get("type", ""),
            doc_ids=d.get("doc_ids", []) or [],
        )

    @property
    def valid_letters(self) -> list[str]:
        return sorted(self.options.keys())


def load_questions(group: str = "group_a", domain: str | None = None) -> list[Question]:
    """加载题目。domain 为空则加载全部领域。"""
    base = settings.QUESTIONS_DIR / group
    domains = [domain] if domain else settings.DOMAINS
    out: list[Question] = []
    for dom in domains:
        fp = base / f"{dom}_questions.json"
        if not fp.exists():
            continue
        data = json.loads(fp.read_text(encoding="utf-8"))
        out.extend(Question.from_dict(d) for d in data)
    return out
