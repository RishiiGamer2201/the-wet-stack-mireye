# The Wet Stack — Mireye

A data-center construction and EPC intelligence platform featuring two unified workflows: **Site Intelligence (Before Construction)** and **Change Intelligence (During Construction)**.

The system is built on a strict separation of concerns: **AI agents plan and orchestrate investigations, while deterministic Python engines execute all mathematical calculations, unit conversions, gate validations, and scoring.**

---

## Core Libraries and Dependencies

### Backend (Python 3.10+)
* **FastAPI (`>=0.110`)**: High-performance asynchronous API framework and OpenAPI contract generation.
* **Pydantic v2 (`>=2.6`) & Pydantic-Settings**: Strict data validation, schema enforcement, and environment configuration.
* **Pint (`>=0.23`)**: Deterministic physical and electrical unit arithmetic, dimensional analysis, and conversion.
* **LangGraph (`>=0.2`)**: Stateful graph orchestration for multi-step agent workflows.
* **PyMuPDF / fitz (`>=1.24`)**: High-speed PDF ingestion, structured text/table extraction, and OCR document processing.
* **HTTPX (`>=0.27`)**: Asynchronous HTTP client for external dataset querying and live Mireye API connectivity.
* **Redis (`>=5.0`)**: In-memory caching for external datasets, rate-limiting, and distributed state caching.
* **Uvicorn (`>=0.29`)**: ASGI production web server.
* **Neo4j (`>=5.19`) & Psycopg 3 (`>=3.1`)** *(Optional Live Mode)*: Graph database impact traversal and Postgres / pgvector vector storage.
* **Pytest (`>=8.1`) & Ruff (`>=0.4`)**: Test runner, static analysis, and code formatting.

### Frontend (Node 20+, TypeScript)
* **React 18 & TypeScript**: Typed component architecture for critical engineering interfaces.
* **Vite 6**: Fast modern frontend build tool and dev server.
* **Tailwind CSS v4**: Design system and responsive layout styling.
* **Lucide React**: Clean technical iconography.
* **Recharts**: Engineering metrics visualization and design margin charts.
* **Leaflet & React-Leaflet**: Geospatial candidate site mapping and GIS overlays.

---

## System Architecture

```
                                  +---------------------------------------+
                                  |         React / Vite Web UI           |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |         FastAPI Gateway Layer         |
                                  +---------+-------------------+---------+
                                            |                   |
                     +----------------------+                   +---------------------+
                     |                                                                |
                     v                                                                v
+--------------------------------------------+                   +--------------------------------------------+
|            AGENTIC WORKFLOWS               |                   |           DETERMINISTIC ENGINES            |
|                                            |                   |                                            |
| * Change Orchestrator Agent                |                   | * 9 Verification Gates (gates.py)          |
| * Site Intelligence Supervisor (LangGraph) |                   | * 13 Pint Unit-Checked Deltas (deltas.py)  |
| * Project Knowledge MCP Agent              |                   | * Facility Design Margins (margins.py)     |
| * Requirement Parser Agent                 |                   | * Multi-Change Cascade Loading (cascade.py)|
+--------------------+-----------------------+                   | * Catalog Recommendation (catalog.py)     |
                     |                                           | * Cost & Schedule Impact (cost_schedule.py)|
                     +----------------------+                    | * Multi-Factor Site Scoring (scoring.py)   |
                                            |                    +--------------------+-----------------------+
                                            v                                         v
                                  +---------------------------------------------------+---+
                                  |               SHARED UNIFIED STATE                |
                                  |                                                       |
                                  | * Evidence Store with Full Provenance & Relations    |
                                  | * Information Gap Tracking (Blocking / Non-Blocking)  |
                                  | * Dependency Impact Graph (Cross-Discipline Traversal)|
                                  | * Stale Assumption Detection & Invalidation Engine    |
                                  +-------------------------------------------------------+
```

---

## AI Agents in the Architecture

1. **Change Orchestrator Agent (`apps/api/app/agent/change_orchestrator.py`)**
   * Manages the lifecycle of an equipment substitution review.
   * Coordinates extraction of submittal parameters, triggers verification gates, runs Pint unit delta checks, evaluates facility margins, and determines the formal engineering decision state.

