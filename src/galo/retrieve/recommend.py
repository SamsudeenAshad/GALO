"""Recommendation: graph neighborhood ∩ semantic similarity.

Given a seed entity, take its graph neighbors (structural signal: co-occurrence
weight) and re-rank them by embedding similarity between the seed's text and the
neighbor's text. The blend is what makes a recommendation more than either a
pure graph walk or a pure vector lookup.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from galo.models.gateway import ModelGateway, Vector
from galo.stores.neo4j import Neo4jStore


@dataclass(frozen=True)
class Recommendation:
    entity_id: uuid.UUID
    name: str
    graph_weight: float
    similarity: float
    score: float


def _cosine(a: Vector, b: Vector) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def recommend(
    graph: Neo4jStore,
    gateway: ModelGateway,
    seed_name: str,
    *,
    k: int,
    alpha: float = 0.5,
) -> list[Recommendation]:
    """Recommend entities related to ``seed_name``.

    ``alpha`` blends the two signals: ``score = alpha*similarity +
    (1-alpha)*normalized_graph_weight``. alpha=1 → pure semantic, 0 → pure graph.
    Returns [] if the seed isn't in the graph.
    """
    seed_id = await graph.find_entity(seed_name)
    if seed_id is None:
        return []

    neighbors = await graph.neighbors(seed_id, limit=k * 3)
    if not neighbors:
        return []

    # Embed seed + neighbor names together (one batch) for similarity.
    names = [seed_name] + [name for _id, name, _w in neighbors]
    vectors = await gateway.embed(names)
    seed_vec, neighbor_vecs = vectors[0], vectors[1:]

    max_weight = max(w for _id, _name, w in neighbors) or 1.0

    recs: list[Recommendation] = []
    for (eid, name, weight), nvec in zip(neighbors, neighbor_vecs, strict=True):
        sim = _cosine(seed_vec, nvec)
        norm_w = weight / max_weight
        score = alpha * sim + (1.0 - alpha) * norm_w
        recs.append(
            Recommendation(
                entity_id=eid,
                name=name,
                graph_weight=weight,
                similarity=sim,
                score=score,
            )
        )

    recs.sort(key=lambda r: r.score, reverse=True)
    return recs[:k]
