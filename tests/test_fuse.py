"""RRF fusion tests — pure."""

from __future__ import annotations

import uuid

from galo.retrieve.fuse import reciprocal_rank_fusion
from galo.retrieve.types import Candidate

D = uuid.uuid4()


def _c(n: int, *, vr=None, gr=None, path=None) -> Candidate:
    return Candidate(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_OID, str(n)),
        document_id=D,
        text=f"chunk {n}",
        vector_rank=vr,
        graph_rank=gr,
        graph_path=path or [],
    )


def test_chunk_in_both_lists_outranks_single_source() -> None:
    both = _c(1, vr=3)
    vec_only = _c(2, vr=1)
    fused = reciprocal_rank_fusion([both, vec_only], [_c(1, gr=5)], rrf_k=60)
    # chunk 1 appears in both sources; even at worse individual ranks the summed
    # RRF can lift it above a single-source top hit.
    by_id = {c.chunk_id: c for c in fused}
    assert by_id[_c(1).chunk_id].score > by_id[_c(2).chunk_id].score


def test_merge_preserves_both_ranks_and_path() -> None:
    fused = reciprocal_rank_fusion(
        [_c(1, vr=2)], [_c(1, gr=4, path=["A", "B"])], rrf_k=60
    )
    assert len(fused) == 1
    c = fused[0]
    assert c.vector_rank == 2 and c.graph_rank == 4
    assert c.graph_path == ["A", "B"]


def test_sorted_descending_by_score() -> None:
    fused = reciprocal_rank_fusion(
        [_c(1, vr=1), _c(2, vr=2), _c(3, vr=3)], rrf_k=10
    )
    scores = [c.score for c in fused]
    assert scores == sorted(scores, reverse=True)


def test_graph_only_candidate_is_included() -> None:
    fused = reciprocal_rank_fusion([], [_c(9, gr=1, path=["X"])], rrf_k=60)
    assert len(fused) == 1
    assert fused[0].graph_rank == 1
    assert fused[0].score > 0
