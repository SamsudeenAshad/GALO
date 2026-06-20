"""Ingestion orchestrator: load → chunk → embed → persist.

Idempotent per content hash: identical content re-ingested is a no-op (unless
``force=True``). This is the only place in M1 that touches both the model
gateway and the store together.
"""

from __future__ import annotations

import uuid

from galo.ingest.chunker import chunk_text
from galo.ingest.extract import extract_chunk
from galo.ingest.loader import load_bytes, load_text
from galo.ingest.types import IngestResult
from galo.models.gateway import ModelGateway
from galo.stores.neo4j import Neo4jStore
from galo.stores.pg import PgStore


class IngestionOrchestrator:
    def __init__(
        self,
        store: PgStore,
        gateway: ModelGateway,
        *,
        graph: Neo4jStore | None = None,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._graph = graph
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def ingest_text(
        self,
        text: str,
        *,
        title: str | None = None,
        source_uri: str | None = None,
        force: bool = False,
    ) -> IngestResult:
        doc = load_text(text, title=title, source_uri=source_uri)
        return await self._run(doc, force=force)

    async def ingest_bytes(
        self,
        data: bytes,
        *,
        title: str | None = None,
        source_uri: str | None = None,
        force: bool = False,
    ) -> IngestResult:
        doc = load_bytes(data, title=title, source_uri=source_uri)
        return await self._run(doc, force=force)

    async def _run(self, doc, *, force: bool) -> IngestResult:
        job_id = uuid.uuid5(doc.id, "ingest")

        if not force and await self._store.content_exists(doc.content_hash):
            await self._store.record_job(job_id, doc.id, "ingest", "done", "skipped (exists)")
            return IngestResult(doc.id, doc.content_hash, chunks=0, skipped=True)

        try:
            await self._store.record_job(job_id, doc.id, "ingest", "running")
            await self._store.upsert_document(doc)

            chunks = chunk_text(
                doc.text, size=self._chunk_size, overlap=self._chunk_overlap
            )
            embeddings = (
                await self._gateway.embed([c.text for c in chunks]) if chunks else []
            )
            await self._store.replace_chunks(doc.id, chunks, embeddings)

            # Graph extraction is best-effort: Postgres is the source of truth and
            # the graph is rebuildable, so a graph failure must not fail ingest.
            if self._graph is not None and chunks:
                await self._extract_graph(doc.id, chunks, job_id)

            await self._store.record_job(job_id, doc.id, "ingest", "done")
            return IngestResult(doc.id, doc.content_hash, chunks=len(chunks), skipped=False)
        except Exception as exc:  # noqa: BLE001 — record then re-raise for the caller
            await self._store.record_job(job_id, doc.id, "ingest", "failed", str(exc))
            raise

    async def _extract_graph(self, document_id, chunks, job_id) -> None:
        """Extract entities/relations per chunk → Neo4j, and write the
        chunk→entity backlink in Postgres. Best-effort: a failure is recorded
        on the job but does not abort ingestion."""
        try:
            for chunk in chunks:
                chunk_id = self._store.chunk_id_for(document_id, chunk.ord)
                extraction = await extract_chunk(self._gateway, chunk.text)
                if not extraction.entities:
                    continue
                await self._graph.upsert_extraction(chunk_id, extraction)
                entity_ids = [e.id for e in extraction.entities]
                await self._store.set_chunk_entities(chunk_id, entity_ids)
        except Exception as exc:  # noqa: BLE001
            await self._store.record_job(
                job_id, document_id, "graph", "failed", str(exc)
            )
