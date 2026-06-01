"""Sample connector that reads local Markdown files.

This is intentionally read-only and useful for fixtures, docs folders, and
transparent knowledge-vault experiments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from backend.sdk import SourceDocument


class LocalMarkdownConnector:
    name = "local_markdown"

    def __init__(self, root: str | Path, glob: str = "**/*.md") -> None:
        self.root = Path(root).expanduser().resolve()
        self.glob = glob

    def health(self) -> dict:
        exists = self.root.exists() and self.root.is_dir()
        count = len(list(self.root.glob(self.glob))) if exists else 0
        return {
            "name": self.name,
            "ok": exists,
            "root": str(self.root),
            "documents": count,
        }

    def fetch(self, limit: int = 100) -> Iterable[SourceDocument]:
        if not self.root.exists():
            return []

        documents = []
        for path in sorted(self.root.glob(self.glob))[: max(0, limit)]:
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(errors="replace")
            rel = path.relative_to(self.root)
            documents.append(
                SourceDocument(
                    source=self.name,
                    external_id=str(rel),
                    title=path.stem.replace("-", " ").replace("_", " ").strip() or path.name,
                    text=text,
                    url=f"file://{path}",
                    metadata={"path": str(path), "relative_path": str(rel)},
                )
            )
        return documents
