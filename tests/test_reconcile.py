"""Reconcile job tests with fakes for PG, graph, and gateway."""

from __future__ import annotations

import uuid

from galo.maintain.reconcile import reconcile
from galo.models.gateway import HealthStatus

DOC = uuid.uuid4()


class FakeGateway:
    def __init__(self, by_text: dict[str, str], raise_on: str | None = None) -> None:
        self._by_text = by_text
        self._raise_on = raise_on

    async def embed(self, texts):
        return [[0.0] for _ in texts]

    async def generate(self, prompt, *, system=None):
        # extraction prompt embeds the chunk text; find which chunk it is
        for text, out in self._by_text.items():
            if text in prompt:
                if text == self._raise_on:
                    raise RuntimeError("model error")
                return out
        return '{"entities":[],"relations":[]}'

    async def health(self):
        return HealthStatus(ok=True, detail="fake")

    async def aclose(self):
        pass


class FakePg:
    def __init__(self, chunks) -> None:
        self._chunks = chunks      # [(id, doc, ord, text)]
        self.backlinks: dict = {}

    async def count_chunks(self):
        return len(self._chunks)

    async def iter_chunks(self, batch_size=200):
        for row in self._chunks:
            yield row

    async def set_chunk_entities(self, chunk_id, entity_ids):
        self.backlinks[chunk_id] = entity_ids


class FakeGraph:
    def __init__(self) -> None:
        self.cleared = False
        self.upserts: list = []

    async def clear(self):
        self.cleared = True

    async def upsert_extraction(self, chunk_id, extraction):
        self.upserts.append((chunk_id, extraction))


C1 = uuid.uuid5(uuid.NAMESPACE_OID, "c1")
C2 = uuid.uuid5(uuid.NAMESPACE_OID, "c2")


async def test_reconcile_rebuilds_from_chunks() -> None:
    pg = FakePg([(C1, DOC, 0, "alpha text"), (C2, DOC, 1, "beta text")])
    graph = FakeGraph()
    gw = FakeGateway(
        {
            "alpha text": '{"entities":[{"name":"Alpha","type":"OTHER"}],"relations":[]}',
            "beta text": '{"entities":[],"relations":[]}',
        }
    )
    report = await reconcile(pg, graph, gw)

    assert graph.cleared is True
    assert report.chunks_total == 2
    assert report.chunks_with_entities == 1
    assert report.failures == 0
    assert len(graph.upserts) == 1
    assert pg.backlinks[C2] == []          # empty backlink cleared for chunk 2


async def test_reconcile_counts_failures_and_continues() -> None:
    pg = FakePg([(C1, DOC, 0, "boom text"), (C2, DOC, 1, "ok text")])
    graph = FakeGraph()
    gw = FakeGateway(
        {
            "boom text": "x",
            "ok text": '{"entities":[{"name":"Ok","type":"OTHER"}],"relations":[]}',
        },
        raise_on="boom text",
    )
    report = await reconcile(pg, graph, gw)
    assert report.failures == 1
    assert report.chunks_with_entities == 1   # the good chunk still processed
