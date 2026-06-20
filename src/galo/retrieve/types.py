"""Shared retrieval types."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class Candidate:
    """A retrieved chunk, annotated with where/how it surfaced."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    text: str
    # Per-source ranks (1-based). Absent from a source => not retrieved there.
    vector_rank: int | None = None
    graph_rank: int | None = None
    # The graph path that surfaced it, if any (entity names), for provenance.
    graph_path: list[str] = field(default_factory=list)
    # Fused score (filled by the fuser).
    score: float = 0.0


@dataclass(frozen=True)
class Citation:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    score: float
    graph_path: list[str]


@dataclass(frozen=True)
class QueryResult:
    answer: str
    citations: list[Citation]
