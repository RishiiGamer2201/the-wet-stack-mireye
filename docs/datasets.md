# Public datasets: what is real, what is synthetic, and how to close the gap

This document exists to answer one question: **which numbers in this system came
from the physical world, and what does it take to make the rest of them real?**

It is written so that someone with no prior context can do the work. Every
source below was probed from this machine, most recently on 2026-08-22; where a
source was unreachable from here, that is stated rather than glossed over.

---

## 1. Where the data stands today

Counts from the live store (`apps/api/var/wetstack.db`, 1,585 evidence records):

| Provenance | Records | Synthetic? |
|---|---:|---|
| Mireye (live API — USGS, FEMA, NREL, EIA, NOAA, EPA, NRCS, FCC) | 1,483 | No |
| User input (uploaded documents, confirmations) | 18 | No |
| `manufacturer_document` (equipment cut sheets) | 57 | **Yes** |
| `project_document` (specs, submittals, RFIs) | 27 | **Yes** |

Plus, as of this change, two public datasets shipped with the code:

| Source | Serves | Records | Licence |
|---|---|---:|---|
| PeeringDB `/api/fac` | `distance_to_ix_km`, `ix_facility_carrier_count` | 1,353 US facilities | CC-BY 4.0 |
| EPA/USGS Water Quality Portal | `water_quality_tds_mg_l` (as context) | per-location query | Public domain |
| USGS PAD-US 4.1 | `protected_area_distance_km` | 298,244 areas | Public domain |
| EIA Form EIA-861 (2023) | `grid_reliability_saidi_min` (as context) | 734 utilities, 2,840 counties | Public domain |
| FEMA National Risk Index v1.20 | `wildfire_risk_index` | 84,093 census tracts | Public domain |

So the **before-construction** side is now almost entirely real. The
**after-construction** side — the 84 synthetic document records — is not, and
section 5 is how to fix that.

---

## 2. What was implemented (no action needed from you)

### 2.1 PeeringDB — interconnection

`apps/api/app/adapters/datasets.py` → `PeeringDBFacilities`

PeeringDB is the industry's own registry of where networks physically meet. The
adapter measures the great-circle distance from the site to the nearest facility
that hosts an internet exchange, and reports how many carriers are present there.

- 1,353 US facilities with coordinates ship inside the wheel at
  `apps/api/app/data/datasets/peeringdb_facilities.json`, so a fresh deploy on an
  empty disk still has them.
- Refresh at any time: `python -m app.datasets_cli download peeringdb`. The
  download writes under `DATA_DIR`, never over the bundled copy.
- Beyond 400 km the adapter returns **nothing**. A distance that large is not a
  near miss expressed precisely; it is the absence of an interconnection story,
  and the field stays an open gap.

**`latency_to_ix_ms` deliberately stays missing.** Latency is a function of the
route and the carrier, not of straight-line distance. Serving one as the other
would be the same error as reading a wet-bulb temperature as a dry-bulb one.

### 2.2 Water Quality Portal — measured TDS

`apps/api/app/adapters/datasets.py` → `WaterQualityPortal`

The Portal aggregates real laboratory results from USGS, EPA and state agencies.
The adapter takes the most recent mg/L total-dissolved-solids reading from a
monitoring station within 40 km.

Readings already cached for the demo's sites:

| Site | TDS | Sampled |
|---|---:|---|
| Cascade Flats, WA | 967 mg/L | 2023-08-11 |
| Rio Verde Mesa, AZ | 413 mg/L | 2026-07-15 |
| Delta Fields, MS | 96 mg/L | 2026-06-10 |
| Harbour Point, VA | 6,610 mg/L | 2023-08-23 |
| Prairie Junction, NE | 552 mg/L | 2023-12-05 |

Harbour Point at 6,610 mg/L is brackish coastal groundwater — exactly the kind of
finding that changes a cooling design, and exactly the kind of thing that was
invisible while the number was synthetic.

**This value is recorded as `CONTEXTUAL_PROXY`.** The sample came from someone
else's monitoring well some kilometres away. It is real, it is cited with its
station, date and organisation, and it informs the recommendation — but it never
fills `water_quality_tds_mg_l`, never closes that gap and never moves a score.
Only a laboratory analysis of the site's own source water can do that.

Notes:
- Results in `tons/ac ft` are the same sample in another unit and are discarded.
  Censored results (`<5`, `ND`) state a detection limit, not a value, and are
  discarded too. Readings from different stations are never averaged: different
  wells sample different aquifers and their mean describes none of them.
- A reading older than 15 years is carried at confidence 0.5 instead of 0.7, and
  says so in its own note.
- Pre-warm the cache after a deploy: `python -m app.datasets_cli warm`.

### 2.4 USGS PAD-US — distance to protected land

`apps/api/app/adapters/datasets.py` → `PADUSProtectedAreas`

