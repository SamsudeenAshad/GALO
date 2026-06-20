"""Pydantic request/response models for the API."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Raw document text to ingest.")
    title: str | None = None
    source_uri: str | None = None
    force: bool = Field(False, description="Re-ingest even if content already exists.")


class IngestResponse(BaseModel):
    document_id: uuid.UUID
    content_hash: str
    chunks: int
    skipped: bool
