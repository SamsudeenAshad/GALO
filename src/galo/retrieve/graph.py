"""Graph retrieval path: seed entities → N-hop expansion → chunks.

v0 seeding strategy: take the entity ids attached to the strongest vector hits
as seeds, then expand the graph from there. This makes a chunk rank because it
is *near an entity the query is about*, even if the chunk itself isn't
semantically similar to the query — the "graph aware" signal.
"""

from __future__ import annotations

import uuid

from galo.retrieve.types import Candidate
from galo.stores.neo4j import Neo4jStore
from galo.stores.pg import PgStore


async def graph_search(
    pg: PgStore,
    graph: Neo4jStore,
    seed_entity_ids: list[uuid.UUID],
    *,
    hops: int,
    k: int,
) -> list[Candidate]:
    """Expand from seed entities and return chunks mentioning the neighbors."""
    if not seed_entity_ids:
        return []

    neighbors = await graph.expand(seed_entity_ids, hops=hops, limit=k * 2)
    if not neighbors:
        return []

    neighbor_ids = [eid for eid, _path in neighbors]
    path_by_entity = {eid: path for eid, path in neighbors}

    chunk_rows = await pg.chunks_for_entities(neighbor_ids, limit=k)
    candidates: list[Candidate] = []
    for rank, (cid, did, text) in enumerate(chunk_rows, start=1):
        candidates.append(
            Candidate(
                chunk_id=cid,
                document_id=did,
                text=text,
                graph_rank=rank,
                # Best-effort provenance: attach a path from one seed neighbor.
                graph_path=next(iter(path_by_entity.values()), []),
            )
        )
    return candidates


async def seed_entities_from_candidates(
    candidates: list[Candidate], pg_pool, *, max_seeds: int
) -> list[uuid.UUID]:
    """Collect entity ids from the chunk rows backing the given candidates."""
    if not candidates:
        return []
    chunk_ids = [c.chunk_id for c in candidates]
    rows = await pg_pool.fetch(
        "SELECT DISTINCT unnest(entity_ids) AS eid FROM chunks WHERE id = ANY($1::uuid[])",
        chunk_ids,
    )
    seeds = [r["eid"] for r in rows if r["eid"] is not None]
    return seeds[:max_seeds]
