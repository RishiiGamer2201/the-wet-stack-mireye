# Verification report

Independent QA pass over the prototype, run against
`The Wet Stack - Mireye Documentation.pdf` rather than against the previous
implementation summary. Everything recorded here was executed; nothing is
inferred from reading the code alone.

**Date:** 2026-08-17 · **Platform:** Windows 11, Python 3.13.13 (`apps/api/.venv`), Node 24.18.0,
headless Chromium driven from a script · **Mode:** demo (no credentials configured).

The numbers in §3–§5 were re-checked against a live API after the report was written; every
ranking, gate tally, delta tally, gap count and rank change below reproduced exactly. The
clean-checkout run in §2 was also repeated independently: 86 tracked files exported to an empty
directory, `python scripts/dev.py --check` created the virtualenv, installed both dependency sets,
generated the three synthetic PDFs, seeded the database and reported **122 passed / lint clean /
type-check clean / build succeeded**.

---

## 1. Requirement coverage

Every requirement below is taken from the PDF and mapped to the code that implements it and
the check that proves it.

### 1.1 Problem statement and the two workflows (PDF p.1)

| Requirement | Implementation | Verified by |
| --- | --- | --- |
| Pre-construction site viability across terrain, water, agriculture, power, connectivity, hazards, civil complexity, regulatory | `app/fields.py` — 34 fields over 8 `SiteDimension`s; `app/engine/scoring.py` | `GET /api/meta` → `mireye_field_count: 34`; all 8 dimensions scored for Cascade Flats (§4.1) |
| During-construction change understanding by connecting spec, drawings, schedules, manufacturer data, site info and code | `app/services/changes.py` joins requirements, equipment configs, site observations and gates | CH-01 run: capacity requirement (spec) + configs (datasheet/submittal) + `ambient_design_db_c` (Mireye) all reach one decision |
| Fragmentation resolved by an agent deciding what evidence is needed | `app/agent/planner.py` builds a case-specific plan | PDU-3 plan differs from CH-01's; replan adds steps only for what was OPEN (§4.3) |
| Two workflows connected — the physical site becomes engineering context | `gates.gate_site_compatibility` | CH-01 TRIGGERED because Rio Verde Mesa's 46 °C design dry-bulb exceeds the proposed unit's 35 °C rating (§5.2) |

### 1.2 Features 1–6 (PDF p.2)

| # | Feature | Implementation | Verified by |
| --- | --- | --- | --- |
| 1 | Site intelligence: score, explain risks, suggest lower-risk alternatives | `engine/scoring.py` (`score_site`, `rank`, `compare`) | Ranking + per-dimension explanations + "Why this order" comparisons (§4.1) |
| 2 | Identify replaced equipment, verify comparability, compute true deltas in weight, load, dimensions, electrical, refrigerant, operating conditions | `engine/gates.py`, `engine/deltas.py` | 15 deltas per change; all 11 numeric deltas recomputed by hand and matched (§5.1) |
| 2 | Flag structural coordination **without** claiming adequacy | `deltas.structural_coordination_required`, `impact.RULES[structural_coordination]` | Impact detail contains "does not assess structural adequacy"; caveat present on every recommendation (§6) |
| 3 | Situation-specific plan, not a fixed checklist | `agent/planner.py`, `agent/workflow.py` | CH-01 plan has weight/refrigerant/electrical/site steps; CH-02 fewer; PDU-3 gains 2 replan steps (§4.3, §5.3) |
| 3 | Impact tracing across structural, electrical, cooling, controls, installation, commissioning | `engine/impact.py` (6 rules) | CH-01 → 6 impacts over 5 disciplines, graph reaches commissioning (§5.2) |
| 4 | Extract requirements from specs/schedules/submittals/drawings; capability data from datasheets; Mireye facts on demand | `services/ingest.py`, `adapters/mireye.py` | Upload of a 3-page spec → 3 chunks, 12 candidate requirements with page + span (§7.4) |
| 4 | Every fact source-traceable; only relevant fields retrieved | `domain.Evidence`/`EvidenceSource`; `fields.broad_fields()`/`deep_fields()` | Evidence drawer shows source, endpoint, page, span, time, confidence, coordinates (§4.2); 24 broad fields for all 5 sites, 10 deep fields only for the 2 shortlisted |
| 5 | Track source, time, location and status per observation; explicitly mark missing data | `EvidenceStatus` (live/cached/synthetic/user_confirmed/missing/stale) | Missing fields render "no value — not substituted"; score excludes them (§4.2) |
| 5 | Compare manufacturer evidence with site conditions; identify gaps; mark assumptions stale | `gate_site_compatibility`, `impact.mark_stale_assumptions` | 5 of 6 CH-01 assumptions STALE with the reason naming the delta (§5.2) |
| 6 | Validate model identity, values, units, configuration, rating conditions, sources and location before accepting a comparison | 9 gates in `engine/gates.py` | All 9 exercised across the three cases (§5) |
| 6 | Convert findings into RFIs, vendor evidence requests or review comments, classified `FIRST-PASS CHECKS CLOSED` / `NEEDS INFORMATION` / `ENGINEER REVIEW` | `engine/decisions.py` | All three states reached, each with the matching action type (§5) |

