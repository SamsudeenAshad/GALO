# UI Generation Prompt — GALO Dashboard (Neumorphism)

Copy everything in the code block below into your UI generator (v0, Lovable,
Bolt, Claude, etc.). It is self-contained: the design direction, the full API
contract, and every panel. Paste as a single message.

---

```
Build a single-page web dashboard for "GALO — Graph Aware Learning Orchestration
System", a self-hosted GraphRAG platform. Use a NEUMORPHISM (soft UI) visual
style throughout. The dashboard is served same-origin with the API (no CORS,
no auth). Output a single self-contained HTML file with inline CSS and vanilla
JS — no external libraries, no CDN links, no build step.

========================= DESIGN: NEUMORPHISM =========================
Neumorphism / soft UI. Get these details right — they are what make it read as
neumorphic rather than flat:

- Single near-monochrome background. Use a soft light theme:
  background #e0e5ec, surfaces the SAME color as the background (this is key —
  neumorphic elements are extruded FROM the background, not layered on a
  different color).
- Every "card", button, and input is a rounded shape (border-radius 16–24px)
  that appears extruded using TWO shadows: a dark bottom-right shadow and a
  light top-left highlight. Example raised:
    box-shadow: 8px 8px 16px #a3b1c6, -8px -8px 16px #ffffff;
  Example pressed/inset (for inputs, active toggles, the graph well):
    box-shadow: inset 6px 6px 12px #a3b1c6, inset -6px -6px 12px #ffffff;
- NO hard borders, NO flat drop shadows, NO high-contrast outlines. Depth comes
  only from the dual soft shadows.
- Buttons: raised by default; on :active press IN (swap to inset shadow) so they
  feel physically clickable. Subtle transition (transitions ~150ms).
- Text: dark slate (#4b5563 / #52606d) on the light bg; never pure black.
- Accent color used sparingly for primary actions and active states:
  a soft blue (#6d8dc7) or muted indigo. Status colors: green #57cc99,
  red #e07a5f, amber #e9c46a — but render them softly (no neon).
- Icons: simple line icons drawn inline as SVG or unicode; no icon library.
- Typography: a clean rounded sans (system-ui / Inter / "Segoe UI"); generous
  spacing; section titles small, uppercase, letter-spaced, muted.
- Layout: responsive CSS grid, max-width ~1100px centered, comfortable gaps.
  Cards reflow to one column on narrow screens.
- Provide a small dark-mode variant of the same neumorphism (bg #2e3239,
  shadows: dark #23262b / light #393f47) toggled by a switch in the header.

============================ LAYOUT ============================
Sticky header: app name "GALO", subtitle "Graph Aware Learning Orchestration",
and on the right three live status indicators (Ollama, Postgres, Neo4j) shown
as soft neumorphic dots that glow green when ok / red when down (tooltip = the
"detail" string). Auto-poll /health every 15s.

Then a grid of cards:
1. Corpus stats (chunks, entities) + Refresh button.
2. Recent ingest jobs (list of step/status, scrollable).
3. Ingest a document (title input + large text area + Ingest button + result).
4. Ask a question (GraphRAG) — input + Ask button + answer + citation cards.
5. Knowledge graph visualization (full width) — interactive force-directed graph.
6. Recommend — entity input, k number, alpha slider (0..1) + results.
7. Learning path — from/to concept inputs + ordered chain of chips.

============================ API CONTRACT ============================
All same-origin. JSON in/out. On error, responses have {"detail": "..."} with a
non-200 status (commonly 502 when a backend dependency is down, 422 on bad
input) — surface the detail string to the user.

GET /health ->
  { "status": "ok"|"degraded",
    "dependencies": {
      "ollama":   {"ok": bool, "detail": str},
      "postgres": {"ok": bool, "detail": str},
      "neo4j":    {"ok": bool, "detail": str} } }

GET /stats ->
  { "chunks": int|null, "entities": int|null }   // null if that store is down

GET /jobs?limit=8 ->
  { "jobs": [ { "id": str, "document_id": str|null, "step": str,
               "status": "pending"|"running"|"done"|"failed",
               "error": str|null, "updated_at": str(ISO) } ] }   // newest first

POST /ingest   body: { "text": str(required), "title": str|null,
                       "source_uri": str|null, "force": bool }
  -> { "document_id": str, "content_hash": str, "chunks": int, "skipped": bool }
  // skipped=true means identical content already ingested (idempotent no-op).
  // Slow call (embeds + LLM entity extraction): show a loading state.

POST /query    body: { "question": str(required) }
  -> { "answer": str,
       "citations": [ { "chunk_id": str, "document_id": str,
                        "score": float, "graph_path": [str] } ] }
  // graph_path is the entity-name chain that surfaced the chunk via the graph
  // (e.g. ["GALO","Postgres"]) — display it as provenance on each citation.
  // Render answer as text; it may contain [1],[2] markers matching citations.

POST /recommend body: { "entity": str(required), "k": int(1..100, default 10),
                        "alpha": float(0..1, default 0.5) }
  -> { "seed_found": bool,
       "recommendations": [ { "entity_id": str, "name": str,
                              "graph_weight": float, "similarity": float,
                              "score": float } ] }   // sorted by score desc
  // alpha blends signals: 1 = pure semantic similarity, 0 = pure graph weight.
  // If seed_found is false, show "entity not found in graph".

POST /path     body: { "from_concept": str(required), "to_concept": str(required) }
  -> { "found": bool, "steps": [ {"entity_id": str, "name": str} ],
       "reason": str|null }   // reason explains why found=false
  // Render steps as an ordered chain: A -> B -> C.

GET /graph?limit=200 ->
  { "nodes": [ {"id": str, "name": str,
                "type": "PERSON"|"ORG"|"CONCEPT"|"PLACE"|"OTHER",
                "degree": int} ],
    "edges": [ {"source": str(node id), "target": str(node id),
                "type": str, "weight": float} ] }

====================== GRAPH VISUALIZATION ======================
Render /graph as a force-directed graph on an HTML <canvas> using a small inline
physics simulation (charge repulsion + spring attraction along edges + gentle
centering + velocity damping). No D3 / vis.js / cytoscape — write the sim in
plain JS so the file stays self-contained.
- Node radius scales with degree. Node color encodes type; include a legend:
  PERSON #f778ba, ORG #6d8dc7, CONCEPT #57cc99, PLACE #e9c46a, OTHER #9aa5b1.
- Node labels = entity name.
- Edges are thin soft lines; optionally show edge "type" on hover.
- Nodes are draggable (the sim re-settles around a held node).
- The canvas sits in a neumorphic INSET well (pressed-in shadow).
- A "Reload" button re-fetches /graph (call it after a successful /ingest too).

========================== BEHAVIOR ==========================
- On load: call /health, /stats, /jobs, and /graph.
- Disable a button + show a loading state while its request is in flight
  (/ingest and /query are the slow ones — they hit local LLM models).
- After a successful /ingest, refresh /stats, /jobs, and the graph.
- All errors: show the {detail} message inline near the relevant card, styled
  softly in the red status color — never a raw alert().
- Pure client-side; no routing, no framework required (plain JS is fine, or a
  single React component if the generator prefers — but still one file, no CDN).
```

---

## Notes

- The current working dashboard lives at `src/galo/serve/static/dashboard.html`
  (dark theme, served at `/`). This prompt regenerates it in neumorphism — drop
  the generated HTML in at that same path to replace it; the
  [`/` route](../src/galo/serve/routes/dashboard.py) and packaging already point
  there.
- Because the dashboard is served same-origin by GALO, the generated file must
  use relative API paths (`/query`, not `http://host/query`) — the prompt says so.