2. **Site Intelligence Supervisor (`apps/api/app/agent/workflow.py` & `planner.py`)**
   * A LangGraph-powered state machine that plans site evaluation sequences across 8 spatial and civil dimensions.
   * Dispatches data-gathering tasks to external dataset adapters (USGS, FEMA, EIA, EPA, NOAA), identifies unverified parameters as information gaps, and feeds validated evidence into the scoring engine.

3. **Project Knowledge & Document Agent (`apps/api/app/agent/knowledge_agent.py`)**
   * A Model Context Protocol (MCP) copilot that interfaces with project submittals and engineering drawings.
   * Searches PDF vector embeddings, executes live web queries for manufacturer specs, inspects live project state, and provides verified page-level citations for technical inquiries.

4. **Requirement Parser Agent (`apps/api/app/agent/change_orchestrator.py`)**
   * Translates natural language equipment inquiries into structured physics, electrical, and dimensional constraints with mathematical operators (e.g., `cooling_capacity >= 1200 kW`, `voltage == 480 V`).

---

## Feature Architecture: Change Intelligence (During Construction)

The During Construction workspace manages equipment substitutions and engineering changes with 5 primary sub-features:

### 1. Change Intelligence & Verification
* **9 Deterministic Verification Gates (`gates.py`):** Pre-comparison boundary checks that must be satisfied before substitution approval (e.g., Manufacturer Comparability, Voltage/Phase Match, Refrigerant Environmental Suitability, Rated Ambient vs Site ASHRAE Climate Extremes, Physical Footprint Boundary, Structural Floor Loading).
* **13 Pint Unit-Checked Deltas (`deltas.py` & `units.py`):** Dimensionally verified physical and electrical deltas (Weight, Length, Width, Height, Voltage, Full Load Amps, MCA, MOCP, Power Input, Refrigerant Charge, Cooling Capacity, COP).
* **Deterministic Design Margins (`margins.py`):** Evaluates remaining facility headroom (electrical substation capacity, central plant chilled water duty, structural slab capacity). If baseline capacity is unbacked by evidence, it explicitly assigns `NEEDS_INFORMATION` rather than hallucinating safety.
* **Cost, Energy & Schedule Impact (`cost_schedule.py`):** Calculates annual energy and water utility cost deltas based on efficiency curves and evaluates critical-path lead-time schedule delay risks.
* **Dependency Impact Graph (`impact.py`):** Traverses cross-discipline dependencies (electrical, mechanical, civil, structural, environmental) to identify downstream components affected by a change.

### 2. Equipment Recommendation Studio (`catalog_engine.py`)
* **Multi-Category Catalog:** Covers 11 critical equipment classes (Chillers, CRAH fan walls, AHUs, Cooling Towers, Pumps, Substation Transformers, Modular UPS, Standby Generators, Switchgear, PDUs, Economizer Heat Exchangers).
* **Deterministic Multi-Criteria Ranking:** Scores candidates out of 100 based on weighted engineering parameters: Capacity (25%), Energy Efficiency / COP (20%), Electrical Compatibility (15%), Climate Design Fit (10%), Physical Footprint (10%), and Acoustic/Refrigerant limits.
* **One-Click Impact Pipeline:** Automatically loads top-ranked catalog alternatives into the verification pipeline for instant impact re-calculation.

### 3. Cumulative Cascade Loading Analysis (`cascade.py`)
* **Facility-Wide Multi-Change Aggregation:** Assesses the cumulative impact of multiple concurrent equipment substitutions across an entire facility.
* **Infrastructure Headroom Protection:** Aggregates electrical load changes ($\Delta\text{kW}$), structural weight increases ($\Delta\text{kg}$), and cooling duty changes ($\Delta\text{kW}$) to ensure simultaneous changes do not collectively overload substation transformers, backup generators, or roof steel.
* **Binary Facility Verdict:** Produces an overall status (`WITHIN_FACILITY_LIMITS` or `EXCEEDED_CAPACITY`) with detailed engineering boundary explanations.

### 4. Action Package & RFI Generator (`routers/during.py`)
* **Structured Engineering Documentation:** Generates formal documentation drafts tailored for project stakeholders:
  * **RFIs (Requests for Information):** Formatted for the Structural Engineer of Record (EOR), Electrical Lead, or Mechanical Consultant.
  * **Vendor Clarification Requests:** Requests missing submittal data directly from suppliers.
  * **Engineering Change Review Packages:** Executive summaries with delta tables and governing specifications for client sign-off.
