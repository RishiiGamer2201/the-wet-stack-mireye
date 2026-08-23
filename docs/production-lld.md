# Low-level design: taking this to production

The prototype runs as one FastAPI process with SQLite, an in-process graph, and a
single worker. That is the right shape for a demo and the wrong shape for a real
EPC deployment. This document is the design for the second thing.

It is written against what the code actually does today, so every section says
what exists, what breaks at scale, and what replaces it. Where a component is not
needed yet, that is stated rather than added for completeness.

---

## 1. What actually breaks first

Worth being concrete, because "add Kafka" is not a design.

| Constraint today | Where it bites | Trigger |
|---|---|---|
| Single uvicorn worker | All request throughput | ~20 concurrent users |
| In-process impact graph | Two workers disagree | The moment you add a worker |
| SQLite, one guarded connection | Write contention | ~50 writes/second |
| Synchronous ingestion | Request holds open for the whole OCR run | A 30-page scan, ~60 s |
| Synchronous site investigation | Request holds open across every Mireye call | 5 sites x 30 fields, ~40 s |
| Mireye credits billed per field per location | Cost, not latency | Any repeated investigation |
| Ephemeral disk | Everything is lost on deploy | Every deploy |

Two of those - **long-running work inside a request** and **paid third-party
calls** - are what actually shape the architecture. The rest is ordinary
horizontal scaling.

---

## 2. Target topology

```
                         ┌──────────────┐
   browser ─── HTTPS ───▶│  API (n pods)│  FastAPI, stateless, autoscaled
                         └──────┬───────┘
                                │ produce
                    ┌───────────▼────────────┐
                    │        Kafka           │
                    │  investigation.request │
                    │  document.uploaded     │
                    │  evidence.recorded     │
                    │  change.submitted      │
                    └───────────┬────────────┘
            ┌───────────────────┼────────────────────┐
            ▼                   ▼                    ▼
   ┌────────────────┐  ┌─────────────────┐  ┌──────────────────┐
   │ investigation  │  │  ingestion      │  │  projection      │
   │ workers        │  │  workers (OCR)  │  │  workers         │
   └───────┬────────┘  └────────┬────────┘  └────────┬─────────┘
           │                    │                    │
           ▼                    ▼                    ▼
   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
   │  Postgres    │    │  S3 / object │    │    Neo4j     │
   │  + pgvector  │    │   storage    │    │ impact graph │
   └──────┬───────┘    └──────────────┘    └──────────────┘
          │
          ▼
   ┌──────────────┐
   │    Redis     │  provider cache, idempotency keys, credit budget,
   │              │  rate limits, SSE fan-out
   └──────────────┘
```

Everything above the dashed line is stateless. All durable state is Postgres,
S3 and Neo4j. Redis holds nothing that cannot be rebuilt.

---

## 3. Kafka: what deserves a topic

A topic per *fact that other components care about*, not per function call.

### 3.1 `investigation.requested`

```json
{
  "investigation_id": "inv_7c1a…",
  "project_id": "prj_83f9…",
  "workflow": "before_construction",
  "site_ids": ["site_89ae…"],
  "field_keys": ["elevation_m", "flood_zone", "…"],
  "requested_by": "user_412",
  "requested_at": "2026-08-23T09:14:02Z",
  "idempotency_key": "prj_83f9:site_89ae:broad:v7"
}
```

* **Key:** `project_id`. Investigations for one project land on one partition, so
  they are processed in order and two runs cannot interleave writes to the same
  site.
* **Partitions:** 12 to start. Project count is the natural parallelism, and
  re-partitioning Kafka is disruptive, so overshoot deliberately.
* **Retention:** 7 days. Long enough to replay a bad deploy, short enough that
  the topic is not a database.
* **Consumer group:** `investigation-workers`, one consumer per pod.

The `idempotency_key` is the reason this is a queue and not an RPC. It encodes
project, subject, pass and the field-set version, so a retry after a worker crash
re-runs the same logical work rather than paying for the fields twice. The worker
checks Redis `SETNX idem:{key}` with a 24 h TTL before spending a credit.

