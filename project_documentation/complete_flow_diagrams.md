# Complete Architecture & Workflow Flow Diagrams

This document contains complete, detailed visual flowcharts and state diagrams representing the entire lifecycle of data, agent execution, deterministic calculations, and user interactions in **The Wet Stack — Mireye**.

---

## 1. System Architecture & Component Boundaries

```mermaid
flowchart TB
    subgraph Client["Frontend Client (React 18 / TypeScript / Vite / Tailwind)"]
        UI_MAIN["App Shell & Navigation"]
        UI_BC["Before Construction Dashboard (Map / Scores / What-If)"]
        UI_DC["During Construction Dashboard (Submittal Compare / Gates / Deltas)"]
        UI_KN["Project Knowledge & PDF Search"]
        UI_EV["Evidence & Provenance Slide-over"]
        UI_GAP["Information Gap Drawer"]
        UI_ACT["Next Action / Draft RFI Viewer"]
    end

    subgraph API["Backend API (FastAPI / Pydantic / Uvicorn)"]
        ROUTERS["Typed API Routers (/api/projects, /sites, /changes, /documents)"]
        SERVICES["Business Services (sites · changes · ingest · evidence)"]
        
        subgraph AgentLayer["Agent Orchestration (LangGraph)"]
            SUP["Supervisor Planner"]
            GRAPH["7-Phase StateGraph"]
            NARR["Deterministic / LLM Narrator"]
        end

        subgraph DeterministicEngine["Deterministic Engineering Engine (Python / Pint)"]
            UNITS["Unit Registry (Pint)"]
            GATES["9 Verification Gates"]
            DELTAS["13 Threshold Delta Computations"]
            SCORE["8-Dimension Scoring Engine"]
            IMPACT["Multi-Discipline Impact Derivation"]
            DECIDE["3-Tier Precedence Decision Engine"]
        end
    end

    subgraph Adapters["Dual-Mode Adapter Layer"]
        AD_MIR["Mireye Client (Live HTTPX / Mock Client)"]
        AD_GRP["Graph Store (Neo4j / In-Memory Store)"]
        AD_VEC["Retrieval Index (pgvector / BM25 + Local Vectors)"]
        AD_DB["Document Store (PostgreSQL / SQLite3)"]
    end

    Client <-->|REST over HTTP (JSON)| ROUTERS
    ROUTERS --> SERVICES
    SERVICES --> AgentLayer
    SERVICES --> DeterministicEngine
    AgentLayer --> DeterministicEngine
    SERVICES <--> Adapters
    AgentLayer <--> Adapters
```

---

## 2. Before Construction — Site Intelligence Flow

```mermaid
flowchart TD
    START([User initiates Site Investigation]) --> GEO[Geocode Candidate Addresses via /v1/geocode]
    GEO --> PASS1[Pass 1: Broad Sweep - Fetch 24 standard Mireye fields per site]
    PASS1 --> PROV1[Assign Evidence Provenance & Confidence Multipliers]
    PROV1 --> SCORE1[Compute Baseline Dimension Scores & Overall Ranks]
    SCORE1 --> SHORT[Identify Shortlisted Sites]
    
    SHORT --> PASS2[Pass 2: Targeted Deep Pass - Fetch 10 specialized fields on Shortlist]
    PASS2 --> EVAL_TARGETS{Evaluate Mandatory Hard Targets?}
    
    EVAL_TARGETS -->|Violated| FLAG[Flag Site Target Violation & Penalize]
    EVAL_TARGETS -->|Satisfied| RESCORE[Deterministic Final Rescore & Ranking]
    FLAG --> RESCORE
    
    RESCORE --> GAPS[Catalog Missing Fields as InformationGaps]
    GAPS --> VIEW[Render Interactive Map, Radar Charts & Candidate Cards]
    
    VIEW --> WHATIF{User modifies Weights or Overrides Metric?}
    WHATIF -->|Adjust Weights| INSTANT_RESCORE[Instant Local Deterministic Rescore]
    WHATIF -->|Override Metric| CONFIRM_EVIDENCE[Create USER_CONFIRMED Evidence]
    CONFIRM_EVIDENCE --> INSTANT_RESCORE
    INSTANT_RESCORE --> EXPLAIN[Generate Rank & Score Shift Explanation]
    EXPLAIN --> VIEW
```

---

## 3. During Construction — Change Intelligence Decision Pipeline

