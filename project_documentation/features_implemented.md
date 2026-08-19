# Features Implemented in The Wet Stack — Mireye

This document provides a comprehensive inventory of all features fully implemented, tested, and operational across the backend API, deterministic engine, agent layer, and frontend interface.

---

## 1. Before Construction — Site Intelligence Workflow

### 1.1 Multi-Dimensional Site Evaluation
* **8 Core Physical & Infrastructure Dimensions:**
  1. `geo_terrain`: Elevation, terrain slope, seismic zone risk, topographic viability.
  2. `water`: Water availability, municipal supply flow capacity, drought risk, wetland buffers.
  3. `power`: Distance to grid substation, available capacity, transmission line voltage.
  4. `connectivity`: Fiber path diversity, long-haul broadband proximity, carrier density.
  5. `civil_soil`: Soil bearing capacity, geotechnical viability, shallow bedrock depth.
  6. `hazards_climate`: 100-year flood zone, cooling design dry-bulb temp, extreme weather risks.
  7. `environmental`: Protected habitats, endangered species proximity, conservation easements.
  8. `regulatory`: Zoning classification, data center permitted use, local permitting timelines.
* **34 Mireye Catalog Fields:** Standardized catalog mapping each field to canonical units, default ranges, and evaluation dimensions. Unknown fields are rejected with structured errors.
* **Progressive 2-Pass Site Investigation:**
  - **Pass 1 (Broad Sweep):** Fetches 24 baseline fields across all candidate sites.
  - **Pass 2 (Targeted Deep Pass):** Automatically triggers on shortlisted candidates, fetching 10 deeper specialized metrics (e.g., specific substation capacities, geotechnical layers).

### 1.2 Deterministic Multi-Criteria Site Scoring
* **Explainable Math Engine (`app/engine/scoring.py`):**
  - Continuous piece-wise linear scoring functions mapping physical values to normalized 0–100 scores.
  - Directional scoring: Properly models "higher is better" (e.g., fiber carriers, water capacity) vs "lower is better" (e.g., slope, grid distance, flood risk).
* **Metric Coverage & Penalty Model:**
  - Dimension coverage = `evaluated_fields / total_dimension_fields`.
  - Unobserved or missing fields lower coverage and score confidence rather than assuming dummy defaults.
* **Evidence Confidence Multiplier:**
  - Modulates score reliability based on evidence provenance: `Live` & `User Confirmed` = 1.0, `Cached` = 0.9, `Synthetic` = 0.6, `Stale` = 0.35, `Missing` = 0.0.
* **Risk Classification:**
  - Automated risk classification: `Low`, `Moderate`, `Elevated`, `High`.
* **Hard Target Constraints Validation:**
  - Evaluates project-defined mandatory pass/fail rules (e.g., `max_slope <= 5%`, `min_power >= 50 MW`). Sites violating hard targets are visibly flagged.

### 1.3 What-If Simulation & User Overrides
* **Real-time Weight Tuning:** Engineers can modify dimension weights in real time; the backend immediately recomputes scores without re-fetching external data.
* **User-Confirmed Metric Overrides:** Allows engineers to input certified survey values (e.g., actual soil test results). Automatically upgrades evidence status to `user_confirmed`, adjusts confidence to 0.99, and recalibrates ranking.
* **Rank Differential Explanations:** Explains exact rank changes (e.g., *"Cascade Flats: rank 2 → 1 (score 78.4 → 84.1)"*).

### 1.4 Interactive Geospatial Mapping
* **Leaflet Mapping Component (`SiteMap.tsx`):**
  - Renders all candidate site coordinates with dynamic color-coded markers.
  - Highlights shortlisted vs non-shortlisted sites.
  - Interactive popups displaying site details, overall scores, and dimension breakdowns.
* **Geocoding & Resolution Tracking:** Handles address geocoding via `/v1/geocode` and tracks precision resolution (`rooftop`, `parcel`, `street`, `city`).

---

## 2. During Construction — Change Intelligence Workflow

### 2.1 Equipment Substitution Analysis
* **Equipment Specification Models:** Structured Pydantic schemas capturing physical dimensions, operating weight, dry weight, shipping weight, electrical specs (MCA, MOCP, FLA, power input, voltage, phases), refrigerant details (type, charge), cooling capacity, and rated ambient conditions.
* **Submittal Pair Comparison:** Compares existing/specified equipment against proposed substitution records with full metadata traceability.

### 2.2 9 Deterministic Verification Gates (`app/engine/gates.py`)
Executes strict pre-comparison checks to verify that equipment substitution is legally, physically, and thermodynamically comparable before running delta calculations:

1. **Model Identity Gate:** Validates manufacturer and model identity. Triggers if models are identical (no change) or missing.
2. **Data Type Gate:** Verifies weight bases match (e.g., compares *operating weight to operating weight*, triggering an error if operating weight is compared to dry weight).
3. **Configuration Gate:** Checks equipment classification, refrigerant circuit counts, and layout compatibility.
4. **Unit Compatibility Gate:** Uses Pint to prevent dimensional conflicts (e.g., comparing kg to kW). Downgrades downstream deltas to `SKIPPED` on failure.
5. **Rating & Operating Conditions Gate:** Ensures capacities are rated at identical standard temperatures (within 0.15 K) and flow rates (within 1%).
6. **Source Availability Gate:** Verifies every compared number cites an ingested source document or catalog record.
7. **Site Compatibility Gate:** Cross-references the proposed unit's maximum rated ambient temperature against the candidate site's peak design dry-bulb temperature.
8. **Coordinate Accuracy Gate:** Ensures the associated site has rooftop/parcel-level geocoding resolution.
9. **Capacity vs Requirement Gate:** Validates that proposed capacity meets or exceeds project requirements specified in engineering documents.

### 2.3 13 Delta Calculations & Engineering Thresholds (`app/engine/deltas.py`)
Computes absolute and percentage deltas with automated status classification (`CLOSED`, `OPEN`, `TRIGGERED`, `SKIPPED`):

| Metric | Trigger Threshold | Critical Threshold | Canonical Unit |
| :--- | :--- | :--- | :--- |
| **Operating Weight** | > +5.0% | > +15.0% | Kilograms (kg) |
| **Support-Point Load** | > +5.0% | > +15.0% | Kilonewtons (kN) |
| **Physical Dimensions (L/W/H)** | > +2.0% | > +10.0% | Millimeters (mm) |
| **Footprint Area** | > +3.0% | > +12.0% | Square Meters ($m^2$) |
| **Minimum Circuit Ampacity (MCA)** | > 0.0% (any increase) | > +10.0% | Amperes (A) |
| **Max Overcurrent Protection (MOCP)** | > 0.0% (any increase) | > +10.0% | Amperes (A) |
| **Full Load Amps (FLA)** | > 0.0% (any increase) | > +10.0% | Amperes (A) |
| **Power Input** | > +5.0% | > +15.0% | Kilowatts (kW) |
| **Refrigerant Charge** | > +10.0% | > +30.0% | Kilograms (kg) |
| **Cooling Capacity** | > +2.0% | > +10.0% | Kilowatts (kW) |
| **Supply Voltage** | Any change triggers | Categorical | Volts (V) |
| **Electrical Phases** | Any change triggers | Categorical | Phase count |
| **Refrigerant Type** | Any change triggers | Categorical | ASHRAE designation |

* **Zero-Baseline & Missing Data Handlers:** Unobserved fields produce `OPEN` checks and spawn `InformationGap` items rather than guessing values. Incompatible units raise explicit errors.

### 2.4 Downstream Impact Tracing & Stale Assumption Management (`app/engine/impact.py`)
* **Design Assumption Invalidation:** Tracks project assumptions (e.g., *"Roof steel sized for 8,500 kg chiller"*). When linked fields change, assumption status transitions to `STALE`.
* **Multi-Discipline Impact Derivation:** Traces consequences across 6 engineering disciplines:
  1. `structural`: Roof steel deflection, support-point load redesign, vibration isolator sizing.
  2. `electrical`: Feeder conductor upsizing, breaker swap, switchboard bus rating, generator sizing.
  3. `mechanical`: Header pipe velocity, expansion tank capacity, chilled water flow rebalancing.
  4. `controls`: BMS sensor points, BACnet/Modbus mapping, sequencing logic.
  5. `installation_logistics`: Crane rigging capacity, transport clearances, roof access pathways.
  6. `commissioning`: Factory Acceptance Testing (FAT), site acoustic testing, seasonal re-testing.
* **Interactive Knowledge Graph:** Renders traversable `ImpactGraph` (`Change -> Stale Assumption -> Discipline -> Activity -> Commissioning`) in both UI visualizer and backend Neo4j/In-Memory graph stores.

### 2.5 3-Tier Deterministic Decision Engine (`app/engine/decisions.py`)
Enforces strict engineering hierarchy to determine final verdict:

1. **`NEEDS INFORMATION` (Highest Precedence):** Triggered when any gate or delta is `OPEN` due to missing documentation or unstated rating conditions.
2. **`ENGINEER REVIEW`:** Triggered when all data is present, but one or more engineering gates or threshold deltas are `TRIGGERED`.
3. **`FIRST-PASS CHECKS CLOSED`:** Reached only when all gates are `CLOSED`, all deltas fall within tolerance, and no assumptions are invalidated.

