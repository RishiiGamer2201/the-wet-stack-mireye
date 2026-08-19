# Architecture

The architecture follows the one principle stated in the source document:

> **The agent decides what needs to be investigated; deterministic software performs the
> important calculations and verification.**

Everything the LLM may do is confined to *planning* and *explaining*. Every number that a
decision depends on is produced by tested Python in `apps/api/app/engine/`.

## System overview

```mermaid
flowchart TB
    subgraph UI["Frontend — React / TypeScript / Vite / Tailwind"]
        SEL[Project & workflow selector]
        BC[Before Construction dashboard]
        DC[During Construction dashboard]
        EV[Evidence & provenance drawer]
        GAP[Information-gap panel]
        TL[Investigation timeline]
        IG[Impact graph view]
        DEC[Decision card & next action]
    end

    subgraph API["Backend — FastAPI / Pydantic / Uvicorn"]
        R[Typed routers + OpenAPI]
        AG["Agent layer (LangGraph supervisor)"]
        SV["Services: evidence · ingest · sites · changes"]
        EN["Deterministic engine: units · scoring · deltas · gates · impact · decisions"]
    end

    subgraph AD["Adapters — live + local implementation each"]
        MI["Mireye client<br/>live · mock · fallback"]
        GR["Graph store<br/>Neo4j · in-memory"]
        VS["Retrieval<br/>pgvector · BM25 + local vectors"]
        LLM["LLM provider<br/>Gemini · deterministic"]
        ST["Store<br/>Postgres/Supabase · SQLite"]
    end

    UI -->|JSON over HTTP| R
    R --> AG --> SV --> EN
    SV --> MI & GR & VS & ST
    AG --> LLM
    EN -.->|never called by the LLM| LLM
```

## Architecture flow (source document, page 4)

```mermaid
flowchart TD
    U[User / project team] --> W{Select workflow}
    W -->|1| BC[Before Construction — Site Intelligence]
    W -->|2| DC[During Construction — Change Intelligence]

    BC --> BCD["8 site-evaluation dimensions<br/>geo · water · power · connectivity<br/>civil · hazards · environment · regulatory"]
    BCD --> ALT["Alternatives comparison<br/>weighted scoring · shortlist"]
    ALT --> WI["What-if simulator<br/>weights · site assumptions"]

    DC --> EQ[Equipment change input]
    EQ --> PLAN["Automatic investigation planning<br/>situation-specific, not a fixed checklist"]
    PLAN --> DOC[Project document reading]
    PLAN --> MFG[Manufacturer document reading]
    PLAN --> SITE["Selective site investigation<br/>only the fields actually needed"]
    SITE --> PROV[Mireye provenance & missing-data handling]

    WI --> UIE[Unified intelligence engine]
    PROV --> UIE
    UIE --> DA["Derived analysis<br/>rating-condition gap · evidence closure gap · substitution delta"]
    UIE --> IA["Impact analysis<br/>support-point loads · STALE assumptions · downstream tracing"]
    UIE --> NA["Automated next action<br/>RFI · vendor request · review comment"]
    UIE --> KG["Knowledge graph<br/>equipment · documents · requirements · impacts · assumptions"]

    DA & IA --> VER[Verification & engineering assurance]
    VER --> VG["Verification gate<br/>model · data type · configuration · units<br/>rating conditions · sources · location"]
    VER --> DET["Deterministic engineering logic (not LLM)<br/>unit conversion · weight/load · thresholds"]

    VG & DET --> SUF{Evidence sufficient?}
    SUF -->|no| GAPS["Information-gap handling<br/>identify · source · request · track"]
    SUF -->|yes| HUM["Human confirmation<br/>show extracted requirements · engineer confirms"]
    GAPS --> OUT
    HUM --> OUT

    OUT{{"Final decision state"}}
    OUT --> S1[FIRST-PASS CHECKS CLOSED]
    OUT --> S2[NEEDS INFORMATION]
    OUT --> S3[ENGINEER REVIEW]
```

## Agent workflow

`apps/api/app/agent/workflow.py` compiles a LangGraph `StateGraph` per workflow. The nodes are the
seven phases; `Replan` is entered conditionally and loops at most once, which is what makes the
investigation progressive rather than a fixed checklist.

