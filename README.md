# The Wet Stack — Mireye

A data-center construction and EPC intelligence prototype with two connected workflows:

1. **Before Construction — Site Intelligence.** Evaluate candidate sites across terrain, water,
   power, connectivity, civil/soil, hazards, environment and regulatory dimensions; rank them
   with an explainable deterministic score; show what evidence is missing.
2. **During Construction — Change Intelligence.** Verify that an equipment substitution is even
   comparable, compute the real deltas, trace downstream impacts across disciplines, and land on
   one of three decision states with the next action drafted.

Both workflows share one project context: the same evidence store with full provenance, the same
information-gap tracking, the same impact graph and the same agent orchestration layer.

**The agent decides what to investigate. Deterministic, tested Python does every calculation.**
No score, delta, threshold, unit conversion or decision state is ever produced by a language model.

> **Safety limitation.** This prototype performs first-pass deterministic checks. It flags where
> structural, electrical or mechanical coordination is *required*; it never asserts structural
> adequacy and is not professional engineering approval. All demo data is synthetic.

---

## Quick start (no credentials needed)

Requires Python 3.11+ and Node 18+. Nothing else — no Docker, no database, no API keys.

### One command

```bash
python scripts/dev.py
```

From a clean checkout this creates the backend virtualenv, installs both dependency sets, seeds the
synthetic demo data and runs the API and the UI together. Then open <http://localhost:5173>.
Ctrl-C stops both.

```bash
python scripts/dev.py --reset   # wipe and re-seed the demo data first
python scripts/dev.py --check   # tests + lint + type-check + production build, then exit
python scripts/dev.py --api-only / --ui-only
```

The manual equivalent, if you prefer to run the two halves yourself:

### 1. Backend

```bash
cd apps/api
python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # optional: the defaults are fine
python -m app.seed --reset    # seed demo data (also happens automatically on first start)
uvicorn app.main:app --reload --port 8000
```

API: <http://127.0.0.1:8000> · OpenAPI docs: <http://127.0.0.1:8000/docs> ·
health: `/api/health` · readiness: `/api/ready`

### 2. Frontend

```bash
cd apps/web
npm install
cp .env.example .env          # optional: empty means "use the dev proxy"
npm run dev
```

UI: <http://localhost:5173> (Vite proxies `/api` to the backend, so there is no CORS setup.)

### 3. Tests

```bash
cd apps/api
python -m pytest ../../tests -q      # 122 tests
python -m ruff check app ../../tests # lint
```

```bash
cd apps/web
npm run lint                          # tsc --noEmit
npm run build
```

### Reset / reseed

```bash
cd apps/api && python -m app.seed --reset      # CLI
curl -X POST http://127.0.0.1:8000/api/admin/seed   # API (also the "Reseed demo" button in the UI)
```

---

## What the demo contains

| Item | Count | Notes |
| --- | --- | --- |
| Candidate sites | 5 | Cascade Flats, Rio Verde Mesa, Delta Fields, Harbour Point, Prairie Junction — all synthetic |
| Mireye fields | 34 | The catalog the agent may request; unknown fields are rejected, not invented |
| Source documents | 3 | Synthetic specification, datasheet and submittal PDFs, generated at seed time |
| Equipment change cases | 3 | One per decision state (see below) |
| Project assumptions | 7 | Go stale when the evidence they depend on changes |

The three change cases are built to reach all three decision states:

| Case | Result | Why |
| --- | --- | --- |
| **CH-01** chiller substitution | `ENGINEER REVIEW` | Everything is evidenced, but weight +9.1 %, MCA +12.1 %, refrigerant charge +10.5 % and the site design dry-bulb (46 °C) exceeds the proposed unit's rated ambient (35 °C) |
| **CH-02** fan-wall running change | `FIRST-PASS CHECKS CLOSED` | Like-for-like: every gate closes, every delta is inside its threshold, nothing downstream is affected |
| **PDU-3** substitution | `NEEDS INFORMATION` | The submittal arrived without weight, dimensions or electrical data — the platform records gaps instead of assuming values |

---

## Demo mode vs live mode

