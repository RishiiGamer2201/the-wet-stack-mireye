"""Generate reproducible prototype data for the During Construction workflows.

The equipment records are intentionally synthetic. They provide enough breadth
to exercise filtering, ranking, sizing, cost, and substitution flows without
pretending that generated model numbers are manufacturer-certified submittals.

The state electricity rates are extracted from the official EIA 2024 Table 4
workbook. All other state multipliers are deterministic prototype assumptions
and are labelled as such in the output.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "apps" / "api" / "app" / "data" / "datasets"

EIA_SOURCE_URL = "https://www.eia.gov/electricity/sales_revenue_price/xls/table_4.xlsx"
DOE_CCMS_URL = "https://www.energy.gov/cmei/buildings/implementation-certification-and-enforcement"
NOAA_NORMALS_URL = "https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals"

STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

REGIONS = {
    "northeast": {"CT", "DC", "DE", "MA", "MD", "ME", "NH", "NJ", "NY", "PA", "RI", "VT"},
    "southeast": {"AL", "AR", "FL", "GA", "KY", "LA", "MS", "NC", "SC", "TN", "VA", "WV"},
    "midwest": {"IA", "IL", "IN", "KS", "MI", "MN", "MO", "ND", "NE", "OH", "SD", "WI"},
    "southwest": {"AZ", "NM", "NV", "OK", "TX", "UT"},
    "west": {"AK", "CA", "CO", "HI", "ID", "MT", "OR", "WA", "WY"},
}

PROTOTYPE_SCENARIOS = [
    ("Ashburn hyperscale corridor", "VA", 38.9696, -77.3861, 96.0, "2N"),
    ("Dallas-Fort Worth campus", "TX", 32.8998, -97.0403, 72.0, "N+1"),
    ("Phoenix-Mesa campus", "AZ", 33.4152, -111.8315, 64.0, "N+1"),
    ("Quincy hydro-powered campus", "WA", 47.2343, -119.8526, 48.0, "N+1"),
    ("New Albany compute campus", "OH", 40.0812, -82.8088, 48.0, "N+1"),
    ("Santa Clara infill facility", "CA", 37.3541, -121.9552, 32.0, "2N"),
    ("Atlanta regional campus", "GA", 33.7490, -84.3880, 48.0, "N+1"),
    ("Chicago metro campus", "IL", 41.8781, -87.6298, 40.0, "N+1"),
    ("Salt Lake City campus", "UT", 40.7608, -111.8910, 36.0, "N+1"),
    ("Des Moines low-latency campus", "IA", 41.5868, -93.6250, 32.0, "N+1"),
    ("Portland edge campus", "OR", 45.5152, -122.6784, 24.0, "N+1"),
    ("Northern New Jersey interconnect", "NJ", 40.7357, -74.1724, 40.0, "2N"),
]

CATEGORY_CONFIG = {
    "chiller": {"capacities": [350, 500, 700, 900, 1200, 1500, 1800, 2100, 2500, 3000], "unit": "kW cooling", "base_cost": 360000},
    "crah": {"capacities": [80, 120, 160, 200, 250, 300, 350, 400, 500, 600], "unit": "kW cooling", "base_cost": 65000},
    "ahu": {"capacities": [100, 150, 200, 300, 400, 500, 650, 800, 1000, 1200], "unit": "kW cooling", "base_cost": 85000},
    "cooling_tower": {"capacities": [500, 750, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000], "unit": "kW thermal", "base_cost": 140000},
    "pump": {"capacities": [20, 30, 45, 60, 80, 100, 130, 160, 200, 250], "unit": "L/s", "base_cost": 28000},
    "transformer": {"capacities": [500, 750, 1000, 1500, 2000, 2500, 3000, 3750, 5000, 7500], "unit": "kVA", "base_cost": 260000},
    "ups": {"capacities": [250, 400, 600, 800, 1000, 1200, 1500, 1800, 2000, 2500], "unit": "kW", "base_cost": 420000},
    "generator": {"capacities": [500, 750, 1000, 1250, 1500, 1750, 2000, 2250, 2500, 3000], "unit": "kW standby", "base_cost": 580000},
    "switchgear": {"capacities": [800, 1200, 1600, 2000, 2500, 3000, 3500, 4000, 5000, 6000], "unit": "A", "base_cost": 240000},
    "pdu": {"capacities": [75, 100, 150, 200, 250, 300, 400, 500, 600, 750], "unit": "kW", "base_cost": 48000},
    "heat_exchanger": {"capacities": [300, 500, 750, 1000, 1250, 1500, 2000, 2500, 3000, 4000], "unit": "kW thermal", "base_cost": 90000},
}


def _xlsx_rows(path: Path) -> list[list[str | float | None]]:
    """Read the first worksheet with the standard library only."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{ns}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{ns}t")))
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    rows: list[list[str | float | None]] = []
    for row in sheet.iter(f"{ns}row"):
        values: dict[int, str | float | None] = {}
        for cell in row.findall(f"{ns}c"):
            ref = cell.attrib.get("r", "A1")
            letters = re.match(r"[A-Z]+", ref).group(0)
            column = 0
            for letter in letters:
                column = column * 26 + ord(letter) - 64
            raw = cell.find(f"{ns}v")
            if raw is None or raw.text is None:
                value: str | float | None = None
            elif cell.attrib.get("t") == "s":
                value = shared[int(raw.text)]
            else:
                try:
                    value = float(raw.text)
                except ValueError:
                    value = raw.text
            values[column - 1] = value
        width = max(values, default=-1) + 1
        rows.append([values.get(index) for index in range(width)])
    return rows


