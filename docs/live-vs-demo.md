# Live mode vs demo mode

The prototype is designed so that **no credential is ever a blocker**. Each external service has a
local implementation with the same interface; supplying credentials swaps one adapter without
touching any caller.

## Adapter matrix

| Service | Demo implementation | Live implementation | Enabled by |
| --- | --- | --- | --- |
| Mireye | `MockMireyeClient` — deterministic fixtures, every value `synthetic` | `LiveMireyeClient` wrapped in `FallbackMireyeClient` | `MIREYE_BASE_URL` + `MIREYE_API_KEY` |
| Impact graph | `InMemoryGraphStore` | `Neo4jGraphStore` (Cypher, same traversal semantics) | `NEO4J_URI` + `NEO4J_USER` + `NEO4J_PASSWORD` |
| Retrieval | `HybridIndex(LexicalIndex BM25, LocalVectorIndex)` | `HybridIndex(LexicalIndex, PgVectorIndex)` | `DATABASE_URL` |
| Storage | SQLite document store | Postgres / Supabase (same `Store` interface) | `DATABASE_URL`, `SUPABASE_*` |
| Explanations & planning | `DeterministicNarrator` (templates) | `GeminiProvider` | `GEMINI_API_KEY` |
| Agent tracing | off (nothing sent) | LangSmith traces of every LangGraph run | `LANGSMITH_API_KEY` |

`GET /api/meta` reports `demo_mode` plus the adapter actually in use for each service — a
configured service that failed to connect reports its fallback, not its intent. The UI renders this
as the amber **Demo mode** banner.

## What changes, and what does not

**Changes with live mode**

* Evidence status becomes `live`/`cached` instead of `synthetic`, raising the confidence multiplier
  from 0.6 to 1.0/0.9 and therefore raising every site's reported confidence.
* Values become real, so scores and ranks change.
* The impact graph is persisted in Neo4j and survives a restart.
* Retrieval uses real embeddings via pgvector.
* Recommendations gain an extra `(agent explanation)` paragraph written by the LLM.

**Never changes**

* Scoring formulas, delta thresholds, verification gates, decision precedence — all deterministic
  and identical in both modes.
* The decision state for the same inputs.
* Provenance requirements: an unavailable field is a gap in both modes.

## Turning on live mode

```bash
cd apps/api
cp .env.example .env
```

### Mireye
```dotenv
MIREYE_BASE_URL=https://api.mireye.example
MIREYE_API_KEY=...
```
Check the assumed contract in [`mireye-contract.md`](mireye-contract.md) first; if the real payloads
differ, adjust `LiveMireyeClient._to_observation` and the request builders. On any failure the
client falls back to the mock, marks itself `degraded_mock` and records the reason.

### Neo4j and pgvector
```bash
docker compose -f infra/docker-compose.yml up -d
```
```dotenv
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/wetstack
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=wetstacklocal
```
Install the optional drivers: `pip install -e ".[live]"`. If a driver is missing or the server is
unreachable, the API logs a warning and continues on the local implementation.

### LLM
```dotenv
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.0-flash
LANGSMITH_API_KEY=...     # optional: agent tracing
```
The LLM may add up to three investigation steps (validated against the field catalog) and write the
explanation paragraph. An LLM failure is caught and logged; the deterministic pipeline continues.

## Synthetic-data labelling

Synthetic data is labelled at every layer, so it cannot be mistaken for a real observation:

| Layer | Marker |
| --- | --- |
| Adapter | `FieldValue.status = "synthetic"`, note "not a real observation" |
| Evidence | `status = synthetic`, `source.synthetic = true` |
| Domain | `Project.synthetic`, `CandidateSite.synthetic`, `Equipment.synthetic`, `ProjectDocument.synthetic` |
| Scoring | `SiteScore.synthetic_field_count`, and a caveat on every recommendation |
| API | `GET /api/meta.demo_mode` and per-service modes |
| UI | Amber "synthetic" badges, the demo-mode banner, and the count of synthetic fields on the leading site |

Sample PDFs carry a banner on every page: *"SYNTHETIC DEMONSTRATION DOCUMENT — values are invented
for the Wet Stack / Mireye prototype and are not real product or project data."* Manufacturers
(Northwind Thermal, Vertex Climate, Halden Cooling, Ferrous Power, Kestrel Energy) are fictional, so
no real vendor's data is ever misrepresented.
