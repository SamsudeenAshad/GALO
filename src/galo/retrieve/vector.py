"""Vector retrieval path: embed the query, ANN-search pgvector."""

from __future__ import annotations

from galo.models.gateway import ModelGateway
from galo.retrieve.types import Candidate
from galo.stores.pg import PgStore


async def vector_search(
    store: PgStore, gateway: ModelGateway, query: str, k: int
) -> list[Candidate]:
    """Return up to ``k`` candidates ranked by semantic similarity."""
    embedding = (await gateway.embed([query]))[0]
    hits = await store.search_vectors(embedding, k)
    return [
        Candidate(
            chunk_id=cid,
            document_id=did,
            text=text,
            vector_rank=rank,  # 1-based
        )
        for rank, (cid, did, text, _dist) in enumerate(hits, start=1)
    ]
