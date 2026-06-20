"""Retrieval orchestrator tests with stores + gateway stubbed.

Verifies the hybrid path wires together: vector hits seed the graph expansion,
graph chunks are fused in, and the generated answer carries citations. Also
covers the empty-corpus short-circuit.
"""

from __future__ import annotations

import uuid

import pytest

from galo.models.gateway import HealthStatus
from galo.retrieve.orchestrator import RetrievalOrchestrator

DOC = uuid.uuid4()
C1 = uuid.uuid5(uuid.NAMESPACE_OID, "c1")
C2 = uuid.uuid5(uuid.NAMESPACE_OID, "c2")
E1 = uuid.uuid5(uuid.NAMESPACE_OID, "e1")
E2 = uuid.uuid5(uuid.NAMESPACE_OID, "e2")


class FakeGateway:
    def __init__(self) -> None:
        self.gen_prompts: list[str] = []

    async def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def generate(self, prompt, *, system=None):
        self.gen_prompts.append(prompt)
        return "The answer is GALO [1]."

    async def health(self):
        return HealthStatus(ok=True, detail="fake")

    async def aclose(self):
        pass


class FakePool:
    """Stands in for asyncpg pool's .fetch used by seed_entities_from_candidates."""

    def __init__(self, entity_rows) -> None:
        self._entity_rows = entity_rows

    async def fetch(self, sql, *args):
        return self._entity_rows


class FakePg:
    def __init__(self, vector_hits, entity_seed_ids, graph_chunks) -> None:
        self._vector_hits = vector_hits
        self._graph_chunks = graph_chunks
        self.pool = FakePool([{"eid": e} for e in entity_seed_ids])

    async def search_vectors(self, embedding, k):
        return self._vector_hits

    async def chunks_for_entities(self, entity_ids, limit):
        return self._graph_chunks


class FakeGraph:
    def __init__(self, neighbors) -> None:
        self._neighbors = neighbors
        self.expand_called_with = None

    async def expand(self, seed_ids, hops, limit):
        self.expand_called_with = (list(seed_ids), hops)
        return self._neighbors


async def test_hybrid_query_returns_answer_and_citations() -> None:
    pg = FakePg(
        vector_hits=[(C1, DOC, "GALO is a graph aware system", 0.1)],
        entity_seed_ids=[E1],
        graph_chunks=[(C2, DOC, "Neo4j stores structure")],
    )
    graph = FakeGraph(neighbors=[(E2, ["GALO", "Neo4j"])])
    gw = FakeGateway()
    orch = RetrievalOrchestrator(pg, graph, gw, k=10, hops=2)

    result = await orch.query("What is GALO?")

    assert "GALO" in result.answer
    assert result.citations  # at least one citation
    cited_ids = {c.chunk_id for c in result.citations}
    assert C1 in cited_ids and C2 in cited_ids  # both sources fused in
    # graph expansion was seeded from the vector hits' entities
    assert graph.expand_called_with == ([E1], 2)


async def test_empty_corpus_short_circuits() -> None:
    pg = FakePg(vector_hits=[], entity_seed_ids=[], graph_chunks=[])
    graph = FakeGraph(neighbors=[])
    gw = FakeGateway()
    orch = RetrievalOrchestrator(pg, graph, gw)

    result = await orch.query("anything?")
    assert result.citations == []
    assert "don't know" in result.answer.lower()
    assert gw.gen_prompts == []  # no generation when nothing retrieved


async def test_graph_path_carried_into_citation() -> None:
    pg = FakePg(
        vector_hits=[(C1, DOC, "seed chunk", 0.1)],
        entity_seed_ids=[E1],
        graph_chunks=[(C2, DOC, "neighbor chunk")],
    )
    graph = FakeGraph(neighbors=[(E2, ["GALO", "Neo4j"])])
    orch = RetrievalOrchestrator(pg, graph, FakeGateway(), k=10, hops=1)

    result = await orch.query("q")
    c2_cite = next(c for c in result.citations if c.chunk_id == C2)
    assert c2_cite.graph_path == ["GALO", "Neo4j"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
