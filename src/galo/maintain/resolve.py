"""Entity resolution v1: merge near-duplicate entities.

v0 (in extraction) already collapses entities sharing a normalized name. v1
catches the harder cases ("NYC" ≈ "New York City") via embedding similarity:

  1. Embed all entity names.
  2. Block candidate pairs within the same type whose name embeddings exceed a
     cosine threshold.
  3. Optionally adjudicate each candidate pair with the LLM (yes/no), to avoid
     false merges; threshold-only when ``adjudicate=False``.
  4. Union-find the surviving pairs into clusters; merge each cluster into one
     canonical node (the longest name — usually the most explicit surface form).

This is an out-of-band maintenance job, not on the request path.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from galo.models.gateway import ModelGateway, Vector
from galo.stores.neo4j import Neo4jStore


@dataclass(frozen=True)
class MergePair:
    keep: uuid.UUID
    drop: uuid.UUID
    keep_name: str
    drop_name: str
    similarity: float


@dataclass(frozen=True)
class ResolveReport:
    candidates: int
    merged: int
    pairs: list[MergePair]


def _cosine(a: Vector, b: Vector) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class _UnionFind:
    def __init__(self, ids: list[uuid.UUID]) -> None:
        self._parent = {i: i for i in ids}

    def find(self, x: uuid.UUID) -> uuid.UUID:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: uuid.UUID, b: uuid.UUID) -> None:
        self._parent[self.find(a)] = self.find(b)

    def clusters(self) -> dict[uuid.UUID, list[uuid.UUID]]:
        out: dict[uuid.UUID, list[uuid.UUID]] = {}
        for x in self._parent:
            out.setdefault(self.find(x), []).append(x)
        return out


async def _adjudicate(gateway: ModelGateway, a: str, b: str) -> bool:
    raw = await gateway.generate(
        f'Do "{a}" and "{b}" refer to the same real-world entity? '
        'Answer with only YES or NO.',
        system="You are a strict entity-resolution judge. Answer YES only when "
        "confident the two names denote the same entity.",
    )
    return raw.strip().upper().startswith("YES")


async def resolve_entities(
    graph: Neo4jStore,
    gateway: ModelGateway,
    *,
    threshold: float = 0.92,
    adjudicate: bool = False,
    dry_run: bool = False,
) -> ResolveReport:
    """Find and (unless ``dry_run``) merge near-duplicate entities."""
    entities = await graph.all_entities()
    if len(entities) < 2:
        return ResolveReport(candidates=0, merged=0, pairs=[])

    ids = [eid for eid, _n, _t in entities]
    names = [n for _id, n, _t in entities]
    types = [t for _id, _n, t in entities]
    vectors = await gateway.embed(names)

    by_index = {i: (ids[i], names[i]) for i in range(len(ids))}
    candidates: list[MergePair] = []

    # O(n^2) blocking within same type — fine at v0 scale.
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if types[i] != types[j]:
                continue
            sim = _cosine(vectors[i], vectors[j])
            if sim < threshold:
                continue
            if adjudicate and not await _adjudicate(gateway, names[i], names[j]):
                continue
            # keep the longer (more explicit) name as canonical
            (ki, kj) = (i, j) if len(names[i]) >= len(names[j]) else (j, i)
            candidates.append(
                MergePair(
                    keep=by_index[ki][0],
                    drop=by_index[kj][0],
                    keep_name=by_index[ki][1],
                    drop_name=by_index[kj][1],
                    similarity=sim,
                )
            )

    if dry_run or not candidates:
        return ResolveReport(candidates=len(candidates), merged=0, pairs=candidates)

    # Cluster transitive matches, then merge each cluster into one canonical id.
    uf = _UnionFind(ids)
    for p in candidates:
        uf.union(p.keep, p.drop)

    name_by_id = {ids[i]: names[i] for i in range(len(ids))}
    merged = 0
    for members in uf.clusters().values():
        if len(members) < 2:
            continue
        canonical = max(members, key=lambda m: len(name_by_id[m]))
        for m in members:
            if m == canonical:
                continue
            await graph.merge_entities(canonical, m)
            merged += 1

    return ResolveReport(candidates=len(candidates), merged=merged, pairs=candidates)
