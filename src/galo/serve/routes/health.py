"""Health endpoint: liveness + per-dependency probes.

Probes all three dependencies concurrently. Returns HTTP 200 when the process is
alive regardless of dependency state (this is a status report, not a gate); the
per-dependency ``ok`` flags and the top-level ``status`` convey health. Use a
load balancer / orchestrator readiness check on ``status == "ok"`` if desired.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from galo.models.gateway import HealthStatus

router = APIRouter(tags=["ops"])


@router.get("/health")
async def health(request: Request) -> dict:
    state = request.app.state
    names = ("ollama", "postgres", "neo4j")
    probes = (state.gateway.health(), state.pg.health(), state.neo4j.health())

    results = await asyncio.gather(*probes, return_exceptions=True)

    deps: dict[str, dict] = {}
    all_ok = True
    for name, result in zip(names, results, strict=True):
        if isinstance(result, HealthStatus):
            deps[name] = {"ok": result.ok, "detail": result.detail}
            all_ok &= result.ok
        else:  # a probe itself raised — report rather than 500
            deps[name] = {"ok": False, "detail": f"probe error: {result}"}
            all_ok = False

    return {"status": "ok" if all_ok else "degraded", "dependencies": deps}
