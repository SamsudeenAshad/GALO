"""Async Neo4j client (Community Edition).

Owns the driver. Exposes a connectivity ``health`` probe, one-time schema
constraint setup, and the graph-upsert used by ingestion (M2). Traversals for
hybrid retrieval land in M3.
"""

from __future__ import annotations

import uuid

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from galo.ingest.extract import Extraction
from galo.models.gateway import HealthStatus


class Neo4jStore:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self._uri = uri
        self._auth = (user, password)
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(self._uri, auth=self._auth)

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("Neo4jStore not connected; call connect() first")
        return self._driver

    async def health(self) -> HealthStatus:
        try:
            if self._driver is None:
                return HealthStatus(ok=False, detail="driver not initialized")
            await self._driver.verify_connectivity()
            return HealthStatus(ok=True, detail="connected")
        except (ServiceUnavailable, Neo4jError, OSError) as exc:
            return HealthStatus(ok=False, detail=f"unreachable: {exc}")

    # --- schema ---------------------------------------------------------

    async def migrate(self) -> None:
        """Create constraints/indexes. Idempotent (IF NOT EXISTS)."""
        statements = [
            "CREATE CONSTRAINT entity_id IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE e.id IS UNIQUE",
            "CREATE INDEX entity_norm IF NOT EXISTS "
            "FOR (e:Entity) ON (e.normalized_name)",
        ]
        async with self._driver.session() as session:
            for stmt in statements:
                await session.run(stmt)

    # --- ingestion upserts ----------------------------------------------

    async def upsert_extraction(
        self, chunk_id: uuid.UUID, extraction: Extraction
    ) -> None:
        """MERGE entities and relations from one chunk, appending the chunk id to
        each touched entity's ``chunk_ids`` (deduped). Relations carry the
        originating ``chunk_id`` for provenance.

        Runs as a single transaction so a chunk's graph contribution is atomic.
        """
        if not extraction.entities:
            return

        entities = [
            {
                "id": str(e.id),
                "name": e.name,
                "normalized_name": e.normalized_name,
                "type": e.type,
            }
            for e in extraction.entities
        ]
        relations = [
            {"source": str(r.source.id), "target": str(r.target.id), "type": r.type}
            for r in extraction.relations
        ]
        cid = str(chunk_id)

        async with self._driver.session() as session:
            await session.execute_write(
                self._write_extraction, cid, entities, relations
            )

    @staticmethod
    async def _write_extraction(tx, chunk_id, entities, relations) -> None:
        await tx.run(
            """
            UNWIND $entities AS e
            MERGE (n:Entity {id: e.id})
              ON CREATE SET n.name = e.name,
                            n.normalized_name = e.normalized_name,
                            n.type = e.type,
                            n.chunk_ids = [$chunk_id]
              ON MATCH SET  n.chunk_ids =
                            CASE WHEN $chunk_id IN n.chunk_ids
                                 THEN n.chunk_ids
                                 ELSE n.chunk_ids + $chunk_id END
            """,
            entities=entities,
            chunk_id=chunk_id,
        )
        if relations:
            await tx.run(
                """
                UNWIND $relations AS r
                MATCH (s:Entity {id: r.source})
                MATCH (t:Entity {id: r.target})
                MERGE (s)-[rel:RELATED {type: r.type}]->(t)
                  ON CREATE SET rel.chunk_id = $chunk_id, rel.weight = 1
                  ON MATCH SET  rel.weight = coalesce(rel.weight, 1) + 1
                """,
                relations=relations,
                chunk_id=chunk_id,
            )

    async def aclose(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
