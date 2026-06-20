"""Ingestion orchestrator: load → chunk → embed → persist.

Idempotent per content hash: identical content re-ingested is a no-op (unless
``force=True``). This is the only place in M1 that touches both the model
gateway and the store together.
"""

from __future__ import annotations

import uuid

from galo.ingest.chunker import chunk_text
from galo.ingest.loader import load_bytes, load_text
from galo.ingest.types import IngestResult
from galo.models.gateway import ModelGateway
from galo.stores.pg import PgStore


class IngestionOrchestrator:
    def __init__(
        self,
        store: PgStore,
        gateway: ModelGateway,
        *,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
    ) -> None:
        self._store = store
        self._gateway = gateway
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

            await self._store.record_job(job_id, doc.id, "ingest", "done")
            return IngestResult(doc.id, doc.content_hash, chunks=len(chunks), skipped=False)
        except Exception as exc:  # noqa: BLE001 — record then re-raise for the caller
            await self._store.record_job(job_id, doc.id, "ingest", "failed", str(exc))
            raise
