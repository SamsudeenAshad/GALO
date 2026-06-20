"""Shared ingestion result types."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class IngestResult:
    document_id: uuid.UUID
    content_hash: str
    chunks: int
    skipped: bool  # True when content was already ingested (idempotent no-op)
