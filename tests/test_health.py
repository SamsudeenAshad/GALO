"""Health endpoint tests with all dependencies stubbed.

These cover the route's aggregation logic — happy path, a degraded dependency,
and a probe that raises — without needing real Neo4j/Postgres/Ollama.
"""

from __future__ import annotations

import contextlib

import pytest
from fastapi.testclient import TestClient

from galo.config import Settings
from galo.models.gateway import HealthStatus
from galo.serve.app import build_app


class _StubClient:
    """Stands in for any dependency client in the health route."""

    def __init__(self, status: HealthStatus | Exception) -> None:
        self._status = status

    async def connect(self) -> None:  # used by lifespan for pg/neo
        pass

    async def health(self) -> HealthStatus:
        if isinstance(self._status, Exception):
            raise self._status
        return self._status

    async def aclose(self) -> None:
        pass


@contextlib.contextmanager
def _client(ollama, pg, neo):
    """Yield a started TestClient whose dependency clients are stubs.

    The stubs are installed *inside* the lifespan window (after ``__enter__``
    runs the real lifespan) so the running app actually uses them.
    """
    app = build_app(Settings())
    with TestClient(app) as c:
        app.state.gateway = ollama
        app.state.pg = pg
        app.state.neo4j = neo
        yield c


def test_health_all_ok() -> None:
    ok = HealthStatus(ok=True, detail="up")
    with _client(_StubClient(ok), _StubClient(ok), _StubClient(ok)) as c:
        resp = c.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert all(d["ok"] for d in body["dependencies"].values())


def test_health_degraded_when_one_down() -> None:
    ok = HealthStatus(ok=True, detail="up")
    down = HealthStatus(ok=False, detail="unreachable")
    with _client(_StubClient(ok), _StubClient(down), _StubClient(ok)) as c:
        body = c.get("/health").json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["postgres"]["ok"] is False


def test_health_probe_exception_is_reported() -> None:
    ok = HealthStatus(ok=True, detail="up")
    with _client(_StubClient(ok), _StubClient(RuntimeError("boom")), _StubClient(ok)) as c:
        body = c.get("/health").json()
    assert body["status"] == "degraded"
    assert "probe error" in body["dependencies"]["postgres"]["detail"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
