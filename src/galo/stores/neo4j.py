"""Async Neo4j client (Community Edition).

Owns the driver. In M0 it only exposes a ``ping`` via the driver's built-in
connectivity check; graph upserts and traversals land in later milestones.
"""

from __future__ import annotations

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from galo.models.gateway import HealthStatus


class Neo4jStore:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self._uri = uri
        self._auth = (user, password)
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(self._uri, auth=self._auth)

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("Neo4jStore not connected; call connect() first")
        return self._driver

    async def health(self) -> HealthStatus:
        try:
            if self._driver is None:
                return HealthStatus(ok=False, detail="driver not initialized")
            await self._driver.verify_connectivity()
            return HealthStatus(ok=True, detail="connected")
        except (ServiceUnavailable, Neo4jError, OSError) as exc:
            return HealthStatus(ok=False, detail=f"unreachable: {exc}")

    async def aclose(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None
