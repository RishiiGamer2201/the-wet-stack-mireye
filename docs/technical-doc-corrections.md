# Corrections carried into the technical document

Every figure in `The-Wet-Stack-Mireye-Technical-Document.docx` was measured from
the running system on 2026-08-24 rather than carried over. Seven claims in the
previous draft did not survive that check.

| Previous draft | Verified | How it was checked |
|---|---|---|
| 13 Pint-checked deltas, "including COP" | **15**, and COP is not among them | `len(compute_deltas(empty, empty))` returns 15; the set is weight, max support point load, length, width, height, footprint area, voltage, phases, FLA, MCA, MOCP, power input, refrigerant type, refrigerant charge, cooling capacity |
| 273 tests passing | **277** | full suite run |
| 2,011 live Mireye records | **3,435** | count over the evidence store by `source_type` |
| 96% of 2,182 records real | **97.8% of 3,819** | 84 synthetic document records remain, everything else is sourced |
| Cascade returns a binary `WITHIN_FACILITY_LIMITS` / `EXCEEDED_CAPACITY` verdict | **Three states**, and the second is named `FACILITY_LIMITS_EXCEEDED` | `CascadeImpactSummary.collective_status` is `Literal["WITHIN_FACILITY_LIMITS", "FACILITY_LIMITS_EXCEEDED", "NEEDS_INFORMATION"]`. The third state matters: it is what the engine returns when a facility capacity is not stated, instead of issuing a structural verdict against an assumed building. |
| Catalog weighting remainder "split across acoustic and refrigerant limits" | The remainder is **water efficiency 5%, cost 5%, maintenance 5%, project compatibility 5%** | read from `catalog_engine.py`; there are no acoustic or refrigerant weights |
| "considered CONTEXTUAL_PROXY and registered, never taken as a proxy" | Reads as its own opposite | rewritten: it *is* a proxy, and is never taken as **the measurement** |
| "made it more accurate, not more honest" | Backwards | rewritten: the coverage drop is the system being honest |

## Claims that were checked and stand

30 concepts across 8 dimensions; 9 verification gates; 11 equipment classes;
5 public datasets; 8 concepts kept as gaps and 6 removed; coverage 0.348 to
0.259; 5 Mireye contract mismatches; the three decision states; the Harbour
Point, Rio Verde Mesa and FEMA findings.

## What was added

A **How We Use Mireye** section, because the hackathon is Mireye's and the
previous draft described the product without describing the integration. It
covers the catalog binding (30 concepts against 310 live fields, 11 exact, 6
unit-converted, 3 labelled proxies, 2 billed), the five contract corrections,
the credit and caching discipline, which endpoints feed scores versus which are
exploratory only, and what happens to the 14 concepts the catalog does not serve.

## Rebuilding

```bash
python scripts/build_technical_doc.py
```

Writes the `.docx`. Page count was confirmed at two through Word's own
`ComputeStatistics`, not estimated from a word count.