### 3.2 `document.uploaded`

```json
{
  "document_id": "doc_e48b…",
  "project_id": "prj_83f9…",
  "object_key": "s3://wetstack-uploads/prj_83f9/doc_e48b.pdf",
  "sha256": "…",
  "page_count_hint": null,
  "kind": "submittal"
}
```

* **Key:** `document_id`, so retries of one document stay ordered.
* **Consumer group:** `ingestion-workers`, sized separately from the API because
  OCR is CPU-bound and bursty. These pods carry the Tesseract binary; the API
  pods do not need it.
* The API stores the file, writes a `ProjectDocument` row with
  `extraction_status = "pending"`, produces the event and returns **202** with
  the document id. The current synchronous 201 stays for files under a page
  threshold, because a one-page datasheet finishing inline is better UX than a
  poll.

**Backpressure that matters:** a 200-page scan is 200 x ~2 s of Tesseract. Cap
`OCR_MAX_PAGES` per document as today, and give the ingestion consumer group a
`max.poll.interval.ms` above the worst-case document, or Kafka will rebalance
mid-document and the work restarts. This is the single most common way an OCR
pipeline livelocks.

### 3.3 `evidence.recorded`

The interesting one, because it is what makes the system *reactive* rather than
batch.

```json
{
  "evidence_id": "ev_…",
  "project_id": "prj_83f9…",
  "subject_id": "site_89ae…",
  "field_key": "seismic_pga_g",
  "value": 0.31,
  "unit": "g",
  "relation": "exact",
  "status": "live",
  "supersedes": "ev_older…"
}
```

Consumers:

| Consumer group | What it does |
|---|---|
| `projection-neo4j` | Writes the impact edges for this evidence |
| `projection-scores` | Recomputes the affected site score |
| `assumption-invalidator` | Marks assumptions this contradicts as stale |
| `notifier` | Pushes an SSE frame to anyone watching that project |

That last row is why the current design cannot simply keep the graph in process:
four different things need to react to one fact, and three of them are slow.

**Ordering rule:** keyed by `project_id`, not `evidence_id`. Score recomputation
must see evidence for one project in the order it was written, or a stale value
can overwrite a fresh one.

### 3.4 `change.submitted`

Same shape and reasoning as investigations, keyed by `project_id`. Kept separate
because change analysis is latency-sensitive in a way site investigation is not:
someone is waiting on the screen for it.

### 3.5 What does *not* get a topic

* **Search queries.** Synchronous, sub-second, no fan-out. A queue would add
  latency and buy nothing.
* **LLM chat.** Streamed straight to the client over SSE. Putting a token stream
  through Kafka is a well-known way to make an interactive feature feel broken.
* **Mireye `/v1/ask`.** Exploratory, single-consumer, already slow; a queue makes
  it slower without making it more reliable.

---

## 4. Redis: five distinct jobs

Redis is doing five unrelated things and each has a different failure posture.
Worth separating in the code even if they share a cluster.

### 4.1 Provider response cache

Already implemented (`RedisCacheManager`), and this is the one that pays for
itself. Mireye bills per field per location; `parcel_record` is 300 credits.

```
mireye:fetch:{lat:.5f},{lng:.5f}:{field}   → value + provenance
TTL = the field's own ttl_seconds from Mireye's catalog
      (elevation 1 year, flood zone 30 days)
```

Round coordinates to 5 decimals - about 1 m - so two requests for the same parcel
share a cache entry, and no further. Rounding harder would serve one parcel's
flood zone for its neighbour.

**Failure posture: degrade.** A cache miss costs money, not correctness. The
existing file-backed fallback stays.

### 4.2 Credit budget

```
mireye:budget:{yyyy-mm}   → INCRBY on every billed field
mireye:budget:project:{id}
```

Checked before a fetch, not after. When a budget is exhausted the worker records
an `InformationGap` for the unqueried fields and finishes the investigation -
the existing `LiveBudget` behaviour, moved behind Redis so it holds across pods.