### 1.3 Tech stack (PDF p.2)

| Required | Present | Evidence |
| --- | --- | --- |
| React, TypeScript, Vite, Tailwind, shadcn-style UI, MapLibre/Leaflet, Recharts, Lucide | yes (`apps/web`) | `npm run build` succeeds; Leaflet map, Recharts bar/radar, Lucide icons all render (§7) |
| Python, FastAPI, Pydantic, Uvicorn | yes | `/openapi.json` generated; 122 tests |
| LangGraph orchestrating Understand → Plan → Evidence → Signals → Replan → Impact → Action | `agent/workflow.py` | Investigation payload reports `orchestrator: "langgraph"`; phase rail walks all seven phases |
| LLM for extraction/investigation/explanation/RFI drafting | `adapters/llm.py` (Anthropic, optional) | Absent by design in demo mode: `llm_mode: "deterministic"`, deterministic templates used |
| PyMuPDF/Docling + PostgreSQL/pgvector for RAG | PyMuPDF + `PgVectorIndex`; local hybrid fallback | `/api/ready` → `vector: hybrid(lexical+local_vector)` |
| Neo4j knowledge graph for impact tracing | `Neo4jGraphStore`; `InMemoryGraphStore` fallback | `/api/ready` → `graph: in_memory`; identical traversal contract |
| Python + Pint for units, scoring, thresholds — **not the LLM** | `engine/units.py` and the rest of `engine/` | §6, and every numeric assertion in §5.1 |
| Supabase Postgres/Storage, Neo4j Aura, Vercel, Render/Railway | `infra/render.yaml`, `apps/web/vercel.json`, `infra/docker-compose.yml` | Config present; not deployed as part of this pass |

### 1.4 Mireye API surface (PDF p.5)

All nine documented endpoints are modelled in `adapters/mireye.py` with both a live HTTP client and
a deterministic mock: `/v1/meta/fields`, `/v1/geocode`, `/v1/fetch`, `/v1/ask`, `/v1/ask/stream`,
`/v1/sites`, `/v1/sites/{id}`, `/v1/ask-site`, `/v1/feature-requests`.

* **Catalog is authoritative** — a field outside the catalog is rejected, never invented:
  `fetch_site_fields(..., ["not_a_real_field"])` → *"rejected unsupported field request"*.
* **`/fetch` for calculation, `/ask` for exploration** — the ask endpoint's response carries
  *"Exploratory answer. Scores and engineering checks use /v1/fetch fields only."*
* **`/v1/feature-requests` instead of hallucinating** — Prairie Junction's two unavailable fields each
  carry a `feature_request_id`, shown in the gap panel.
* The assumed payload shapes are isolated in that one module and documented in
  [`mireye-contract.md`](mireye-contract.md).

### 1.5 Two-week plan deliverables (PDF pp.5–6)

Days 1–2 schemas and field catalog · 3–4 RAG + extraction + a requirement-confirmation UI ·
5 MireyeTool with source/timestamp/confidence/status and cache/fallback · 6–7 before-construction
with progressive investigation · 8–10 deltas with `CLOSED/OPEN/TRIGGERED/SKIPPED` and the
verification gate · 11 `Change → Stale assumption → Discipline → Activity → Commissioning` ·
12 unified UI with evidence viewer and agent history · 13 failure testing plus 3 cases and 5 sites —
**all present and exercised below.**

---

## 2. Commands executed

```bash
# one-command path, from a clean checkout
python scripts/dev.py --check          # installs, seeds, then runs everything below

# backend
apps/api/.venv/Scripts/python -m pytest tests -q          # 122 passed
apps/api/.venv/Scripts/python -m ruff check app tests scripts   # All checks passed

# frontend
npm run lint          # tsc --noEmit, clean
npm run build         # vite build, 2249 modules, 791 kB / 224 kB gzip

# servers
apps/api/.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
npm run dev                                               # http://localhost:5173
```

**Clean-checkout run.** Every tracked file was copied to an empty directory (no `.venv`, no
`node_modules`, no `var/`, no generated sample PDFs) and `python scripts/dev.py --check` was run
there: it created the virtualenv, installed both dependency sets, generated the three synthetic
PDFs, seeded the demo project and reported **122 passed / lint clean / type-check clean / build
succeeded**.

