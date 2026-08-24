# The Wet Stack - Mireye
### Physical-world intelligence for data-centre siting and EPC change control

---

## The problem

A hyperscale data centre is decided twice: when the site is chosen, and again
every time equipment is substituted during construction. Both decisions turn on
physical facts, and in practice both are made on numbers nobody can trace.

The failure mode is specific, and it is not "we lacked data". It is that **absent
data quietly becomes a number**. A blank cell scores as zero. A nearby
measurement gets used because it is the closest thing available. A supplier's
figure is entered without its rating conditions. Each looks identical to a
measurement, and by the time anyone notices it is inside a capital decision.

Mireye solves retrieval: it tells you what the physical world is doing at a
coordinate. We went after what happens **after** retrieval, which is how a system
reasons over physical data without inventing the parts it does not have.

---

## The idea: absence is a finding, not a blank

One rule drives the whole design.

> **A value nobody measured is missing. Missing never becomes zero, and a
> related measurement is never the measurement.**

Obvious to say, structurally hard to hold, because the wrong answer is always
the convenient one. Three ways we enforce it:

**1. Every value carries how it relates to the question.** Mireye publishes a
0.4% design *wet-bulb* temperature; our model needs *dry-bulb*. Both are
temperatures in °C, so nothing breaks if you swap them. The score is just wrong.
Instead the reading is stored as `CONTEXTUAL_PROXY`: real, cited, visible, and
structurally unable to fill the field, close its gap or pass a gate. Applying
that rule dropped evidence coverage from 0.348 to 0.259 and left the decision
unchanged. That drop is the system telling the truth.

**2. A gap is an instruction.** When nothing can answer a concept the output is a
named next action: *commission a geotechnical investigation*, *ask the utility
for circuit-level outage history*. Eight concepts have no public source today and
are deliberately kept, because each produces an action. Six others were
**deleted**, because they produced only noise.

**3. The model explains; deterministic code calculates.** Every number, unit
conversion, threshold and decision state comes from tested Python. The LLM plans
investigations and writes the narrative. A regression test asserts that no LLM
path can write a number.

---

## How it works

| Workflow | Question | Output |
|---|---|---|
| **Before construction** | Which candidate site should we build on? | Ranked sites, per-dimension scores, coverage, open gaps |
| **During construction** | This equipment was substituted - what does it touch? | Deterministic checks, impact graph, decision state |

The agent runs a seven-node LangGraph loop - Understand, Plan, Evidence, Signals,
Replan, Impact, Action - over 30 concepts across 8 dimensions (water, power,
connectivity, civil, hazards, terrain, environmental, regulatory).

```
React + Vite  →  FastAPI  →  ┌ Mireye API (live physical data)
                             ├ 5 public datasets (bundled)
                             ├ Deterministic scoring engine (Pint units)
                             ├ Document ingestion + OCR
                             └ Neo4j impact graph
```

---

## What is built, and how we know

Not a mock. The numbers below are measured from the running system.

| | |
|---|---|
| **Live Mireye integration** | 2,011 evidence records from USGS, FEMA, NREL, EIA, NOAA, EPA, NRCS, FCC |
| **Contract correctness** | 5 mismatches between the assumed and real Mireye API found and fixed against the live service, documented in `docs/mireye-contract.md` |
| **Public datasets wired** | PeeringDB, EPA/USGS Water Quality Portal, USGS PAD-US, EIA-861, FEMA National Risk Index - 6 concepts served, 1 proxy retired |
| **Real vs synthetic** | 2,098 of 2,182 evidence records (96%) are real measurements; the remaining 84 are labelled synthetic documents |
| **Document ingestion** | PDF text + OCR for scans; a transcribed value is carried at half confidence and flagged for human review |
| **Verification** | 273 tests, lint and typecheck clean |

Two findings the system produced that the team did not know beforehand:

* **Harbour Point, VA** - groundwater at **6,610 mg/L** total dissolved solids.
  Brackish. That changes the cooling design, and it was invisible while the
  number was synthetic.
* **Rio Verde Mesa, AZ** - sits **inside Tonto National Forest** and is rated
  **Very High** for wildfire. Two independent public datasets agree. An earlier
  version of our own code reported it as 4 km from a shooting range; we found and
  fixed the query bug that hid it.

One scale trap worth naming: FEMA's wildfire index runs 0-100 and looks directly
comparable to any other 0-100 index. It is not. The median tract FEMA calls *Very
Low* scores 43.6, so evenly-spread thresholds would have penalised every safe
site in the country by half its wildfire points. Thresholds are now anchored to
FEMA's own published class boundaries, with a test that fails if a future release
moves them.

---

## Why this is impactful

A single hyperscale campus is a **$1-3 bn** commitment, and the siting decision
is made in weeks on the thinnest evidence in the project's life. Two concrete
consequences:

**Before construction:** the cost of choosing wrong is not the land. It is
discovering brackish water, an unbuildable interconnection queue or a wildfire
exposure after the option is signed. This surfaces them as tracked gaps with
named owners, in hours rather than a six-week consultant study.

**During construction:** substitutions are constant and each is a small
coordination risk. The system flags where structural, electrical or mechanical
review is *required*, and never claims adequacy. That distinction is what makes
it usable by the engineer who carries the liability.

**For Mireye:** a demonstration of what the API is worth when something reasons
over it rather than displaying it. Every call is credit-metered, cached against
the catalog's own TTLs and budget-capped, because a product built on a paid API
has to respect what it costs.

---

## What is next

1. **Replace the last synthetic data.** 84 document records remain; the path is
   documented. AHRI certified ratings and manufacturer submittals, through the
   upload flow that already works.
2. **Four more public datasets.** WRI Aqueduct, USGS 3DEP, USDA CropScape and
   NOAA ISD, each with its blocker and procedure written up.
3. **Production architecture.** Kafka, Redis, Postgres and a projection-based
   impact graph, designed in `docs/production-lld.md`, with a migration order
   whose first four steps carry a real pilot on their own.

---

**Stack** React 18 · TypeScript · Vite · Tailwind · FastAPI · Pydantic v2 ·
LangGraph · Pint · Neo4j AuraDB · SQLite/pgvector · Tesseract · OpenAI ·
Deployed on Render (Docker) + Vercel

**Repository** `github.com/RishiiGamer2201/the-wet-stack-mireye` - 42 commits,
~21,000 lines, 15 documents including a verified Mireye contract reference, a
public-dataset procedure guide, and a production low-level design.
