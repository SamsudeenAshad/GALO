# GALO — Task Tracker

Tracks implementation progress against the milestones in
[ARCHITECTURE.md](ARCHITECTURE.md#9-roadmap). Check items off as they land.

---

## M0 — Skeleton  *(done)*

Goal: config, store clients, Model Gateway, and `/health`. Connectivity proven.

- [x] `pyproject.toml` — deps, scripts, tooling
- [x] `.gitignore`
- [x] `docs/ARCHITECTURE.md` — design doc
- [x] `docs/TASK.md` — this tracker
- [x] `src/galo/__init__.py`
- [x] `.env.example` — documented config surface
- [x] `src/galo/config.py` — pydantic-settings, env-driven
- [x] `src/galo/models/gateway.py` — `ModelGateway` protocol + types
- [x] `src/galo/models/ollama.py` — `OllamaGateway` (embed/generate, health)
- [x] `src/galo/stores/pg.py` — async Postgres/pgvector client + ping
- [x] `src/galo/stores/neo4j.py` — async Neo4j client + ping
- [x] `src/galo/serve/app.py` — FastAPI app, lifespan wiring, `main()`
- [x] `src/galo/serve/routes/health.py` — `/health` dependency probes
- [x] `tests/test_health.py` — health endpoint with deps mocked (3 passing)
- [x] Manual smoke: `galo` serves; `/health` returns 200 + `degraded` with
      accurate per-dependency detail when all deps are down

**Exit criteria:** `galo` starts; `GET /health` returns liveness + per-dependency
(Neo4j, Postgres, Ollama) status without crashing when a dependency is down.

---

## M1 — Ingestion *(done, pending live-infra verification)*

load → chunk → embed → pgvector. Documents searchable by vector.

- [x] `stores/schema.sql` — documents, chunks (vector{EMBED_DIM}), jobs; HNSW + GIN indexes
- [x] `stores/pg.py` — migrate(), upsert_document, replace_chunks, record_job, content_exists
- [x] `ingest/loader.py` — text/bytes load, normalized, content-hash + deterministic id
- [x] `ingest/chunker.py` — overlapping windows, boundary-aware, forward-progress guaranteed
- [x] `ingest/orchestrator.py` — load→chunk→embed→persist, idempotent per content hash, `force`
- [x] `serve/schemas.py`, `serve/routes/ingest.py` — `POST /ingest`
- [x] app wiring: best-effort migrate at startup, orchestrator on app.state
- [x] tests: chunker (5) + ingestion orchestrator (4) — all passing (12 total)
- [x] smoke: `/ingest` returns 502 when PG down, 422 on empty text, registered in OpenAPI
- [ ] **Pending live infra:** verify successful persist path against real Postgres+pgvector+Ollama

**Exit criteria:** a document POSTed to `/ingest` is chunked, embedded, and stored
in pgvector; re-posting identical content is a no-op. *(Happy path needs live
Postgres+Ollama to confirm — logic is unit-tested with stubs.)*

## M2 — Graph *(not started)*

Entity/relation extraction → Neo4j upsert + backlinks.

- [ ] `ingest/extract.py` — LLM structured entity/relation extraction
- [ ] Neo4j MERGE upserts + `chunk_ids` / `entity_ids` backlinks

## M3 — Hybrid retrieval *(not started)*

vector ∪ graph → RRF → `/query` with citations.

- [ ] `retrieve/vector.py`, `retrieve/graph.py`, `retrieve/fuse.py`
- [ ] `retrieve/orchestrator.py`, `POST /query`

## M4 — Platform endpoints *(not started)*

- [ ] `POST /recommend`, `POST /path` (curriculum layer)

## M5 — Hardening *(not started)*

- [ ] Entity resolution v1, reconcile job, observability, load tests

---

## Open questions blocking later milestones

See [ARCHITECTURE.md §10](ARCHITECTURE.md#10-open-questions-need-confirmation-before-m0).
The embedding **dimension** (M1) and exact **Ollama model tags** are the
highest-priority unknowns — kept configurable in M0 so we are not blocked.