```mermaid
flowchart TD
    INPUT[Input: Existing Equipment vs Proposed Substitution] --> AGENT_PLAN[Agent Plans Situation-Specific Investigation]
    AGENT_PLAN --> FETCH_DOCS[Retrieve Cited Project & Manufacturer Documents]
    AGENT_PLAN --> FETCH_SITE[Fetch Relevant Site Ambient Conditions]
    
    FETCH_DOCS & FETCH_SITE --> GATES[Run 9 Pre-Verification Gates]
    
    subgraph GateVerification["Verification Gates Check (gates.py)"]
        G1[1. Model Identity]
        G2[2. Weight Basis / Data Type]
        G3[3. Configuration Comparability]
        G4[4. Pint Unit Compatibility]
        G5[5. Rating Conditions Equivalency]
        G6[6. Document Source Provenance]
        G7[7. Site Ambient Temperature Compatibility]
        G8[8. Coordinate Resolution]
        G9[9. Capacity vs Spec Requirement]
    end
    
    GATES --> G1 & G2 & G3 & G4 & G5 & G6 & G7 & G8 & G9
    
    G1 & G2 & G3 & G4 & G5 & G6 & G7 & G8 & G9 --> GATE_EVAL{Any Gate Open or Triggered?}
    
    GATE_EVAL --> DELTAS[Run 13 Deterministic Delta Computations (deltas.py)]
    
    subgraph DeltaComputations["Delta Computations"]
        D_WT[Weight Δ% > 5%]
        D_SP[Support Point Load Δ% > 5%]
        D_DIM[Dimensions L/W/H Δ% > 2%]
        D_ELE[MCA / MOCP / FLA Any Increase > 0%]
        D_PWR[Power Input Δ% > 5%]
        D_REF[Refrigerant Charge Δ% > 10%]
        D_CAP[Cooling Capacity Δ% > 2%]
        D_CAT[Voltage / Phase / Refrigerant Type Mismatch]
    end
    
    DELTAS --> D_WT & D_SP & D_DIM & D_ELE & D_PWR & D_REF & D_CAP & D_CAT
    
    D_WT & D_SP & D_DIM & D_ELE & D_PWR & D_REF & D_CAP & D_CAT --> IMPACT[Trace Downstream Impacts & Mark Stale Assumptions]
    
    IMPACT --> PRECEDENCE{Decision Precedence Logic}
    
    PRECEDENCE -->|Any OPEN check / missing data / gap| DEC_NEEDS[Decision: NEEDS INFORMATION]
    PRECEDENCE -->|Any TRIGGERED gate or threshold breach| DEC_ENG[Decision: ENGINEER REVIEW]
    PRECEDENCE -->|All Gates CLOSED & All Deltas ≤ Threshold| DEC_PASS[Decision: FIRST-PASS CHECKS CLOSED]
    
    DEC_NEEDS --> ACT_VEND[Draft Vendor Evidence Request / Clarification RFI]
    DEC_ENG --> ACT_REV[Draft Structured Review Comments & Confirmation Package]
    DEC_PASS --> ACT_SIGN[Draft Engineer Sign-off Package]
```

---

## 4. LangGraph 7-Phase Agent Execution & Replanning Loop

```mermaid
stateDiagram-v2
    [*] --> Understand
    
    Understand --> Plan : Project scope, sites, and change items parsed
    note right of Understand: Reads target specifications, candidate sites or change cases
    
    Plan --> Evidence : Supervisor constructs situation-specific plan
    note right of Plan: Validates requested fields against catalog; drops unknown keys
    
    Evidence --> Signals : Execute parallel API fetches & doc retrievals
    note right of Evidence: Queries Mireye /v1/fetch and vector search index
    
    Signals --> Replan : Unresolved gates or missing fields detected (max 1 loop)
    Signals --> Impact : All required evidence evaluated
    note right of Signals: Evaluates 9 gates, 13 deltas, and scoring functions
    
    Replan --> Impact : Targeted follow-up evidence collected
    note right of Replan: Re-queries targeted endpoints for specific missing data
    
    Impact --> Action : Assumptions evaluated & impact graph generated
    note right of Impact: Marks stale assumptions and maps 6-discipline ripple effects
    
    Action --> Done : Decision state finalized & next action drafted
    note right of Action: Computes final confidence and generates actionable drafts
    
    Done --> [*]
```

---

## 5. 6-Stage Evidence Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> live : Retrieved directly from active Mireye API
    [*] --> synthetic : Loaded from demo fixture database
    [*] --> missing : Requested metric unavailable from source

    live --> cached : Stored in SQLite/Redis cache within TTL
    cached --> stale : Observation age exceeds configured TTL
    live --> stale : Field invalidated by design revision

    synthetic --> user_confirmed : Certified / corrected by authorized engineer
    cached --> user_confirmed : Verified / overridden by engineer
    stale --> user_confirmed : Current field value entered by engineer
    missing --> user_confirmed : Missing metric supplied by engineer

    user_confirmed --> [*]

    note right of user_confirmed
        Confidence = 0.99
        Status = VERIFIED
        Supersedes previous evidence
    end note
