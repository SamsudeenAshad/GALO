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


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The question to answer.")


class CitationModel(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    score: float
    graph_path: list[str] = Field(default_factory=list)


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationModel]
