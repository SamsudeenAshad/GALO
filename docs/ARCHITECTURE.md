# GALO — Graph Aware Learning Orchestration System

**Design & Architecture Document**
Version 0.1 · 2026-06-19 · Status: Draft

---

## 1. Overview

GALO is a self-hosted GraphRAG platform. It ingests documents, extracts a
knowledge graph of entities and relationships, embeds text chunks as vectors,
and serves retrieval-augmented answers, recommendations, and learning paths by
**combining graph traversal with vector similarity**.

The defining idea: structure and semantics live in separate stores, each doing
what it is best at, and an orchestration layer joins them per query.

- **Neo4j (Community Edition)** — *structure*: entities, relationships, topology,
  graph algorithms (paths, communities, centrality).
- **Postgres + pgvector** — *semantics*: chunk embeddings, dense vector search,
  plus relational metadata (documents, chunks, jobs, provenance).
- **Ollama (self-hosted)** — *intelligence*: embeddings + generation, served at
  `http://zuselk-node-001.tru.zt:11434/` (model tag configurable, e.g. `gemma3`).

All three components are self-hosted. No external API dependency is required.

### 1.1 Goals

1. **Platform, not point solution** — cover ingestion, retrieval, and serving.
2. **Hybrid retrieval** — graph + vector, fused, not either/or.
3. **Provenance everywhere** — every answer traces to source chunks and graph paths.
4. **Pluggable model layer** — Ollama today; swap models/providers via one interface.
5. **Operable** — observable, idempotent ingestion, reproducible runs.

### 1.2 Non-goals (v0)

- Multi-tenant isolation / per-tenant encryption (single-tenant first).
- Distributed training of GNNs (we use graph *algorithms*, not learned GNNs, in v0).
- Real-time streaming ingestion (batch + incremental first).

---

## 2. The data split (why two stores)

| Concern                       | Store            | Rationale |
|-------------------------------|------------------|-----------|
| Entities & relationships      | Neo4j            | Native traversal, Cypher, graph algos (APOC/GDS-lite). |
| Topology queries (paths, neighbors) | Neo4j      | Multi-hop expansion is a join-heavy nightmare in SQL. |
| Chunk embeddings + ANN search | pgvector         | Mature ANN (HNSW/IVFFlat), SQL filtering, scales on commodity Postgres. |
| Documents, chunks, jobs, runs | Postgres         | Relational metadata, transactions, provenance. |
| Source of truth for raw text  | Postgres         | One canonical text store; Neo4j references chunk IDs, never duplicates text. |

**Linking key.** Both stores share stable IDs. A Neo4j `:Entity` node carries
`chunk_ids: [uuid]` (the chunks that mention it); a pgvector `chunk` row carries
`entity_ids: [uuid]` (entities extracted from it). This bidirectional link is the
seam the orchestrator walks across during hybrid retrieval.

> **Decision:** Embeddings live **only** in pgvector, not in Neo4j's vector index.
> Reason: one ANN engine to tune, SQL pre-filtering, and Community Edition keeps
> Neo4j lean for what it's uniquely good at. Revisit if cross-store latency hurts.

---

## 3. High-level architecture

```
                      ┌─────────────────────────────────────────┐
                      │              API / Serving               │
                      │  FastAPI: /ingest /query /recommend /path │
                      └───────────────┬──────────────────────────┘
                                      │
                 ┌────────────────────┼─────────────────────┐
                 ▼                    ▼                       ▼
        ┌─────────────────┐  ┌─────────────────┐   ┌──────────────────┐
        │   Ingestion     │  │   Retrieval     │   │   Generation     │
        │   Orchestrator  │  │   Orchestrator  │   │   Orchestrator   │
        └────────┬────────┘  └────────┬────────┘   └────────┬─────────┘
                 │                     │                     │
   ┌─────────────┼──────────┐         │                     │
   ▼             ▼          ▼         ▼                     ▼
┌────────┐ ┌──────────┐ ┌────────┐ ┌──────────────────────────────────┐
│ Loader │ │ Chunker  │ │ Entity │ │        Model Gateway (Ollama)     │
│        │ │          │ │ + Rel  │ │   embed() · generate() · rerank() │
└────────┘ └──────────┘ │ Extract│ └──────────────────────────────────┘
                        └────────┘
        │                     │
   ┌────┴─────┐         ┌─────┴──────┐
   ▼          ▼         ▼            ▼
┌──────┐  ┌─────────┐ ┌──────┐  ┌─────────┐
│Neo4j │  │pgvector │ │Neo4j │  │pgvector │
└──────┘  └─────────┘ └──────┘  └─────────┘
```

