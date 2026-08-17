# Verification report

What was actually executed against this build, and what was observed. Anything not listed here was
not verified — see [`limitations.md`](limitations.md) for the gaps.

Environment: Windows 11, Python 3.13.13, Node 24.18.0, no external credentials configured
(`demo_mode = true`; Mireye mock, in-memory graph, hybrid lexical + local vectors, SQLite,
deterministic narrator).

## 1. Automated suites

| Check | Command | Result |
| --- | --- | --- |
| Backend tests | `python -m pytest tests -q` | **122 passed** |
| Backend lint | `ruff check .` (repo root and `apps/api`) | clean |
| Frontend types | `npm run lint` (`tsc --noEmit`) | clean |
| Frontend build | `npm run build` | built, 791 kB / 224 kB gzipped |
| All of the above | `python scripts/dev.py --check` | "All checks passed." |

Test coverage by area: units (10), scoring and ranking (13), deltas (12), verification gates and
decision precedence (22), evidence provenance, status lifecycle and Mireye adapter failure/retry/
cache/fallback (17), impact derivation, stale propagation and graph traversal (11), ingestion,
extraction and retrieval (14), API contract and both end-to-end workflows (23).

## 2. Packaging

`pip install -e ".[dev]"` succeeds from a clean virtualenv and `pip show wetstack-mireye-api`
reports an editable install at `apps/api`. This is the command the README and `scripts/dev.py` both
use; it required declaring `[build-system]` and `[tool.setuptools.packages.find]` because the
runtime writes `var/` next to `app/`, which makes setuptools' flat-layout auto-discovery refuse to
build.

## 3. API behaviour (HTTP, against a running server)

| Scenario | Observed |
| --- | --- |
| `GET /api/ready` | `ready: true`; store ok, Mireye ok (34 fields, mode=mock), graph in_memory, vector hybrid(lexical+local_vector), seeded yes |
| Site investigation | 5 candidates scored: Cascade Flats 92.94 (low) → Rio Verde Mesa 72.93 → Prairie Junction 70.85 → Harbour Point 66.71 → Delta Fields 58.27 (high) |
| CH-01 analysis | `ENGINEER REVIEW`, 5 stale assumptions, 6 impacts, graph 35 nodes / 47 edges / 24 paths |
| CH-02 analysis | `FIRST-PASS CHECKS CLOSED`, 0 impacts, graph holds the change node only |
| PDU-3 analysis | `NEEDS INFORMATION`, replan adds a blocked step per open gate |
| **Re-analysis idempotency** | CH-01 run twice: identical `stale=5, impacts=6, nodes=35, edges=47`, and the project gap count stayed at 2 (no duplicates) |
| **Graph after a restart** | With the process restarted and the in-memory graph empty, `GET /api/impact/{id}` rebuilt 35 nodes / 47 edges / 24 paths from the stored analysis, with node kinds `activity, assumption, change, commissioning, discipline` |
| Never-analysed change | still `404` |

## 4. Browser session

Driven with Chrome (headless) via puppeteer-core against the dev server, listening for `pageerror`
and console errors throughout.

| Step | Observed |
| --- | --- |
| Initial load | Demo-mode banner present, project header renders |
| Before Construction | Investigation runs; 5 ranking rows; decision card, comparison sentences, gap panel, activity timeline all populated |
| During Construction | First case is CH-01; analysis reaches `ENGINEER REVIEW`; stale badges shown; impact graph header reads `in_memory · 35 nodes · 47 edges` |
| Units | Footprint renders `m²`, not `m ** 2` |
| Extraction | `R-134a` is not misread as `-134 A` |
| Console | **zero** page errors and zero console errors on the final run |

Screenshots were captured for the ranking view, the CH-01 analysis and the CH-02 contrast case
during the session; they are not committed.

## 5. Defects found and fixed during verification

| Defect | How it surfaced | Fix |
| --- | --- | --- |
| Upload wrote a client-controlled filename onto a path | code review | `safe_filename()` strips directory components |
| One flat graph store let a change traverse into another change's nodes (node ids are content-derived and therefore shared) | code review | one isolated sub-graph per change, replaced on re-analysis |
| Graph node ids used `hash()`, salted per process | code review | blake2b slug |
| Re-analysis reported 0 stale assumptions and dropped the graph's assumption layer | code review | `mark_stale_assumptions` returns every invalidated assumption |
| Re-analysis appended duplicate gaps | code review | stable `(project, subject, field)` gap id, preserving human triage |
| A restarted API showed "no downstream impact" for a change with 6 impacts | browser session after a restart | `/api/impact/{id}` rebuilds from the stored analysis on a miss |
| `float(obs.value)` on non-numeric site data | code review | non-numeric is unverifiable evidence, never an implicit zero |
| `R-134a` extracted as `-134 A` | browser session | identifiers matched before measurements |
| Orphaned server held port 8000, so an earlier check hit a stale process | background task exited `[Errno 10048]` | process killed; every later check ran against a single known server |

## 6. Not verified

* No frontend component tests and no committed browser end-to-end suite — the browser run above was
  driven manually for this pass and is not in CI.
* Live mode is unexercised: no Mireye, Supabase/pgvector, Neo4j or LLM credentials were available,
  so only the adapter fallback paths (and their unit tests with mocked transports) were run.
* No load, concurrency or security testing beyond the input-validation tests in the suite.
* Deployment configs (`vercel.json`, `render.yaml`) are written but were not deployed.
