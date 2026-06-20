"""Tests for /recommend and /path logic with the graph + gateway stubbed."""

from __future__ import annotations

import uuid

from galo.models.gateway import HealthStatus
from galo.retrieve.path import learning_path
from galo.retrieve.recommend import recommend

SEED = uuid.uuid5(uuid.NAMESPACE_OID, "seed")
N1 = uuid.uuid5(uuid.NAMESPACE_OID, "n1")
N2 = uuid.uuid5(uuid.NAMESPACE_OID, "n2")
A = uuid.uuid5(uuid.NAMESPACE_OID, "A")
B = uuid.uuid5(uuid.NAMESPACE_OID, "B")
C = uuid.uuid5(uuid.NAMESPACE_OID, "C")


class FakeGateway:
    """Returns hand-picked vectors keyed by text so similarity is predictable."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    async def embed(self, texts):
        return [self._vectors[t] for t in texts]

    async def generate(self, prompt, *, system=None):
        return ""

    async def health(self):
        return HealthStatus(ok=True, detail="fake")

    async def aclose(self):
        pass


class FakeGraph:
    def __init__(self, entities=None, neighbors=None, path=None) -> None:
        self._entities = entities or {}        # normalized name -> id
        self._neighbors = neighbors or []      # [(id, name, weight)]
        self._path = path                      # [(id, name)] or None

    async def find_entity(self, name):
        return self._entities.get(" ".join(name.lower().split()))

    async def neighbors(self, entity_id, *, limit):
        return self._neighbors[:limit]

    async def prerequisite_path(self, source_id, target_id):
        return self._path


# --- recommend ---------------------------------------------------------


async def test_recommend_blends_similarity_and_weight() -> None:
    graph = FakeGraph(
        entities={"seed": SEED},
        neighbors=[(N1, "near", 1.0), (N2, "far", 10.0)],
    )
    # N1 is semantically identical to seed; N2 is orthogonal but high weight.
    gw = FakeGateway(
        {"seed": [1.0, 0.0], "near": [1.0, 0.0], "far": [0.0, 1.0]}
    )
    # alpha=1 → pure semantic: N1 (sim=1) beats N2 (sim=0) despite weight.
    recs = await recommend(graph, gw, "seed", k=2, alpha=1.0)
    assert recs[0].entity_id == N1

    # alpha=0 → pure graph: N2 (weight 10) wins.
    recs = await recommend(graph, gw, "seed", k=2, alpha=0.0)
    assert recs[0].entity_id == N2


async def test_recommend_unknown_seed_returns_empty() -> None:
    graph = FakeGraph(entities={})
    gw = FakeGateway({})
    assert await recommend(graph, gw, "ghost", k=5) == []


# --- path --------------------------------------------------------------


async def test_path_found() -> None:
    graph = FakeGraph(
        entities={"a": A, "c": C},
        path=[(A, "A"), (B, "B"), (C, "C")],
    )
    result = await learning_path(graph, "A", "C")
    assert result.found
    assert [s.name for s in result.steps] == ["A", "B", "C"]


async def test_path_unknown_concept() -> None:
    graph = FakeGraph(entities={"a": A})
    result = await learning_path(graph, "A", "Nope")
    assert not result.found
    assert "unknown concept" in result.reason


async def test_path_no_route() -> None:
    graph = FakeGraph(entities={"a": A, "c": C}, path=None)
    result = await learning_path(graph, "A", "C")
    assert not result.found
    assert "no prerequisite path" in result.reason


async def test_path_same_concept_is_trivial() -> None:
    graph = FakeGraph(entities={"a": A})
    result = await learning_path(graph, "A", "A")
    assert result.found
    assert len(result.steps) == 1