PAD-US is the national inventory of protected land: every federal, state, local
and private conservation holding, 298,244 of them. This **replaces a proxy with
the real measurement**. The field used to borrow Mireye's distance to the nearest
Clean Air Act Class I area — national parks and large wilderness only, a strict
subset. Because the concept scores higher-is-better, that subset always made a
site look more remote from protected land than it is, which is why it was never
allowed to be the value. Now the field is `EXACT` and asks Mireye for nothing.

| Site | Nearest protected area | Distance |
|---|---|---:|
| Cascade Flats, WA | WA State Parks Eastern (SP) | 1.8 km |
| Rio Verde Mesa, AZ | **Tonto National Forest** (NF) | **0.0 km — inside it** |
| Delta Fields, MS | Walter Chandler Park (LCA) | 2.41 km |
| Harbour Point, VA | Fort Wool (SOTH) | 11.12 km |
| Prairie Junction, NE | Pioneer State Recreation Area (SREC) | 3.84 km |

Rio Verde Mesa sitting **inside** Tonto National Forest is the kind of finding
that ends a siting conversation, and the old proxy could not see it.

Three decisions worth knowing about, because each one is a judgement rather than
a lookup:

* **Expanding-ring search.** The ArcGIS service caps a response at a fixed number
  of features, so querying a 50 km buffer returns *some* 60 of the hundreds in
  range — not the nearest. The adapter searches 2 km, then 5, 15 and 50, pages
  every result in the first ring that contains anything, and computes true
  point-to-polygon distance locally. The first version of this did query the
  50 km buffer directly and reported Rio Verde Mesa as 4.02 km from a shooting
  range, because the national forest it sits inside was not in the returned page.
* **GAP status 1–3 only.** Status 4 is open space with *no known protection
  mandate*.
* **Municipal recreation is excluded from the value, never hidden.** A ball field
  300 m away is a land-use neighbour, not an ecological constraint, and this
  concept means conservation. Local Park / Local Recreation designations are
  filtered out of the number and named in the evidence detail instead, so the
  exclusion is visible. Local *Conservation* Areas stay in.

Boundary geometry is simplified server-side (~200 m) to keep a response near
20 kB, and the evidence says so: a gate within that margin needs the
full-resolution polygon.

### 2.5 EIA Form EIA-861 — grid reliability

`apps/api/app/adapters/datasets.py` → `EIAReliability`, built by
`scripts/build_eia861.py`

Every distribution utility in the US reports SAIDI — the average minutes a
customer spent without power in a year — to the EIA. That is real, audited,
nationwide data, and it is the best public answer to "how reliable is the grid
here". 734 utilities reported for 2023, covering 2,840 counties.

| Site | County | Worst utility | SAIDI |
|---|---|---|---:|
| Ashburn, VA | Loudoun | Northern Virginia Elec Coop | 40.3 min/yr |
| Prairie Junction, NE | Saunders | Omaha Public Power District | 57.9 min/yr |
| Rio Verde Mesa, AZ | Maricopa | 4 utilities, 10.6–160.3 | 160.3 min/yr |
| Delta Fields, MS | Shelby (TN) | City of Memphis | 408.6 min/yr |
| Cascade Flats, WA | Chelan | — | not reported; stays a gap |

**This is `CONTEXTUAL_PROXY`, and the Maricopa row is why.** SAIDI is a
utility-wide average over an entire service territory: a substation-adjacent site
and a rural end-of-line site on the same utility share one number that describes
neither. Worse, a county is often served by several utilities and nothing public
says which will serve a given parcel — Maricopa spans 10.6 to 160.3 minutes, a
15× range. The adapter reports the **worst** utility in the county, because a
siting decision that turns on reliability should not rest on the most flattering
of several possible suppliers, and it names every utility it found. The gap stays
open until the serving utility provides circuit-level history.

Two details that matter:

* **SAIDI without Major Event Days** is the figure used. "With MED" is dominated
  by individual storms and is not comparable between utilities.
* EIA writes `.` for "not reported". Four small municipal systems genuinely
  reported **0.0** minutes. Those are different values and the loader keeps them
  different — a reported zero is a measurement, a `.` is a gap.

Site → county comes from the Census geocoder (free, no key), cached to disk.
County names are normalised on both sides, because Census says "St. Louis city"
and "Doña Ana" where EIA says "St Louis City" and "Dona Ana", and an unnormalised
join silently misses.

Rebuild for a newer year: `pip install openpyxl && python scripts/build_eia861.py`
(openpyxl is a download-time dependency only; the runtime reads the JSON).

### 2.6 FEMA National Risk Index — wildfire risk

`apps/api/app/adapters/datasets.py` → `FEMANationalRiskIndex`, built by
`scripts/build_fema_nri.py`

FEMA's own baseline risk measurement for every US census tract. Mireye's catalog
has an annual wildfire frequency and hazard-zone classes, but no composite index,
so this concept had no source at all.