---

## 3. Results

| Check | Result |
| --- | --- |
| Backend tests | **122 passed**, 0 failed |
| Backend lint (ruff: E, F, I, UP, B) | clean |
| Frontend type-check (`tsc --noEmit`, strict) | clean |
| Frontend production build | succeeded (791 kB / 224 kB gzip, one chunk) |
| `/api/health`, `/api/ready` | `ok`; store ok, mireye ok (34 fields, mock), graph in_memory, vector hybrid, seeded yes |
| Browser console over the full walkthrough | **0 errors, 0 warnings** |
| Failed network requests (normal operation) | **0** |
| HTTP ≥ 400 (normal operation) | **0** |

Test distribution (`pytest --collect-only`): API contract and both end-to-end workflows 28 ·
verification gates and decision precedence 22 · evidence provenance, status lifecycle and Mireye
adapter retry/cache/fallback 15 · ingestion, extraction and retrieval 14 · scoring and ranking 12 ·
deltas 11 · impact derivation, stale propagation and graph traversal 11 · units 9.

---

## 4. Before Construction — verified behaviour

### 4.1 Candidate-site ranking

Run through the UI (`Run investigation`), cross-checked against `POST /investigations/site`:

| Rank | Site | Score | Risk | Coverage | Confidence | Missing |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Cascade Flats | 92.94 | low | 100 % | 43 % | 0 |
| 2 | Rio Verde Mesa | 72.93 | high | 100 % | 43 % | 0 |
| 3 | Prairie Junction | 70.85 | elevated | 65 % | 34 % | 12 |
| 4 | Harbour Point | 66.71 | high | 75 % | 37 % | 10 |
| 5 | Delta Fields | 58.27 | high | 75 % | 37 % | 10 |

**Independent recomputation.** The scoring formula was re-implemented from `docs/scoring.md`
(normalisation, weighted dimension mean, weighted overall) in a separate script and run against the
raw observation values returned by the API. All eight dimension scores and the overall score matched
to floating-point precision:

```
geo_terrain 94.624 | water 92.538 | power 97.908 | connectivity 95.774
civil_soil  98.427 | hazards 77.478 | environmental 95.947 | regulatory 90.216
OVERALL mine=92.9423  api=92.94   MATCH
```

Risk levels were re-derived by hand and match the ladder in `scoring.risk_level`: Rio Verde Mesa is
`high` despite a 72.9 score because water stress 4.4 misses the 3.5 target by 25.7 % (critical) —
i.e. a hard target failure outranks a good aggregate.

**Frontend vs raw API.** The values in the ranking table, the bar chart and the radar chart are the
same numbers the API returned; the browser performs no arithmetic beyond `toFixed`. Verified by
capturing the `/ranking` response body in the browser and diffing it against the rendered table.

### 4.2 Evidence and missing data

* Evidence drawer shows, per item: claim, value + unit, status badge, source type and name,
  endpoint, page/character span where applicable, retrieved time, observed time, confidence,
  coordinates + location resolution, verification state and the synthetic-value note.
* Prairie Junction shows **12 metrics as `missing`**, each rendered "No evidence — excluded from the
  score", and its coverage drops to 65 % — the score is never padded with a zero.
* The *Missing information* panel lists the two fields Mireye could not supply
  (`grid_capacity_mw`, `wetland_fraction`), each with why it matters, expected source, suggested
  action and the **Mireye feature-request id** filed instead of a guess.
* Requirement flags with no evidence report `passed: null` ("cannot be verified"), never `false`
  and never an assumed pass.

### 4.3 Scoring-weight changes

Driven through the real slider in the browser; the ranking is recomputed on the backend against the
same stored evidence:

| Weights | Result |
| --- | --- |
| default | Cascade 92.9, Rio Verde 72.9, Prairie 70.8, Harbour 66.7, Delta 58.3 |
| `water → 0` | Cascade 93.0, Rio Verde 80.3, **Harbour 69.8 (rank 4→3)**, **Prairie 69.2 (rank 3→4)**, Delta 55.2 |
| `hazards_climate → 3.0` | Cascade 90.5, Rio Verde 75.0, Harbour 72.0, Prairie 71.0, Delta 54.9 |

The blue *Effect of the change* panel names each rank change. Rejected inputs: a negative weight
returns 422 with `dimension weights must be >= 0`; an unknown dimension key returns a 422 enumerating
the eight valid keys.

### 4.4 Replan loop