**Failure posture: fail closed.** If Redis is unreachable the worker must not
spend credits it cannot count. This is the one place where losing Redis stops
work, and that is the correct trade.

### 4.3 Idempotency keys

`SETNX idem:{key}` with a 24 h TTL, as above. Prevents a Kafka redelivery from
paying twice.

**Failure posture: fail closed**, same reasoning.

### 4.4 Rate limiting

Token bucket per user and per project, and a separate global bucket for each
upstream provider. PeeringDB, the Census geocoder and the PAD-US ArcGIS service
are free services being used by a commercial product; a runaway loop hammering
them is both rude and the fastest route to being blocked.

**Failure posture: degrade to a conservative local limit.**

### 4.5 SSE fan-out

Redis pub/sub, channel per project. With n API pods the browser's SSE connection
lands on one pod while the worker that produced the update runs on another.

**Failure posture: degrade.** The client already polls as a fallback.

---

## 5. Postgres: the schema that replaces the document store

Today everything is `records(collection, id, project_id, parent_id, data JSON)`.
That is a fine prototype store and a poor production one: no foreign keys, no
partial indexes, no way to query evidence by field without a full scan.

```sql
CREATE TABLE evidence (
    id              text PRIMARY KEY,
    project_id      text NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    subject_id      text,
    field_key       text NOT NULL,
    value_numeric   double precision,          -- one of these two, never both
    value_text      text,
    unit            text,
    relation        text NOT NULL,             -- exact | unit_converted | …
    status          text NOT NULL,             -- live | cached | synthetic | …
    verification    text NOT NULL,
    confidence      real NOT NULL,
    source          jsonb NOT NULL,
    superseded_by   text REFERENCES evidence(id),
    observed_at     timestamptz,
    recorded_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT one_value CHECK (num_nonnulls(value_numeric, value_text) <= 1)
);

-- The query the scoring engine actually makes: current canonical evidence for
-- one subject. A partial index keeps superseded rows out of it entirely.
CREATE INDEX evidence_current
    ON evidence (project_id, subject_id, field_key)
    WHERE superseded_by IS NULL
      AND relation IN ('exact', 'unit_converted', 'categorical_normalized');
```

Three things this buys that the JSON store cannot:

1. **`one_value` is enforced by the database.** The prototype relies on every
   writer being careful. A CHECK constraint does not get tired.
2. **The partial index encodes the canonical-relation rule** - a contextual proxy
   is physically absent from the index scoring reads, so a proxy cannot populate
   a value even if application code regresses. The rule stops depending on one
   `if` statement.
3. **`superseded_by` makes history immutable.** Evidence is appended, never
   updated. That is what lets a decision made in March be reconstructed in
   September, which is the actual requirement in construction disputes.

Retrieval moves to **pgvector** in the same database, which the code already
supports (`PgVectorIndex`). One fewer service, and chunk retrieval joins directly
against document rows.

**Partitioning:** not yet. Evidence grows at roughly (sites x fields x runs); a
large EPC programme is maybe 10 million rows a year, which Postgres handles
without partitioning. Revisit past 100 million.

---

## 6. Neo4j: what the graph is for

The impact graph answers one question: *what else does this change touch?* That
is a variable-depth traversal, which is where a graph database earns its keep and
where SQL recursive CTEs get painful.

```cypher
MATCH (c:Change {id: $change_id})-[:AFFECTS*1..4]->(n)
WHERE n.project_id = $project_id
RETURN n, length(path) AS hops
```

Written by the `projection-neo4j` consumer group, never by the API. This matters:
the graph is a **projection**, not a source of truth. If Neo4j is lost it is
rebuilt by replaying `evidence.recorded` and `change.submitted` from Kafka, which
is exactly why those topics exist.

The in-memory implementation stays as the fallback, as it is today. A degraded
graph is a smaller answer, not a wrong one.

---

## 7. The delivery guarantee, stated plainly

