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
    def __init__(
        self, dim: int = 3, raise_exc: Exception | None = None, extraction: str = ""
    ) -> None:
        self._dim = dim
        self._raise = raise_exc
        self._extraction = extraction

    async def embed(self, texts):
        if self._raise is not None:
            raise self._raise
        return [[0.1] * self._dim for _ in texts]

    async def generate(self, prompt, *, system=None):
        return self._extraction

    async def health(self):
        return HealthStatus(ok=True, detail="fake")

    async def aclose(self):
        pass


class FakeGraph:
    def __init__(self, raise_exc: Exception | None = None) -> None:
        self._raise = raise_exc
        self.upserts: list = []

    async def upsert_extraction(self, chunk_id, extraction):
        if self._raise is not None:
            raise self._raise
        self.upserts.append((chunk_id, extraction))


class FakeStore:
    """In-memory stand-in for PgStore's ingestion surface."""

    def __init__(self) -> None:
        self.docs: dict[str, object] = {}      # content_hash -> doc
        self.chunks: dict = {}                 # document_id -> (chunks, embeddings)
        self.backlinks: dict = {}              # chunk_id -> entity_ids
        self.jobs: list[tuple] = []            # (step, status, error)

    async def content_exists(self, content_hash):
        return content_hash in self.docs

    async def upsert_document(self, doc):
        self.docs[doc.content_hash] = doc

    async def replace_chunks(self, document_id, chunks, embeddings):
        if len(chunks) != len(embeddings):
            raise ValueError("length mismatch")
        self.chunks[document_id] = (chunks, embeddings)

    async def record_job(self, job_id, document_id, step, status, error=None):
        self.jobs.append((step, status, error))

    def chunk_id_for(self, document_id, ord):
        import uuid

        return uuid.uuid5(document_id, str(ord))

    async def set_chunk_entities(self, chunk_id, entity_ids):
        self.backlinks[chunk_id] = entity_ids


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
    assert store.jobs[-1] == ("ingest", "done", None)


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
    assert store.jobs[-1][1] == "failed"


async def test_graph_extraction_upserts_and_backlinks(store) -> None:
    extraction_json = (
        '{"entities":[{"name":"GALO","type":"CONCEPT"},{"name":"Neo4j","type":"ORG"}],'
        '"relations":[{"source":"GALO","target":"Neo4j","type":"uses"}]}'
    )
    graph = FakeGraph()
    orch = IngestionOrchestrator(store, FakeGateway(extraction=extraction_json), graph=graph)
    result = await orch.ingest_text("GALO uses Neo4j for structure.")

    assert result.skipped is False
    assert len(graph.upserts) >= 1          # at least one chunk's extraction upserted
    assert store.backlinks                  # entity_ids backlinked onto chunks
    assert store.jobs[-1] == ("ingest", "done", None)


async def test_graph_failure_does_not_fail_ingest(store) -> None:
    extraction_json = '{"entities":[{"name":"X","type":"OTHER"}],"relations":[]}'
    graph = FakeGraph(raise_exc=RuntimeError("neo4j down"))
    orch = IngestionOrchestrator(store, FakeGateway(extraction=extraction_json), graph=graph)
    result = await orch.ingest_text("some text mentioning X")

    # Ingest still succeeds; a 'graph' failed job is recorded alongside.
    assert result.skipped is False
    steps = {(step, status) for step, status, _ in store.jobs}
    assert ("graph", "failed") in steps
    assert ("ingest", "done") in steps
