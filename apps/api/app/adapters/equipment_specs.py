"""Equipment specification, climate station and data center benchmarks adapters.

Integrates open source datasets:
- RacksDB (github.com/rackslab/RacksDB) for equipment metadata and baseline sizing.
- LBNL Center of Expertise (datacenters.lbl.gov/resources) for energy benchmarks and COP baselines.
- StationFinder (klimaat.github.io/StationFinder) for nearest weather station and ASHRAE design conditions.
- Chelsea Bann & LBNL AI Water Stress datasets for WUE and cooling water consumption modeling.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("equipment_specs")

BUNDLED_DIR = Path(__file__).resolve().parent.parent / "data" / "datasets"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in km."""
    r = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


@dataclass
class ClimateStation:
    station_id: str
    name: str
    state: str
    country: str
    latitude: float
    longitude: float
    elevation_m: float
    cooling_db_0_4_pct_degc: float
    cooling_wb_0_4_pct_degc: float
    cooling_db_1_0_pct_degc: float
    cooling_wb_1_0_pct_degc: float
    heating_db_99_6_pct_degc: float
    distance_km: float = 0.0


class EquipmentSpecsAdapter:
    """Provides RacksDB & LBNL reference data for data-center equipment substitutions."""

    def __init__(self, catalog_path: Path | None = None, stations_path: Path | None = None) -> None:
        self._catalog_path = catalog_path or (BUNDLED_DIR / "equipment_reference_catalog.json")
        self._stations_path = stations_path or (BUNDLED_DIR / "climate_stations.json")
        self._catalog: dict | None = None
        self._stations: list[dict] | None = None

    def _ensure_catalog(self) -> dict:
        if self._catalog is None:
            if self._catalog_path.exists():
                with open(self._catalog_path, encoding="utf-8") as f:
                    self._catalog = json.load(f)
            else:
                self._catalog = {"equipment_models": {}}
        return self._catalog

    def _ensure_stations(self) -> list[dict]:
        if self._stations is None:
            if self._stations_path.exists():
                with open(self._stations_path, encoding="utf-8") as f:
                    data = json.load(f)
                    self._stations = data.get("stations", [])
            else:
                self._stations = []
        return self._stations

    def get_reference_spec(self, equipment_tag_or_type: str) -> dict | None:
        """Find baseline reference model by tag (e.g. 'PDU-3') or equipment type."""
        cat = self._ensure_catalog().get("equipment_models", {})
        if equipment_tag_or_type in cat:
            return cat[equipment_tag_or_type]
        for item in cat.values():
            if item.get("equipment_type") == equipment_tag_or_type or item.get("id") == equipment_tag_or_type:
                return item
        return None

    def list_models_by_type(self, equipment_type: str | None = None) -> list[dict]:
        """List equipment models from catalog, optionally filtered by type."""
        cat = self._ensure_catalog().get("equipment_models", {})
        results = []
        for key, item in cat.items():
            record = dict(item)
            record.setdefault("id", key)
            if equipment_type is None or equipment_type == "all":
                results.append(record)
            elif record.get("equipment_type", "").lower() == equipment_type.lower():
                results.append(record)
            elif equipment_type.lower() in record.get("equipment_type", "").lower():
                results.append(record)
        return results

    def get_model_by_id(self, model_id: str) -> dict | None:
        """Get model details by catalog id."""
        cat = self._ensure_catalog().get("equipment_models", {})
        if model_id in cat:
            rec = dict(cat[model_id])
            rec.setdefault("id", model_id)
            return rec
        for key, item in cat.items():
            if item.get("id") == model_id or item.get("model_number") == model_id:
                rec = dict(item)
                rec.setdefault("id", key)
                return rec
        return None

    def find_nearest_climate_station(self, latitude: float, longitude: float) -> ClimateStation | None:
        """Find the closest ASHRAE / NOAA climate station from StationFinder catalog."""
        stations = self._ensure_stations()
        if not stations:
            return None

        best_station: dict | None = None
        min_dist = float("inf")

        for st in stations:
            dist = _haversine_km(latitude, longitude, st["latitude"], st["longitude"])
            if dist < min_dist:
                min_dist = dist
                best_station = st

        if not best_station:
            return None

        return ClimateStation(
            station_id=best_station["station_id"],
            name=best_station["name"],
            state=best_station["state"],
            country=best_station["country"],
            latitude=best_station["latitude"],
            longitude=best_station["longitude"],
            elevation_m=best_station["elevation_m"],
            cooling_db_0_4_pct_degc=best_station["cooling_db_0_4_pct_degc"],
            cooling_wb_0_4_pct_degc=best_station["cooling_wb_0_4_pct_degc"],
            cooling_db_1_0_pct_degc=best_station["cooling_db_1_0_pct_degc"],
            cooling_wb_1_0_pct_degc=best_station["cooling_wb_1_0_pct_degc"],
            heating_db_99_6_pct_degc=best_station["heating_db_99_6_pct_degc"],
            distance_km=round(min_dist, 1),
        )

    def calculate_water_consumption_estimate(
        self,
        cooling_capacity_kw: float,
        cooling_type: str = "water_cooled",
        cop: float = 5.5,
    ) -> dict[str, float]:
        """Estimate annual water consumption (m3/year) based on LBNL / WaterStress models.

        Water-cooled systems: ~1.4 - 1.8 L/kWh of cooling thermal energy for evaporative tower.
        Air-cooled systems: ~0.0 - 0.2 L/kWh (closed loop / adiabatic trim only).
        """
        wue_liters_per_kwh_thermal = 1.45 if "water" in cooling_type.lower() else 0.15
        hours_per_year = 8760.0
        annual_thermal_kwh = cooling_capacity_kw * hours_per_year * 0.70  # 70% average load factor
        annual_water_liters = annual_thermal_kwh * wue_liters_per_kwh_thermal
        annual_water_m3 = annual_water_liters / 1000.0
        electrical_input_kw = cooling_capacity_kw / max(cop, 1.0)
        annual_power_mwh = (electrical_input_kw * hours_per_year * 0.70) / 1000.0

        return {
            "wue_l_per_kwh_thermal": wue_liters_per_kwh_thermal,
            "annual_water_m3": round(annual_water_m3, 1),
            "annual_power_mwh": round(annual_power_mwh, 1),
            "effective_cop": round(cop, 2),
        }


_specs_adapter: EquipmentSpecsAdapter | None = None


def get_equipment_specs_adapter() -> EquipmentSpecsAdapter:
    global _specs_adapter
    if _specs_adapter is None:
        _specs_adapter = EquipmentSpecsAdapter()
    return _specs_adapter
