# Site scoring

Implemented in [`apps/api/app/engine/scoring.py`](../apps/api/app/engine/scoring.py), specified in
[`apps/api/app/fields.py`](../apps/api/app/fields.py), tested in
[`tests/test_scoring.py`](../tests/test_scoring.py). **No part of this runs through a language model.**

## 1. Normalisation — raw value → 0–100 (higher is better)

Each of the 34 catalog fields declares a direction and its thresholds:

| Direction | Formula |
| --- | --- |
| `higher_better` | `n = clamp((v − bad) / (good − bad), 0, 1) × 100` |
| `lower_better` | `n = clamp((bad − v) / (bad − good), 0, 1) × 100` |
| `band` | `100` inside `[low, high]`, then decaying linearly to `0` at `low − tolerance` / `high + tolerance` |
| `categorical` | table lookup; **an unmapped category is missing, not zero** |

`v = None` (no evidence) returns `None` — the metric is excluded from the mean, not scored as 0.
That distinction is the whole point: an unknown site is not a bad site.

Worked example — `grid_capacity_mw` (`good = 300`, `bad = 20`, `higher_better`):

```
v = 420 → clamp((420−20)/(300−20)) = clamp(1.43) = 1.0   → 100
v = 180 → (180−20)/280 = 0.571                            → 57
v =  10 → clamp(−0.036) = 0                               →  0
```

## 2. Dimension score

```
score_d    = Σ(w_i · n_i) / Σ(w_i)          over metrics that have evidence
coverage_d = Σ(w_i evidenced) / Σ(w_i all)
conf_d     = [Σ(w_i · c_i · s_i) / Σ(w_i evidenced)] × (0.4 + 0.6 · coverage_d)
```

`c_i` is the evidence confidence, `s_i` the status multiplier:

| Status | Multiplier |
| --- | --- |
| `live`, `user_confirmed` | 1.00 |
| `cached` | 0.90 |
| `synthetic` | 0.60 |
| `stale` | 0.35 (and not usable for the score at all) |
| `missing` | 0.00 |

## 3. Site score

```
overall  = Σ(W_d · score_d) / Σ(W_d)     over dimensions that scored
coverage = Σ(W_d · coverage_d) / Σ(W_d)  over all dimensions
conf     = Σ(W_d · conf_d) / Σ(W_d)
```

`W_d` are the dimension weights, editable per project and live in the UI. Default weights:

| Dimension | Weight | Metrics |
| --- | --- | --- |
| Power & grid | 2.0 | grid capacity, distance to substation, SAIDI, planned expansion |
| Water | 1.6 | water stress, groundwater availability, TDS, FEMA flood zone, distance to source |
| Hazards & climate | 1.3 | seismic PGA, wildfire, extreme-heat days, design wind, ambient design dry-bulb |
| Connectivity & access | 1.2 | fiber routes, distance to fiber, IX latency, distance to highway |
| Civil & soil | 1.1 | bearing capacity, depth to bedrock, cut/fill volume, drainage class |
| Regulatory | 1.1 | zoning, permit lead time, incentives, jurisdiction complexity |
| Geography & terrain | 1.0 | elevation, mean slope, ruggedness, land cover |
| Environmental & agriculture | 0.9 | distance to protected area, cropland fraction, wetland fraction, biodiversity |

## 4. Hard project targets

Separate from the score, `RequirementTargets` are evaluated as pass/fail flags:

| Target | Field | Test |
| --- | --- | --- |
| `min_grid_capacity_mw` | `grid_capacity_mw` | ≥ |
| `max_distance_to_substation_km` | `distance_to_substation_km` | ≤ |
| `max_water_stress_index` | `water_stress_index` | ≤ |
| `max_permit_lead_time_months` | `permit_lead_time_months` | ≤ |
| `min_bearing_capacity_kpa` | `soil_bearing_capacity_kpa` | ≥ |
| `max_seismic_pga_g` | `seismic_pga_g` | ≤ |
| `max_latency_to_ix_ms` | `latency_to_ix_ms` | ≤ |

A target with no evidence yields `passed = None` (**unknown**, severity `high`) — never an assumed
pass. A miss of more than 25 % is `critical`.

## 5. Risk level

Start from the score: `≥75 low`, `≥62 moderate`, `≥48 elevated`, else `high`. Then escalate one
level for coverage below 60 %, one level for any failed target, and one more per *critical* failed
target. Capped at `high`.

## 6. Ranking and explanation

Sort by `overall_score`, tie-break on confidence then coverage. Sites with no scored dimension rank
last with `rank = None`.

The comparison sentence attributes the gap to weighted contributions:

```
contribution_d = (score_d(A) − score_d(B)) × W_d / ΣW
```

which produces, from the seeded demo:

> Cascade Flats (92.9) ranks above Rio Verde Mesa (72.9). Largest weighted contributions:
> Water +9.3 pts weighted; Hazards & climate +3.7 pts weighted; Power & grid +2.0 pts weighted.

## 7. Progressive investigation

24 fields are marked `broad` and fetched for every candidate. 10 are marked `deep` and fetched only
for the shortlist (top 2 after the broad pass), which is what the `Replan` phase does. Deep fields:
water TDS, SAIDI, planned expansion, depth to bedrock, cut/fill volume, design wind speed,
biodiversity sensitivity, permit lead time, incentive score, jurisdiction complexity.

## 8. What-if

Two supported interactions, both recomputed by the backend against the *same* stored evidence:

1. **Change dimension weights** — `POST /api/projects/{id}/ranking` returns the new ranking, the
   baseline, and a rank-change explanation.
2. **Correct one site value** — `POST /api/projects/{id}/sites/{site_id}/override` records the value
   as `user_confirmed` evidence (superseding, not deleting, the previous record) and re-ranks.
