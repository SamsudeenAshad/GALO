"""Serve the single-page dashboard at the app root (same-origin → no CORS)."""

from __future__ import annotations

from importlib import resources

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"], include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    html = resources.files("galo.serve.static").joinpath("dashboard.html").read_text()
    return HTMLResponse(html)