def load_eia_rates(path: Path) -> dict[str, float]:
    rates: dict[str, float] = {}
    for row in _xlsx_rows(path):
        if len(row) < 3 or row[0] not in STATES or not isinstance(row[2], (int, float)):
            continue
        rates[STATES[str(row[0])]] = round(float(row[2]) / 100.0, 5)
    missing = sorted(set(STATES.values()) - rates.keys())
    if missing:
        raise ValueError(f"EIA workbook is missing state rows: {', '.join(missing)}")
    return rates


def region_for(state_code: str) -> str:
    return next(name for name, states in REGIONS.items() if state_code in states)


def generate_profiles(rates: dict[str, float]) -> dict:
    profiles = []
    region_cost = {"northeast": 1.16, "southeast": 0.94, "midwest": 0.98, "southwest": 1.01, "west": 1.13}
    for state_name, state_code in STATES.items():
        region = region_for(state_code)
        rng = random.Random(f"mireye-us-construction-profile-v1:{state_code}")
        profiles.append({
            "state": state_name,
            "state_code": state_code,
            "region": region,
            "commercial_electricity_rate_usd_kwh": rates[state_code],
            "electricity_rate_source": "EIA 2024 Table 4, commercial sector state average",
            "construction_cost_index": round(region_cost[region] + rng.uniform(-0.06, 0.06), 3),
            "lead_time_multiplier": round(1.0 + rng.uniform(-0.08, 0.18), 3),
            "planning_water_cost_usd_m3": round(rng.uniform(1.4, 4.8), 2),
            "synthetic_fields": ["construction_cost_index", "lead_time_multiplier", "planning_water_cost_usd_m3"],
        })

    scenarios = []
    by_code = {profile["state_code"]: profile for profile in profiles}
    for name, state_code, latitude, longitude, it_load_mw, redundancy in PROTOTYPE_SCENARIOS:
        profile = by_code[state_code]
        scenarios.append({
            "name": name,
            "state_code": state_code,
            "latitude": latitude,
            "longitude": longitude,
            "it_load_mw": it_load_mw,
            "redundancy": redundancy,
            "target_pue": 1.30 if state_code in {"IA", "OH", "OR", "UT", "WA"} else 1.38,
            "electricity_rate_usd_kwh": profile["commercial_electricity_rate_usd_kwh"],
            "prototype_only": True,
        })

    return {
        "version": "1.0.0",
        "coverage": "50 U.S. states plus District of Columbia",
        "real_data_fields": ["commercial_electricity_rate_usd_kwh"],
        "synthetic_data_fields": ["construction_cost_index", "lead_time_multiplier", "planning_water_cost_usd_m3"],
        "sources": [{"name": "U.S. EIA Electric Sales, Revenue, and Average Price 2024 Table 4", "url": EIA_SOURCE_URL, "data_year": 2024}],
        "disclaimer": "State electricity prices are EIA averages, not utility tariffs. Other multipliers and all prototype scenarios are synthetic planning assumptions.",
        "state_profiles": profiles,
        "prototype_scenarios": scenarios,
    }


def _round_breaker(amps: float) -> int:
    return int(math.ceil(amps / 25.0) * 25)