The site investigation plans 4 steps, then re-plans: *"Broad pass separated the field; deepening only
on Cascade Flats, Rio Verde Mesa with 10 additional field(s)."* The deep pass is issued for the two
shortlisted sites only — confirmed by the per-site tool events and by Prairie Junction still showing
its 10 deep fields as `missing`.

---

## 5. During Construction — verified behaviour

### 5.1 CH-01 → ENGINEER REVIEW

Gates: 8 CLOSED, **`site_compatibility` TRIGGERED**. 11 results exceed a threshold. Confidence 65 %.

Every numeric delta was recomputed by hand from the raw configuration values and matched the API to
3 decimal places:

| Field | Old → new | Recomputed Δ% | API Δ% | Status |
| --- | --- | --- | --- | --- |
| Operating weight | 4850 → 5290 kg | 9.0722 | 9.072 | TRIGGERED |
| Max support-point load | 12.1 → 13.2 kN | 9.0909 | 9.091 | TRIGGERED |
| Length | 6800 → 7100 mm | 4.4118 | 4.412 | TRIGGERED |
| Height | 2450 → 2600 mm | 6.1224 | 6.122 | TRIGGERED |
| Footprint area | 15.300 → 15.975 m² | 4.4118 | 4.412 | TRIGGERED |
| Full load amps | 240 → 268 A | 11.6667 | 11.667 | TRIGGERED |
| MCA | 265 → 297 A | 12.0755 | 12.075 | TRIGGERED |
| MOCP | 350 → 400 A | 14.2857 | 14.286 | TRIGGERED |
| Power input | 310 → 336 kW | 8.3871 | 8.387 | TRIGGERED |
| Refrigerant charge | 210 → 232 kg | 10.4762 | 10.476 | TRIGGERED |
| Cooling capacity | 1050 → 1055 kW | 0.4762 | 0.476 | **CLOSED** (inside the 2 % threshold) |

Width is unchanged (0 %, CLOSED); voltage, phases and refrigerant type are unchanged categoricals.

Decision confidence was also re-derived: 24 of 24 checks+deltas evaluated → base 1.0; evidence is
100 % synthetic → `1.0 × (1 − 0.35 × 1.0) = 0.65`, matching the reported 0.65.

### 5.2 CH-01 impact and stale assumptions

