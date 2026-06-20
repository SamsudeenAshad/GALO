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

## M2 — Graph *(done, pending live-infra verification)*

Entity/relation extraction → Neo4j upsert + backlinks.

- [x] `ingest/extract.py` — LLM structured extraction; defensive JSON parsing
      (strips fences, recovers from prose, dedupes, deterministic entity ids)
- [x] `stores/neo4j.py` — `migrate()` (constraints/indexes) + `upsert_extraction()`
      (MERGE entities w/ appended `chunk_ids`, MERGE :RELATED w/ weight + provenance)
- [x] `stores/pg.py` — `set_chunk_entities()` backlink + `chunk_id_for()` helper
- [x] orchestrator: best-effort graph step (Postgres = source of truth, graph rebuildable);
      graph failure records a 'graph' failed job but does NOT fail ingest
- [x] app wiring: Neo4j migrate at startup, graph passed to orchestrator
- [x] tests: extraction parser (8) + graph orchestrator path (2) — 22 total passing
- [ ] **Pending live infra:** verify entities/relations land in Neo4j and backlinks
      in pgvector against a real corpus

**Exit criteria:** ingesting a document populates Neo4j with entities/relations
linked back to their chunks, and pgvector chunks carry their `entity_ids`.
*(Needs live Neo4j+Ollama to confirm end-to-end; logic unit-tested with stubs.)*

## M3 — Hybrid retrieval *(done, pending live-infra verification)*

vector ∪ graph → RRF → `/query` with citations.

- [x] `stores/pg.py` — `search_vectors()` (cosine ANN) + `chunks_for_entities()` (graph→chunk map)
- [x] `stores/neo4j.py` — `expand()` N-hop :RELATED traversal w/ provenance paths
- [x] `retrieve/vector.py` — embed query → ANN candidates
- [x] `retrieve/graph.py` — seed from vector hits' entities → expand → chunks
- [x] `retrieve/fuse.py` — Reciprocal Rank Fusion (rank-only, scale-agnostic)
- [x] `retrieve/orchestrator.py` — retrieve→fuse→assemble(token-budgeted)→generate→cite
- [x] `serve/routes/query.py` + schemas — `POST /query`
- [x] app wiring: RetrievalOrchestrator on app.state
- [x] tests: fuse (4) + retrieve orchestrator (3) — 29 total passing
- [x] smoke: `/query` registered; 502 when deps down, 422 on empty; graph seeded from vector hits
- [ ] **Pending live infra:** verify answer quality + citation accuracy on a real corpus

**Exit criteria:** `POST /query` returns an LLM answer grounded in fused
graph+vector context, with chunk/document citations and graph paths.
*(Answer quality needs live Neo4j+pgvector+Ollama; orchestration unit-tested.)*

**v0 seeding note:** graph path is seeded from the top vector hits' `entity_ids`
(no separate query-NER). Query-side entity extraction is a future enhancement.

## M4 — Platform endpoints *(done, pending live-infra verification)*

- [x] `stores/neo4j.py` — `find_entity`, `neighbors` (weighted), `prerequisite_path`
      (shortestPath over :PREREQUISITE), `set_prerequisite` (hand-authored curriculum)
- [x] `retrieve/recommend.py` — graph neighbors re-ranked by semantic similarity;
      `alpha` blends signals (1=semantic, 0=graph)
- [x] `retrieve/path.py` — resolve two concepts → shortest prerequisite chain
- [x] `serve/routes/recommend.py` + schemas — `POST /recommend`, `POST /path`
- [x] app wiring: router mounted (reuses neo4j + gateway already on app.state)
- [x] tests: recommend blend + path resolution (6) — 35 total passing
- [x] smoke: both registered; 502 deps-down; 422 on invalid alpha
- [ ] **Pending live infra:** verify recommendations + paths on a real graph;
      decide curriculum-authoring story (hand-authored via set_prerequisite vs inferred)

**Exit criteria:** `/recommend` returns blended graph+semantic suggestions for a
seed entity; `/path` returns an ordered prerequisite chain between two concepts.

## M5 — Hardening *(not started)*

- [ ] Entity resolution v1, reconcile job, observability, load tests

---

## Open questions blocking later milestones

See [ARCHITECTURE.md §10](ARCHITECTURE.md#10-open-questions-need-confirmation-before-m0).
The embedding **dimension** (M1) and exact **Ollama model tags** are the
highest-priority unknowns — kept configurable in M0 so we are not blocked.
