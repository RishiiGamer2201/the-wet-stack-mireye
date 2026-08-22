"""The site-evaluation field catalog.

This is the single list of physical-world facts the platform knows how to reason
about. It doubles as the Mireye field catalog (`GET /v1/meta/fields`) so the
agent can never request a field name that does not exist — an unknown field
becomes an InformationGap plus a Mireye feature request instead.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel

from .domain import EvidenceRelation, SiteDimension

Direction = Literal["higher_better", "lower_better", "band", "categorical"]

#: How a concept relates to the real Mireye catalog.
#:
#:   mapped        a verified provider field measures the same thing
#:   proxy         a verified provider field is close but not identical — the
#:                 difference is recorded on the evidence, never hidden
#:   billed_extra  mapped, but the field sits in Mireye's `parcel_record` group
#:                 (300 credits per location), so it is opt-in
#:   unavailable   the catalog has no equivalent; the concept becomes an
#:                 InformationGap and a Mireye feature request, never a value
ProviderAvailability = Literal["mapped", "proxy", "billed_extra", "unavailable"]

#: Named conversions from a provider unit to the unit the scoring engine uses.
#: Every one is deterministic and unit-tested; `None` in, `None` out — a missing
#: provider value must never become a number.
CONVERSIONS: dict[str, tuple[str, callable]] = {
    "identity": ("same unit", lambda v: v),
    "m_to_km": ("metres -> kilometres", lambda v: v / 1000.0),
    "cm_to_m": ("centimetres -> metres", lambda v: v / 100.0),
    # Grade, not angle: a 45° slope is a 100% grade.
    "degrees_to_slope_percent": ("degrees -> percent grade", lambda v: math.tan(math.radians(v)) * 100.0),
}


class FieldSpec(BaseModel):
    key: str
    label: str
    dimension: SiteDimension
    unit: str | None = None
    kind: Literal["number", "category"] = "number"
    direction: Direction = "higher_better"
    good: float | None = None
    bad: float | None = None
    band_low: float | None = None
    band_high: float | None = None
    band_tolerance: float | None = None
    categories: dict[str, float] | None = None
    weight: float = 1.0
    description: str = ""
    depth: Literal["broad", "deep"] = "broad"
    provider: str = "mireye"

    # --- real-provider mapping ---------------------------------------------
    #: Name in Mireye's catalog. None means the catalog has no equivalent.
    provider_field: str | None = None
    #: Unit as the provider states it, kept for provenance.
    provider_unit: str | None = None
    #: Key into CONVERSIONS, applied at the provider boundary.
    conversion: str = "identity"
    provider_availability: ProviderAvailability = "unavailable"
    #: Provider category value -> our vocabulary. A provider value absent from
    #: this map stays unmapped, which scoring treats as missing rather than
    #: guessing at the nearest-looking category.
    provider_categories: dict[str, str] | None = None
    #: Why a mapping is a proxy, or why nothing maps. Surfaced on the evidence.
    provider_note: str | None = None

    @property
    def internal_unit(self) -> str | None:
        """The unit scoring works in — `unit` under its explicit name."""
        return self.unit

    @property
    def relation(self) -> EvidenceRelation:
        """How the provider field relates to this concept.

        A `proxy` mapping is a *different* measurement, so it is contextual no
        matter how it is expressed. Everything else is the same measurement,
        either as-is, unit-converted, or vocabulary-normalised.
        """
        if self.provider_availability == "proxy":
            return EvidenceRelation.CONTEXTUAL_PROXY
        if self.direction == "categorical" or self.kind == "category":
            return EvidenceRelation.CATEGORICAL_NORMALIZED
        if self.conversion != "identity":
            return EvidenceRelation.UNIT_CONVERTED
        return EvidenceRelation.EXACT


def _f(**kw) -> FieldSpec:
    return FieldSpec(**kw)


FIELDS: list[FieldSpec] = [
    # --- 1. Geo & terrain --------------------------------------------------
    _f(
        key="elevation_m",
        label="Elevation",
        dimension=SiteDimension.GEO_TERRAIN,
        unit="m",
        direction="band",
        band_low=40,
        band_high=900,
        band_tolerance=400,
        weight=1.0,
        description="Ground elevation above sea level; very low sites carry flood exposure, "
        "very high sites carry logistics and cooling-design cost.",
    ),
    _f(
        key="mean_slope_pct",
        label="Mean slope",
        dimension=SiteDimension.GEO_TERRAIN,
        unit="percent",
        direction="lower_better",
        good=1.0,
        bad=12.0,
        weight=1.4,
        description="Average ground slope across the parcel; drives earthworks volume.",
    ),
    _f(
        key="terrain_ruggedness_index",
        label="Terrain ruggedness",
        dimension=SiteDimension.GEO_TERRAIN,
        direction="lower_better",
        good=0.5,
        bad=8.0,
        weight=0.8,
        description="Local relief variability index.",
    ),
    _f(
        key="land_cover_class",
        label="Land cover",
        dimension=SiteDimension.GEO_TERRAIN,
        kind="category",
        direction="categorical",
        categories={
            "barren": 100,
            "shrubland": 92,
            "grassland": 85,
            "brownfield": 78,
            "cropland": 55,
            "forest": 38,
            "urban": 60,
            "wetland": 8,
        },
        weight=0.8,
        description="Dominant land-cover classification of the parcel.",
    ),
    # --- 2. Water ----------------------------------------------------------
    _f(
        key="water_stress_index",
        label="Water stress index",
        dimension=SiteDimension.WATER,
        direction="lower_better",
        good=0.5,
        bad=4.5,
        weight=1.6,
        description="Baseline water stress 0 (low) – 5 (extremely high).",
    ),
    _f(
        key="groundwater_availability_l_s",
        label="Groundwater availability",
        dimension=SiteDimension.WATER,
        unit="liter / second",
        direction="higher_better",
        good=60,
        bad=5,
        weight=1.2,
        description="Sustainable abstraction rate from local aquifer.",
    ),
    _f(
        key="water_quality_tds_mg_l",
        label="Water quality (TDS)",
        dimension=SiteDimension.WATER,
        unit="mg/l",
        direction="lower_better",
        good=200,
        bad=1500,
        weight=0.9,
        description="Total dissolved solids; drives make-up water treatment cost.",
        depth="deep",
    ),
    _f(
        key="flood_zone",
        label="FEMA flood zone",
        dimension=SiteDimension.WATER,
        kind="category",
        direction="categorical",
        categories={"X": 100, "X_shaded": 78, "AO": 35, "AE": 25, "A": 20, "VE": 0},
        weight=1.5,
        description="National Flood Hazard Layer zone at the parcel centroid.",
    ),
    _f(
        key="distance_to_water_source_km",
        label="Distance to water source",
        dimension=SiteDimension.WATER,
        unit="km",
        direction="lower_better",
        good=1.0,
        bad=25.0,
        weight=1.0,
        description="Distance to a usable surface or municipal water connection.",
    ),
    # --- 3. Power ----------------------------------------------------------
    _f(
        key="grid_capacity_mw",
        label="Available grid capacity",
        dimension=SiteDimension.POWER,
        unit="MW",
        direction="higher_better",
        good=300,
        bad=20,
        weight=2.0,
        description="Deliverable capacity at the nearest interconnection.",
    ),
    _f(
        key="distance_to_substation_km",
        label="Distance to substation",
        dimension=SiteDimension.POWER,
        unit="km",
        direction="lower_better",
        good=1.5,
        bad=25.0,
        weight=1.4,
        description="Distance to nearest transmission substation.",
    ),
    _f(
        key="grid_reliability_saidi_min",
        label="Grid reliability (SAIDI)",
        dimension=SiteDimension.POWER,
        unit="minute",
        direction="lower_better",
        good=40,
        bad=400,
        weight=1.0,
        description="Average interruption duration per customer per year.",
        depth="deep",
    ),
    _f(
        key="planned_grid_expansion_mw",
        label="Planned grid expansion",
        dimension=SiteDimension.POWER,
        unit="MW",
        direction="higher_better",
        good=250,
        bad=0,
        weight=0.8,
        description="Utility-published capacity additions within the planning horizon.",
        depth="deep",
    ),
    # --- 4. Connectivity ---------------------------------------------------
    _f(
        key="fiber_routes_count",
        label="Diverse fiber routes",
        dimension=SiteDimension.CONNECTIVITY,
        direction="higher_better",
        good=4,
        bad=0,
        weight=1.4,
        description="Count of physically diverse long-haul fiber routes.",
    ),
    _f(
        key="distance_to_fiber_km",
        label="Distance to fiber",
        dimension=SiteDimension.CONNECTIVITY,
        unit="km",
        direction="lower_better",
        good=0.5,
        bad=20.0,
        weight=1.2,
        description="Distance to the nearest long-haul fiber route.",
    ),
    _f(
        key="distance_to_ix_km",
        label="Distance to internet exchange",
        dimension=SiteDimension.CONNECTIVITY,
        unit="km",
        direction="lower_better",
        good=15.0,
        bad=250.0,
        weight=1.2,
        description="Great-circle distance to the nearest PeeringDB facility that hosts an "
        "internet exchange. A measured distance, not a latency estimate.",
        provider="peeringdb",
    ),
    _f(
        key="ix_facility_carrier_count",
        label="Carriers at nearest exchange",
        dimension=SiteDimension.CONNECTIVITY,
        direction="higher_better",
        good=20,
        bad=1,
        weight=0.9,
        description="Carriers present at the nearest interconnection facility, from "
        "PeeringDB. Evidence of competitive transit, not of physical route diversity.",
        provider="peeringdb",
        depth="deep",
    ),
    _f(
        key="latency_to_ix_ms",
        label="Latency to internet exchange",
        dimension=SiteDimension.CONNECTIVITY,
        unit="ms",
        direction="lower_better",
        good=3,
        bad=25,
        weight=1.0,
        description="Round-trip latency to the nearest major internet exchange.",
    ),
    _f(
        key="distance_to_highway_km",
        label="Distance to highway",
        dimension=SiteDimension.CONNECTIVITY,
        unit="km",
        direction="lower_better",
        good=2.0,
        bad=30.0,
        weight=0.9,
        description="Road access for heavy equipment delivery.",
    ),
    # --- 5. Civil & soil ---------------------------------------------------
    _f(
        key="soil_bearing_capacity_kpa",
        label="Soil bearing capacity",
        dimension=SiteDimension.CIVIL_SOIL,
        unit="kPa",
        direction="higher_better",
        good=300,
        bad=75,
        weight=1.6,
        description="Presumptive allowable bearing pressure from regional soil survey.",
    ),
    _f(
        key="depth_to_bedrock_m",
        label="Depth to bedrock",
        dimension=SiteDimension.CIVIL_SOIL,
        unit="m",
        direction="band",
        band_low=3,
        band_high=15,
        band_tolerance=10,
        weight=1.0,
        description="Shallow bedrock implies blasting; very deep implies deep foundations.",
        depth="deep",
    ),
    _f(
        key="cut_fill_volume_m3",
        label="Estimated cut/fill volume",
        dimension=SiteDimension.CIVIL_SOIL,
        unit="m ** 3",
        direction="lower_better",
        good=20000,
        bad=400000,
        weight=1.1,
        description="Earthworks volume implied by terrain to reach a level pad.",
        depth="deep",
    ),
    _f(
        key="soil_drainage_class",
        label="Soil drainage",
        dimension=SiteDimension.CIVIL_SOIL,
        kind="category",
        direction="categorical",
        categories={
            "well_drained": 100,
            "moderately_well_drained": 80,
            "somewhat_poorly_drained": 45,
            "poorly_drained": 20,
            "very_poorly_drained": 5,
        },
        weight=0.9,
        description="USDA drainage classification.",
    ),
    # --- 6. Hazards & climate ---------------------------------------------
    _f(
        key="seismic_pga_g",
        label="Seismic ground acceleration",
        dimension=SiteDimension.HAZARDS_CLIMATE,
        unit="dimensionless",
        direction="lower_better",
        good=0.05,
        bad=0.50,
        weight=1.5,
        description="Peak ground acceleration, 2% in 50 years.",
    ),
    _f(
        key="wildfire_risk_index",
        label="Wildfire risk",
        dimension=SiteDimension.HAZARDS_CLIMATE,
        direction="lower_better",
        # FEMA's own published class boundaries, measured from the NRI December
        # 2025 tract table: 68.65 is the top of "Very Low", 96.26 the start of
        # "Relatively High". The NRI score is 0-100 but heavily skewed — its
        # median "Very Low" tract scores 43.6 — so the evenly spread 10/80 ramp
        # this used to have scored Ashburn (31.2, Very Low) at 70/100 instead of
        # 100. Anchoring to the real boundaries is what lets the value be carried
        # as-is instead of rescaled.
        #
        # Known limit: anything FEMA rates "Relatively High" or worse scores 0
        # here, so this ramp does not separate High from Very High. Both are
        # already a serious wildfire constraint for a data centre, and the
        # evidence carries FEMA's rating text for a human to read.
        good=68.65,
        bad=96.26,
        weight=1.2,
        description="FEMA National Risk Index composite wildfire risk score for the "
        "census tract, 0–100 on FEMA's own non-linear scale.",
        provider="fema_nri",
    ),
    _f(
        key="extreme_heat_days_per_year",
        label="Extreme heat days",
        dimension=SiteDimension.HAZARDS_CLIMATE,
        unit="day",
        direction="lower_better",
        good=10,
        bad=90,
        weight=1.2,
        description="Days per year above the cooling design dry-bulb temperature.",
    ),
    _f(
        key="design_wind_speed_mph",
        label="Design wind speed",
        dimension=SiteDimension.HAZARDS_CLIMATE,
        unit="mph",
        direction="lower_better",
        good=90,
        bad=160,
        weight=0.9,
        description="ASCE 7 basic wind speed for Risk Category III.",
        depth="deep",
    ),
    _f(
        key="ambient_design_db_c",
        label="Ambient design dry-bulb",
        dimension=SiteDimension.HAZARDS_CLIMATE,
        unit="degC",
        direction="lower_better",
        good=28,
        bad=45,
        weight=1.0,
        description="0.4% cooling design dry-bulb temperature; also used to check "
        "equipment rating conditions in the During Construction workflow.",
    ),
    # --- 7. Environmental --------------------------------------------------
    _f(
        key="protected_area_distance_km",
        label="Distance to protected area",
        dimension=SiteDimension.ENVIRONMENTAL,
        unit="km",
        direction="higher_better",
        good=15,
        bad=0.5,
        weight=1.2,
        description="Distance to the nearest designated protected area, from the USGS "
        "PAD-US national inventory. Conservation land only: municipal parks and ball "
        "fields are reported alongside but are not treated as an ecological constraint.",
        provider="padus",
    ),
    _f(
        key="cropland_fraction",
        label="Cropland fraction",
        dimension=SiteDimension.ENVIRONMENTAL,
        direction="lower_better",
        good=0.05,
        bad=0.80,
        weight=1.1,
        description="Share of the parcel classified as active cropland (USDA CDL).",
    ),
    _f(
        key="wetland_fraction",
        label="Wetland fraction",
        dimension=SiteDimension.ENVIRONMENTAL,
        direction="lower_better",
        good=0.0,
        bad=0.30,
        weight=1.2,
        description="Share of the parcel mapped as wetland.",
    ),
    _f(
        key="biodiversity_sensitivity_index",
        label="Biodiversity sensitivity",
        dimension=SiteDimension.ENVIRONMENTAL,
        direction="lower_better",
        good=15,
        bad=75,
        weight=0.9,
        description="Composite habitat sensitivity 0–100.",
        depth="deep",
    ),
    # --- 8. Regulatory -----------------------------------------------------
    _f(
        key="zoning_class",
        label="Zoning",
        dimension=SiteDimension.REGULATORY,
        kind="category",
        direction="categorical",
        categories={
            "industrial": 100,
            "light_industrial": 85,
            "commercial": 60,
            "mixed_use": 45,
            "agricultural": 30,
            "residential": 10,
        },
        weight=1.4,
        description="Current parcel zoning designation.",
    ),
    _f(
        key="permit_lead_time_months",
        label="Permit lead time",
        dimension=SiteDimension.REGULATORY,
        unit="month",
        direction="lower_better",
        good=4,
        bad=24,
        weight=1.3,
        description="Historic median approval time for comparable projects.",
        depth="deep",
    ),
    _f(
        key="incentive_score",
        label="Incentive strength",
        dimension=SiteDimension.REGULATORY,
        direction="higher_better",
        good=80,
        bad=10,
        weight=0.8,
        description="Composite of tax abatement and utility incentive programmes.",
        depth="deep",
    ),
    _f(
        key="jurisdiction_complexity_index",
        label="Jurisdiction complexity",
        dimension=SiteDimension.REGULATORY,
        direction="lower_better",
        good=20,
        bad=85,
        weight=1.0,
        description="Number and overlap of authorities having jurisdiction.",
        depth="deep",
    ),
]

#: Internal concept -> real Mireye catalog field.
#:
#: Every provider name below was verified against the recorded 306-field catalog
#: in `tests/fixtures/mireye/meta_fields.json`; `test_no_mapping_invents_a_field_
#: absent_from_the_catalog` enforces that. A concept absent from this table has
#: no equivalent and becomes an InformationGap — it is never given a value.
#:
#:   key: (provider_field, provider_unit, conversion, availability, note)
PROVIDER_MAP: dict[str, tuple[str, str | None, str, ProviderAvailability, str | None]] = {
    # --- direct, same quantity --------------------------------------------
    "elevation_m": ("elevation", "meters", "identity", "mapped", None),
    "seismic_pga_g": ("seismic_pga_2pct_50yr_g", "g", "identity", "mapped", None),
    "design_wind_speed_mph": ("design_wind_speed_mph", "mph", "identity", "mapped", None),
    "extreme_heat_days_per_year": ("days_above_32c_annual_count", "days", "identity", "mapped", None),
    "flood_zone": ("fema_flood_zone", None, "identity", "mapped", None),
    "soil_drainage_class": ("soil_drainage_class", None, "identity", "mapped", None),
    "ambient_design_db_c": (
        "design_wet_bulb_temperature_0_4pct_degc", "degC", "identity", "proxy",
        "CONTEXTUAL ONLY — this is the 0.4% design WET-BULB temperature, a different "
        "measurement from the design dry-bulb this concept requires. Wet-bulb is always "
        "the lower of the two, so treating it as dry-bulb would make an equipment "
        "rating check optimistic and could pass a unit that fails at site conditions. "
        "It is shown as evaporative-cooling context; the dry-bulb must come from "
        "project climate data.",
    ),
    "land_cover_class": (
        "lcms_class", None, "identity", "mapped",
        "USFS LCMS life-form taxonomy, translated to our vocabulary. LCMS has no crop "
        "class and reports 'Barren or Impervious' as one class, so cropland, brownfield, "
        "urban and wetland cannot be expressed and those readings stay unmapped — "
        "scored as missing rather than guessed.",
    ),

    # --- converted at the boundary ----------------------------------------
    "mean_slope_pct": (
        "slope_degrees", "degrees", "degrees_to_slope_percent", "mapped",
        "Provider states slope as an angle; scoring uses percent grade.",
    ),
    "distance_to_substation_km": ("nearest_substation_distance_m", "meters", "m_to_km", "mapped", None),
    "distance_to_highway_km": (
        "nearest_major_road_distance_m", "meters", "m_to_km", "mapped", None,
    ),
    "depth_to_bedrock_m": ("bedrock_depth_cm", "centimeters", "cm_to_m", "mapped", None),
    "distance_to_water_source_km": ("nearest_wetland_distance_m", "meters", "m_to_km", "unavailable", "Distance to nearest wetland/waterbody"),
    "distance_to_fiber_km": ("nearest_antenna_structure_distance_m", "meters", "m_to_km", "unavailable", "Distance to nearest telecom antenna structure"),

    # --- proxies: close, but not the same quantity -------------------------
    "terrain_ruggedness_index": (
        "slope_degrees", "degrees", "identity", "unavailable",
        "Local relief index derived from slope",
    ),
    "groundwater_availability_l_s": (
        "nearest_groundwater_well_depth_to_water_m", "meters", "identity", "unavailable",
        "Depth to water table at nearest well",
    ),
    "fiber_routes_count": (
        "fiber_provider_count", None, "identity", "proxy",
        "CONTEXTUAL ONLY — this counts broadband service providers in the hex, which is "
        "not physical route diversity. Several providers can share one conduit, so a "
        "high count does not evidence diverse paths. Shown as telecommunications context; a physical route survey is required.",
    ),
    "planned_grid_expansion_mw": (
        "nearest_proposed_generator_capacity_mw", "MW", "identity", "proxy",
        "CONTEXTUAL ONLY — this counts proposed generation capacity in the queue, which is "
        "not deliverable load capacity. Shown as power-grid expansion context; grid utility agreement is required.",
    ),
    "soil_bearing_capacity_kpa": (
        "soil_hydrologic_group", None, "identity", "unavailable",
        "Soil hydrologic group classification",
    ),
    "wildfire_risk_index": (
        "wildfire_annual_frequency", None, "identity", "unavailable",
        "Annual wildfire frequency",
    ),
    "cropland_fraction": (
        "is_cultivated", None, "identity", "unavailable",
        "Parcel cultivation status",
    ),
    "biodiversity_sensitivity_index": (
        "intersects_critical_habitat", None, "identity", "unavailable",
        "Critical habitat intersection status",
    ),

    # --- mapped but billed separately (Mireye `parcel_record`, 300 credits) --
    "wetland_fraction": (
        "wetland_fraction_of_parcel", None, "identity", "billed_extra",
        "Mireye bills the parcel_record group at 300 credits per location.",
    ),
    "zoning_class": (
        "parcel_zoning", None, "identity", "billed_extra",
        "Mireye bills the parcel_record group at 300 credits per location.",
    ),
}

#: Why a concept has no provider field. Shown on the gap it produces.
NO_PROVIDER_EQUIVALENT: dict[str, str] = {
    "grid_capacity_mw": "The catalog exposes interconnection-queue capacity, which is generation "
    "seeking connection — not deliverable load capacity at the point of interconnection.",
    "latency_to_ix_ms": "No network-latency field exists in the Mireye catalog, and latency "
    "cannot be derived from distance - it depends on the route and the carrier. "
    "`distance_to_ix_km` is served from PeeringDB and measures distance only.",
    "permit_lead_time_months": "The catalog exposes county building-permit counts, not approval "
    "duration for comparable projects.",
    "incentive_score": "The catalog exposes opportunity-zone membership only, not a composite "
    "incentive strength.",
    "jurisdiction_complexity_index": "No field describes the number or overlap of authorities "
    "having jurisdiction.",
    "water_stress_index": "The catalog exposes a US Drought Monitor category (D0–D4), which is a "
    "short-term drought class, not a baseline water-stress index.",
    "grid_reliability_saidi_min": "No utility reliability (SAIDI/SAIFI) field exists in the catalog.",
    "terrain_ruggedness_index": "No ruggedness or local-relief index exists in the catalog.",
    "land_cover_class": "No single land-cover classification field exists in the catalog.",
    "water_quality_tds_mg_l": "No total-dissolved-solids or raw water-quality field exists.",
    "groundwater_availability_l_s": "The catalog exposes well counts and depth to water, not a "
    "sustainable abstraction rate.",
    "distance_to_water_source_km": "The catalog exposes wastewater-plant distance and water-system "
    "names, not distance to a usable supply connection.",
    "distance_to_fiber_km": "The catalog reports fiber availability and provider counts, not "
    "distance to a long-haul route.",
    "cut_fill_volume_m3": "Earthworks volume is a derived design quantity, not a physical-world "
    "observation the provider offers.",
    "cropland_fraction": "The catalog exposes a dominant CDL class and farmland classification, not "
    "the cropland share of the parcel.",
    "biodiversity_sensitivity_index": "The catalog exposes critical-habitat status, not a composite "
    "habitat-sensitivity index.",
}

FIELD_INDEX: dict[str, FieldSpec] = {f.key: f for f in FIELDS}

for _key, (_pf, _pu, _conv, _avail, _note) in PROVIDER_MAP.items():
    _spec = FIELD_INDEX[_key]
    _spec.provider_field = _pf
    _spec.provider_unit = _pu
    _spec.conversion = _conv
    _spec.provider_availability = _avail
    _spec.provider_note = _note

for _key, _why in NO_PROVIDER_EQUIVALENT.items():
    # Only explain the absence for concepts that really have no mapping. A key
    # left in this table after it gains one must not clobber the mapping's own
    # note — that silently erased the proxy warning once already.
    if not FIELD_INDEX[_key].provider_field:
        FIELD_INDEX[_key].provider_note = _why  # availability stays "unavailable"

#: Provider name -> internal key, for reading a fetch response back.
#: USFS LCMS life-form classes -> our land-cover vocabulary.
#:
#: Only unambiguous translations are listed. LCMS has no crop class, and its
#: "Barren or Impervious" merges two of our categories that score very
#: differently (barren 100, urban 60), so it is deliberately absent: an
#: untranslated value is scored as missing, never as the nearer-looking guess.
LCMS_LAND_COVER: dict[str, str] = {
    "Trees": "forest",
    "Tall Shrubs & Trees Mix": "forest",
    "Shrubs & Trees Mix": "forest",
    "Tall Shrubs": "shrubland",
    "Shrubs": "shrubland",
    "Grass/Forb/Herb": "grassland",
}
FIELD_INDEX["land_cover_class"].provider_categories = LCMS_LAND_COVER

PROVIDER_TO_INTERNAL: dict[str, str] = {
    spec.provider_field: spec.key for spec in FIELD_INDEX.values() if spec.provider_field
}

DIMENSION_FIELDS: dict[SiteDimension, list[FieldSpec]] = {
    dim: [f for f in FIELDS if f.dimension == dim] for dim in SiteDimension
}

DEFAULT_DIMENSION_WEIGHTS: dict[SiteDimension, float] = {
    SiteDimension.GEO_TERRAIN: 1.0,
    SiteDimension.WATER: 1.6,
    SiteDimension.POWER: 2.0,
    SiteDimension.CONNECTIVITY: 1.2,
    SiteDimension.CIVIL_SOIL: 1.1,
    SiteDimension.HAZARDS_CLIMATE: 1.3,
    SiteDimension.ENVIRONMENTAL: 0.9,
    SiteDimension.REGULATORY: 1.1,
}

DIMENSION_LABELS: dict[SiteDimension, str] = {
    SiteDimension.GEO_TERRAIN: "Geography & terrain",
    SiteDimension.WATER: "Water",
    SiteDimension.POWER: "Power & grid",
    SiteDimension.CONNECTIVITY: "Connectivity & access",
    SiteDimension.CIVIL_SOIL: "Civil & soil",
    SiteDimension.HAZARDS_CLIMATE: "Hazards & climate",
    SiteDimension.ENVIRONMENTAL: "Environmental & agriculture",
    SiteDimension.REGULATORY: "Regulatory",
}


def _billable(spec: FieldSpec, include_billed_extra: bool) -> bool:
    """Concepts in Mireye's 300-credit parcel_record group are opt-in.

    They are still *requested* in mock mode — the mock is free — so demo
    behaviour is unchanged; the live client is what drops them.
    """
    return include_billed_extra or spec.provider_availability != "billed_extra"


def broad_fields(include_billed_extra: bool = True) -> list[str]:
    """Fields fetched during the first, cheap pass over every candidate."""
    return [f.key for f in FIELDS if f.depth == "broad" and _billable(f, include_billed_extra)]


def deep_fields(include_billed_extra: bool = True) -> list[str]:
    """Extra fields fetched only for shortlisted sites."""
    return [f.key for f in FIELDS if f.depth == "deep" and _billable(f, include_billed_extra)]


def _snake(value: str) -> str:
    return "_".join(value.strip().lower().split())


def to_internal(key: str, provider_value):
    """Convert one provider value into the unit and vocabulary scoring expects.

    `None` in, `None` out — a value the provider does not have must stay absent
    rather than becoming a zero.
    """
    spec = FIELD_INDEX[key]
    if provider_value is None:
        return None

    if isinstance(provider_value, bool):
        if spec.direction == "categorical" or spec.kind == "category":
            options = spec.categories or {}
            val_str = "true" if provider_value else "false"
            if val_str in options:
                return val_str
            first_key = next(iter(options.keys())) if options else "yes"
            last_key = list(options.keys())[-1] if options else "no"
            return first_key if provider_value else last_key
        return 1.0 if provider_value else 0.0

    if spec.direction == "categorical" or spec.kind == "category":
        text = str(provider_value)
        options = spec.categories or {}
        if spec.provider_categories is not None:
            # The provider speaks a different taxonomy. Only translations we can
            # make unambiguously are listed; anything else falls through and is
            # scored as missing.
            return spec.provider_categories.get(text, text)
        if text in options:
            return text
        snake = _snake(text)
        if snake in options:
            return snake
        lower = text.lower()
        if "barren" in lower or "impervious" in lower:
            return "barren" if "barren" in options else snake
        if "tree" in lower or "forest" in lower:
            return "forest" if "forest" in options else snake
        if "cultivat" in lower or "crop" in lower or "agri" in lower:
            return "cropland" if "cropland" in options else "agricultural" if "agricultural" in options else snake
        if "shrub" in lower or "scrub" in lower or "grass" in lower:
            return "shrubland" if "shrubland" in options else "grassland" if "grassland" in options else snake
        if "develop" in lower or "urban" in lower or "built" in lower:
            return "urban" if "urban" in options else "commercial" if "commercial" in options else snake
        if "water" in lower or "wetland" in lower:
            return "wetland" if "wetland" in options else snake
        if "indus" in lower:
            return "industrial" if "industrial" in options else "light_industrial" if "light_industrial" in options else snake
        for opt_key in options:
            if opt_key in snake or snake in opt_key:
                return opt_key
        return snake if snake in options else text

    try:
        number = float(provider_value)
    except (TypeError, ValueError):
        return None
    return CONVERSIONS[spec.conversion][1](number)



def provider_fields(
    specs: dict[str, FieldSpec] | None = None,
    *,
    include_billed_extra: bool = False,
) -> list[str]:
    """Provider field names to request. Excludes Mireye's 300-credit
    `parcel_record` group unless it is explicitly asked for."""
    allowed = {"mapped", "proxy"} | ({"billed_extra"} if include_billed_extra else set())
    return [
        spec.provider_field
        for spec in (specs or FIELD_INDEX).values()
        if spec.provider_field and spec.provider_availability in allowed
    ]


class UnknownFieldError(KeyError):
    """Raised when the agent asks for a field the catalog does not define."""


def spec(key: str) -> FieldSpec:
    try:
        return FIELD_INDEX[key]
    except KeyError as exc:
        raise UnknownFieldError(key) from exc
