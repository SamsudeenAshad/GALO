"""Async Postgres + pgvector client.

Owns the connection pool. In M0 it only exposes a ``ping`` (and a check that the
``vector`` extension is present); ingestion/retrieval queries land in later
milestones.
"""

from __future__ import annotations

import uuid
from importlib import resources

import asyncpg

from galo.ingest.chunker import Chunk
from galo.ingest.loader import LoadedDocument
from galo.models.gateway import HealthStatus, Vector


def _vector_literal(vec: Vector) -> str:
    """Render an embedding as a pgvector text literal: ``[0.1,0.2,...]``."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


class PgStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=10)

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PgStore not connected; call connect() first")
        return self._pool

    async def health(self) -> HealthStatus:
        try:
            if self._pool is None:
                return HealthStatus(ok=False, detail="unreachable: pool not initialized (connect failed at startup)")
            async with self._pool.acquire() as conn:
                await conn.execute("SELECT 1")
                has_vector = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                )
            if not has_vector:
                return HealthStatus(ok=False, detail="pgvector extension not installed")
            return HealthStatus(ok=True, detail="connected; pgvector present")
        except (asyncpg.PostgresError, OSError) as exc:
            return HealthStatus(ok=False, detail=f"unreachable: {exc}")

    # --- schema ---------------------------------------------------------

    async def migrate(self, embed_dim: int) -> None:
        """Apply the schema, substituting the embedding dimension. Idempotent
        (all DDL is ``IF NOT EXISTS``)."""
        sql = resources.files("galo.stores").joinpath("schema.sql").read_text()
        sql = sql.replace("{EMBED_DIM}", str(int(embed_dim)))
        async with self.pool.acquire() as conn:
            await conn.execute(sql)

    # --- ingestion persistence ------------------------------------------

    async def content_exists(self, content_hash: str) -> bool:
        row = await self.pool.fetchval(
            "SELECT 1 FROM documents WHERE content_hash = $1", content_hash
        )
        return row is not None

    async def upsert_document(self, doc: LoadedDocument) -> None:
        await self.pool.execute(
            """
            INSERT INTO documents (id, title, source_uri, content_hash)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (content_hash) DO UPDATE
              SET title = EXCLUDED.title, source_uri = EXCLUDED.source_uri
            """,
            doc.id,
            doc.title,
            doc.source_uri,
            doc.content_hash,
        )

    async def replace_chunks(
        self, document_id: uuid.UUID, chunks: list[Chunk], embeddings: list[Vector]
    ) -> None:
        """Atomically replace a document's chunks with new (text, embedding)
        rows. Deterministic ids per (document, ord) keep re-ingest idempotent."""
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM chunks WHERE document_id = $1", document_id)
            await conn.executemany(
                """
                INSERT INTO chunks (id, document_id, ord, text, embedding)
                VALUES ($1, $2, $3, $4, $5::vector)
                """,
                [
                    (
                        uuid.uuid5(document_id, str(c.ord)),
                        document_id,
                        c.ord,
                        c.text,
                        _vector_literal(emb),
                    )
                    for c, emb in zip(chunks, embeddings, strict=True)
                ],
            )

    async def record_job(
        self,
        job_id: uuid.UUID,
        document_id: uuid.UUID | None,
        step: str,
        status: str,
        error: str | None = None,
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO jobs (id, document_id, step, status, error, updated_at)
            VALUES ($1, $2, $3, $4, $5, now())
            ON CONFLICT (id) DO UPDATE
              SET step = EXCLUDED.step, status = EXCLUDED.status,
                  error = EXCLUDED.error, updated_at = now()
            """,
            job_id,
            document_id,
            step,
            status,
            error,
        )

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
