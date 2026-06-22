"""Serve the single-page dashboard at the app root (same-origin → no CORS)."""

from __future__ import annotations

from importlib import resources

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"], include_in_schema=False)


def _static(name: str) -> str:
    return resources.files("galo.serve.static").joinpath(name).read_text()


@router.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(_static("dashboard.html"))


@router.get("/graph-view", response_class=HTMLResponse)
async def graph_view() -> HTMLResponse:
    """Standalone full-page knowledge-graph explorer."""
    return HTMLResponse(_static("graph.html"))
