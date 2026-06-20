"""Entity resolution tests with a fake graph + gateway."""

from __future__ import annotations

import uuid

from galo.maintain.resolve import resolve_entities
from galo.models.gateway import HealthStatus

NYC = uuid.uuid5(uuid.NAMESPACE_OID, "nyc")
NEWYORK = uuid.uuid5(uuid.NAMESPACE_OID, "newyork")
PARIS = uuid.uuid5(uuid.NAMESPACE_OID, "paris")


class FakeGateway:
    def __init__(self, vectors: dict[str, list[float]], judge: bool = True) -> None:
        self._vectors = vectors
        self._judge = judge

    async def embed(self, texts):
        return [self._vectors[t] for t in texts]

    async def generate(self, prompt, *, system=None):
        return "YES" if self._judge else "NO"

    async def health(self):
        return HealthStatus(ok=True, detail="fake")

    async def aclose(self):
        pass


class FakeGraph:
    def __init__(self, entities) -> None:
        self._entities = entities          # [(id, name, type)]
        self.merges: list[tuple] = []

    async def all_entities(self):
        return self._entities

    async def merge_entities(self, keep, drop):
        self.merges.append((keep, drop))


async def test_merges_near_duplicates_same_type() -> None:
    graph = FakeGraph(
        [(NYC, "NYC", "PLACE"), (NEWYORK, "New York City", "PLACE"), (PARIS, "Paris", "PLACE")]
    )
    gw = FakeGateway(
        {"NYC": [1.0, 0.0], "New York City": [0.99, 0.01], "Paris": [0.0, 1.0]}
    )
    report = await resolve_entities(graph, gw, threshold=0.9)

    assert report.merged == 1
    # canonical = longer name ("New York City") kept, "NYC" dropped
    assert graph.merges == [(NEWYORK, NYC)]


async def test_different_types_never_merge() -> None:
    graph = FakeGraph([(NYC, "Apple", "ORG"), (PARIS, "apple", "OTHER")])
    gw = FakeGateway({"Apple": [1.0, 0.0], "apple": [1.0, 0.0]})
    report = await resolve_entities(graph, gw, threshold=0.5)
    assert report.merged == 0


async def test_dry_run_reports_but_does_not_merge() -> None:
    graph = FakeGraph([(NYC, "NYC", "PLACE"), (NEWYORK, "New York City", "PLACE")])
    gw = FakeGateway({"NYC": [1.0, 0.0], "New York City": [1.0, 0.0]})
    report = await resolve_entities(graph, gw, threshold=0.9, dry_run=True)
    assert report.candidates == 1
    assert report.merged == 0
    assert graph.merges == []


async def test_adjudicator_can_veto_a_merge() -> None:
    graph = FakeGraph([(NYC, "Mercury", "OTHER"), (NEWYORK, "Mercury", "OTHER")])
    gw = FakeGateway(
        {"Mercury": [1.0, 0.0]}, judge=False  # planet vs element: judge says NO
    )
    report = await resolve_entities(graph, gw, threshold=0.9, adjudicate=True)
    assert report.merged == 0