| Capability | Demo (default) | Live (when configured) |
| --- | --- | --- |
| Physical-world data | `MockMireyeClient` — deterministic, every value labelled **synthetic** | `LiveMireyeClient` — `MIREYE_BASE_URL` + `MIREYE_API_KEY`, with timeouts, retries, caching and mock fallback |
| Impact graph | In-memory graph store | Neo4j — `NEO4J_URI/USER/PASSWORD` |
| Retrieval | Hybrid BM25 + local hashed-ngram vectors over SQLite | pgvector — `DATABASE_URL` |
| Storage | SQLite (`apps/api/var/wetstack.db`) | Postgres / Supabase — `DATABASE_URL` |
| Explanations & planning | Deterministic templates | OpenAI — `OPENAI_API_KEY`, or Gemini — `GEMINI_API_KEY` |
| Agent tracing | off | LangSmith — `LANGSMITH_API_KEY` |

The UI shows a persistent **Demo mode** banner naming the adapter in use for each service, and every
synthetic value is badged wherever it appears. Live services degrade back to their local
implementation on failure, and the degradation is visible rather than silent.

See [`docs/live-vs-demo.md`](docs/live-vs-demo.md).

---

## Repository layout

```
apps/api/            FastAPI backend
  app/domain.py        shared domain model (all 19 required schemas)
  app/fields.py        Mireye field catalog + normalisation specs
  app/engine/          deterministic logic: units, scoring, deltas, gates, impact, decisions
  app/adapters/        mireye, graphstore, vectorstore, llm — each live + local
  app/services/        evidence, ingest, sites, changes
  app/agent/           LangGraph workflow + supervisor planner
  app/routers/         typed HTTP API
apps/web/            React + TypeScript + Vite + Tailwind frontend
tests/               122 tests (unit, adapter, API, end-to-end)
sample_data/         synthetic source PDFs (generated on first seed)
scripts/dev.py       one-command install / seed / run / verify
infra/               docker-compose (pgvector + Neo4j), render.yaml
docs/                architecture, domain model, API, Mireye contract, scoring, rules, walkthrough
```

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | System architecture, agent workflow, diagrams |
| [`docs/domain-model.md`](docs/domain-model.md) | Every schema and the evidence lifecycle |
| [`docs/api.md`](docs/api.md) | Endpoint reference and frontend contract |
| [`docs/mireye-contract.md`](docs/mireye-contract.md) | The assumed Mireye request/response contract and how to correct it |
| [`docs/datasets.md`](docs/datasets.md) | Public datasets in use, and step-by-step procedures for the data that still has to be sourced by hand |
| [`docs/scoring.md`](docs/scoring.md) | Site scoring formulas, weights and worked examples |
| [`docs/engineering-rules.md`](docs/engineering-rules.md) | Verification gates, delta thresholds, impact rules, decision precedence |
| [`docs/live-vs-demo.md`](docs/live-vs-demo.md) | What changes when credentials are supplied |
| [`docs/demo-walkthrough.md`](docs/demo-walkthrough.md) | A 6-minute scripted demo of both workflows |
| [`docs/limitations.md`](docs/limitations.md) | Assumptions, safety limits and production hardening |
| [`docs/verification-report.md`](docs/verification-report.md) | Requirement coverage, commands run, defects found and fixed |
| [`docs/research-basis.md`](docs/research-basis.md) | Prior work, verified citations, the Procore patent finding, and the minimum agent set |
| [`docs/deployment.md`](docs/deployment.md) | Vercel + Render setup, environment variables, ephemeral-storage behaviour, smoke tests |
| [`IMPLEMENTATION_CHECKLIST.md`](IMPLEMENTATION_CHECKLIST.md) | Build checklist |

## Deployment

Full instructions, environment variables and smoke tests: **[`docs/deployment.md`](docs/deployment.md)**.

* **Frontend → Vercel:** root directory `apps/web`; set `VITE_API_BASE_URL` to the Render origin.
  Config in [`apps/web/vercel.json`](apps/web/vercel.json). A production build *fails* if that URL
  points at localhost or is not `https://`.
* **Backend → Render:** [`render.yaml`](render.yaml) at the repository root (Render only detects a
  Blueprint there). Set `CORS_ORIGINS` to the Vercel origin — there is no wildcard. All service
  credentials are optional; with none set the deployment runs the same demo mode as a local checkout.
* **Smoke test a deployment:** `python scripts/smoke_test.py --api <api-origin> --origin <web-origin>`.
* **Local live infrastructure:** `docker compose -f infra/docker-compose.yml up -d`.

> **Render's filesystem is ephemeral.** The SQLite database and every uploaded PDF are destroyed on
> each deploy and restart; the demo re-seeds itself automatically. That is fine for a demo and is not
> production persistence — see [`docs/deployment.md`](docs/deployment.md) §5.

Secrets never reach the browser: the frontend only ever talks to this backend, which holds the
Mireye, Supabase, Neo4j and LLM credentials.
