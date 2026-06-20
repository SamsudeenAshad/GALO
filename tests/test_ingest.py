"""Ingestion orchestrator tests with the store and gateway stubbed.

Covers: a fresh ingest (chunks + embeddings persisted), idempotent skip on
identical content, force re-ingest, and that an embedding-dim mismatch from the
gateway surfaces as a failed job + raised error.
"""

from __future__ import annotations

import pytest

from galo.ingest.orchestrator import IngestionOrchestrator
from galo.models.gateway import HealthStatus


class FakeGateway:
    def __init__(self, dim: int = 3, raise_exc: Exception | None = None) -> None:
        self._dim = dim
        self._raise = raise_exc

    async def embed(self, texts):
        if self._raise is not None:
            raise self._raise
        return [[0.1] * self._dim for _ in texts]

    async def generate(self, prompt, *, system=None):
        return ""

    async def health(self):
        return HealthStatus(ok=True, detail="fake")

    async def aclose(self):
        pass


class FakeStore:
    """In-memory stand-in for PgStore's ingestion surface."""

    def __init__(self) -> None:
        self.docs: dict[str, object] = {}      # content_hash -> doc
        self.chunks: dict = {}                 # document_id -> (chunks, embeddings)
        self.jobs: list[tuple] = []

    async def content_exists(self, content_hash):
        return content_hash in self.docs

    async def upsert_document(self, doc):
        self.docs[doc.content_hash] = doc

    async def replace_chunks(self, document_id, chunks, embeddings):
        if len(chunks) != len(embeddings):
            raise ValueError("length mismatch")
        self.chunks[document_id] = (chunks, embeddings)

    async def record_job(self, job_id, document_id, step, status, error=None):
        self.jobs.append((status, error))


@pytest.fixture
def store():
    return FakeStore()


async def test_fresh_ingest_persists_chunks(store) -> None:
    orch = IngestionOrchestrator(store, FakeGateway(), chunk_size=50, chunk_overlap=10)
    text = ". ".join(f"fact {i}" for i in range(60))
    result = await orch.ingest_text(text, title="t")

    assert result.skipped is False
    assert result.chunks > 0
    chunks, embeddings = store.chunks[result.document_id]
    assert len(chunks) == len(embeddings) == result.chunks
    assert store.jobs[-1] == ("done", None)


async def test_idempotent_skip_on_identical_content(store) -> None:
    orch = IngestionOrchestrator(store, FakeGateway())
    first = await orch.ingest_text("same content here")
    second = await orch.ingest_text("same content here")

    assert first.skipped is False
    assert second.skipped is True
    assert second.document_id == first.document_id


async def test_force_reingests(store) -> None:
    orch = IngestionOrchestrator(store, FakeGateway())
    await orch.ingest_text("payload")
    forced = await orch.ingest_text("payload", force=True)
    assert forced.skipped is False


async def test_embed_failure_records_failed_job_and_raises(store) -> None:
    gw = FakeGateway(raise_exc=ValueError("embedding dim mismatch: 768 vs 3"))
    orch = IngestionOrchestrator(store, gw)
    with pytest.raises(ValueError, match="dim mismatch"):
        await orch.ingest_text("some text to embed")
    assert store.jobs[-1][0] == "failed"
