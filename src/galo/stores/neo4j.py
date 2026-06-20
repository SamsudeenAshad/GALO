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

    # --- retrieval traversal --------------------------------------------

    async def expand(
        self, seed_ids: list[uuid.UUID], hops: int, limit: int
    ) -> list[tuple[uuid.UUID, list[str]]]:
        """From seed entities, walk up to ``hops`` :RELATED hops and return the
        reachable entities (excluding seeds) as ``(entity_id, path_names)``.

        ``path_names`` is the entity-name sequence from a seed to the neighbor,
        kept for provenance. Distance-ordered (closer neighbors first).
        """
        if not seed_ids or hops < 1:
            return []
        seeds = [str(s) for s in seed_ids]
        # Variable-length undirected expansion. Cap hops via the pattern length;
        # `hops` is interpolated (validated int) since Cypher can't parameterize
        # a path length bound.
        cypher = (
            "MATCH (s:Entity) WHERE s.id IN $seeds "
            f"MATCH path = (s)-[:RELATED*1..{int(hops)}]-(n:Entity) "
            "WHERE NOT n.id IN $seeds "
            "WITH n, min(length(path)) AS dist, "
            "     head(collect([x IN nodes(path) | x.name])) AS names "
            "RETURN n.id AS id, dist, names "
            "ORDER BY dist ASC LIMIT $limit"
        )
        async with self._driver.session() as session:
            result = await session.run(cypher, seeds=seeds, limit=limit)
            out: list[tuple[uuid.UUID, list[str]]] = []
            async for rec in result:
                out.append((uuid.UUID(rec["id"]), list(rec["names"])))
            return out

    async def all_entities(self) -> list[tuple[uuid.UUID, str, str]]:
        """Every entity as ``(id, name, type)`` — used by entity resolution to
        find merge candidates. Fine at v0 scale; paginate when the graph grows."""
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (e:Entity) RETURN e.id AS id, e.name AS name, e.type AS type"
            )
            return [
                (uuid.UUID(rec["id"]), rec["name"], rec["type"]) async for rec in result
            ]

    async def merge_entities(self, keep: uuid.UUID, drop: uuid.UUID) -> None:
        """Fold entity ``drop`` into ``keep``: move its relationships and union
        its ``chunk_ids`` onto ``keep``, then delete ``drop``.

        Idempotent-ish: a no-op if either node is already gone. Relationships are
        rewired by recreating :RELATED edges on ``keep`` (Community Edition has no
        APOC), preserving type and summing weight.
        """
        if keep == drop:
            return
        async with self._driver.session() as session:
            await session.execute_write(self._merge_entities_tx, str(keep), str(drop))

    @staticmethod
    async def _merge_entities_tx(tx, keep: str, drop: str) -> None:
        # 1. union chunk_ids (APOC-free list union via reduce)
        await tx.run(
            """
            MATCH (k:Entity {id: $keep}), (d:Entity {id: $drop})
            SET k.chunk_ids = reduce(
                acc = coalesce(k.chunk_ids, []),
                x IN coalesce(d.chunk_ids, []) |
                CASE WHEN x IN acc THEN acc ELSE acc + x END
            )
            """,
            keep=keep,
            drop=drop,
        )
        # 2. rewire outgoing edges of drop onto keep
        await tx.run(
            """
            MATCH (d:Entity {id: $drop})-[r:RELATED]->(o:Entity)
            WHERE o.id <> $keep
            MATCH (k:Entity {id: $keep})
            MERGE (k)-[nr:RELATED {type: r.type}]->(o)
              ON CREATE SET nr.weight = coalesce(r.weight, 1), nr.chunk_id = r.chunk_id
              ON MATCH SET  nr.weight = coalesce(nr.weight, 1) + coalesce(r.weight, 1)
            """,
            keep=keep,
            drop=drop,
        )
        # 3. rewire incoming edges of drop onto keep
        await tx.run(
            """
            MATCH (o:Entity)-[r:RELATED]->(d:Entity {id: $drop})
            WHERE o.id <> $keep
            MATCH (k:Entity {id: $keep})
            MERGE (o)-[nr:RELATED {type: r.type}]->(k)
              ON CREATE SET nr.weight = coalesce(r.weight, 1), nr.chunk_id = r.chunk_id
              ON MATCH SET  nr.weight = coalesce(nr.weight, 1) + coalesce(r.weight, 1)
            """,
            keep=keep,
            drop=drop,
        )
        # 4. delete the dropped node and its now-redundant edges
        await tx.run("MATCH (d:Entity {id: $drop}) DETACH DELETE d", drop=drop)

    async def set_prerequisite(self, before: uuid.UUID, after: uuid.UUID) -> None:
        """Author a curriculum edge: ``before`` is a prerequisite of ``after``.

        v0 the curriculum layer is hand-authored via this method (see
        ARCHITECTURE.md §10 open question). Both entities must already exist.
        """
        async with self._driver.session() as session:
            await session.run(
                """
                MATCH (b:Entity {id: $before}), (a:Entity {id: $after})
                MERGE (b)-[:PREREQUISITE]->(a)
                """,
                before=str(before),
                after=str(after),
            )

    async def find_entity(self, name: str) -> uuid.UUID | None:
        """Resolve an entity id by (normalized) name. Exact match, v0."""
        norm = " ".join(name.lower().split())
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (e:Entity {normalized_name: $norm}) RETURN e.id AS id LIMIT 1",
                norm=norm,
            )
            rec = await result.single()
            return uuid.UUID(rec["id"]) if rec else None

    async def neighbors(
        self, entity_id: uuid.UUID, *, limit: int
    ) -> list[tuple[uuid.UUID, str, float]]:
        """Direct :RELATED neighbors of an entity, by descending edge weight.

        Returns ``(neighbor_id, neighbor_name, weight)``.
        """
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (e:Entity {id: $id})-[r:RELATED]-(n:Entity)
                RETURN n.id AS id, n.name AS name,
                       coalesce(r.weight, 1) AS weight
                ORDER BY weight DESC
                LIMIT $limit
                """,
                id=str(entity_id),
                limit=limit,
            )
            return [
                (uuid.UUID(rec["id"]), rec["name"], float(rec["weight"]))
                async for rec in result
            ]

    async def prerequisite_path(
        self, source_id: uuid.UUID, target_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, str]] | None:
        """Shortest directed :PREREQUISITE path source→target, as an ordered
        list of ``(entity_id, name)``. None if no path exists.
        """
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (s:Entity {id: $s}), (t:Entity {id: $t}),
                      p = shortestPath((s)-[:PREREQUISITE*..15]->(t))
                RETURN [x IN nodes(p) | [x.id, x.name]] AS steps
                """,
                s=str(source_id),
                t=str(target_id),
            )
            rec = await result.single()
            if not rec:
                return None
            return [(uuid.UUID(sid), name) for sid, name in rec["steps"]]

    async def aclose(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
