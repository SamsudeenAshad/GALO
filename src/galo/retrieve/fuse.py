"""Reciprocal Rank Fusion of the vector and graph candidate lists.

RRF score for a chunk = sum over sources of 1 / (rrf_k + rank). It needs only
ranks, not comparable raw scores, which is exactly right for fusing cosine
distance (vector) with graph hop-distance (graph) — two incomparable scales.
"""

from __future__ import annotations

from galo.retrieve.types import Candidate


def reciprocal_rank_fusion(
    *lists: list[Candidate], rrf_k: int = 60
) -> list[Candidate]:
    """Merge candidate lists by chunk id, summing RRF contributions, and return
    a single list sorted by fused score (desc)."""
    merged: dict = {}  # chunk_id -> Candidate

    for candidates in lists:
        for c in candidates:
            existing = merged.get(c.chunk_id)
            if existing is None:
                existing = Candidate(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    text=c.text,
                )
                merged[c.chunk_id] = existing
            # carry over per-source ranks + provenance
            if c.vector_rank is not None:
                existing.vector_rank = c.vector_rank
            if c.graph_rank is not None:
                existing.graph_rank = c.graph_rank
            if c.graph_path and not existing.graph_path:
                existing.graph_path = c.graph_path

    for c in merged.values():
        score = 0.0
        if c.vector_rank is not None:
            score += 1.0 / (rrf_k + c.vector_rank)
        if c.graph_rank is not None:
            score += 1.0 / (rrf_k + c.graph_rank)
        c.score = score

    return sorted(merged.values(), key=lambda c: c.score, reverse=True)