| Site | Tract score | FEMA rating | Scores |
|---|---:|---|---:|
| Ashburn, VA | 31.19 | Very Low | 100/100 |
| Cascade Flats, WA | 48.33 | Very Low | 100/100 |
| Harbour Point, VA | 50.66 | Very Low | 100/100 |
| Delta Fields, MS | 62.72 | Very Low | 100/100 |
| Prairie Junction, NE | 95.50 | Relatively Moderate | 2.8/100 |
| **Rio Verde Mesa, AZ** | **99.81** | **Very High** | **0/100** |

Rio Verde Mesa is inside Tonto National Forest and rated Very High for wildfire.
Two independent public datasets now say the same thing about that candidate.

**The scale is the trap, and it is worth understanding before trusting the
number.** `WFIR_RISKS` runs 0–100, so it looks directly comparable to any other
0–100 index. It is not. Measured across all 84,093 tracts:

| FEMA rating | Score range | Tracts |
|---|---|---:|
| No Rating (no modelled exposure) | 0.00 | 15,507 |
| Very Low | 18.44 – 68.65 | 42,223 |
| Relatively Low | 68.65 – 88.34 | 16,561 |
| Relatively Moderate | 88.35 – 96.26 | 6,656 |
| Relatively High | 96.26 – 99.06 | 2,356 |
| Very High | 99.06 – 100.00 | 790 |

The median tract FEMA calls **Very Low scores 43.6**. This field previously used
`good=10, bad=80` — round numbers invented for a synthetic 0–100 scale that never
existed. Feeding real NRI scores into that ramp would have scored Ashburn, a Very
Low tract, at 70/100 instead of 100, and would have penalised every safe site in
the country by roughly half its wildfire points. The number looked compatible
because both scales are "0–100"; that is exactly what makes it a silent error
rather than a loud one.

So the thresholds are re-anchored to **FEMA's own published class boundaries**
(68.65 = top of Very Low, 96.26 = start of Relatively High), which are measured
from the data and stored beside it in `_rating_bounds`. A test asserts the
thresholds still match those bounds, so a future NRI version that moves them
fails loudly instead of scoring against the old ones.

Known limit, stated rather than hidden: anything FEMA rates *Relatively High* or
worse scores 0 here, so the ramp does not separate High from Very High. Both are
already a serious constraint for a data centre, and the evidence carries FEMA's
rating text for a human to read.

The tract is resolved from coordinates by the same Census geocoder used for
counties — both layers come back in one request — so no geometry, no shapefile
and no spatial library are involved. That is why the **Table Format** download is
the right one and the 411 MB geodatabase is not.

To rebuild for a newer NRI version: download *All Census tracts / Table Format*
from <https://hazards.fema.gov/nri/data-resources> (605 MB CSV, 467 columns) and
run `python scripts/build_fema_nri.py path/to/NRI_Table_CensusTracts.zip`. It
keeps three columns and writes 2 MB.

### 2.3 Where the datasets live

```
apps/api/app/data/datasets/     # bundled with the wheel, committed
apps/api/var/datasets/          # downloaded at runtime, wins when present
```

| File | What it is |
|---|---|
| `peeringdb_facilities.json` | 1,353 US interconnection facilities |
| `eia861_reliability.json` | SAIDI per utility + county → utility map |
| `fema_nri_wildfire.json` | wildfire risk score + rating for 84,093 tracts |
| `wqp_tds_cache.json` | water-quality answers for the demo's sites |
| `padus_cache.json` | nearest protected area for the demo's sites |
| `county_cache.json` | coordinates → county *and tract*, from the Census geocoder |

```bash
python -m app.datasets_cli list                  # what is present
python -m app.datasets_cli download peeringdb    # refresh a national table
python -m app.datasets_cli warm                  # pre-query per-location sources
```

`warm` matters after a deploy: PAD-US, the Water Quality Portal and the county
lookup answer per coordinate rather than shipping a national table, so a site
nobody has asked about yet queries them live on its first investigation. Warming
moves that cost to deploy time. A failure at either point is a gap, never a
value.

---

## 3. Before construction — the remaining seventeen concepts

These are the fields Mireye's 306-field catalog has no equivalent for. Each one
is currently an **open, tracked gap** — never a zero, never a guess.

Difficulty is honest: **⭐ easy** (one download, one afternoon), **⭐⭐ moderate**
(a download plus a spatial join), **⭐⭐⭐ hard** (needs a paid source, a licence,
or an engineer).

---

### 3.1 `wildfire_risk_index` — FEMA National Risk Index ✅ DONE

**Implemented — see §2.6.** The zip was downloaded by hand, because
`hazards.fema.gov` refuses connections from this network (`ConnectError`, every
attempt, over two days) while being perfectly reachable from a browser. The
steps below are what the build script now does.

1. Open <https://hazards.fema.gov/nri/data-resources>.
2. Under **Download NRI Data**, choose *National — Census Tracts* (or *Counties*
   for a smaller file). Format: **CSV + shapefile**.
3. You get `NRI_Table_CensusTracts.csv`. The columns you need are:
   - `TRACTFIPS` — the join key
   - `WFIR_RISKS` — wildfire risk score, 0–100 (this is the field)
   - `WFIR_RISKR` — the risk rating text ("Relatively High" etc.)
