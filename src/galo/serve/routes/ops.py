"""Operational endpoints: inspect ingestion jobs and corpus stats."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["ops"])


@router.get("/jobs")
async def jobs(request: Request, limit: int = 50) -> dict:
    """Recent ingestion jobs — the provenance/audit trail."""
    pg = request.app.state.pg
    try:
        rows = await pg.recent_jobs(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"jobs query failed: {exc}") from exc
    # serialize uuids/timestamps to strings for JSON
    return {
        "jobs": [
            {
                "id": str(r["id"]),
                "document_id": str(r["document_id"]) if r["document_id"] else None,
                "step": r["step"],
                "status": r["status"],
                "error": r["error"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]
    }


@router.get("/graph")
async def graph(request: Request, limit: int = 300) -> dict:
    """Entity/relationship snapshot for the dashboard visualization."""
    try:
        return await request.app.state.neo4j.graph_snapshot(limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"graph query failed: {exc}") from exc


@router.get("/stats")
async def stats(request: Request) -> dict:
    """Corpus size: chunk count (PG) and entity count (Neo4j)."""
    state = request.app.state
    chunks = entities = None
    try:
        chunks = await state.pg.count_chunks()
    except Exception:  # noqa: BLE001 — report partial stats rather than 502
        pass
    try:
        entities = len(await state.neo4j.all_entities())
    except Exception:  # noqa: BLE001
        pass
    return {"chunks": chunks, "entities": entities}
