"""Query endpoint: GraphRAG Q&A over the ingested corpus."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from galo.serve.schemas import CitationModel, QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest, request: Request) -> QueryResponse:
    orchestrator = request.app.state.retrieval
    try:
        result = await orchestrator.query(req.question)
    except Exception as exc:  # dependency failure → 502, not 500
        raise HTTPException(status_code=502, detail=f"query failed: {exc}") from exc

    return QueryResponse(
        answer=result.answer,
        citations=[
            CitationModel(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                score=c.score,
                graph_path=c.graph_path,
            )
            for c in result.citations
        ],
    )