4. Also download the tract boundaries from the Census TIGER/Line files:
   <https://www2.census.gov/geo/tiger/TIGER2023/TRACT/> — one ZIP per state.
5. Implementation: add a `FEMANationalRiskIndex` provider next to
   `PeeringDBFacilities`. Point-in-polygon the site's coordinates against the
   tract boundaries, then look up `WFIR_RISKS`.
   - Use `shapely` + `pyproj` (add to `pyproject.toml` under `live`), or
     pre-compute a tract-centroid file and match on nearest centroid **only if**
     you also record that the match was by centroid, not by containment.
6. Relation: **EXACT**. The NRI score is a property of the tract the site is in.
7. The same file also carries `RFLD_RISKS` (riverine flooding), `HRCN_RISKS`
   (hurricane), `ERQK_RISKS` (earthquake) and 14 other hazards — Mireye already
   serves flood zone and seismic, so add these only where they answer a field the
   catalog does not.

---

### 3.2 `water_stress_index` — WRI Aqueduct 4.0 ⭐⭐

**Status: reachable (HTTP 200), manual download required.**

1. Open <https://www.wri.org/data/aqueduct-global-maps-40-data>.
2. Download **Aqueduct 4.0 Current and Future Global Maps Data** (hosted on
   Figshare: <https://figshare.com/articles/dataset/26206821>). It is a
   GeoPackage / File Geodatabase of roughly 1 GB.
3. The layer you want is the **annual baseline** at hydrological-basin level.
   Columns:
   - `bws_raw` — baseline water stress, withdrawal ÷ available supply
   - `bws_score` — normalised 0–5
   - `bws_cat` — category (Low / Low-Medium / … / Extremely High)
4. Convert to something small: the full basin geometry is not needed at runtime.
   Extract basin polygons for the US only and simplify, or precompute a
   basin-id → score table plus a coarse raster.
5. Implementation: point-in-basin lookup, same shape as the FEMA provider.
6. Relation: **EXACT** for the concept as defined (a basin-level stress index is
   what the field means). State the basin name in the evidence note so no one
   reads it as a parcel-level measurement.
7. Licence: CC BY 4.0 — attribution to WRI is required and belongs in the
   evidence note, which the `DatasetValue.licence` field already carries.

---

### 3.3 `grid_reliability_saidi_min` — EIA Form 861 ✅ DONE

**Implemented — see §2.5.** What follows is how it was done, and what a better
version would need.

The county-level join below is what shipped. The *territory-polygon* join is
still the better answer and is still open: HIFLD's Electric Retail Service
Territories layer would give the utility serving a parcel rather than every
utility in the county. The authoritative copy has moved — `gii.dhs.gov/hifld`
redirects to an ArcGIS hub, the DC-republished feature service returns
`Invalid URL`, and the remaining ArcGIS Online copies are mirrors of unverifiable
provenance. Left as county-level, and labelled as such, rather than joined
against a mirror nobody can vouch for.

SAIDI is reported per utility, not per location, so this needs two datasets and a
spatial join.

1. **The reliability numbers.** Open
   <https://www.eia.gov/electricity/data/eia861/> and download the most recent
   **Annual Electric Power Industry Report (EIA-861)** ZIP. Inside is
   `Reliability_20XX.xlsx`. Columns of interest:
   - `Utility Number`, `Utility Name`
   - `SAIDI With MED`, `SAIDI Without MED` (minutes per customer per year)
   - `SAIFI`, `CAIDI`, and the IEEE-vs-other standard flag
   - **Use `SAIDI Without MED` for siting comparisons** — "With MED" includes
     Major Event Days, which are dominated by one-off storms and are not
     comparable between utilities.
2. **The service territories.** You need to know which utility serves the site:
   - HIFLD Open Data: <https://hifld-geoplatform.opendata.arcgis.com/> → search
     *Electric Retail Service Territories*. Download the shapefile/GeoJSON. Its
     `UTILITY_ID` matches EIA's `Utility Number`.
3. Join: point-in-territory → `UTILITY_ID` → SAIDI row.
4. Implementation: a `GridReliability` provider holding a simplified territory
   polygon file plus the SAIDI table, keyed by utility id.
5. Relation: **CONTEXTUAL_PROXY**, and this matters. A utility-wide SAIDI average
   is not this site's feeder's reliability — a substation-adjacent site and a
   rural end-of-line site share a number that describes neither. Record it as
   context, keep the gap open, and let the recommendation say *"ask the utility
   for circuit-level reliability history"*.
6. Optional: an EIA API key is free at <https://www.eia.gov/opendata/register.php>
   and makes the generation and price series scriptable, but the 861 reliability
   file is a plain download and needs no key.

---

### 3.4 `grid_capacity_mw` — no public dataset exists ⭐⭐⭐

There is no public dataset of available interconnection capacity at a point.
What exists:

- **Utility hosting-capacity maps.** Many large utilities publish these (Dominion,
  PG&E, Xcel, ComEd…) as ArcGIS layers, each with its own schema and terms. There
  is no national aggregation.
- **Queue data.** LBNL publishes the interconnection-queue dataset at
  <https://emp.lbl.gov/queues>, and each ISO/RTO (PJM, ERCOT, MISO, CAISO, SPP)
  publishes its own queue. This tells you what other people are *trying* to
  connect nearby, which is a signal about congestion, not about your capacity.

**Procedure:** treat this as a *question to the utility*, which is what the
system already does. If you want the queue signal, download the LBNL workbook and
add it as a clearly-labelled `CONTEXTUAL_PROXY` named something honest like
`nearby_queued_capacity_mw` — do not let it populate `grid_capacity_mw`.

The existing proxy `planned_grid_expansion_mw` (from Mireye's
`nearest_proposed_generator_capacity_mw`) already covers part of this ground and
is correctly non-canonical.

---

### 3.5 `distance_to_fiber_km` and `fiber_routes_count` ⭐⭐⭐

There is **no free, authoritative dataset of long-haul fiber routes.** Route maps
are commercially sensitive.

- FCC Broadband Data Collection (<https://broadbandmap.fcc.gov/>) publishes
  *service availability by location*, not physical routes. Mireye already serves
  the provider count from this family, which is why `fiber_routes_count` is
  currently a labelled proxy.
- Commercial: TeleGeography, InfraPedia, and the carriers' own KMZ files under
  NDA. Budget four to five figures.
- Free and partial: OpenStreetMap has some `man_made=cable`/`telecom` ways, but
  coverage is sparse and unverifiable — good enough to draw, not to decide.

**Procedure:** ask carriers directly. A one-page RFI to three regional carriers
("do you have a route within N km of these coordinates, and what is the lateral
build cost?") produces better evidence than any dataset, and it arrives as a
document the system can already ingest through the upload path. Record it as
`USER_INPUT` evidence with the carrier named.

---

### 3.6 `soil_bearing_capacity_kpa` — cannot be a dataset, by design ⭐⭐⭐

USDA NRCS SSURGO (<https://websoilsurvey.nrcs.usda.gov/app/>, reachable, 200)
gives soil texture, drainage class, shrink-swell potential and AASHTO group. It
does **not** give allowable bearing pressure, and no public dataset does.

Bearing capacity comes from a geotechnical investigation: borings, SPT blow
counts, laboratory testing and an engineer's stamp. That is the whole point of
the product rule that structural adequacy is never claimed.

**Procedure:**
1. Optionally add SSURGO-derived *context*: dominant soil series, drainage class,
   shrink-swell. Download via Web Soil Survey (interactive) or the Soil Data
   Access SOAP/REST service at <https://sdmdataaccess.nrcs.usda.gov/>.
2. Record it as `CONTEXTUAL_PROXY` under a field named for what it is
   (`soil_series`, `shrink_swell_potential`) — never under
   `soil_bearing_capacity_kpa`.
3. Leave `soil_bearing_capacity_kpa` as a gap whose suggested action is
   *"commission a geotechnical investigation"*. That gap is not a failure of the
   system; it is the system doing its job.

`cut_fill_volume_m3` is the same story one step further along: it is a derived
design quantity that comes out of a grading model, not an observation.

---

### 3.7 `terrain_ruggedness_index` — USGS 3DEP ⭐⭐

**Status: reachable (200). Computable, but heavy.**

1. Open <https://apps.nationalmap.gov/downloader/>, select *Elevation Products
   (3DEP)* → **1/3 arc-second DEM** (about 10 m resolution), draw the area of
   interest, and download the GeoTIFF tiles. Each tile is roughly 400 MB.
2. Compute the Terrain Ruggedness Index (Riley et al., 1999): for each cell, the
   mean absolute elevation difference against its eight neighbours. Then take the
   mean TRI over a radius around the site — 1 km is a reasonable default for a
   campus-scale question, and whatever you choose must be recorded in the note.
3. `rasterio` + `numpy` is enough; add `rasterio` under the `live` extra.
4. Store a small precomputed value per candidate site rather than shipping DEMs.
5. Relation: **EXACT**, provided the radius is stated.

Mireye already serves elevation and slope, so weigh whether TRI earns its keep
before spending a day on it.

---

### 3.8 `cropland_fraction` — USDA CropScape / CDL ⭐⭐

**Status from this machine: BLOCKED.** `nassgeodata.gmu.edu` refused the
connection (it also returned 503 on an earlier attempt). The service is known to
be intermittent.

1. The CropScape API is a separate web service, not a button in the viewer.
   `GetCDLValue` (one pixel) works today; `GetCDLStat` (histogram over a box),
   which is the one this field needs, returned HTTP 502 after three minutes on
   every attempt. **Coordinates must be EPSG:5070 Albers metres**, not lat/lon —
   passing lat/lon is why the service appears dead when it is not.
   A working alternative without any download: sample `GetCDLValue` on a 5×5
   grid over the parcel and take the crop share, which is ±10 percentage points
   at 25 samples — comfortably inside this field's 0.05/0.80 thresholds.
2. The reliable alternative is the annual national CDL GeoTIFF, roughly 5 GB per
   year, from <https://www.nass.usda.gov/Research_and_Science/Cropland/Release/>.
3. Compute the fraction of cells within the parcel (or a fixed radius) whose CDL
   class is a crop class — CDL codes 1–61 and 66–77 are crops; 111 is water, 121–124
   developed, 141–143 forest, 176 grass/pasture.
4. Relation: **EXACT** for the stated radius.

Mireye already serves a dominant CDL class and a farmland classification, which
is why this field is currently listed as having no equivalent — a dominant class
is not a fraction, and treating it as one would be a fabrication.

---

### 3.9 `protected_area_distance_km` ✅ DONE / `biodiversity_sensitivity_index` ⭐⭐⭐

`protected_area_distance_km` is **implemented — see §2.4**. It is queried live
per site against the PAD-US ArcGIS service and cached, rather than downloading
the national geodatabase, because one query is 20 kB and the geodatabase is many
gigabytes. To work fully offline instead, download the national geodatabase from
<https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-download>
and point a local spatial index at it; the distance maths in
`distance_to_rings_km` does not change.

`biodiversity_sensitivity_index` still has no dataset: there is no national composite
habitat-sensitivity index. USFWS critical habitat (which Mireye already serves)
and NatureServe element occurrences (licensed, per-state, usually paid) are the
building blocks. Either leave the gap open or define a *named, documented*
composite and be explicit that it is your index, not a published one.

---

### 3.10 `distance_to_water_source_km` and `groundwater_availability_l_s` ⭐⭐⭐

- **Surface water** is tractable: USGS NHD (National Hydrography Dataset) from
  <https://apps.nationalmap.gov/downloader/> gives every stream and water body.
  Distance to the nearest flowline is a straightforward computation. What it does
  **not** tell you is whether you may take water from it — that is a water-rights
  question answered by the state engineer's office.
- **Well yield** has no national dataset. Yields live in state well logs
  (e.g. Washington DOE, Arizona ADWR, Texas TWDB), each with its own portal and
  format, and coverage is patchy.

**Procedure:** implement surface-water distance from NHD as *context*, then leave
the availability question as a gap whose suggested action names the specific
authority — the state water resources department for the site's state. A real
answer here is a water-rights determination, not a dataset lookup.

---

### 3.11 `permit_lead_time_months`, `incentive_score`, `jurisdiction_complexity_index` ⭐⭐⭐

These are institutional knowledge, not measurements. No dataset publishes them.

- **Incentives:** DSIRE (<https://programs.dsireusa.org/system/program>) is the
  authoritative free catalogue of state and utility energy incentives. It returned
  200 for the web UI; the API returned **403 Access denied** — DSIRE requires a
  licence agreement for programmatic access. Contact them via
  <https://www.dsireusa.org/> for terms. Manual extraction for a handful of
  candidate states is entirely feasible and is what most teams do.
- **Permit lead time:** county- and city-level. The honest source is the AHJ
  itself. Three phone calls to three planning departments beats any index.
- **Jurisdiction complexity:** define it or drop it. If it stays, it must be a
  documented rubric (number of agencies, discretionary vs ministerial review,
  known moratoria) filled in by a human and recorded as `USER_INPUT`.

**Procedure:** build a small, versioned, human-maintained table keyed by FIPS
code, ingest it as `USER_INPUT` evidence with the researcher's name and date, and
let it go stale on a schedule. That is a legitimate source. A number invented by
software is not.

---

### 3.12 `ambient_design_db_c` — already correctly handled

Mireye serves the 0.4% **wet-bulb** design temperature, and this field asks for
**dry-bulb**. The system records the wet-bulb reading as `CONTEXTUAL_PROXY`, so it
is visible and citable but cannot satisfy a dry-bulb gate. This is the reference
example of the rule every entry above follows.

The real dry-bulb value comes from **ASHRAE Handbook — Fundamentals, Chapter 14**
climatic design conditions, available through the ASHRAE Weather Data Viewer
(paid, per-seat). Alternatively derive it from NOAA ISD hourly station data
(<https://www.ncei.noaa.gov/data/global-hourly/>, free) by computing the 0.4%
annual exceedance dry-bulb from at least 10 years of hourly observations at the
nearest station — and then record the station, its distance and the years used,
because a station 40 km away at a different elevation is a proxy, not the site.

---

## 4. Summary table — before construction

| Field | Source | Effort | Blocked from here? | Relation when added |
|---|---|:--:|:--:|---|
| `distance_to_ix_km` | PeeringDB | ✅ done | — | EXACT |
| `ix_facility_carrier_count` | PeeringDB | ✅ done | — | EXACT |
| `water_quality_tds_mg_l` | Water Quality Portal | ✅ done | — | CONTEXTUAL_PROXY |
| `wildfire_risk_index` | FEMA NRI | ✅ done | manual download | EXACT |
| `water_stress_index` | WRI Aqueduct 4.0 | ⭐⭐ | No (manual, ~1 GB) | EXACT |
| `terrain_ruggedness_index` | USGS 3DEP | ⭐⭐ | No (large files) | EXACT |
| `cropland_fraction` | USDA CDL | ⭐⭐ | Yes (service down) | EXACT |
| `protected_area_distance_km` | USGS PAD-US | ✅ done | — | EXACT (replaced the proxy) |
| `grid_reliability_saidi_min` | EIA-861 + Census county | ✅ done | — | CONTEXTUAL_PROXY |
| `distance_to_water_source_km` | USGS NHD | ⭐⭐ | No | CONTEXTUAL_PROXY |
| `ambient_design_db_c` | ASHRAE / NOAA ISD | ⭐⭐ | ASHRAE is paid | EXACT or PROXY |
| `grid_capacity_mw` | Utility RFI | ⭐⭐⭐ | No dataset exists | USER_INPUT |
| `distance_to_fiber_km` | Carrier RFI | ⭐⭐⭐ | No dataset exists | USER_INPUT |
| `fiber_routes_count` | Carrier RFI | ⭐⭐⭐ | No dataset exists | USER_INPUT |
| `latency_to_ix_ms` | Measurement | ⭐⭐⭐ | Route-dependent | USER_INPUT |
| `groundwater_availability_l_s` | State well logs | ⭐⭐⭐ | Per-state | USER_INPUT |
| `soil_bearing_capacity_kpa` | Geotech report | ⭐⭐⭐ | **By design** | USER_INPUT |
| `cut_fill_volume_m3` | Grading model | ⭐⭐⭐ | **By design** | USER_INPUT |
| `biodiversity_sensitivity_index` | No source | ⭐⭐⭐ | No index exists | — |
| `permit_lead_time_months` | AHJ | ⭐⭐⭐ | Human research | USER_INPUT |
| `incentive_score` | DSIRE | ⭐⭐⭐ | API 403, licence needed | USER_INPUT |
| `jurisdiction_complexity_index` | Rubric | ⭐⭐⭐ | Must be defined | USER_INPUT |

---

## 5. After construction — replacing the 84 synthetic documents

This is where the remaining synthetic data actually is, and it is the higher-value
half of the work. The change-impact workflow reads equipment ratings and project
specifications. Right now 57 `manufacturer_document` and 27 `project_document`
records are fabricated — clearly labelled as such, but fabricated.

### 5.1 Equipment performance — AHRI Directory ⭐⭐

**Status: <https://www.ahridirectory.org/> reachable (200). No API. HTML only.**

AHRI certifies the performance ratings that HVAC equipment is actually sold
against. This is the authoritative source for chiller, CRAH and cooling-tower
performance, and it is free.

1. Go to <https://www.ahridirectory.org/> and pick the programme:
   - *Water-Chilling Packages Using the Vapor Compression Cycle* (AHRI 550/590)
     for chillers
   - *Computer and Data Processing Room Air Conditioners* (AHRI 1360) for CRAH
     and CRAC units
   - *Water-Cooling Towers* (CTI/AHRI 550) for towers
2. Search by manufacturer and model. Each certified model gives you:
   - Net capacity (tons or kW)
   - Full-load efficiency (kW/ton, COP or EER)
   - **IPLV/NPLV** — the part-load value, which is the one that matters for a
     data centre that rarely runs at 100%
   - The rating conditions the numbers are certified at
3. Export: the directory offers a per-search **PDF or CSV of certified ratings**.
   Download it.
4. **Ingest it through the app.** `POST /api/documents/upload` already parses PDFs,
   chunks them and records `SourceType.USER_INPUT` evidence with the page number.
   Nothing new needs to be built — the upload path is the ingestion path.
5. Scraping: the directory is HTML-only and its terms of use restrict automated
   access. Read them before writing a scraper. Manual export of the twenty models
   that actually appear in a bid package takes about an hour and carries no legal
   ambiguity.
6. Scanned documents are fine now: pages with no text layer are OCR'd on upload.
   The values come in flagged as transcriptions at half confidence and must be
   confirmed against the page — see `deployment.md` §5a.

### 5.2 Manufacturer cut sheets ⭐

Every major vendor publishes full technical documents as free PDFs:

| Vendor | What you get |
|---|---|
| Vertiv | CRAH/CRAC, UPS, busway — capacity tables, airflow, electrical data |
| Schneider Electric / APC | UPS, PDU, containment — full spec sheets |
| Trane, Carrier, Daikin Applied, York | Chillers — performance curves, dimensions, weights |
| Baltimore Aircoil, EVAPCO, SPX | Cooling towers — thermal performance, water consumption |
| Caterpillar, Cummins, Kohler | Generators — ratings, fuel consumption, emissions |
| Eaton, ABB, Siemens | Switchgear, transformers |

**Procedure:**
1. Pick the actual models in your reference design (or the models in the demo's
   equipment list).
2. Download the manufacturer's technical/submittal PDF — not the marketing
   brochure. The submittal document is the one with the tables.
3. Upload each through the document endpoint.
4. Delete the corresponding synthetic `manufacturer_document` seed records so the
   real document is the only one answering that question.

This single step removes most of the 57 synthetic equipment records.

### 5.3 Real project documents — specifications and submittals ⭐⭐

The 27 synthetic `project_document` records stand in for drawings, specifications,
submittals and RFIs. Real, publicly available equivalents:

1. **Public procurement portals.** Government construction projects publish full
   bid packages, including Division 23 (HVAC) and Division 26 (Electrical)
   specifications:
   - <https://sam.gov/opp/> — US federal solicitations (reachable, 200). Search
     for *"data center"*, *"chilled water"*, *"emergency generator"* and filter to
     construction NAICS codes (236220, 238220).
   - State and university procurement portals (state DOT, state DAS, university
     facilities) — often the richest source, since universities publish complete
     spec books.
2. **What to take:** the CSI-format specification sections. Section 23 64 00
   (Packaged Water Chillers) and 26 32 13 (Engine Generators) are the ones that
   exercise this system's change-impact logic most directly.
3. **Licence check.** Federal solicitation documents are US Government works and
   generally public domain. State documents vary. A downloaded spec section is
   fine for a demonstration; check terms before redistributing.
4. **Upload them.** Same endpoint. The evidence becomes `USER_INPUT` with page
   citations, and the change-impact workflow starts operating on real text.

### 5.4 Constructed-facility reference data ⭐

For "after construction" performance context rather than documents:

- **Uptime Institute** and the **ASHRAE TC 9.9** thermal-guidelines publications
  are the canonical references for operating envelopes (paid, but ASHRAE 9.9
  Class A1–A4 ranges are widely reproduced and citable).
- **Data Center Dynamics** and **Uptime Intelligence** publish annual PUE survey
  data — useful as an industry benchmark, never as a measurement of your facility.
- **ENERGY STAR Portfolio Manager** (<https://www.energystar.gov/buildings>)
  publishes data-centre energy benchmarking methodology, free.

Each of these is a **benchmark**, so anything derived from them belongs in the
system as `CONTEXTUAL_PROXY`: it describes an industry, not this building.

---

## 6. The rule that governs all of it

Every procedure above ends with the same two decisions, and getting them right
matters more than how many datasets are wired up:

1. **Does this measurement answer the concept, or merely resemble it?** If it
   resembles it, the value is `CONTEXTUAL_PROXY`: stored, shown, cited, and unable
   to fill the field, close its gap or move a score. Wet-bulb for dry-bulb.
   Utility-average SAIDI for this feeder's reliability. A neighbour's well for
   this site's water.
2. **If nothing answers it, the concept stays missing.** Not zero. Not a default.
   Not the nearest-looking category. A tracked gap that names who to ask.

An open gap is a finding. A fabricated number is a defect that looks like a
finding — and by the time anyone notices, it is in a decision.

---

## 7. What is left, and in what order

Done: PeeringDB, Water Quality Portal, PAD-US, EIA-861, FEMA NRI. Five concepts
served, one proxy retired.

1. **AHRI + manufacturer cut sheets** (§5.1, §5.2) — biggest reduction in
   synthetic data per hour spent, no spatial code, and scanned documents now work
   because OCR runs on upload. This is the highest-value item left.
2. **WRI Aqueduct** (§3.2) — water stress is central to this product's thesis.
   The Figshare id in §3.2 no longer resolves; take the current download link
   from the WRI landing page, which is live.
4. **USGS 3DEP** (§3.7) — terrain ruggedness. Heavy files, simple maths.
5. **USDA CropScape** (§3.8) — the service returned 500 and 503 on every attempt
   across two days. Use the annual national GeoTIFF instead.

Items in §3.11 and §5.3 are research tasks for a person, not engineering tasks.
Schedule them separately.

### Sources that resisted, and what actually happened

| Source | Result | Why it is not done |
|---|---|---|
| FEMA NRI | `ConnectError` — TCP reset, every attempt | This network cannot reach `hazards.fema.gov`. Downloaded by hand instead; the build script takes the zip. |
| USDA CropScape `GetCDLStat` | HTTP 502 after 183 s, twice | Their histogram operation is broken. `GetCDLValue` (single pixel) *does* work — coordinates must be EPSG:5070 Albers metres, not lat/lon, which is why it looks dead. A 5×5 grid of point queries would give cropland fraction to about ±10 pp, inside this field's 0.05/0.80 thresholds. |
| WRI Aqueduct | Landing page 200, Figshare id 404 | The dataset moved; the direct link has to be re-read from the landing page. |
| DSIRE incentives API | HTTP 403 | Programmatic access needs a licence agreement. |
| HIFLD service territories | `Invalid URL` from the DHS-republished service | Authoritative copy moved; remaining mirrors are of unverifiable provenance. |
| NREL utility rates | DNS failure | Not needed for any current field. |
