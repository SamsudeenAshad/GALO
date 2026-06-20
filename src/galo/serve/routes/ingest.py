"""Ingestion endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from galo.serve.schemas import IngestRequest, IngestResponse

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest, request: Request) -> IngestResponse:
    orchestrator = request.app.state.ingestion
    try:
        result = await orchestrator.ingest_text(
            req.text, title=req.title, source_uri=req.source_uri, force=req.force
        )
    except Exception as exc:  # surface dependency failures as 502, not 500
        raise HTTPException(status_code=502, detail=f"ingestion failed: {exc}") from exc

    return IngestResponse(
        document_id=result.document_id,
        content_hash=result.content_hash,
        chunks=result.chunks,
        skipped=result.skipped,
    )
