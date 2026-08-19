# Tech Stack & Frameworks Catalog

This document details the complete technology stack, frameworks, libraries, toolchains, and deployment configurations used in **The Wet Stack — Mireye**.

---

## 1. Architecture Stack Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND CLIENT                               │
│  React 18 · TypeScript 5.6 · Vite 6 · Tailwind CSS 4 · Leaflet · Lucide │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ JSON / REST (Proxied in dev via Vite)
┌────────────────────────────────────▼────────────────────────────────────┐
│                             BACKEND API                                 │
│         FastAPI 0.110+ · Uvicorn 0.29+ · Pydantic v2 · Python 3.10+     │
├────────────────────────────────────┬────────────────────────────────────┤
│           AGENT LAYER              │        DETERMINISTIC ENGINE        │
│    LangGraph 0.2+ StateGraph       │   Pint 0.23+ (Physical Units)       │
│    Dynamic Supervisor Planner      │   Multi-Criteria Scoring Engine    │
│    LLM Guardrails / Narrator       │   9 Verification Gates & 13 Deltas │
│                                    │   Multi-Discipline Impact Engine   │
├────────────────────────────────────┴────────────────────────────────────┤
│                         ADAPTER & STORAGE SEAM                          │
│  ┌──────────────────────┬────────────────────────┬───────────────────┐  │
│  │     Mireye API       │     Graph Storage      │ Vector Retrieval  │  │
│  │ Live (HTTPX) / Mock  │ Neo4j / In-Memory Store│ pgvector / SQLite │  │
│  └──────────────────────┴────────────────────────┴───────────────────┘  │
│  ┌───────────────────────────────────────────────┬───────────────────┐  │
│  │               Document Store                  │   LLM Narrator    │  │
│  │        PostgreSQL / Supabase / SQLite3        │ Anthropic / Local │  │
│  └───────────────────────────────────────────────┴───────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Backend Tech Stack & Libraries

### 2.1 Core Framework & Runtime
* **Python Runtime:** `Python >= 3.10` (tested with 3.10 and 3.11).
* **FastAPI (`>=0.110`):** High-performance asynchronous REST API framework providing automatic OpenAPI schema generation, dependency injection, and request validation.
* **Uvicorn (`[standard] >=0.29`):** Lightning-fast ASGI web server implementation based on uvloop and httptools.
* **Pydantic (`>=2.6`):** Data parsing, validation, and domain model definitions with strict typing and serialization.
* **Pydantic-Settings (`>=2.2`):** Environment-based settings and configuration management supporting `.env` files.

### 2.2 Domain Logic & Engineering Calculations
* **Pint (`>=0.23`):** Industrial-grade physical quantity and unit registry. Ensures dimensional safety (e.g., converting tons to kW, lbs to kg, gallons/min to L/s) and raises strict errors on dimensional conflicts.
* **PyMuPDF / `fitz` (`>=1.24`):** High-speed C-backed PDF parsing engine used for page-aware text extraction, chunking, and character span indexing.
* **LangGraph (`>=0.2`):** Graph-based agent orchestration framework used to define the 7-phase stateful investigation workflow and replanning loops.
* **HTTPX (`>=0.27`):** Modern async/sync HTTP client for communicating with external Mireye endpoints with connection pooling, retries, and backoff.
* **Python-Multipart (`>=0.0.9`):** Streaming multipart form parser for document and PDF submittal uploads.

### 2.3 Live Mode & Storage Connectors (Optional Dependencies)
* **SQLite3 (Standard Library):** Embedded document and metadata store for zero-dependency local demo execution.
* **psycopg (`[binary] >=3.1`):** High-performance PostgreSQL driver supporting binary data transfer and `pgvector` similarity search.
* **neo4j (`>=5.19`):** Official Neo4j Python driver for executing Cypher queries and traversing multi-discipline impact graphs in live deployments.
* **Anthropic SDK (`anthropic`):** LLM integration for generating prose summaries and answering exploratory questions (Claude 3.5 Sonnet / Claude Opus).

