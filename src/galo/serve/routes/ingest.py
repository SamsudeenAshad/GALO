"""Ingestion endpoints: raw text and file upload."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from galo.ingest.parse import UnsupportedFileType, parse_document
from galo.serve.schemas import IngestRequest, IngestResponse

router = APIRouter(tags=["ingest"])


def _to_response(result) -> IngestResponse:
    return IngestResponse(
        document_id=result.document_id,
        content_hash=result.content_hash,
        chunks=result.chunks,
        skipped=result.skipped,
    )


@router.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest, request: Request) -> IngestResponse:
    orchestrator = request.app.state.ingestion
    try:
        result = await orchestrator.ingest_text(
            req.text, title=req.title, source_uri=req.source_uri, force=req.force
        )
    except Exception as exc:  # surface dependency failures as 502, not 500
        raise HTTPException(status_code=502, detail=f"ingestion failed: {exc}") from exc
    return _to_response(result)


@router.post("/ingest/file", response_model=IngestResponse)
async def ingest_file(
    request: Request,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    force: bool = Form(False),
) -> IngestResponse:
    """Upload a document (PDF, DOCX, MD/TXT) → parse locally → ingest."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty file")
    try:
        text = parse_document(file.filename or "", data)
    except UnsupportedFileType as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    orchestrator = request.app.state.ingestion
    try:
        result = await orchestrator.ingest_text(
            text,
            title=title or file.filename,
            source_uri=file.filename,
            force=force,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ingestion failed: {exc}") from exc
    return _to_response(result)
