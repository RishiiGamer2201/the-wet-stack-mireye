# Implementation Checklist — The Wet Stack / Mireye

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done

**Status: complete.** 122 backend tests pass, ruff clean, `tsc --noEmit` clean, production build
succeeds, and both workflows were verified end to end in a real browser session against the running
API. Full record — including the defects found and fixed during verification, and what was *not*
verified — in [`docs/verification-report.md`](docs/verification-report.md).

## 0. Foundations
- [x] Read source PDF (6 pages) + architecture diagram (page 4)
- [x] Repo skeleton, git init, `.gitignore`
- [x] Python venv + dependency install
- [x] Node workspace install

## 1. Backend — domain
- [x] Pydantic domain model (Project, CandidateSite, SiteObservation, ProjectDocument,
      DocumentChunk, Requirement, Equipment, EquipmentConfiguration, EquipmentChange,
      Evidence, EvidenceSource, Assumption, Investigation, InvestigationStep,
      EngineeringCheck, Impact, InformationGap, Recommendation, NextAction)
- [x] Evidence provenance + status lifecycle (live/cached/synthetic/user_confirmed/missing/stale)
- [x] SQLite store with repository interface (Postgres/Supabase adapter seam)

## 2. Backend — deterministic engine
- [x] `units.py` — Pint registry, conversion, incompatible-unit errors
- [x] `scoring.py` — 8 dimension scores, weights, coverage, confidence, risk
- [x] `deltas.py` — weight / load / dimension / electrical / refrigerant / capacity deltas
- [x] `gates.py` — model identity, data type, configuration, units, rating conditions,
      source availability, site compatibility, coordinate accuracy
- [x] `checks.py` — CLOSED / OPEN / TRIGGERED / SKIPPED classification
- [x] `impact.py` — Change → Stale Assumption → Discipline → Activity → Commissioning
- [x] `decisions.py` — FIRST-PASS CHECKS CLOSED / NEEDS INFORMATION / ENGINEER REVIEW
- [x] `nextaction.py` — RFI / vendor request / clarification / review comment drafts

## 3. Backend — adapters
- [x] Mireye client abstraction (9 documented endpoints) + field-catalog cache
- [x] Deterministic mock Mireye adapter (demo mode)
- [x] Live Mireye adapter: timeouts, retries, backoff, cache, error → InformationGap
- [x] Vector store: lexical fallback + pgvector/Supabase seam
- [x] Graph store: in-memory + Neo4j adapter
- [x] LLM provider: deterministic narrator + Anthropic provider via env

## 4. Backend — ingestion
- [x] PDF upload validation (type, size)
- [x] PyMuPDF page-aware text extraction + chunking with spans
- [x] Requirement / equipment-tag / model-id extraction
- [x] User confirm/correct extracted requirements
- [x] Retrieval + citations

## 5. Backend — agent
- [x] LangGraph orchestration: Understand → Plan → Evidence → Signals → Replan → Impact → Action
- [x] Supervisor builds situation-specific plan (not fixed checklist)
- [x] Step/tool event stream persisted and exposed to UI
- [x] Fallback executor when LangGraph unavailable

## 6. Backend — API
- [x] Typed FastAPI routers, OpenAPI, health + readiness
- [x] CORS, structured logging, error envelopes
- [x] Seed / reset endpoints and CLI

## 7. Frontend
- [x] Vite + React + TS + Tailwind + accessible primitives
- [x] Project / workflow selector, demo-mode banner
- [x] Before Construction: map, candidates, weights, progressive investigation, ranking, what-if
- [x] During Construction: change cases, comparison, gates, deltas, decision card
- [x] Evidence drawer with provenance, information-gap panel
- [x] Investigation timeline, impact graph view, next-action preview
- [x] Loading / empty / error / demo states, responsive, a11y

## 8. Tests
- [x] Units, scoring/ranking, deltas, gates, evidence status, stale propagation
- [x] Impact traversal, missing data, Mireye failure/retry/fallback
- [x] Ingestion + retrieval, API endpoints
- [x] E2E happy path for both workflows
- [x] Adverse cases (bad units, invalid model, stale cache, API down, bad extraction,
      graph/vector unavailable)

## 9. Docs
- [x] README with exact commands
- [x] Architecture, domain model, API/integration, Mireye contract
- [x] Scoring + engineering rules, live vs demo mode
- [x] Assumptions & safety limitations, demo walkthrough, known limitations