* **Evidence Citation & Export:** Links all calculated deltas and references directly to source submittal page numbers with one-click Markdown export.

### 5. Project Knowledge & Document Agent (`knowledge_agent.py`)
* **Interactive Engineering Copilot:** Queries ingested PDF specifications, engineering submittals, and site contracts using hybrid vector and BM25 search.
* **Real-Time Tool Execution:** Can run diagnostic calculations, query the live project state, and conduct external web queries through integrated MCP tools.
* **Stale Assumption Invalidation:** Automatically detects when new submittals or field changes invalidate earlier engineering assumptions.

---

## Feature Architecture: Site Intelligence (Before Construction)

The Before Construction workspace evaluates candidate site locations across 8 distinct dimensions:

1. **Terrain & Topography:** Slope analysis, elevation changes, cut-and-fill grading complexity.
2. **Water Availability & Quality:** Municipal capacity, groundwater chemistry (TDS/pH), cooling water source availability.
3. **Power Infrastructure:** Substation proximity, transmission line voltage, utility reliability metrics (SAIDI/SAIFI from EIA-861).
4. **Fiber Connectivity:** Distance to long-haul fiber routes, carrier density, latency metrics.
5. **Civil & Geotechnical:** Soil bearing capacity, seismic risk, soil expansion potential.
6. **Natural Hazards:** FEMA flood zone classifications, wildfire risk, extreme weather frequency.
7. **Environmental & Climate:** ASHRAE 0.4% and 1.0% dry-bulb/wet-bulb temperatures from StationFinder, wetland delineations, air permit constraints.
8. **Zoning & Regulatory:** Industrial zoning compliance, local permitting timeline estimates.

Each site receives an explainable, deterministic score with exact evidence citations and an explicit list of missing data gaps.

---

## Decision State Precedence

Every change case resolves deterministically to one of three engineering states:

```
[ Incoming Substitution Case ]
              │
              ▼
   Any required parameters
    missing or unevidenced? ──────► YES ──────► [ NEEDS INFORMATION ]
              │                                 (Generates Information Gaps)
              ▼ NO
   Any verification gate failed
     OR delta threshold breached
     OR site design limit exceeded? ─► YES ───► [ ENGINEER REVIEW ]
              │                                 (Triggers Impact Graph Traversal)
              ▼ NO
  [ FIRST-PASS CHECKS CLOSED ]
  (Within all design limits)
```

---

## Quick Start

### Prerequisites
* Python 3.10+
* Node.js 20+

### Single Command Launch
```bash
python scripts/dev.py
```
This script automatically sets up the Python virtual environment, installs backend and frontend dependencies, seeds synthetic demo datasets, and starts the API and UI servers.

* Web UI: `http://localhost:5173`
* Backend API: `http://127.0.0.1:8000`
* Interactive API Documentation: `http://127.0.0.1:8000/docs`

### Useful Development Commands
```bash
python scripts/dev.py --reset    # Wipe and re-seed the local database
python scripts/dev.py --check    # Run pytest, ruff lint, type check, and web build
python scripts/dev.py --api-only # Run API server only
python scripts/dev.py --ui-only  # Run frontend UI server only
```

---

## Testing & Quality Assurance

### Backend Tests
```bash
cd apps/api
pytest ../../tests -v
ruff check app ../../tests
```

### Frontend Type-Checking and Build
```bash
cd apps/web
npm run lint
npm run build
```

---

## Documentation Index

Detailed architectural and engineering documentation is available in the [`docs/`](docs/) directory:

* [`docs/architecture.md`](docs/architecture.md): Detailed component architecture and data flow diagrams.
* [`docs/domain-model.md`](docs/domain-model.md): Comprehensive schema definitions and evidence lifecycle.
* [`docs/engineering-rules.md`](docs/engineering-rules.md): Verification gates, delta thresholds, and decision precedence logic.
* [`docs/scoring.md`](docs/scoring.md): Multi-factor site scoring formulas and weighting methodology.
* [`docs/api.md`](docs/api.md): REST API endpoints and payload specifications.
* [`docs/production-lld.md`](docs/production-lld.md): Production deployment design (Postgres/pgvector, Redis, Kafka, Neo4j).
* [`docs/deployment.md`](docs/deployment.md): Deployment guides for Render (API) and Vercel (Web).
* [`docs/live-vs-demo.md`](docs/live-vs-demo.md): Configuration guide for switching from local mock adapters to live cloud services.