```

---

## 6. Multi-Discipline Downstream Impact Graph Traversal

```mermaid
flowchart LR
    CHANGE[Equipment Change: CH-01 Substitution] -->|INVALIDATES| ASSUMP[Stale Assumption: Roof Steel Sizing]
    
    ASSUMP -->|AFFECTS| D_STRUCT[Discipline: Structural]
    ASSUMP -->|AFFECTS| D_ELEC[Discipline: Electrical]
    ASSUMP -->|AFFECTS| D_MECH[Discipline: Mechanical]
    ASSUMP -->|AFFECTS| D_CTRL[Discipline: Controls]
    ASSUMP -->|AFFECTS| D_LOG[Discipline: Installation & Logistics]
    
    D_STRUCT -->|REQUIRES| A_STEEL[Activity: Recalculate Roof Deflection & Sizing]
    D_ELEC -->|REQUIRES| A_FEEDER[Activity: Upsize Feeder Conductor & Breaker]
    D_MECH -->|REQUIRES| A_FLOW[Activity: Header Velocity & Flow Rebalancing]
    D_CTRL -->|REQUIRES| A_BMS[Activity: Remap BACnet/Modbus Registers]
    D_LOG -->|REQUIRES| A_CRANE[Activity: Crane Capacity & Rigging Plan]
    
    A_STEEL -->|VERIFIED_BY| C_LOAD[Commissioning: Support Load Inspection]
    A_FEEDER -->|VERIFIED_BY| C_ELEC[Commissioning: Full-Load Current Draw Test]
    A_FLOW -->|VERIFIED_BY| C_MECH[Commissioning: Seasonal Flow Capacity Verification]
```

---

## 7. Document Ingestion, Chunking & Hybrid Retrieval Pipeline

```mermaid
flowchart TD
    UPLOAD[PDF Document Uploaded] --> VALIDATE{Validate Filetype & Size ≤ 25MB}
    VALIDATE -->|Invalid| REJECT[Reject with 422 Error]
    VALIDATE -->|Valid| STORE_FILE[Save File to Secure Upload Directory]
    
    STORE_FILE --> MUPDF[PyMuPDF / fitz Page-Aware Parser]
    MUPDF --> CHUNK[Split into Text Chunks with Character Spans & Page Offsets]
    
    CHUNK --> REGEX[Regex & Entity Extraction Engine]
    REGEX --> EXTRACT_REQ[Extract Requirements, Equipment Tags & Model IDs]
    EXTRACT_REQ --> STORE_REQ[Persist Requirements & Document Records]
    
    CHUNK --> HYBRID[Index in Hybrid Retrieval Store]
    
    subgraph RetrievalEngine["Hybrid Search Engine (vectorstore.py)"]
        BM25[BM25 Lexical Keyword Indexer]
        VEC[Local Hashed N-Gram Embeddings / pgvector]
        FUSION[Reciprocal Rank Fusion / Scoring]
    end
    
    HYBRID --> BM25 & VEC --> FUSION
    
    STORE_REQ --> HUMAN_UI[Display in UI for Human Confirmation / Sign-off]
    FUSION --> SEARCH_API[Serve Citations via /api/projects/{id}/search]
```

---

## 8. Frontend-Backend Request & Response Sequence

```mermaid
sequenceDiagram
    autonumber
    actor Engineer as Project Engineer
    participant UI as React Dashboard
    participant API as FastAPI Backend
    participant Sup as LangGraph Supervisor
    participant Engine as Deterministic Engine (Pint)
    participant Adapt as Mireye / Adapters
    participant Store as Store / Knowledge Graph

    Engineer->>UI: Selects Change Case (e.g. CH-01) & clicks "Analyze"
    UI->>API: POST /api/projects/{id}/changes/{cid}/analyze
    API->>Sup: run_change_investigation(project, change)
    
    Sup->>Sup: Phase 1 & 2: Understand & Plan investigation steps
    Sup->>Adapt: Fetch site design temperatures & equipment submittals
    Adapt-->>Sup: Returns observed values + source provenance
    
    Sup->>Store: Save Evidence & InformationGap records
    Sup->>Engine: Run 9 Verification Gates (gates.py)
    Engine-->>Sup: Gate Statuses (CLOSED / OPEN / TRIGGERED)
    
    Sup->>Engine: Run 13 Delta Calculations (deltas.py)
    Engine-->>Sup: Delta Percentages & Threshold Statuses
    
    Sup->>Engine: Evaluate Stale Assumptions & Impacts (impact.py)
    Engine-->>Sup: Multi-Discipline Impact Map
    
    Sup->>Store: Upsert Impact Knowledge Graph
    Sup->>Engine: Evaluate Decision Precedence & Draft Next Actions (decisions.py)
    Engine-->>Sup: Decision State (ENGINEER REVIEW) + Draft RFI
    
    Sup-->>API: Returns complete Investigation object
    API-->>UI: 200 OK (Typed JSON Investigation)
    
    UI->>API: GET /api/impact/{cid}
    API->>Store: Traverse Knowledge Graph paths
    Store-->>API: ImpactGraph (Nodes & Edges)
    API-->>UI: 200 OK (Graph Data)
    
    UI-->>Engineer: Renders Decision Banner, Gate Cards, Deltas, Graph & Draft RFI
```
