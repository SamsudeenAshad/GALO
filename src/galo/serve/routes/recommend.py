"""Recommendation + learning-path endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from galo.retrieve.path import learning_path
from galo.retrieve.recommend import recommend
from galo.serve.schemas import (
    PathRequest,
    PathResponse,
    PathStepModel,
    RecommendationModel,
    RecommendRequest,
    RecommendResponse,
)

router = APIRouter(tags=["platform"])


@router.post("/recommend", response_model=RecommendResponse)
async def recommend_route(req: RecommendRequest, request: Request) -> RecommendResponse:
    state = request.app.state
    try:
        recs = await recommend(
            state.neo4j, state.gateway, req.entity, k=req.k, alpha=req.alpha
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"recommend failed: {exc}") from exc

    return RecommendResponse(
        seed_found=bool(recs) or await _seed_exists(state.neo4j, req.entity),
        recommendations=[
            RecommendationModel(
                entity_id=r.entity_id,
                name=r.name,
                graph_weight=r.graph_weight,
                similarity=r.similarity,
                score=r.score,
            )
            for r in recs
        ],
    )


@router.post("/path", response_model=PathResponse)
async def path_route(req: PathRequest, request: Request) -> PathResponse:
    state = request.app.state
    try:
        result = await learning_path(state.neo4j, req.from_concept, req.to_concept)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"path failed: {exc}") from exc

    return PathResponse(
        found=result.found,
        steps=[PathStepModel(entity_id=s.entity_id, name=s.name) for s in result.steps],
        reason=result.reason,
    )


async def _seed_exists(graph, name: str) -> bool:
    """Distinguish 'seed not in graph' from 'seed has no neighbors' for the
    seed_found flag."""
    return await graph.find_entity(name) is not None
