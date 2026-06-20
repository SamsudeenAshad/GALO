"""Retrieval orchestrator: hybrid retrieve → fuse → assemble → generate.

This is the heart of GALO. It runs the vector path, seeds the graph path from
the vector hits' entities, expands the graph, fuses both with RRF, assembles a
token-budgeted context, and asks the model to answer using only that context —
returning the answer plus citations (chunk → document + graph path).
"""

from __future__ import annotations

from galo.models.gateway import ModelGateway
from galo.retrieve.fuse import reciprocal_rank_fusion
from galo.retrieve.graph import graph_search, seed_entities_from_candidates
from galo.retrieve.types import Candidate, Citation, QueryResult
from galo.retrieve.vector import vector_search
from galo.stores.neo4j import Neo4jStore
from galo.stores.pg import PgStore

_SYSTEM = (
    "You answer questions using ONLY the provided context passages. "
    "Cite passages by their [n] marker. If the context does not contain the "
    "answer, say you don't know. Do not invent facts."
)


class RetrievalOrchestrator:
    def __init__(
        self,
        pg: PgStore,
        graph: Neo4jStore,
        gateway: ModelGateway,
        *,
        k: int = 10,
        hops: int = 2,
        rrf_k: int = 60,
        max_context_chars: int = 6000,
    ) -> None:
        self._pg = pg
        self._graph = graph
        self._gateway = gateway
        self._k = k
        self._hops = hops
        self._rrf_k = rrf_k
        self._max_context_chars = max_context_chars

    async def retrieve(self, query: str) -> list[Candidate]:
        """Hybrid retrieval → fused, ranked candidates (no generation)."""
        vector_hits = await vector_search(self._pg, self._gateway, query, self._k)

        seeds = await seed_entities_from_candidates(
            vector_hits, self._pg.pool, max_seeds=self._k
        )
        graph_hits = await graph_search(
            self._pg, self._graph, seeds, hops=self._hops, k=self._k
        )

        fused = reciprocal_rank_fusion(vector_hits, graph_hits, rrf_k=self._rrf_k)
        return fused[: self._k]

    async def query(self, question: str) -> QueryResult:
        """Full GraphRAG path: retrieve, ground a prompt, generate, cite."""
        candidates = await self.retrieve(question)
        if not candidates:
            return QueryResult(answer="I don't know — no relevant context found.", citations=[])

        context, used = self._assemble_context(candidates)
        prompt = (
            f"Context passages:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer using only the context above, citing passages as [n]."
        )
        answer = await self._gateway.generate(prompt, system=_SYSTEM)

        citations = [
            Citation(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                score=c.score,
                graph_path=c.graph_path,
            )
            for c in used
        ]
        return QueryResult(answer=answer, citations=citations)

    def _assemble_context(self, candidates: list[Candidate]) -> tuple[str, list[Candidate]]:
        """Build a numbered, token-budgeted context block. Returns the text and
        the candidates that actually fit (for citation alignment)."""
        parts: list[str] = []
        used: list[Candidate] = []
        budget = self._max_context_chars
        for i, c in enumerate(candidates, start=1):
            snippet = c.text.strip()
            block = f"[{i}] {snippet}"
            if budget - len(block) < 0 and used:
                break
            parts.append(block)
            used.append(c)
            budget -= len(block)
        return "\n\n".join(parts), used
