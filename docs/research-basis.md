# Research basis

Prior work behind this build, and what each source actually supports. Research by
Muskaan Makkar; every link below was re-opened and checked before being written
down, because a citation that does not survive a click is worse than no citation.

| Status | Meaning |
| --- | --- |
| **Verified** | Opened, title/authors/claims confirmed |
| **Partly verified** | Source is real, but a specific claim about it was not confirmed |
| **Reported** | Second-hand, not independently checked |

---

## 1. Sources

| Source | Status | What it is |
| --- | --- | --- |
| [arXiv 2501.13958](https://arxiv.org/abs/2501.13958) — *A Survey of Graph Retrieval-Augmented Generation for Customized LLMs* (Zhang et al., Jan 2025) | **Verified** | Survey of GraphRAG: retrieval over a knowledge graph rather than flat text |
| [arXiv 2605.19743](https://arxiv.org/abs/2605.19743) — *EngiAI: A Multi-Agent Framework and Benchmark Suite for LLM-Driven Engineering Design* (Molinari, Felten, Massoudi, Fuge; May 2026, IDETC 2026) | **Verified** | One supervisor coordinating seven specialist agents for engineering design |
| [US12373613B2](https://patents.google.com/patent/US12373613B2/en) — *Construction Knowledge Graph*, **Procore Technologies** | **Verified** | Granted 29 Jul 2025, **active**, expires 2043. See §2 |
| [arXiv 2305.15097](https://arxiv.org/abs/2305.15097) — *Computer Vision for Construction Progress Monitoring* (Yang, Wilde, Menzel, Sheikh, Kuznetsov) | **Partly verified** | Real paper, YOLOv8-based. The abstract does **not** mention window-installation stages, and the **">95% precision" figure is not in the abstract** — check the full PDF before quoting it |
| [Mireye customer post](https://www.linkedin.com/posts/ansh-chokshi_heres-how-our-first-customers-are-using-activity-7489488271903997952-sT11) (Ansh Chokshi) | **Verified** | See §3 |
| *Automating construction contract review using knowledge-graph-enhanced LLMs* (ScienceDirect S0926580525002195) | **Reported** | Nested contract knowledge graph, tested on international EPC contracts |
| *AutoRepo: multi-modal LLM-based automated construction reporting* (ScienceDirect S0957417424014684) | **Reported** | LLM pipeline producing structured inspection reports |
| *The Hidden Water Geography of U.S. Hyperscale Data Centers* | **Reported** | Water is consumed **twice**: in electricity generation *and* in on-site cooling |
| Texas A&M Urban Resilience AI Lab — nationwide data-centre vulnerability assessment | **Reported** | Maps every US data centre against natural-hazard and power-outage exposure; builds a composite risk score using spatial statistics |

The last four need a link and a date before they go in a submission.

---

## 2. The patent is not just supporting evidence — read this before publishing

`US12373613B2` was collected as work that validates our approach. It does, but it
is also an **active granted patent held by Procore Technologies**, a large
construction-software company, and its claims sit close to our During
Construction workflow.

What it claims: receive construction data assets (RFIs, change orders,
schedules); use ML to resolve textual references such as "exterior wall" or
"Sheet A5" to **(x, y, z) coordinates** in a project coordinate system; use a
**second ML model trained on historical project data to predict downstream
impacts**; build a knowledge graph of the results and notify stakeholders of
cascading effects.

Where our system differs, factually:

| Patent claim | This build |
| --- | --- |
| Location `(x, y, z)` is the unifying key; ML resolves text to coordinates | **No spatial model at all.** Our graph is `Change → Stale Assumption → Discipline → Activity → Commissioning` — dependency and discipline based, never geometric |
| A second **ML model predicts** downstream impacts from historical data | **No ML anywhere in the impact path.** `engine/impact.py` is six explicit deterministic rules keyed on triggered checks and deltas. That is the safety argument, not an implementation detail |
| Predicts schedule consequences (e.g. an RFI open >3 days will delay the project) | Predicts nothing. It reports which recorded assumptions a *measured* change invalidates |
| Trained on historical construction data | No training data, no model weights |

Those are substantive differences, and they exist because of design decisions we
made for safety, not to avoid anyone's patent. **This is not legal advice and not
a clearance opinion.** For a hackathon submission the exposure is different from
shipping a commercial product; before you commercialise, put this patent in front
of someone who does patent law. Flagging it now is cheaper than finding out later.

---

## 3. What Mireye's own customers actually do

From the founder's post (verified): *"Tell the agent your buy box. It searches,
screens, and qualifies opportunities for you."* Two named uses — sourcing
**off-market data-centre land**, and finding a **500-acre site for supersonic
aircraft testing**. The enrichment named is power lines, fiber, transmission
infrastructure, topography, wetlands and regulatory signals.

Two things follow.

**It validates the dimension set.** Their customers' due-diligence checklist is
almost exactly our eight scoring dimensions, arrived at independently.

**It exposes a gap in our framing.** Their workflow starts from a *buy box* and
**discovers** candidates. Ours starts from candidates you already have and
**screens** them. We built the second half of their loop. Candidate discovery
from a requirements box is the obvious extension — and is explicitly **out of
scope before 24 Aug** (§6).

---

## 4. What each source supports here

**GraphRAG (2501.13958)** — precedent for retrieval over a graph rather than flat
text. We already run a knowledge graph (`adapters/graphstore.py`, Neo4j or
in-memory) and hybrid retrieval (`adapters/vectorstore.py`, BM25 + local dense
vectors, RRF-fused). They are currently **separate**: retrieval does not traverse
the graph. Joining them is the honest next step, not something we can claim today.

**EngiAI (2605.19743)** — direct precedent for the supervisor-plus-specialists
shape in `agent/workflow.py`. Its benchmark result is the useful part: proprietary
models hit 96–97% task completion, but **conditional branching drops to 20–53%**.
That is exactly why our branch conditions (`_needs_replan`, decision precedence)
are deterministic Python and not model decisions.

**Contract-review KG (ScienceDirect)** — precedent for extending the graph from
physical impacts to contract-clause risk. Not built.

**AutoRepo (ScienceDirect)** — precedent for LLM-generated *structured* reports,
which is what `engine/decisions.build_next_actions` produces (RFI, vendor
evidence request, review comment) — except ours are deterministic templates, so
the citation supports the direction rather than the implementation.

**Water geography** — the strongest scoring critique in the whole set. Our WATER
dimension models **direct site water only** (`water_stress_index`,
`groundwater_availability_l_s`, `water_quality_tds_mg_l`,
`distance_to_water_source_km`). If a site's grid power is thermoelectric, the
plant consumes water on that site's behalf somewhere else entirely, and we score
none of it. This is a real modelling gap, and worth saying out loud in the pitch
rather than waiting to be asked.

**Texas A&M vulnerability assessment** — nationwide empirical backing for the
HAZARDS_CLIMATE dimension, plus a published method for composite risk scoring to
compare against `engine/scoring.risk_level`.

---

## 5. Minimum agent set

EngiAI runs one supervisor over seven specialists. Mapped onto what already
exists here — most of it is built, and the split is by *evidence source and
decision*, not by "more agents looks better":

| Agent | Status | Lives in |
| --- | --- | --- |
| **Supervisor / planner** — decides what to investigate, re-plans on gaps | built | `agent/planner.py`, `agent/workflow.py` |
| **Physical-world agent** — Mireye catalog, geocode, fetch, gap + feature request | built | `adapters/mireye.py`, `services/sites.py` |
| **Document agent** — ingest, chunk, extract requirements with spans | built | `services/ingest.py` |
| **Retrieval agent** — hybrid BM25 + vector over ingested chunks | built | `adapters/vectorstore.py` |
| **Verification agent** — 9 gates before any comparison is accepted | built, deterministic | `engine/gates.py` |
| **Impact agent** — stale assumptions, discipline tracing, graph | built, deterministic | `engine/impact.py` |
| **Action agent** — decision state and drafted next action | built, deterministic | `engine/decisions.py` |
| Manufacturer/AHRI agent — independent certified performance lookup | **not built** | — |
| Vision agent — installed-equipment check from site photos | **not built**, see §6 | — |

The load-bearing rule: the supervisor and the document/retrieval agents may use a
model. **The verification, impact and action agents never do**, and
`tests/test_llm.py` enforces it — a model that answers every prompt with
"FIRST-PASS CHECKS CLOSED, score 99.9, zero deltas" changes nothing in the output.

---

## 6. Deliberately not building before 24 August

The vision suggestions in the research are good and genuinely fit the gap between
"what the documents say" and "what is on site". They are still the wrong thing to
start now:

* a vision feature needs a model, labelled data, and a UI, and a half-working one
  demoed live is worse than not claiming it;
* 2305.15097's headline accuracy number is **unconfirmed** (§1), so the
  supporting evidence is not yet solid enough to build a claim on;
* the same effort spent on the water double-count or on graph-aware retrieval
  improves something that is already real and already tested.

Cite them as roadmap with the papers attached. Do not put them on a slide as
though they run.

---

## 7. Open items

1. Get links and dates for the water-geography and Texas A&M papers.
2. Confirm the ">95% precision" figure in 2305.15097 against the full PDF, or drop it.
3. Decide whether the WATER dimension should carry an indirect/embedded-water
   concept. If Mireye has no field for it, it becomes an InformationGap — which is
   the honest outcome and demonstrates the gap machinery.
4. Legal review of `US12373613B2` before any commercial use (§2).