def generate_equipment_catalog() -> dict:
    models: dict[str, dict] = {}
    voltages = [400, 480, 600]
    ambient_ratings = [40, 50]

    for category, config in CATEGORY_CONFIG.items():
        capacities = config["capacities"]
        for tier, capacity in enumerate(capacities, start=1):
            for voltage in voltages:
                for efficiency_band, max_ambient in enumerate(ambient_ratings, start=1):
                    model_id = f"SYN-{category.upper().replace('_', '-')}-{tier:02d}-{voltage}-{efficiency_band}"
                    scale = capacity / capacities[0]
                    efficiency = 0.955 + efficiency_band * 0.012 + min(tier, 8) * 0.0015
                    power_kw = capacity / (5.2 + efficiency_band * 0.55) if category in {"chiller", "crah", "ahu"} else max(5.0, capacity * 0.035)
                    if category == "cooling_tower":
                        power_kw = capacity * 0.025
                    elif category == "pump":
                        power_kw = capacity * 1.65
                    elif category == "heat_exchanger":
                        power_kw = capacity * 0.006
                    elif category == "transformer":
                        power_kw = capacity * (1.0 - min(efficiency, 0.995))
                    elif category == "generator":
                        power_kw = capacity
                    elif category == "switchgear":
                        power_kw = math.sqrt(3) * voltage * capacity / 1000.0
                    elif category in {"ups", "pdu"}:
                        power_kw = capacity / min(efficiency, 0.99)

                    electrical_kw = capacity if category not in {"pump", "switchgear", "transformer"} else power_kw
                    amps = max(10.0, electrical_kw * 1000.0 / (math.sqrt(3) * voltage * 0.92))
                    cost_low = config["base_cost"] * (0.55 + 0.45 * scale)
                    record = {
                        "id": model_id,
                        "equipment_type": category,
                        "model_number": f"MIREYE-SYN {category.replace('_', ' ').title()} {capacity:g} {config['unit']}",
                        "manufacturer": "Mireye Synthetic Benchmark",
                        "voltage_v": voltage,
                        "phases": 3,
                        "full_load_amps_a": round(amps, 1),
                        "mca_a": _round_breaker(amps * 1.15),
                        "mocp_a": _round_breaker(amps * 1.25),
                        "power_input_kw": round(power_kw, 2),
                        "efficiency_pct": round(min(efficiency, 0.995) * 100.0, 2),
                        "max_ambient_degc": max_ambient,
                        "weight_kg": round(650 * scale ** 0.72 + 250, 1),
                        "length_mm": round(1200 + 520 * scale ** 0.58),
                        "width_mm": round(800 + 270 * scale ** 0.48),
                        "height_mm": round(1600 + 190 * scale ** 0.35),
                        "installed_cost_low_usd": round(cost_low, 2),
                        "installed_cost_high_usd": round(cost_low * 1.42, 2),
                        "lead_time_weeks": int(round(12 + math.log2(max(scale, 1)) * 4 + efficiency_band * 2)),
                        "synthetic": True,
                        "source": "Mireye synthetic USA prototype equipment catalog v3.0",
                        "provenance_note": "Generated engineering benchmark; not a manufacturer submittal, certified rating, quotation, or procurement recommendation.",
                        "description": f"Synthetic {category.replace('_', ' ')} benchmark for deterministic prototype filtering and change-impact demonstrations.",
                    }
                    if category in {"chiller", "crah", "ahu"}:
                        record.update({"cooling_capacity_kw": capacity, "cop": round(capacity / power_kw, 2), "wue_l_per_kwh": round(1.5 - efficiency_band * 0.12, 2)})
                    elif category in {"cooling_tower", "heat_exchanger"}:
                        record["thermal_capacity_kw"] = capacity
                    elif category == "pump":
                        record.update({"flow_rate_l_s": capacity, "head_m": 24 + tier * 2, "motor_power_kw": round(power_kw, 2)})
                    elif category == "transformer":
                        record.update({"kva_rating": capacity, "power_capacity_kw": round(capacity * 0.9, 1), "primary_voltage_v": 13800, "secondary_voltage_v": voltage})
                    elif category == "generator":
                        record.update({"standby_rating_kw": capacity, "fuel_type": "diesel", "derate_temp_threshold_degc": 40})
                    elif category == "switchgear":
                        record.update({"bus_continuous_amps": capacity, "power_capacity_kw": round(power_kw * 0.9, 1), "short_circuit_rating_ka": 65})
                    elif category in {"ups", "pdu"}:
                        record["power_capacity_kw"] = capacity
                    models[model_id] = record

    aliases = {
        "PDU-3": ("pdu", 200), "UPS-1": ("ups", 1200), "CH-01": ("chiller", 1200),
        "CH-02": ("crah", 500), "GEN-01": ("generator", 2500),
    }
    for alias, (category, capacity) in aliases.items():
        template = next(record for record in models.values() if record["equipment_type"] == category and str(capacity) in record["model_number"] and record["voltage_v"] == 480)
        record = dict(template)
        record.update({"id": alias, "model_number": f"{alias} Mireye Synthetic Demo Baseline", "prototype_alias": True})
        models[alias] = record

    return {
        "version": "3.0.0",
        "synthetic": True,
        "model_count": len(models),
        "categories": sorted(CATEGORY_CONFIG),
        "source": "Mireye deterministic synthetic USA prototype catalog",
        "licence": "Project-generated data; repository licence applies",
        "disclaimer": "Every equipment record is synthetic and must be replaced by certified manufacturer data and vendor quotations before engineering approval or procurement.",
        "production_data_sources": [
            {"name": "DOE Compliance Certification Database", "url": DOE_CCMS_URL, "use": "Candidate source for certified ratings of covered equipment"},
            {"name": "NOAA U.S. Climate Normals", "url": NOAA_NORMALS_URL, "use": "Candidate source for site climate context"},
        ],
        "equipment_models": models,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eia-xlsx", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    args = parser.parse_args()
    args.dataset_dir.mkdir(parents=True, exist_ok=True)

    rates = load_eia_rates(args.eia_xlsx)
    profiles = generate_profiles(rates)
    catalog = generate_equipment_catalog()

    (args.dataset_dir / "us_construction_profiles.json").write_text(
        json.dumps(profiles, indent=2) + "\n", encoding="utf-8"
    )
    (args.dataset_dir / "equipment_reference_catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(profiles['state_profiles'])} state profiles")
    print(f"wrote {catalog['model_count']} synthetic equipment models")


if __name__ == "__main__":
    main()
