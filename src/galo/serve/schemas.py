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


class RecommendRequest(BaseModel):
    entity: str = Field(..., min_length=1, description="Seed entity name.")
    k: int = Field(10, ge=1, le=100)
    alpha: float = Field(
        0.5, ge=0.0, le=1.0, description="Blend: 1=semantic only, 0=graph only."
    )


class RecommendationModel(BaseModel):
    entity_id: uuid.UUID
    name: str
    graph_weight: float
    similarity: float
    score: float


class RecommendResponse(BaseModel):
    seed_found: bool
    recommendations: list[RecommendationModel]


class PathRequest(BaseModel):
    from_concept: str = Field(..., min_length=1)
    to_concept: str = Field(..., min_length=1)


class PathStepModel(BaseModel):
    entity_id: uuid.UUID
    name: str


class PathResponse(BaseModel):
    found: bool
    steps: list[PathStepModel]
    reason: str | None = None
