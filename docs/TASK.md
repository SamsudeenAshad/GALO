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

## M1 — Ingestion *(not started)*

load → chunk → embed → pgvector. Documents searchable by vector.

- [ ] `stores/schema.sql` + migrations (documents, chunks, jobs)
- [ ] `ingest/loader.py`, `ingest/chunker.py`
- [ ] `ingest/orchestrator.py` — load→chunk→embed, idempotent per content hash
- [ ] `POST /ingest`

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
