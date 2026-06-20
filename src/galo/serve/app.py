"""FastAPI application: lifespan wiring of dependencies + route mounting.

The lifespan builds the three dependency clients (Ollama gateway, Postgres,
Neo4j) once at startup and stashes them on ``app.state`` so routes can reach
them. Connection failures at startup are tolerated — ``/health`` is the place
that reports them — so the server still boots when a dependency is down.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from galo.config import Settings, get_settings
from galo.ingest.orchestrator import IngestionOrchestrator
from galo.models.ollama import OllamaGateway
from galo.serve.routes import health, ingest
from galo.stores.neo4j import Neo4jStore
from galo.stores.pg import PgStore


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        gateway = OllamaGateway(
            settings.ollama_base_url,
            gen_model=settings.gen_model,
            embed_model=settings.embed_model,
            embed_dim=settings.embed_dim,
            timeout_s=settings.model_timeout_s,
        )
        pg = PgStore(settings.pg_dsn)
        neo = Neo4jStore(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)

        # Best-effort connect; a down dependency must not block boot — /health
        # is responsible for surfacing it.
        for client in (pg, neo):
            with contextlib.suppress(Exception):
                await client.connect()

        # Best-effort schema migration (idempotent). If Postgres is down, boot
        # proceeds; /ingest will then return a 502 until it recovers.
        with contextlib.suppress(Exception):
            await pg.migrate(settings.embed_dim)

        app.state.settings = settings
        app.state.gateway = gateway
        app.state.pg = pg
        app.state.neo4j = neo
        app.state.ingestion = IngestionOrchestrator(
            pg,
            gateway,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        try:
            yield
        finally:
            for closer in (gateway.aclose, pg.aclose, neo.aclose):
                with contextlib.suppress(Exception):
                    await closer()

    app = FastAPI(title="GALO", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(ingest.router)
    return app


app = build_app()


def main() -> None:
    """Console entry point (``galo``)."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "galo.serve.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