Three orchestrators, one shared **Model Gateway**, two stores. Each orchestrator
is a coordinator: it sequences steps, handles retries/idempotency, and is the
only place that knows about *both* stores at once.

---

## 4. Component design

### 4.1 Model Gateway (`galo.models`)

A single abstraction over the Ollama endpoint so the rest of the system never
hardcodes a model or URL.

```python
class ModelGateway(Protocol):
    async def embed(self, texts: list[str]) -> list[Vector]: ...
    async def generate(self, prompt: str, *, system: str | None = None,
                       stream: bool = False) -> str | AsyncIterator[str]: ...
    async def rerank(self, query: str, docs: list[str]) -> list[float]: ...
```

- **Backend:** `OllamaGateway` hitting `/api/embeddings` and `/api/generate`
  (or `/api/chat`). Base URL + model tags from config.
- **Embedding model:** a dedicated embedding model (e.g. `nomic-embed-text` or
  `bge-m3`), *not* the chat model — confirm what the node serves at deploy.
- **Generation model:** `gemma3` (confirm exact tag pulled on the node).
- **Dimensionality** is read from the embedding model and pinned in config; the
  pgvector column dimension MUST match (see §5.2). Changing models = re-embed.
- Retries with backoff, request timeout, and a circuit breaker; the gateway is
  the single failure-isolation boundary for the model node.

### 4.2 Ingestion Orchestrator (`galo.ingest`)

Pipeline, idempotent per `document_id` (content-hash dedupe):

1. **Load** — pull raw bytes → text (loaders per type: md, pdf, html, txt).
2. **Chunk** — split into overlapping chunks; record `(document_id, ord, text)`.
3. **Embed** — `gateway.embed(chunks)` → write `chunk.embedding` to pgvector.
4. **Extract** — LLM-driven entity + relation extraction over each chunk
   (structured output: `entities[]`, `relations[]`).
5. **Upsert graph** — MERGE entities/relations into Neo4j; attach `chunk_ids`.
6. **Backlink** — write `entity_ids` onto the pgvector chunk rows.

Idempotency: every step keyed by stable IDs + content hash; re-running a document
updates in place. A `jobs` table tracks run state for resume/observability.

> Entity-resolution (merging "NYC" ≈ "New York City") is a known hard problem.
> v0: exact + normalized-name match. v1: embedding-similarity blocking + LLM
> adjudication. Flagged as a roadmap risk, not solved here.

### 4.3 Retrieval Orchestrator (`galo.retrieve`)

The heart of GALO — **hybrid retrieval** fusing two signals:

1. **Vector path** — embed query → pgvector ANN top-k chunks.
2. **Graph path** — seed entities (from query NER or from the vector hits'
   `entity_ids`) → traverse Neo4j N hops → collect neighbor entities → map back
   to their `chunk_ids`.
3. **Fuse** — combine candidate chunks from both paths via **Reciprocal Rank
   Fusion (RRF)**; optionally rerank top-N with `gateway.rerank()`.
4. **Assemble context** — dedupe, budget by token count, attach provenance
   (chunk → document, and the graph path that surfaced it).

This is what makes answers *graph aware*: a chunk can rank highly not because it
is semantically similar to the query, but because it is one hop from an entity
the query is about.

### 4.4 Generation / Serving (`galo.serve`)

FastAPI. Core endpoints:

| Endpoint        | Purpose |
|-----------------|---------|
| `POST /ingest`  | Enqueue/run ingestion for documents. |
| `POST /query`   | GraphRAG Q&A: hybrid retrieve → generate, with citations. |
| `POST /recommend` | Next-item recommendations: graph relations + semantic similarity. |
| `POST /path`    | Learning path: shortest/weighted traversal between concept nodes, ordered by prerequisite edges. |
| `GET  /health`  | Liveness + dependency checks (Neo4j, Postgres, Ollama). |

`/recommend` and `/path` reuse the same retrieval primitives — recommendation is
graph neighborhood ∩ vector similarity; a learning path is a Neo4j traversal over
`PREREQUISITE`/`RELATED` edges, re-ranked for the learner's current frontier.

---

## 5. Data model

### 5.1 Neo4j (structure)

```cypher
(:Entity   {id, name, normalized_name, type, chunk_ids: [uuid], created_at})
(:Document {id, title, source_uri, content_hash})
(:Concept  {id, name})   // optional curriculum layer for /path

(:Entity)-[:RELATED {type, weight, chunk_id}]->(:Entity)
(:Concept)-[:PREREQUISITE]->(:Concept)
(:Entity)-[:MENTIONED_IN]->(:Document)
```

Indexes on `Entity.id`, `Entity.normalized_name`, `Document.content_hash`.

