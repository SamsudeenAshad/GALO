"""Reconcile job: rebuild the Neo4j graph from Postgres (the source of truth).

Postgres holds canonical chunks; the graph is derived and rebuildable. When the
two drift (a failed graph step during ingest, a model change, a corrupted
graph), reconcile re-extracts entities/relations over every stored chunk and
rewrites the graph + the chunk→entity backlinks from scratch.

Out-of-band only — this re-runs the LLM over the whole corpus.
"""

from __future__ import annotations

from dataclasses import dataclass

from galo.ingest.extract import extract_chunk
from galo.models.gateway import ModelGateway
from galo.stores.neo4j import Neo4jStore
from galo.stores.pg import PgStore


@dataclass(frozen=True)
class ReconcileReport:
    chunks_total: int
    chunks_with_entities: int
    failures: int


async def reconcile(
    pg: PgStore,
    graph: Neo4jStore,
    gateway: ModelGateway,
    *,
    clear_first: bool = True,
) -> ReconcileReport:
    """Rebuild the graph from stored chunks. Returns a summary report.

    Per-chunk failures are counted and skipped rather than aborting the whole
    rebuild, so one bad chunk can't strand the graph half-built.
    """
    if clear_first:
        await graph.clear()

    total = await pg.count_chunks()
    with_entities = 0
    failures = 0

    async for chunk_id, _doc_id, _ord, text in pg.iter_chunks():
        try:
            extraction = await extract_chunk(gateway, text)
            if not extraction.entities:
                # clear any stale backlink so PG matches the rebuilt graph
                await pg.set_chunk_entities(chunk_id, [])
                continue
            await graph.upsert_extraction(chunk_id, extraction)
            await pg.set_chunk_entities(chunk_id, [e.id for e in extraction.entities])
            with_entities += 1
        except Exception:  # noqa: BLE001 — count and continue
            failures += 1

    return ReconcileReport(
        chunks_total=total, chunks_with_entities=with_entities, failures=failures
    )
