"""Stable contributor-facing interfaces for SudoBrain extensions.

These protocols keep connectors, intelligence modules, and workflow actions
small and testable while the internal product surface continues to evolve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol


@dataclass(frozen=True)
class SourceDocument:
    """A normalized read-only source record ready for extraction."""

    source: str
    external_id: str
    title: str
    text: str
    occurred_at: str | None = None
    author: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedItem:
    """A typed knowledge item emitted by an intelligence module."""

    kind: str
    text: str
    confidence: float = 1.0
    source_id: str | None = None
    project: str | None = None
    people: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowActionResult:
    """Result returned by a workflow action."""

    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False


class Connector(Protocol):
    """Read-only source connector."""

    name: str

    def health(self) -> dict[str, Any]:
        """Return a safe health summary with no credentials or private payloads."""

    def fetch(self, limit: int = 100) -> Iterable[SourceDocument]:
        """Yield normalized source documents."""


class IntelligenceModule(Protocol):
    """Module that derives knowledge from normalized source documents."""

    name: str

    def analyze(self, documents: Iterable[SourceDocument]) -> Iterable[ExtractedItem]:
        """Yield extracted knowledge items."""


class WorkflowAction(Protocol):
    """Permission-aware action invoked by the workflow engine."""

    name: str
    requires_approval: bool

    def run(self, payload: dict[str, Any], dry_run: bool = True) -> WorkflowActionResult:
        """Run or preview an action. Write actions must honor dry_run."""