### 5.2 Postgres + pgvector (semantics + metadata)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id            uuid PRIMARY KEY,
  title         text,
  source_uri    text,
  content_hash  text UNIQUE NOT NULL,
  created_at    timestamptz DEFAULT now()
);

CREATE TABLE chunks (
  id          uuid PRIMARY KEY,
  document_id uuid REFERENCES documents(id) ON DELETE CASCADE,
  ord         int  NOT NULL,
  text        text NOT NULL,
  entity_ids  uuid[] DEFAULT '{}',
  embedding   vector(768)        -- DIM MUST MATCH the embedding model
);

CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON chunks USING gin (entity_ids);

CREATE TABLE jobs (         -- ingestion run state / provenance
  id           uuid PRIMARY KEY,
  document_id  uuid,
  step         text,
  status       text,        -- pending|running|done|failed
  error        text,
  updated_at   timestamptz DEFAULT now()
);
```

> The `vector(768)` dimension is a placeholder; set it to the deployed embedding
> model's true dimension. This is a hard coupling — changing models requires a
> migration + full re-embed.

---

## 6. Cross-cutting concerns

- **Config** (`galo.config`): pydantic-settings, env-driven. Neo4j URI/creds,
  Postgres DSN, Ollama base URL + `EMBED_MODEL` / `GEN_MODEL` tags, embed dim,
  chunk size/overlap, retrieval k / hops / RRF params.
- **Provenance:** responses carry `sources: [{chunk_id, document_id, score,
  graph_path?}]`. Non-negotiable for trust and debugging.
- **Observability:** structured logs, request IDs threaded through orchestrators,
  `/health` dependency probes, ingestion `jobs` table as the audit trail.
- **Idempotency & consistency:** Postgres is the source of truth for text;
  Neo4j is rebuildable from Postgres + extraction. A reconcile job can rebuild
  the graph from chunks if the two drift.
- **Failure isolation:** Model Gateway is the only thing that talks to Ollama;
  store clients are the only things that talk to their DBs. One boundary each.

---

## 7. Technology stack

| Layer        | Choice                              | Why |
|--------------|-------------------------------------|-----|
| Language     | Python 3.12+                        | Ecosystem for graph/vector/LLM. |
| API          | FastAPI + uvicorn                   | Async, typed, OpenAPI out of the box. |
| Async        | `asyncio` + `httpx`                 | Concurrent embed/extract; async Ollama calls. |
| Postgres     | `asyncpg` / SQLAlchemy 2.x + `pgvector` | Async DB access, typed models. |
| Neo4j        | official `neo4j` async driver       | Cypher, async sessions. |
| Models       | Ollama (self-hosted)                | No external dependency, on-prem. |
| Config       | `pydantic-settings`                 | Validated env config. |
| Migrations   | Alembic (PG) + Cypher migration scripts | Reproducible schema. |
| Packaging    | `uv` / `pyproject.toml`             | Fast, reproducible installs. |
| Testing      | `pytest` + `testcontainers`         | Real Neo4j/PG in CI. |

---

## 8. Proposed repository layout

```
galo/
  pyproject.toml
  docs/ARCHITECTURE.md          ← this file
  src/galo/
    config.py
    models/        gateway.py · ollama.py
    stores/        pg.py · neo4j.py · schema.sql · migrations/
    ingest/        loader.py · chunker.py · extract.py · orchestrator.py
    retrieve/      vector.py · graph.py · fuse.py · orchestrator.py
    serve/         app.py · routes/ · schemas.py
  tests/
```

---

## 9. Roadmap

- **M0 — Skeleton:** config, store clients, Model Gateway, `/health`. Connectivity proven.
- **M1 — Ingestion:** load → chunk → embed → pgvector. Documents searchable by vector.
- **M2 — Graph:** entity/relation extraction → Neo4j upsert + backlinks.
- **M3 — Hybrid retrieval:** vector ∪ graph → RRF → `/query` with citations.
- **M4 — Platform endpoints:** `/recommend`, `/path` (curriculum layer).
- **M5 — Hardening:** entity resolution v1, reconcile job, observability, load tests.

---

## 10. Open questions (need confirmation before M0)

1. **Exact Ollama model tags** served on the node (generation + embedding) and
   the **embedding dimension** — this pins the pgvector column.
2. **Corpus characteristics** — document types, volume, update frequency
   (drives chunker + ingestion mode: batch vs incremental).
3. **Curriculum source for `/path`** — are `Concept`/`PREREQUISITE` edges
   authored by hand, or inferred from the extracted graph?
4. **Auth model** — is the API internal-only, or does it need authn/z in v0?
