# GALO — Architecture

**Graph Aware Learning Orchestration System** · self-hosted GraphRAG platform
Version 0.1 · Python 3.12+ · Apache-2.0

> Companion diagram: [`architecture.excalidraw`](architecture.excalidraw)
> (open at [excalidraw.com](https://excalidraw.com) → *Open*).

---

## 1. What GALO is

GALO ingests documents, builds a **knowledge graph** of the entities and
relationships in them, embeds the text as **vectors**, and answers questions by
**combining graph traversal with vector similarity** (GraphRAG). It also serves
recommendations and learning paths over the same graph.

Everything is **self-hosted** — no external API. Three backing services:

| Service | Role | Why |
|---------|------|-----|
| **Neo4j (Community)** | *structure* — entities, relationships, topology | native traversal, Cypher, graph algorithms |
| **Postgres + pgvector** | *semantics* — chunk embeddings + relational metadata | mature ANN (HNSW), SQL filtering, source of truth for text |
| **Ollama** | *intelligence* — embeddings + generation | on-prem models, no data leaves the network |

The defining idea: **structure and semantics live in separate stores**, and an
orchestration layer joins them per request. A chunk can surface in an answer
because it is *one hop from an entity the question is about* — not only because
it is semantically similar.

---

## 2. The two-store split & the linking seam

Embeddings live **only in pgvector**; the graph lives **only in Neo4j**. They are
joined by a bidirectional ID link:

```
 Neo4j (:Entity)                         Postgres (chunks)
 ┌────────────────────────┐              ┌─────────────────────────┐
 │ id, name, type          │   chunk_ids │ id, document_id, text     │
 │ chunk_ids: [uuid] ──────┼────────────▶│ embedding vector(768)     │
 │                         │◀────────────┼─ entity_ids: uuid[]        │
 │ (:Entity)-[:RELATED]->  │  entity_ids │                           │
 └────────────────────────┘              └─────────────────────────┘
```

- An `:Entity` carries the `chunk_ids` it was mentioned in.
- A `chunk` row carries the `entity_ids` extracted from it.

This seam is what the retriever walks across: vector hits → their entities →
graph neighbors → those neighbors' chunks.

**Postgres is the source of truth for text; Neo4j is rebuildable** from it (see
the reconcile job, §6).

---

## 3. High-level architecture

```
                          ┌────────────────────────────────────────────┐
   Browser ──────────────▶│  FastAPI app (galo.serve)                    │
   dashboard.html         │  request-id + JSON access-log middleware     │
   graph.html             └───────────────┬──────────────────────────────┘
                                           │
          ┌────────────────┬───────────────┼────────────────┬──────────────┐
          ▼                ▼               ▼                ▼              ▼
      /ingest          /query         /recommend         /graph        /health
      /ingest/file                    /path              /graph/subgraph /stats /jobs
          │                │               │                │
          ▼                ▼               ▼                ▼
   ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  graph snapshots
   │ Ingestion   │  │ Retrieval    │  │ recommend /  │
   │ Orchestrator│  │ Orchestrator │  │ path modules │
   └──────┬──────┘  └──────┬───────┘  └──────┬───────┘
          │                │                 │
          │     ┌──────────┴─────────┐       │
          ▼     ▼                    ▼       ▼
   ┌──────────────────────┐   ┌──────────────────────────────────┐
   │  Model Gateway        │   │   Stores                          │
   │  (galo.models)        │   │   PgStore  ·  Neo4jStore           │
   │  embed · generate     │   └──────────────────────────────────┘
   └──────────┬───────────┘            │              │
              ▼                        ▼              ▼
         Ollama node            Postgres+pgvector   Neo4j
```

Plus **out-of-band maintenance** (`galo.maintain`): entity resolution + reconcile.

---

## 4. Components

### 4.1 Model Gateway — `galo.models`
The single boundary to Ollama. Everything depends on the `ModelGateway`
Protocol, never on a concrete backend.
- `gateway.py` — `ModelGateway` protocol (`embed`, `generate`, `health`, `aclose`)
- `ollama.py` — `OllamaGateway`; validates that returned embedding dim equals
  the configured `embed_dim` (mismatch = hard error).

### 4.2 Stores — `galo.stores`
- `pg.py` — `PgStore`: async pool; `migrate()` (templates the embedding dim into
  `schema.sql`), document/chunk upserts, `search_vectors()` (cosine ANN),
  `chunks_for_entities()`, jobs, stats.
- `neo4j.py` — `Neo4jStore`: async driver; `upsert_extraction()`, `expand()`
  (N-hop traversal), `graph_snapshot()`, `subgraph_for_chunks()` (evidence
  subgraph), `merge_entities()`, recommend/path helpers.
- `schema.sql` — `documents`, `chunks (vector{EMBED_DIM}, HNSW + GIN)`, `jobs`.

### 4.3 Ingestion — `galo.ingest`
Pipeline, idempotent per content hash:
**load/parse → chunk → embed → persist → extract → graph upsert → backlink.**
- `parse.py` — local file parsing: **PDF (pypdf), DOCX (python-docx), MD/TXT**.
  No cloud parser; nothing leaves the host.
- `loader.py` — normalize text, content-hash, deterministic document id.
- `chunker.py` — overlapping, boundary-aware windows.
- `extract.py` — LLM entity/relation extraction with a defensive JSON parser.
- `orchestrator.py` — sequences it all; graph step is **best-effort** (Postgres
  is source of truth, graph is rebuildable), so a graph failure records a job
  but does not fail ingest.

### 4.4 Retrieval — `galo.retrieve`
The heart of GALO — **hybrid retrieval**:
1. `vector.py` — embed query → pgvector ANN top-k.
2. `graph.py` — seed entities from the vector hits → `expand()` N hops in Neo4j
   → map neighbors back to chunks.
3. `fuse.py` — **Reciprocal Rank Fusion** (rank-only, so it merges cosine
   distance and graph hop-distance — two incomparable scales).
4. `orchestrator.py` — assemble token-budgeted context → generate a grounded,
   cited answer. `recommend.py` (graph neighbors ∩ semantic similarity, `alpha`
   blend) and `path.py` (shortest `:PREREQUISITE` chain) reuse these primitives.

### 4.5 Serving — `galo.serve`
FastAPI. Routes: `health`, `ingest` (+`/ingest/file`), `query`, `recommend`
(+`/path`), `ops` (`/jobs`, `/stats`, `/graph`, `/graph/subgraph`), `dashboard`
(`/`, `/graph-view`). `middleware.py` adds a request id + structured JSON
access log. Two self-contained pages: `dashboard.html` (Ask + evidence graph)
and `graph.html` (full-graph explorer at `/graph-view`).

### 4.6 Maintenance — `galo.maintain` (out-of-band)
- `resolve.py` — entity resolution v1: embedding-similarity blocking + optional
  LLM adjudication + union-find merge into a canonical node.
- `reconcile.py` — rebuild the Neo4j graph from Postgres chunks when the stores
  drift; per-chunk failures are counted, not fatal.

---

## 5. Request flows

**Ingest** (`POST /ingest` or `/ingest/file`)
`parse → hash (skip if exists) → chunk → embed(nomic) → write chunks+vectors →
extract entities(gemma) → MERGE into Neo4j + write chunk↔entity backlinks → job=done`

**Query** (`POST /query`)
`embed question → pgvector ANN → seed entities → Neo4j N-hop expand →
chunks_for_entities → RRF fuse → assemble context → generate(gemma) →
answer + citations (chunk, score, graph_path)`

**Evidence graph** (`POST /graph/subgraph`, dashboard)
After an answer, the cited `chunk_ids` → entities in those chunks (seeds) +
their neighbors + edges → rendered as the subgraph that explains the answer.

---

## 6. Cross-cutting

- **Config** (`config.py`): `pydantic-settings`, `GALO_`-prefixed env. Ollama
  URL + model tags + `embed_dim`, PG DSN, Neo4j creds, retrieval k/hops/RRF,
  chunk size/overlap. See `.env.example`.
- **Provenance**: answers carry `citations` (chunk, document, score, graph path).
- **Idempotency**: deterministic ids by content hash; re-ingesting is a no-op.
- **Resilience**: dependency failures surface as `502` / `degraded` health, never
  a 500; the app boots even when a backing service is down.
- **Failure isolation**: only the gateway talks to Ollama; only the store clients
  talk to their DBs.

---

## 7. Stack & layout

FastAPI · httpx · asyncpg · neo4j async driver · pypdf · python-docx · Ollama.
Tests: pytest (48), stubbing the gateway/stores; the live stack runs Postgres +
Neo4j in Docker against a self-hosted Ollama node.

```
src/galo/
  config.py
  models/   gateway.py · ollama.py
  stores/   pg.py · neo4j.py · schema.sql
  ingest/   parse.py · loader.py · chunker.py · extract.py · orchestrator.py
  retrieve/ vector.py · graph.py · fuse.py · orchestrator.py · recommend.py · path.py
  maintain/ resolve.py · reconcile.py
  serve/    app.py · middleware.py · schemas.py · routes/ · static/{dashboard,graph}.html
tests/      test_*.py
```

---

## 8. Status & open questions

Implemented end-to-end (ingest → graph → query → recommend → path), verified live
against real Postgres + Neo4j + Ollama (`gemma4:e4b` generation,
`nomic-embed-text` 768-dim embeddings).

Open / future:
1. `:PREREQUISITE` curriculum edges are **hand-authored** (`set_prerequisite`);
   inferring them from the extracted graph is future work.
2. `/recommend` embeds bare entity *names* — a weak similarity signal; embedding
   entity *context* would be stronger.
3. Resolve/reconcile are modules, not yet exposed as an admin endpoint/CLI.
4. Query-side entity extraction (NER) instead of seeding the graph only from
   vector hits.