Kafka gives at-least-once. Everything downstream must therefore be idempotent,
and it is worth being explicit about how each consumer achieves that rather than
asserting it:

| Consumer | Idempotency mechanism |
|---|---|
| Investigation worker | Redis `SETNX` on the idempotency key before spending |
| Ingestion worker | `sha256` of the file; a re-delivered document is recognised |
| Score projection | Recompute is pure - same inputs, same output |
| Neo4j projection | `MERGE` on a deterministic edge id, never `CREATE` |
| Notifier | Duplicate SSE frames are harmless |

**Exactly-once is not attempted.** Kafka transactions across an external paid API
cannot give it anyway: the credit is spent the moment Mireye answers, whatever
the transaction does afterwards. Idempotency keys are the honest mechanism.

---

## 8. What must not change

The production design cannot quietly relax the rules the product is built on.
Three of them have specific implications here:

1. **Missing data must never become zero.** In Postgres, absent means `NULL`, and
   `num_nonnulls` allows zero non-null values. No `DEFAULT 0` on any measurement
   column, ever.
2. **A contextual proxy can never populate a value.** Enforced by the partial
   index above rather than by application code alone.
3. **Deterministic software performs the calculation; the model explains it.**
   The LLM path stays outside the write path entirely - it has no producer for
   `evidence.recorded`. This is checkable in CI, and there is already a
   regression test asserting no LLM path writes a number. That test becomes an
   architectural boundary rather than a unit test.

---

## 9. Observability

| Signal | Why this one |
|---|---|
| Consumer lag per group | The first symptom of every pipeline problem |
| Mireye credits spent per project per day | It is money, and the budget fails closed |
| Cache hit ratio on `mireye:fetch:*` | Directly proportional to the bill |
| p99 ingestion time, split OCR vs text | OCR is the only unbounded step |
| Evidence written per status | A spike in `synthetic` or `fallback` means a provider degraded |
| Investigations ending NEEDS INFORMATION | Rising means data quality is falling |

The last two are product signals, not infrastructure ones, and they are the pair
worth alerting on. A deployment where everything is green and every investigation
returns NEEDS INFORMATION is failing at the only thing it is for.

LangSmith tracing already exists and stays opt-in. It captures the agent's
reasoning; it is not a substitute for metrics on the deterministic path.

---

## 10. Migration order

Each step is independently shippable and independently revertible. That is the
point of the ordering - no step requires the next one to be useful.

1. **Postgres + pgvector.** Set `DATABASE_URL`, `SEED_ON_STARTUP=false`. Biggest
   single reliability win: state stops vanishing on deploy.
2. **Redis for the provider cache and credit budget.** Immediate cost reduction,
   no architectural change. Already implemented behind the settings.
3. **S3 for uploads.** Removes the last local-disk dependency, which is what
   unblocks running more than one API pod.
4. **Multiple API pods.** Only safe once 1-3 are done and the impact graph is
   external.
5. **Kafka + ingestion workers.** Moves OCR out of the request. Do this before
   investigation workers: it is the simpler consumer and it proves the operational
   pattern on work that is not billed.
6. **Kafka + investigation workers.** Needs idempotency keys in place first.
7. **Neo4j as a projection.** Last, because the in-memory fallback is genuinely
   adequate until several pods need to agree.

Steps 1-4 are ordinary hardening and would carry a real pilot. Steps 5-7 are for
concurrent programmes, and adding them earlier means operating Kafka for a system
whose actual bottleneck is a paid API with a rate limit.

---

## 11. What this design deliberately leaves out

* **A service mesh.** Four services do not need one.
* **CQRS with separate read models.** The read and write shapes are close enough
  that the partial index above covers it.
* **Event sourcing as the system of record.** Evidence is already append-only
  with `superseded_by`, which gives the audit trail without the replay
  complexity. Kafka retains 7 days, not forever.
* **A second LLM provider for failover.** The deterministic narrator is the
  failover, and it is a better one: it cannot hallucinate.
* **Multi-region.** Mireye is a US dataset provider. Until the product is used
  outside North America this is cost without benefit.
