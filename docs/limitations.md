# Assumptions, limitations and production hardening

## Safety limitations (read first)

* **This is not engineering approval.** The platform runs first-pass deterministic checks. It flags
  where structural, electrical or mechanical coordination is *required*; it never asserts structural
  adequacy, code compliance or fitness for purpose. Every recommendation carries this caveat, and
  `FIRST-PASS CHECKS CLOSED` still requires a human sign-off action.
* **Most demo data is synthetic.** The generated equipment catalog, costs, regional multipliers,
  scenarios, seeded sites and documents are synthetic and visibly labelled. State commercial
  electricity averages come from U.S. EIA 2024 Table 4, while several before-construction adapters
  use cited public datasets. None of this replaces a project tariff, certified vendor submittal,
  site survey, or engineer-approved design criterion.
* **The LLM cannot compute anything that matters.** Scores, deltas, thresholds, unit conversions and
  decision states come from `app/engine/`. The LLM plans investigations and explains findings.
* **Thresholds are illustrative.** The 5 % weight / 2 % dimension / 10 % refrigerant coordination
  thresholds are reasonable defaults for a prototype, not values drawn from a specific project
  specification or code. Real deployments must set them per project.

## Product assumptions

| Assumption | Rationale | If wrong |
| --- | --- | --- |
| Mireye's `/v1/ask/stream`, `/v1/feature-requests` and `/v1/sites*` payload shapes | Unlike `/v1/meta/fields`, `/v1/geocode`, `/v1/fetch` and `/v1/ask`, these were not exercised against the live service | Confined to one file; the four verified shapes are recorded in `tests/fixtures/mireye/` |
| Three provider mappings are proxies, not exact matches | The catalog has no field measuring precisely the same quantity | Each is labelled `proxy` on the evidence and in the UI; see `docs/mireye-contract.md`. The wet-bulb → dry-bulb proxy makes the CH-01 site check *optimistic* in live mode |
| 34 site fields are enough to rank candidates | Covers all eight dimensions from the source document | Add a `FieldSpec` — scoring picks it up with no other change |
| Weight/support-load increase is the structural trigger | It is the coordination trigger a reviewer would use | Thresholds are one dict in `engine/deltas.py` |
| Missing evidence outranks a threshold breach | You cannot ask for judgement on an invalid comparison | Precedence is one function, `decisions.decide` |
| Only engineer-confirmed requirements should gate a decision | Extraction is a proposal, not a fact | Unconfirmed requirements are used as a fallback and labelled *(extracted, unconfirmed)* in the check text |

## Known limitations

**Backend**

* SQLite document store with a single global lock — correct, but not concurrent. Fine for a demo,
  not for multi-tenant load. (Marked with a `ponytail:` comment at the lock.)
* BM25 scores the whole project corpus per query in Python; fine at hundreds of chunks, not at
  hundreds of thousands.
* `HashingEmbedder` produces genuine dense vectors with no network dependency, but it is not
  semantically strong — it is a stand-in for a real embedding model, not a replacement.
* Requirement extraction is regex + keyword based. It finds the common "shall not exceed N unit"
  patterns and misses prose, tables and drawings. No OCR: a scanned PDF is reported as failed
  extraction rather than silently returning nothing.
* Investigations run synchronously inside the request. A real deployment needs a task queue and
  streaming progress (the data model already supports incremental step/event updates).
* No authentication, authorisation or multi-tenancy. Every project is world-readable.
* Rate limiting, request quotas and upload virus scanning are absent.
* The current high-utilization Mireye defaults can request broad field coverage, including the
  separately metered parcel group, across many sites. Use explicit limits and disable parcel fields
  outside a controlled demo budget; the test suite never performs paid calls by default.

**Frontend**

* Polls on demand rather than streaming; the investigation timeline appears when the run completes.
  `POST /v1/ask/stream` is wired in the adapter but not yet surfaced live in the UI.
* The impact graph is a layered column view with path highlighting, not a force-directed canvas.
  It was chosen for legibility at demo resolution.
* Map tiles come from OpenStreetMap; with no network the markers still render (they are div icons)
  but the basemap is blank.
* One bundle, no code splitting (~790 kB minified / 224 kB gzipped).

**Testing**

* 122 backend tests cover the engine, adapters, ingestion, API and both end-to-end paths. There are
  no frontend component tests and no committed browser-level end-to-end tests; the frontend is
  covered by strict TypeScript and a production build in CI terms. The browser scenarios that were
  driven manually for the QA pass are listed in [`verification-report.md`](verification-report.md).

## Production hardening checklist

1. **Identity** — authentication, per-project authorisation, audit logging of every confirmation and
   override (the evidence model already records who confirmed what).
2. **Storage** — move `Store` onto Postgres/Supabase with real tables and migrations; keep the
   interface, drop the JSON blob. Add row-level security per project.
3. **Async** — run investigations on a worker (Celery/RQ/Arq); stream `ToolEvent`s over SSE or
   WebSocket so the timeline fills in live.
4. **Retrieval** — real embeddings (Voyage/OpenAI/Cohere) into pgvector, plus a reranker; add
   table-aware and OCR extraction (Docling) for drawings and scanned submittals.
5. **Mireye** — the four endpoints the product uses are now aligned with the live API, but only 15 of
   34 concepts have a provider equivalent (3 of those are proxies). Close the remaining 19 by
   deriving them from other catalog fields, sourcing them elsewhere, or dropping them from the
   scoring model. Then add a circuit breaker, per-field TTLs matched to how fast each dataset
   actually changes (the catalog publishes `ttl_seconds` per field — currently ignored in favour of
   one global TTL), and a background refresh that re-marks stale observations.
6. **Engineering rules** — make thresholds project-configurable with an approval trail; add
   AHRI-certified performance lookups; add per-discipline rule packs reviewed by a licensed engineer.
7. **Graph** — Neo4j Aura with a schema migration, plus versioned graph snapshots per analysis so an
   impact assessment can be reproduced exactly as it was issued.
8. **Observability** — OpenTelemetry traces across agent phases, per-tool latency and failure
   dashboards, alerting on degraded-adapter mode.
9. **Compliance** — retention policy for uploaded documents, PII scanning, signed URLs for document
   access, and a formal "not engineering approval" acceptance in the UI.
10. **Frontend** — code splitting, component tests, Playwright end-to-end runs of both walkthroughs,
    and an accessibility audit against WCAG 2.2 AA (colour contrast, focus order, live regions for
    long-running analysis).