* **5 of the 6 CH-01 assumptions go STALE**, each naming the evidence that changed
  (e.g. *"Upstream evidence changed: Operating weight: 4850 kg → 5290 kg (440 kilogram, +9.1 %);
  |Δ| 9.1 % exceeds the 5 % coordination threshold"*).
* The sixth (BMS points list) correctly stays **active** — it depends on model identity and
  configuration comparability, and both gates CLOSED.
* 6 impacts across structural, electrical, mechanical (×2), installation-logistics and controls.
* Impact graph: 35 nodes, 47 edges, 24 traced paths, reaching commissioning nodes.
* Site link verified: the Rio Verde Mesa design dry-bulb of **46 °C** (Mireye evidence from
  workflow 1) exceeds the proposed unit's rated **35 °C**, which is what TRIGGERS the gate.

### 5.3 CH-02 → FIRST-PASS CHECKS CLOSED and PDU-3 → NEEDS INFORMATION

| | CH-02 | PDU-3 |
| --- | --- | --- |
| Gates | 7 CLOSED, 2 SKIPPED (no site linked) | 2 OPEN, 3 CLOSED, 4 SKIPPED |
| Deltas | 14 CLOSED, 1 SKIPPED | 6 OPEN, 2 CLOSED, 7 SKIPPED |
| Gaps | 0 | **8**, all blocking |
| Impacts | 0 — empty-graph state renders "No downstream impact" | 0 |
| Replan | not needed | **2 steps added**, each BLOCKED pending external evidence |
| Next action | engineer sign-off | vendor evidence request + RFI |

PDU-3's structural assumption stays **active**, not stale: the proposed weight is unknown, so the
platform declines to conclude in either direction. That is the missing-data rule working in the
direction that is easy to get wrong.

### 5.4 Generated next actions

Each drafted action names its recipient, due date, the exact missing items and the conditions each
value must be stated at, and carries the safety caveat. Types observed: `review_comment`,
`human_confirmation`, `vendor_evidence_request`, `rfi`, `clarification_request`.

---

## 6. Product rules — explicitly re-tested

| Rule | Evidence |
| --- | --- |
| **Missing data never becomes zero** | Site with no evidence at all → `overall_score: null`, `rank: null`, risk `high` (not 0/100). Unknown unit → delta `OPEN`, `percent_delta: null`. Both sides missing → `SKIPPED`. Non-numeric override → metric excluded and the target flag reads `passed: null`. |
| **Deterministic software calculates and verifies** | All 11 CH-01 deltas, all 8 dimension scores, the overall score and the confidence figure reproduced by hand from the documented formulas. No LLM is configured in demo mode (`llm_mode: "deterministic"`). |
| **LLM may investigate and explain, never calculate** | `_llm_explain` only appends prose to an already-computed `Recommendation`; `_llm_extra_steps` discards any field key not in the catalog. Neither path can write a number into a score, delta, threshold or decision state. |
| **Structural coordination flagged, adequacy never claimed** | `structural_coordination_required` fires only on an *increase* past threshold; impact detail and every recommendation caveat state "does not assess structural adequacy and does not constitute engineering approval". |
| **Synthetic evidence clearly labelled** | Persistent amber demo banner naming each adapter; `synthetic` badges on project, sites, changes and documents; amber *Synthetic demo* status on every value; "Deterministic demo value — not a real observation" in the drawer; synthetic share drags decision confidence down to 0.65. |
| **Works without external credentials** | Fresh checkout with no `.env`: mock Mireye, in-memory graph, hybrid local retrieval, SQLite, deterministic narrator. Both workflows complete end to end. |

---

## 7. Failure cases tested

### 7.1 API and network

| Scenario | Behaviour |
| --- | --- |
| API unavailable (all `/api/**` aborted) | Full-width alert: *"Cannot reach the API. Is the backend running on http://127.0.0.1:8000?"* with a **Try again** button; retry recovers cleanly |
| API returns 500 on one endpoint | Error surfaced in an `role="alert"` region with the server's detail; the rest of the page keeps working |
| Mireye call fails (`MireyeUnavailableError`) | *"Mireye unavailable (connection refused); 2 field(s) recorded as gaps rather than assumed"* — 2 gaps, **0 evidence**, no substituted values |
| Live Mireye degrades | `FallbackMireyeClient` switches to mock, records `degraded_reason`, and `/api/meta` reports the adapter actually in use rather than the configured one |

### 7.2 Malformed requests

| Request | Response |
| --- | --- |
| `GET /api/projects/nope` | 404 + "seed the demo data with POST /api/admin/seed" |
| Site with neither address nor coordinates | 422 "provide an address, or both latitude and longitude" |
| Site with latitude 999 | 422 field-level validation error |
| Negative dimension weight | 422 "dimension weights must be >= 0" |
| Unknown dimension key | 422 listing the eight valid keys |
| Override of an unknown field | 422 "unknown field 'bogus'" |
| Search query shorter than 2 chars | 422 |
| Invalid gap status | 422 "invalid status 'bogus'" |
| Analyse / impact for an unknown change | 404 with an actionable message |
| Question shorter than 4 chars | 422 |

### 7.3 Documents

| Upload | Result |
| --- | --- |
| `.txt` | 422 "unsupported content type 'text/plain'; allowed: application/pdf" |
| Empty file | 422 "uploaded file is empty" |
| Corrupt PDF | 422 "extraction failed for broken.pdf: could not read PDF…"; the rejected file is deleted and **no server path is leaked** |
| Scanned/image-only PDF | 201 with `extraction_status: "failed"` and "No extractable text found. The PDF is probably a scan; OCR is not enabled." |
| Unknown `kind` form field | 422 listing the valid kinds |
| Filename `../../../pwn.pdf` | Stored as `pwn.pdf` **inside** `var/uploads/` — see defect D1 |
| Valid 3-page spec | 201, 3 chunks, 12 candidate requirements with page + span |

### 7.4 Engineering edge cases

| Scenario | Behaviour |
| --- | --- |
| Incompatible units (kg vs kW) | `IncompatibleUnitsError`; delta `TRIGGERED` with no number; `gate_units` TRIGGERED at severity `critical` |
| Unparseable unit | `UnknownUnitError`; delta `OPEN` + an InformationGap — treated as missing information, not a failed comparison |
| Zero baseline | `percent_delta: null`, reported as undefined |
| Stale observation (>180 days) | Status flips to `stale`, the **value is kept**, reason recorded; `gate_site_compatibility` refuses to use it and returns `OPEN` |
| Non-numeric site value | Gate returns `OPEN`, metric excluded — no crash, no zero |
| Unknown Mireye field requested | Rejected before the call: "unknown Mireye field(s): not_a_real_field" |
| Empty impact graph | "No downstream impact — no deterministic check was triggered by this change" |
| Optional integrations absent | Neo4j → in-memory, pgvector → local hybrid, Anthropic → deterministic templates, Postgres → SQLite; all named in the demo banner and in `/api/ready` |

### 7.5 Frontend robustness

* **Page refresh** — reloads cleanly, re-bootstraps, no errors. The app has no router, so the tab
  resets to *Before construction* (see L1).
* **Direct navigation** to `/during/CH-01` — Vite's SPA fallback serves the app (HTTP 200) and it
  renders; the deep path is not interpreted (L1).
* **Responsive** — at 390 × 844 the page has **no horizontal overflow** (`scrollWidth` 390); wide
  tables and the impact graph scroll inside their own containers.
* **Loading states** — spinners with `role="status"` for investigation, analysis and evidence
  loading; buttons disable and show a spinner while busy.
* **Empty states** — "No investigation has run yet", "This change has not been analysed yet",
  "No open information gaps", "No downstream impact", "No requirements extracted", all with the
  action that resolves them.
* **Accessibility** — one `<h1>`, `lang="en"`, `role="tablist"`/`tab` with `aria-selected`,
  `role="dialog"` + `aria-modal` drawer that closes on Escape, `<caption class="sr-only">` on every
  table, labels on **every** input/select (0 unlabelled), 0 buttons without an accessible name,
  a visible 2 px focus ring on the first tab stop, and a `prefers-reduced-motion` block.
  The only images without `alt` are the 8 Leaflet basemap tiles injected by the map library.

---

## 8. Defects found and fixed

Severity is relative to the demo and to the product's own safety claims.

| # | Sev | Defect | Fix |
| --- | --- | --- | --- |
| **D1** | High (security) | **Path traversal on document upload.** The client-supplied filename was joined straight onto the upload directory. Uploading `../../../pwn.pdf` wrote to `apps/api/var/pwn.pdf`, outside `var/uploads/`. Reproduced before the fix. | `services/ingest.safe_filename()` reduces any name to its final path segment, sanitises the remainder and caps its length; the router uses it before touching the filesystem. Test: `test_safe_filename_strips_any_path_component`, `test_upload_endpoint_cannot_write_outside_the_upload_directory`. |
| **D2** | High | **Re-analysing a change reported 0 stale assumptions.** `mark_stale_assumptions` returned only assumptions that *transitioned* on that run, so the second analysis of CH-01 returned an empty list — the UI badge read "0 stale" and the impact graph lost its assumption layer. Re-running is the most likely demo action. | It now returns every assumption the change invalidates, while still leaving an already-stale one's reason and timestamp untouched. Tests: `test_stale_is_idempotent` (rewritten), `test_reanalysis_is_idempotent`. |
| **D3** | High | **Information gaps duplicated on every run.** Gap ids were random, so re-analysing PDU-3 three times produced 24 gap records instead of 8, and each site investigation added two more. The header's "open gaps" count grew without bound. | Gap ids are now derived from `(project, subject, field)` (`domain.gap_id`), so a re-run updates one record. A new `put_gap` helper preserves any triage a human already applied (`requested`/`resolved`) and the original creation time. Tests: `test_reanalysis_is_idempotent`, `test_repeat_site_investigation_does_not_multiply_gaps`, `test_triaged_gap_keeps_its_status_across_a_reanalysis`. |
| **D4** | High | **In-memory impact graph accumulated forever.** `InMemoryGraphStore.upsert` merged into one flat node/edge map and never removed a change's previous graph, so CH-01 grew from 47 to 52 edges on re-analysis and superseded impacts survived a correction — diverging from `Neo4jGraphStore`, which does `DETACH DELETE`. | One isolated sub-graph per change, replaced on upsert. Traversal also refuses to revisit a node on the same path. Test: `test_reanalysis_replaces_a_change_subgraph_instead_of_growing_it`. |
| **D5** | High | **`pip install -e ".[dev]"` failed** — the README's own setup step — once `apps/api/var/` existed, because setuptools flat-layout discovery found two top-level packages. A clean checkout worked; any re-install did not. | `[tool.setuptools.packages.find] include = ["app*"]` plus an explicit `[build-system]`. Verified by a full clean-checkout install. |
| **D6** | Medium | **Impact-graph node ids were built from `hash()`**, which is salted per process, so the "deterministic" graph differed after every restart (and would orphan previously stored Neo4j nodes). | Content-derived `blake2b` ids. Test: `test_node_ids_are_stable_across_processes` runs a second interpreter with a different `PYTHONHASHSEED` and compares. |
| **D7** | Medium | **Change ordering was inconsistent.** `GET /projects/{id}` returned changes in `updated_at` order while `GET /changes` used creation order, so after analysing CH-01 the During Construction tab preselected CH-02 while the list showed CH-01 first. | Both endpoints sort by creation. Test: `test_changes_are_listed_in_the_same_order_everywhere`. |
| **D8** | Medium | **Reseeding left the previous project's ranking on screen.** The feature components kept `ranking`/`investigation`/`selectedId` across a project change, and `refresh()` only ever set them. | The feature components are keyed on the project id in `App.tsx`, so a project switch or reseed drops all derived state. Verified in the browser before and after. |
| **D9** | Medium | **Horizontal page overflow at 390 px** (`scrollWidth` 448). Two causes: the header's project `<select>` sized itself to the long project name, and cards are grid items whose default `min-width: auto` let the chart force the track wider. | `max-w`/`truncate` on the select, `min-w-0` on the shared `Card`. Re-measured: 390 on every view. |
| **D10** | Medium | **A corrupt PDF leaked the server's absolute path** into the 422 response, and the rejected file stayed on disk (on Windows PyMuPDF held a handle on it, so deleting it raised). | PDFs are opened from a byte stream rather than a path, which removes both the handle and the path from the message; the rejected file is then deleted. Test: `test_unreadable_upload_is_not_left_on_disk`. |
| **D11** | Medium | **A non-numeric value could crash scoring or a gate.** `check_requirements` and `gate_site_compatibility` called `float(obs.value)` unguarded, so a user override such as "n/a" on `grid_capacity_mw` would fail the request. | Both use an `_as_float` guard that treats a non-numeric value as *unverifiable evidence* — `passed: null`, metric excluded — never as zero. Test: `test_non_numeric_value_is_unverifiable_not_zero`. |
| **D12** | Medium | **An unavailable field outside the catalog would 500.** `record_fetch` built a `SiteObservation` with `dimension=None` for any key a live service reported as unavailable, which fails validation. | Unknown keys are logged and skipped. |
| **D13** | Medium | Dragging a weight slider fires one request per step and **responses could arrive out of order**, briefly showing a stale ranking. | A request sequence guard drops any response that is no longer the newest. |
| **D14** | Low | `DELETE /sites/{id}` deleted a site without checking it belonged to the project in the path. | Returns 404 for a site on another project. |
| **D15** | Low | `assumption.updated_at = assumption.updated_at` — a no-op, so a stale transition never updated its timestamp. | The timestamp is set when the assumption actually transitions. |
| **D16** | Low | The test suite wrote uploads into the developer's real `apps/api/var/uploads`. | `conftest` redirects `DATA_DIR` at `tmp_path`. |
| **D17** | Low | Documentation inaccuracies: test count (110 → 122); the walkthrough listed three gap fields for Prairie Junction when only two are raised (the third is a deep field that is never requested for an unshortlisted site); "five of seven assumptions" when six are shown for CH-01; delta percentages quoted at a precision the UI does not render. | README, `limitations.md` and `demo-walkthrough.md` corrected. |

**Also added:** `scripts/dev.py`, a stdlib-only one-command install/seed/run/verify path, and this
report.

---

## 9. Remaining limitations

These are known and deliberate, not defects introduced by this pass.

1. **No client-side routing (L1).** A refresh or a direct deep link always lands on
   *Before construction* and the selected change is not addressable. Adding a router is a genuine
   feature, not a fix, so it was left alone.
2. **The impact graph store is volatile.** `InMemoryGraphStore` is process memory. The API rebuilds
   a change's graph from its stored analysis when the store is empty, which was verified across a
   real process restart (35 nodes / 47 edges / 5 assumption nodes, identical) — but a graph is still
   only durable via the investigation record, not in its own right. Configure Neo4j for persistence.
3. **All demo data is synthetic.** Manufacturers, model numbers, performance data and every site
   fact are invented. This is labelled everywhere, and it caps decision confidence at 0.65.
4. **Extraction is regex + keyword based**, not an LLM or a layout model. It proposes requirements
   with a confidence and a source span and requires human confirmation; it will miss values in
   tables and in scanned documents (no OCR).
5. **Retrieval embeddings are hashed n-grams**, not semantic. Good enough for exact identifiers and
   near-paraphrases; a real embedding model is a drop-in via `PgVectorIndex`.
6. **The site scoring thresholds are illustrative.** The good/bad anchors in `fields.py` are
   defensible defaults, not client-calibrated values, and they drive the ranking directly.
7. **No authentication or authorisation.** Every project is world-readable and world-writable.
8. **Investigations run synchronously** inside the request. Fine at demo scale (a site investigation
   over five sites takes a few seconds); a real deployment needs a worker and streamed events.
9. **One JS bundle, no code splitting** (791 kB / 224 kB gzip).
10. **Map tiles need the network.** Markers are div icons and still render offline, but the basemap
    is blank. Tile `<img>` elements come from Leaflet without `alt` attributes.
11. **No frontend component or committed browser tests.** The browser scenarios in this report were
    driven manually against a headless browser from a throwaway script; neither the script nor the
    scenarios are committed, so they are not part of `dev.py --check`.
12. **The Mireye request/response shapes are an assumption**, isolated in `adapters/mireye.py` and
    documented in `mireye-contract.md`. They will need correcting against the real specification.

### What was *not* verified

* **Live mode is unexercised.** No Mireye, Supabase/pgvector, Neo4j or Anthropic credentials were
  available, so only the fallback paths ran for real. `LiveMireyeClient` retry, caching and
  degradation are covered by unit tests with mocked transports, not against a live service.
* **No load, concurrency or security testing** beyond the input-validation and traversal cases above.
  The SQLite store uses a single guarded connection and is not built for concurrent writers.
* **Deployment was not performed.** `vercel.json`, `render.yaml` and `docker-compose.yml` exist and
  are internally consistent, but nothing was deployed.
* **The browser scenarios are not automated in CI.** They were driven against a headless browser
  from a throwaway script for this pass; `dev.py --check` does not include them.

---

## 10. Exact demo instructions

### Start

```bash
git clone <repo> && cd mireye
python scripts/dev.py
```

This creates the backend virtualenv, installs both dependency sets, generates the three synthetic
source PDFs, seeds the demo project, and starts the API on <http://127.0.0.1:8000> and the UI on
<http://localhost:5173>. Ctrl-C stops both. Requires Python 3.11+ and Node 18+; **no API keys, no
Docker, no database.**

Useful variants:

```bash
python scripts/dev.py --reset      # wipe and re-seed the demo data first
python scripts/dev.py --check      # tests + lint + type-check + build, then exit
python scripts/dev.py --api-only   # backend only
python scripts/dev.py --ui-only    # frontend only
```

Two-terminal equivalent, if you prefer:

```bash
# terminal 1
cd apps/api && python -m venv .venv && .venv\Scripts\activate   # source .venv/bin/activate
pip install -e ".[dev]" && python -m app.seed --reset
uvicorn app.main:app --reload --port 8000

# terminal 2
cd apps/web && npm install && npm run dev
```

### Confirm it is healthy

Open <http://localhost:5173>. The amber banner must read:

```
Demo mode  Mireye: mock · graph: in_memory · vector: hybrid(lexical+local_vector) · store: sqlite · LLM: deterministic
```

Header should show *Aurora DC-1 — 48 MW hyperscale campus (synthetic demo)* with **5 sites,
3 documents, 41 requirements, 84 evidence items, 0 open gaps**.

### Six-minute script

**Before Construction (3 min)**

1. Click **Run investigation**. Watch the phase rail walk Understand → … → Done.
2. Read the ranking: Cascade Flats **92.9** (low risk), Delta Fields **58.3** (high risk).
   Open *Why this order* for the weighted per-dimension explanation.
3. Click **View** on Prairie Junction → the evidence drawer. Scroll to a `missing` item: it reads
   **"no value — not substituted"**.
4. Scroll to *Missing information*: 2 open gaps, each with a Mireye feature-request id.
5. Drag **Water** to 0. The backend re-scores; Harbour Point and Prairie Junction swap rank and the
   blue panel names the change.
6. In *Evidence detail*, pick a field, type a confirmed value, **Apply & re-rank** — stored as
   `user_confirmed` evidence with the previous record kept and marked superseded.

**During Construction (3 min)**

7. Switch tabs. Select **CH-01** → **Run analysis** → `ENGINEER REVIEW`.
   Site compatibility is TRIGGERED because the Rio Verde Mesa design dry-bulb (46 °C) exceeds the
   proposed unit's rated 35 °C — a workflow-1 site fact invalidating a workflow-2 equipment claim.
8. Deltas: weight +9.1 %, MCA +12.1 %, MOCP +14.3 %, refrigerant charge +10.5 %, capacity +0.5 %
   (CLOSED). Assumptions: 5 STALE, each naming the evidence that changed. Impact graph:
   35 nodes across five disciplines, reaching commissioning.
9. Select **CH-02** → **Run analysis** → `FIRST-PASS CHECKS CLOSED`, no impacts, empty graph.
10. Select **PDU-3** → **Run analysis** → `NEEDS INFORMATION`: 8 blocking gaps, 2 replan steps
    marked *added in replan*, and a drafted vendor evidence request. Note the PDU-3 structural
    assumption stays **active** — the new weight is unknown, so nothing is concluded.

**Project knowledge (30 s)**

11. Search `minimum circuit ampacity` — hybrid retrieval with page citations. "Ask Mireye" is
    labelled exploratory and excluded from every calculation.

### Reset between runs

```bash
curl -X POST http://127.0.0.1:8000/api/admin/seed     # or the "Reseed demo" button in the UI
```

Re-running any analysis is idempotent: the same gaps, the same stale assumptions and the same
impact graph, every time.
