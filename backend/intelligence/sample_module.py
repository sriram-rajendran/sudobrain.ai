"""Sample intelligence module for extension authors."""

from __future__ import annotations

from typing import Iterable

from backend.sdk import ExtractedItem, SourceDocument


class KeywordRiskModule:
    name = "keyword_risk"

    def __init__(self, keywords: tuple[str, ...] = ("blocked", "risk", "delay")) -> None:
        self.keywords = keywords

    def analyze(self, documents: Iterable[SourceDocument]) -> Iterable[ExtractedItem]:
        for document in documents:
            lower = document.text.lower()
            hits = [keyword for keyword in self.keywords if keyword in lower]
            if not hits:
                continue
            yield ExtractedItem(
                kind="risk_signal",
                text=f"{document.title}: matched {', '.join(hits)}",
                confidence=0.6,
                source_id=document.external_id,
                metadata={"keywords": hits, "source": document.source},
            )