```mermaid
stateDiagram-v2
    [*] --> Understand
    Understand --> Plan: read project, sites/change, targets
    Plan --> Evidence: supervisor builds a situation-specific plan
    Evidence --> Signals: Mireye /fetch + document retrieval
    Signals --> Replan: something unresolved
    Signals --> Impact: everything evaluated
    Replan --> Impact: targeted follow-up recorded
    Impact --> Action
    Action --> [*]
```

What each phase does per workflow:

| Phase | Before Construction | During Construction |
| --- | --- | --- |
| Understand | Count candidates, read targets and weights | Read the change, both equipment records, the linked site |
| Plan | Broad sweep → shortlist → deep pass (+ a target-check step when the project sets one) | Steps derived from what actually differs: weight/support, refrigerant, electrical, site conditions (+ optional LLM-proposed steps, validated) |
| Evidence | `/v1/geocode` for address-only sites, then `/v1/fetch` of the 24 broad fields per site | Requirement retrieval, manufacturer retrieval, `/v1/fetch` of only the site fields needed |
| Signals | Score, rank, shortlist, evaluate hard targets | Run the 9 verification gates, then the 13 deltas |
| Replan | Deep pass on the shortlist only (10 further fields), then re-score | Add a targeted evidence step per OPEN gate — never assume the value |
| Impact | Consolidate gaps and unverifiable targets | Mark stale assumptions, derive impacts, build the graph |
| Action | Recommendation + clarification requests + confirmation | Decision state, recommendation, RFI / vendor request / review comment |

Every phase writes `InvestigationStep` and `ToolEvent` records, which is exactly what the UI
timeline renders — the observability is the data, not a separate log.

## Where the LLM is and is not

| Allowed | Not allowed |
| --- | --- |
| Propose extra investigation steps (validated against the field catalog; unknown fields dropped) | Compute or adjust any score, delta, threshold or unit conversion |
| Explain already-computed findings in prose, appended and labelled `(agent explanation)` | Decide the decision state |
| Answer exploratory questions via Mireye `/v1/ask` | Supply a value that fills an information gap |

With no `GEMINI_API_KEY` the `DeterministicNarrator` returns `None` and every caller falls back
to its template text. Decisions are byte-identical with and without an LLM.

## Adapter pattern

Each external service has one protocol and at least two implementations:

```mermaid
classDiagram
    class MireyeClient {
        <<protocol>>
        meta_fields()
        geocode(address)
        fetch(lat, lon, fields)
        ask(question)
        create_site() / get_site() / ask_site()
        feature_request(field, reason)
    }
    MireyeClient <|.. LiveMireyeClient
    MireyeClient <|.. MockMireyeClient
    MireyeClient <|.. FallbackMireyeClient
    FallbackMireyeClient --> LiveMireyeClient : try
    FallbackMireyeClient --> MockMireyeClient : on failure, labelled degraded
```

The same shape applies to `GraphStore` (Neo4j / in-memory), the retrieval `Index`
(pgvector / local vectors / BM25, fused) and `LLMProvider` (Gemini / deterministic).

## Storage

`Store` is a small document store over SQLite with a `records(collection, id, project_id,
parent_id, data)` table plus a TTL cache table. Domain objects are Pydantic models serialised to
JSON, so schema iteration costs nothing during a hackathon while the interface (`put`, `get`,
`list`, `delete`, `cache_get`, `cache_set`) is exactly what a Supabase/Postgres implementation
needs to satisfy.

Derived state — rankings, checks, deltas, impacts — is never stored independently. It lives on the
`Investigation` that produced it, so it can never drift from the evidence it was computed from.

## Request flow, end to end

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as FastAPI
    participant G as LangGraph supervisor
    participant M as Mireye adapter
    participant E as Deterministic engine
    participant S as Store / graph

    B->>A: POST /api/projects/{id}/changes/{cid}/analyze
    A->>G: run_change_investigation
    G->>G: Understand → Plan (situation-specific)
    G->>M: /v1/fetch [ambient_design_db_c, elevation_m]
    M-->>G: values + provenance (or "unavailable")
    G->>S: persist Evidence / SiteObservation / InformationGap
    G->>E: verification gates → deltas
    E-->>G: CLOSED / OPEN / TRIGGERED / SKIPPED
    G->>E: stale assumptions → impacts → graph
    G->>S: upsert impact graph
    G->>E: decide() → recommendation → next actions
    G-->>A: Investigation (steps, events, checks, deltas, impacts, decision)
    A-->>B: typed JSON
    B->>A: GET /api/impact/{cid}
    A->>S: traverse Change → Assumption → Discipline → Activity → Commissioning
```