### 2.4 Backend Quality & Testing Toolchain
* **Pytest (`>=8.1`):** Python testing framework executing 122 automated unit, adapter, integration, and end-to-end tests.
* **Pytest-Asyncio (`>=0.23`):** Async test support for FastAPI endpoints and async client flows.
* **Ruff (`>=0.4`):** Ultra-fast Rust-based Python linter and code formatter.

---

## 3. Frontend Tech Stack & Libraries

### 3.1 Core Framework & Build Tool
* **Node.js:** `>= 20.0.0` (LTS).
* **React (`^18.3.1`):** Modern component-based declarative UI library utilizing hooks (`useState`, `useEffect`, `useCallback`, `useMemo`).
* **React-DOM (`^18.3.1`):** DOM rendering layer.
* **TypeScript (`^5.6.3`):** Type-safe JavaScript superset with strict compiler options (`tsc --noEmit`).
* **Vite (`^6.0.5`):** Next-generation frontend build tool and dev server featuring instant HMR (Hot Module Replacement) and automated API proxying.

### 3.2 Styling & Design Tokens
* **Tailwind CSS (`^4.0.0`):** Modern utility-first CSS framework with custom design tokens for data-center engineering (signal colors, dark mode ink scales, status badges).
* **@tailwindcss/vite (`^4.0.0`):** Native Vite plugin for Tailwind CSS v4 compilation.

### 3.3 Data Visualization & Interactive Mapping
* **Leaflet (`^1.9.4`):** Open-source JavaScript library for mobile-friendly interactive maps.
* **React-Leaflet (`^4.2.1`):** React bindings for Leaflet map components, layers, and markers.
* **Recharts (`^2.15.0`):** Composable charting library built on React components and SVG for dimension radar and bar charts.
* **Lucide-React (`^0.469.0`):** Clean, consistent feather-derived icon set.

---

## 4. Infrastructure & Deployment Configurations

### 4.1 Deployment Platforms
* **Backend: Render Web Service (`render.yaml`)**
  - Managed Linux container running Uvicorn on Python 3.11.
  - Auto-configured environment variables and health check routes (`/api/health`).
  - Ephemeral disk handling with automatic synthetic demo data re-seeding on cold start.
* **Frontend: Vercel (`vercel.json`)**
  - Edge static hosting with SPA client routing rewrite rules (`/(.*) -> /index.html`).
  - Production build environment validation rejecting localhost API URLs.

### 4.2 Local Container Infrastructure (`infra/docker-compose.yml`)
* **Neo4j Enterprise/Community:** Containerized graph database running on ports `7474` (HTTP) and `7687` (Bolt).
* **PostgreSQL with `pgvector`:** Containerized relational database running on port `5432` with pre-installed vector extension for dense embedding search.

---

## 5. Summary Dependency Matrix

| Component | Framework / Tool | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **API Server** | FastAPI | `0.110+` | REST API layer, OpenAPI documentation |
| **Server Engine** | Uvicorn | `0.29+` | ASGI runtime |
| **Data Validation** | Pydantic | `2.6+` | Strict schema validation |
| **Unit Arithmetic** | Pint | `0.23+` | Physical quantity conversions |
| **Agent Machine** | LangGraph | `0.2+` | Stateful orchestration |
| **PDF Extraction** | PyMuPDF | `1.24+` | PDF text parsing |
| **Graph DB** | Neo4j Driver | `5.19+` | Live impact graph storage |
| **Relational / Vector**| Psycopg + pgvector | `3.1+` | Live data store & vector search |
| **UI Framework** | React | `18.3+` | Frontend dashboard |
| **Language** | TypeScript | `5.6+` | Type safety across client |
| **Build Tool** | Vite | `6.0+` | Frontend bundling & proxy |
| **Styling** | Tailwind CSS | `4.0+` | UI styling & responsive layouts |
| **Mapping** | Leaflet / React-Leaflet | `1.9+ / 4.2+` | Interactive geospatial site map |
| **Charts** | Recharts | `2.15+` | Dimension analysis charts |
| **Linter / Formatter** | Ruff | `0.4+` | Code quality enforcement |
| **Testing** | Pytest | `8.1+` | 122 automated tests |
