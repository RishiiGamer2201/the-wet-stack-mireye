"""The site-evaluation field catalog.

This is the single list of physical-world facts the platform knows how to reason
about. It doubles as the Mireye field catalog (`GET /v1/meta/fields`) so the
agent can never request a field name that does not exist — an unknown field
becomes an InformationGap plus a Mireye feature request instead.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .domain import SiteDimension

Direction = Literal["higher_better", "lower_better", "band", "categorical"]


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
        good=10,
        bad=80,
        weight=1.2,
        description="Composite wildfire hazard potential 0–100.",
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
        description="Distance to the nearest designated protected area.",
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

FIELD_INDEX: dict[str, FieldSpec] = {f.key: f for f in FIELDS}

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


def broad_fields() -> list[str]:
    """Fields fetched during the first, cheap pass over every candidate."""
    return [f.key for f in FIELDS if f.depth == "broad"]


def deep_fields() -> list[str]:
    """Extra fields fetched only for shortlisted sites."""
    return [f.key for f in FIELDS if f.depth == "deep"]


class UnknownFieldError(KeyError):
    """Raised when the agent asks for a field the catalog does not define."""


def spec(key: str) -> FieldSpec:
    try:
        return FIELD_INDEX[key]
    except KeyError as exc:
        raise UnknownFieldError(key) from exc
