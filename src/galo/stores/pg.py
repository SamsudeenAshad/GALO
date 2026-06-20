"""Async Postgres + pgvector client.

Owns the connection pool. In M0 it only exposes a ``ping`` (and a check that the
``vector`` extension is present); ingestion/retrieval queries land in later
milestones.
"""

from __future__ import annotations

import asyncpg

from galo.models.gateway import HealthStatus


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

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