### 2.6 Automated Next Action Drafting (`app/engine/decisions.py` & `schemas.py`)
Generates actionable, situation-tailored engineering communication drafts:
* **RFI (Request for Information):** Targeted at Engineer of Record (EOR) / Design Team when project specs or assumptions conflict.
* **Vendor Evidence Request:** Formats exact missing datasheets, submittals, or operating conditions required from equipment vendors.
* **Clarification Request:** Outlines site survey or municipal data gaps.
* **Engineering Review Comment / Sign-off:** Drafts structured review packages for human sign-off.

---

## 3. Evidence & Provenance Engine

### 3.1 6-Stage Evidence Lifecycle State Machine
Every single fact throughout the platform is backed by an `Evidence` record:
* `live`: Directly retrieved from live external APIs (Mireye, etc.).
* `cached`: Retrieved from local TTL-managed cache.
* `synthetic`: Generated demo fixture (clearly labeled with amber badges).
* `stale`: Exceeded TTL or invalidated by subsequent changes; excluded from calculations.
* `missing`: Explicitly tracked when requested data was unavailable.
* `user_confirmed`: Validated or overridden by an authorized engineer (highest confidence).

### 3.2 Information Gap Management (`InformationGap`)
* Identifies what information is missing, why it matters, which engineering check is blocked, the expected data source, and the recommended action to resolve it.
* Dedicated slide-over UI panel allowing engineers to inspect and resolve open gaps.

---

## 4. Document Ingestion & Hybrid Retrieval Engine

### 4.1 PDF Parsing & Requirement Extraction (`app/services/ingest.py`)
* **PyMuPDF (fitz) Pipeline:** Extracts page-aware text chunks with character offsets.
* **Regex & Pattern Extractors:** Detects model numbers, cooling capacities, electrical ampacities, dimensions, and weights.
* **Human Confirmation Loop:** Displays extracted requirements in the UI for engineer verification, adjustment, and sign-off.

### 4.2 Hybrid Lexical + Vector Retrieval (`app/adapters/vectorstore.py`)
* Fuses **BM25 Lexical Keyword Matching** with **Local Hashed N-Gram Embeddings** (or Postgres `pgvector` in live mode).
* Provides citation-backed search results indicating exact document name, page number, extraction method, and relevance score.
* **Mireye `/v1/ask` Natural Language Interface:** Allows natural language queries about project requirements and site constraints.

---

## 5. Agent Orchestration Layer (LangGraph + Supervisor)

### 5.1 7-Phase Agent State Machine (`app/agent/workflow.py`)
Orchestrates autonomous investigations through 7 explicit phases:
1. `Understand`: Parses project goals, candidate sites, or proposed equipment changes.
2. `Plan`: Supervisor builds dynamic, situation-tailored investigation steps.
3. `Evidence`: Executes parallel data retrieval across documents and Mireye endpoints.
4. `Signals`: Computes deterministic gates, deltas, and scoring functions.
5. `Replan` *(Conditional Loop)*: Identifies unverified signals or open gates and schedules targeted follow-ups (max 1 loop).
6. `Impact`: Evaluates stale assumptions, traces multi-discipline impacts, and constructs graph.
7. `Action`: Determines final decision state, compiles recommendations, and drafts next actions.

### 5.2 Strict LLM Guardrails
* **Planning & Narration Only:** LLM is restricted to proposing search steps and explaining findings.
* **Deterministic Fallback:** In demo mode or when no API key is supplied, a deterministic template narrator runs seamlessly.

---

## 6. Dual-Mode Adapter Architecture (Live vs Demo)

| Service | Live Mode | Demo Mode (Local Fallback) |
| :--- | :--- | :--- |
| **Physical World API** | `LiveMireyeClient` (HTTPX, retry/backoff, rate limit caps) | `MockMireyeClient` (Deterministic fixture data) |
| **Knowledge Graph** | `Neo4jGraphStore` (Cypher queries) | `InMemoryGraphStore` (NetworkX-style in-memory graph) |
| **Vector Retrieval** | `PgVectorIndex` (PostgreSQL `pgvector`) | `LexicalSqliteIndex` (BM25 + N-gram vectors) |
| **Storage & Persistence** | `PostgresStore` / Supabase | `SqliteStore` (`apps/api/var/wetstack.db`) |
| **Narrator / Explanations** | `AnthropicProvider` (Claude 3.5 Sonnet / Opus) | `DeterministicNarrator` (Deterministic templates) |

---

## 7. Frontend User Interface

* **Before Construction View:** Multi-site radar/bar charts, candidate cards, weight adjustment sliders, what-if overrides, and interactive Leaflet map.
* **During Construction View:** Side-by-side equipment comparison, verification gate cards, delta percentage indicators, 3-state decision banners, downstream impact tree, and next action preview.
* **Investigation Timeline:** Real-time step-by-step audit log of agent thought process, tool calls, and evidence collection.
* **Evidence & Gap Drawers:** Slide-over panels detailing provenance, source documents, confidence ratings, and missing information gaps.
* **Demo Mode Status Banner:** Persistent header banner showing real-time operational mode for each adapter.
