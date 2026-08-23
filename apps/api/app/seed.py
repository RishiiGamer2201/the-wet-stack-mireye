"""Demo seed.

Everything created here is SYNTHETIC and labelled as such: the manufacturers,
model numbers, performance data and site facts are invented for demonstration.
They are not real product data and must not be used for engineering decisions.

Run with:  python -m app.seed          (re-seeds from scratch)
           python -m app.seed --reset  (wipes the database first)
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .adapters.graphstore import get_graph_store
from .config import get_settings
from .domain import (
    Assumption,
    CandidateSite,
    Discipline,
    DocumentKind,
    Equipment,
    EquipmentChange,
    EquipmentConfiguration,
    Evidence,
    EvidenceSource,
    EvidenceStatus,
    Project,
    ProjectDocument,
    Quantity,
    RatingConditions,
    Requirement,
    RequirementKind,
    RequirementTargets,
    SourceType,
    SupportPoint,
    TextSpan,
)
from .fields import DEFAULT_DIMENSION_WEIGHTS
from .services.ingest import ingest_pdf
from .store import C, Store, get_store

log = logging.getLogger("seed")

def _sample_dir() -> Path:
    """Resolved per call, not at import: DATA_DIR is configuration."""
    return get_settings().sample_dir

SYNTHETIC_BANNER = (
    "SYNTHETIC DEMONSTRATION DOCUMENT - values are invented for the Wet Stack / Mireye "
    "prototype and are not real product or project data."
)

SPEC_PAGES = [
    f"""{SYNTHETIC_BANNER}

AURORA DC-1 CAMPUS - MECHANICAL SPECIFICATION (EXTRACT)
Section 23 64 16 - Air-Cooled Chillers

1.1 GENERAL
This section covers air-cooled packaged chillers serving the Aurora DC-1 white space.
All equipment shall comply with AHRI 550/590 certification requirements.

1.2 PERFORMANCE
Each chiller CH-01 shall provide a minimum net cooling capacity of 1040 kW at the
scheduled conditions. Entering water temperature shall be 12 degC and the leaving
water temperature shall be 6.7 degC. The ambient design dry-bulb temperature for
selection is 35 degC.
""",
    f"""{SYNTHETIC_BANNER}

1.3 PHYSICAL AND STRUCTURAL
The maximum operating weight for CH-01 shall not exceed 5000 kg. Support point load
per mounting position shall not exceed 13.5 kN. Overall dimensions shall permit a
service clearance of 1200 mm on all sides.

1.4 ELECTRICAL
Nominal voltage is 480 V, three phase, 60 Hz. Minimum circuit ampacity for CH-01
shall not exceed 300 A. Maximum overcurrent protection shall not exceed 400 A.

1.5 REFRIGERANT
Refrigerant type shall be R-134a. Machine rooms shall comply with ASHRAE 15
ventilation and monitoring requirements for the installed refrigerant charge.
""",
    f"""{SYNTHETIC_BANNER}

Section 23 73 13 - Air Handling Units

2.1 PERFORMANCE
Unit CH-02 shall provide a minimum cooling capacity of 515 kW at the scheduled
conditions. Entering water temperature shall be 12 degC and leaving water
temperature shall be 6.7 degC.

2.2 PHYSICAL
The maximum operating weight for CH-02 shall not exceed 2600 kg.

2.3 ELECTRICAL
Minimum circuit ampacity for CH-02 shall not exceed 150 A at 480 V, three phase.

Section 26 23 00 - Power Distribution
Unit PDU-3 shall be rated for the design block load with the supply voltage of 480 V.
""",
]

DATASHEET_PAGES = [
    f"""{SYNTHETIC_BANNER}

NORTHWIND THERMAL - MODEL NT-1100 AIR-COOLED SCREW CHILLER
Technical data sheet (synthetic)

Model number: NT-1100
Configuration: two refrigerant circuits, air-cooled, standard efficiency

PERFORMANCE (AHRI 550/590)
Net cooling capacity: 1050 kW
Entering water temperature: 12 degC
Leaving water temperature: 6.7 degC
Ambient design dry-bulb: 35 degC

PHYSICAL DATA
Operating weight: 4850 kg
Shipping weight: 4610 kg
Support point load (each of 4 positions): 12.1 kN
Length: 6800 mm    Width: 2250 mm    Height: 2450 mm

ELECTRICAL DATA
Supply voltage: 480 V, three phase
Full load amps: 240 A
Minimum circuit ampacity: 265 A
Maximum overcurrent protection: 350 A
Power input: 310 kW

REFRIGERANT
Refrigerant type: R-134a
Refrigerant charge: 210 kg
""",
]

SUBMITTAL_PAGES = [
    f"""{SYNTHETIC_BANNER}

VERTEX CLIMATE - MODEL VX-1150 AIR-COOLED SCREW CHILLER
Submittal for CH-01 substitution (synthetic)

Model number: VX-1150
Configuration: two refrigerant circuits, air-cooled, high ambient package

PERFORMANCE (AHRI 550/590)
Net cooling capacity: 1055 kW
Entering water temperature: 12 degC
Leaving water temperature: 6.7 degC
Ambient design dry-bulb: 35 degC

PHYSICAL DATA
Operating weight: 5290 kg
Support point load (each of 4 positions): 13.2 kN
Length: 7100 mm    Width: 2250 mm    Height: 2600 mm

ELECTRICAL DATA
Supply voltage: 480 V, three phase
Full load amps: 268 A
Minimum circuit ampacity: 297 A
Maximum overcurrent protection: 400 A
Power input: 336 kW

REFRIGERANT
Refrigerant type: R-134a
Refrigerant charge: 232 kg
""",
]


def write_sample_pdf(path: Path, title: str, pages: list[str]) -> Path:
    """Generate a synthetic source PDF so ingestion is exercised end to end."""
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_textbox(
            pymupdf.Rect(50, 50, 545, 780), body, fontsize=10, fontname="helv", align=0
        )
    doc.set_metadata({"title": title, "subject": "synthetic demonstration document"})
    doc.save(str(path))
    doc.close()
    return path


def ensure_sample_documents() -> dict[str, Path]:
    files = {
        "spec": (
            _sample_dir() / "Aurora-DC1-Mechanical-Specification-SYNTHETIC.pdf",
            "Aurora DC-1 Mechanical Specification (synthetic)",
            SPEC_PAGES,
        ),
        "datasheet": (
            _sample_dir() / "Northwind-NT-1100-Datasheet-SYNTHETIC.pdf",
            "Northwind Thermal NT-1100 datasheet (synthetic)",
            DATASHEET_PAGES,
        ),
        "submittal": (
            _sample_dir() / "Vertex-VX-1150-Submittal-SYNTHETIC.pdf",
            "Vertex Climate VX-1150 submittal (synthetic)",
            SUBMITTAL_PAGES,
        ),
    }
    out = {}
    for key, (path, title, pages) in files.items():
        if not path.exists():
            write_sample_pdf(path, title, pages)
        out[key] = path
    return out


# ---------------------------------------------------------------------------


def _evidence(
    store: Store, project_id: str, tag: str, field: str, claim: str, value, unit, doc: str, page: int
) -> str:
    ev = Evidence(
        project_id=project_id,
        subject_id=tag,
        claim=claim,
        field_key=field,
        value=value,
        unit=unit,
        source=EvidenceSource(
            source_type=SourceType.MANUFACTURER_DOCUMENT,
            source_id=doc,
            source_name=doc,
            page=page,
            field_key=field,
            synthetic=True,
            notes="Synthetic manufacturer value created for the demo.",
        ),
        status=EvidenceStatus.SYNTHETIC,
        confidence=0.8,
    )
    store.put(C.EVIDENCE, ev, project_id=project_id, parent_id=tag)
    return ev.id


def _sourced(store: Store, project_id: str, tag: str, doc: str, page: int, values: dict) -> dict:
    """Create one evidence item per populated configuration field."""
    ids = {}
    for field, (value, unit) in values.items():
        ids[field] = _evidence(
            store,
            project_id,
            tag,
            field,
            f"{tag} {field.replace('_', ' ')} = {value}{(' ' + unit) if unit else ''}",
            value,
            unit,
            doc,
            page,
        )
    return ids


SITES = [
    ("Cascade Flats", "1400 Grant Rd, East Wenatchee, WA", 47.4235, -120.3103, 62.0, "Douglas County, WA"),
    ("Rio Verde Mesa", "18200 E Rio Verde Dr, Scottsdale, AZ", 33.5312, -111.6321, 74.0, "Maricopa County, AZ"),
    ("Delta Fields", "5400 Tulane Rd, Memphis, TN", 35.0512, -90.0421, 55.0, "Shelby County, TN"),
    ("Harbour Point", "800 Terminal Blvd, Norfolk, VA", 36.8912, -76.2612, 28.0, "City of Norfolk, VA"),
    ("Prairie Junction", "12100 Co Rd 36, Fremont, NE", 41.1401, -96.6512, 88.0, "Dodge County, NE"),
]


def seed(store: Store | None = None, reset: bool = True) -> Project:
    store = store or get_store()
    if reset:
        store.clear()
        get_graph_store().clear()

    project = Project(
        name="Aurora DC-1 - 48 MW hyperscale campus (synthetic demo)",
        client="Aurora Digital Infrastructure (synthetic)",
        description=(
            "Demonstration project for The Wet Stack / Mireye. All sites, documents, "
            "equipment and observations in this project are synthetic."
        ),
        region="United States",
        targets=RequirementTargets(
            it_load_mw=48,
            min_grid_capacity_mw=200,
            max_distance_to_substation_km=10,
            max_water_stress_index=3.5,
            max_permit_lead_time_months=12,
            min_bearing_capacity_kpa=200,
            max_seismic_pga_g=0.35,
        ),
        dimension_weights=dict(DEFAULT_DIMENSION_WEIGHTS),
    )
    store.put(C.PROJECTS, project, project_id=project.id)

    sites: list[CandidateSite] = []
    for name, address, lat, lon, area, jurisdiction in SITES:
        site = CandidateSite(
            project_id=project.id,
            name=name,
            address=address,
            latitude=lat,
            longitude=lon,
            area_hectares=area,
            jurisdiction=jurisdiction,
            geocode_resolution="parcel",
            notes="Synthetic candidate site created for the demo.",
        )
        store.put(C.SITES, site, project_id=project.id)
        sites.append(site)

    docs = ensure_sample_documents()
    for key, kind in (
        ("spec", DocumentKind.SPECIFICATION),
        ("datasheet", DocumentKind.MANUFACTURER_DATASHEET),
        ("submittal", DocumentKind.SUBMITTAL),
    ):
        ingest_pdf(store, project.id, docs[key], docs[key].name, kind=kind, synthetic=True)

    # Structured requirements that gate the checks (extraction also proposes its own).
    spec_doc = next(
        d
        for d in store.list(C.DOCUMENTS, ProjectDocument, project_id=project.id)
        if d.kind == DocumentKind.SPECIFICATION
    )
    for tag, value, page in (("CH-01", 1040.0, 1), ("CH-02", 515.0, 3)):
        req = Requirement(
            project_id=project.id,
            document_id=spec_doc.id,
            kind=RequirementKind.CAPACITY,
            label="Minimum net cooling capacity",
            field_key="cooling_capacity",
            value=value,
            unit="kW",
            condition="12 degC EWT / 6.7 degC LWT, 35 degC ambient (AHRI 550/590)",
            equipment_tag=tag,
            page=page,
            span=TextSpan(start=0, end=120, text=f"minimum net cooling capacity of {value:g} kW"),
            raw_text=f"{tag} shall provide a minimum net cooling capacity of {value:g} kW.",
            confidence=0.9,
        )
        ev = Evidence(
            project_id=project.id,
            subject_id=tag,
            claim=req.raw_text,
            field_key="cooling_capacity",
            value=value,
            unit="kW",
            source=EvidenceSource(
                source_type=SourceType.PROJECT_DOCUMENT,
                source_id=spec_doc.id,
                source_name=spec_doc.filename,
                page=page,
                span=req.span,
                field_key="cooling_capacity",
                synthetic=True,
            ),
            status=EvidenceStatus.SYNTHETIC,
            confidence=0.9,
        )
        req.evidence_id = ev.id
        store.put(C.EVIDENCE, ev, project_id=project.id, parent_id=spec_doc.id)
        store.put(C.REQUIREMENTS, req, project_id=project.id, parent_id=spec_doc.id)

    ds = "Northwind-NT-1100-Datasheet-SYNTHETIC.pdf"
    sub = "Vertex-VX-1150-Submittal-SYNTHETIC.pdf"
    rating = RatingConditions(
        entering_water_temp=Quantity(value=12, unit="degC"),
        leaving_water_temp=Quantity(value=6.7, unit="degC"),
        ambient_temp=Quantity(value=35, unit="degC"),
        standard="AHRI 550/590",
    )

    # --- Case A: CH-01 chiller substitution -------------------------------
    ch01_old = Equipment(
        project_id=project.id,
        tag="CH-01",
        name="Chiller CH-01 (existing selection)",
        site_id=sites[1].id,
        configuration=EquipmentConfiguration(
            manufacturer="Northwind Thermal",
            model_number="NT-1100",
            equipment_type="air_cooled_chiller",
            configuration_code="2C-STD",
            circuits=2,
            weight=Quantity(value=4850, unit="kg"),
            weight_basis="operating",
            support_points=[
                SupportPoint(point_id=f"P{i}", load=Quantity(value=12.1, unit="kN"))
                for i in range(1, 5)
            ],
            length=Quantity(value=6800, unit="mm"),
            width=Quantity(value=2250, unit="mm"),
            height=Quantity(value=2450, unit="mm"),
            voltage=Quantity(value=480, unit="V"),
            phases=3,
            full_load_amps=Quantity(value=240, unit="A"),
            mca=Quantity(value=265, unit="A"),
            mocp=Quantity(value=350, unit="A"),
            power_input=Quantity(value=310, unit="kW"),
            refrigerant_type="R-134a",
            refrigerant_charge=Quantity(value=210, unit="kg"),
            cooling_capacity=Quantity(value=1050, unit="kW"),
            rating_conditions=rating,
            evidence_ids=_sourced(
                store, project.id, "CH-01", ds, 1,
                {
                    "weight": (4850, "kg"), "support_points": (12.1, "kN"),
                    "length": (6800, "mm"), "width": (2250, "mm"), "height": (2450, "mm"),
                    "full_load_amps": (240, "A"), "mca": (265, "A"),
                    "power_input": (310, "kW"), "refrigerant_charge": (210, "kg"),
                    "cooling_capacity": (1050, "kW"),
                },
            ),
        ),
    )
    ch01_new = Equipment(
        project_id=project.id,
        tag="CH-01",
        name="Chiller CH-01 (proposed substitution)",
        site_id=sites[1].id,
        configuration=EquipmentConfiguration(
            manufacturer="Vertex Climate",
            model_number="VX-1150",
            equipment_type="air_cooled_chiller",
            configuration_code="2C-STD",
            circuits=2,
            weight=Quantity(value=5290, unit="kg"),
            weight_basis="operating",
            support_points=[
                SupportPoint(point_id=f"P{i}", load=Quantity(value=13.2, unit="kN"))
                for i in range(1, 5)
            ],
            length=Quantity(value=7100, unit="mm"),
            width=Quantity(value=2250, unit="mm"),
            height=Quantity(value=2600, unit="mm"),
            voltage=Quantity(value=480, unit="V"),
            phases=3,
            full_load_amps=Quantity(value=268, unit="A"),
            mca=Quantity(value=297, unit="A"),
            mocp=Quantity(value=400, unit="A"),
            power_input=Quantity(value=336, unit="kW"),
            refrigerant_type="R-134a",
            refrigerant_charge=Quantity(value=232, unit="kg"),
            cooling_capacity=Quantity(value=1055, unit="kW"),
            rating_conditions=rating,
            evidence_ids=_sourced(
                store, project.id, "CH-01", sub, 1,
                {
                    "weight": (5290, "kg"), "support_points": (13.2, "kN"),
                    "length": (7100, "mm"), "width": (2250, "mm"), "height": (2600, "mm"),
                    "full_load_amps": (268, "A"), "mca": (297, "A"),
                    "power_input": (336, "kW"), "refrigerant_charge": (232, "kg"),
                    "cooling_capacity": (1055, "kW"),
                },
            ),
        ),
    )

    # --- Case B: CH-02 like-for-like --------------------------------------
    ahu_rating = RatingConditions(
        entering_water_temp=Quantity(value=12, unit="degC"),
        leaving_water_temp=Quantity(value=6.7, unit="degC"),
        standard="AHRI 550/590",
    )
    ch02_old = Equipment(
        project_id=project.id,
        tag="CH-02",
        name="Fan-wall cooling unit CH-02 (existing)",
        configuration=EquipmentConfiguration(
            manufacturer="Halden Cooling",
            model_number="HC-560",
            equipment_type="fan_wall_cooling_unit",
            configuration_code="FW-6",
            circuits=1,
            weight=Quantity(value=2400, unit="kg"),
            weight_basis="operating",
            length=Quantity(value=4200, unit="mm"),
            width=Quantity(value=1800, unit="mm"),
            height=Quantity(value=2100, unit="mm"),
            voltage=Quantity(value=480, unit="V"),
            phases=3,
            full_load_amps=Quantity(value=126, unit="A"),
            mca=Quantity(value=140, unit="A"),
            mocp=Quantity(value=175, unit="A"),
            power_input=Quantity(value=148, unit="kW"),
            refrigerant_type="R-513A",
            refrigerant_charge=Quantity(value=95, unit="kg"),
            cooling_capacity=Quantity(value=520, unit="kW"),
            rating_conditions=ahu_rating,
            evidence_ids=_sourced(
                store, project.id, "CH-02", "Halden-HC-560-Datasheet-SYNTHETIC", 1,
                {
                    "weight": (2400, "kg"), "length": (4200, "mm"), "width": (1800, "mm"),
                    "height": (2100, "mm"), "full_load_amps": (126, "A"), "mca": (140, "A"),
                    "power_input": (148, "kW"), "refrigerant_charge": (95, "kg"),
                    "cooling_capacity": (520, "kW"),
                },
            ),
        ),
    )
    ch02_new = Equipment(
        project_id=project.id,
        tag="CH-02",
        name="Fan-wall cooling unit CH-02 (proposed)",
        configuration=EquipmentConfiguration(
            manufacturer="Halden Cooling",
            model_number="HC-560A",
            equipment_type="fan_wall_cooling_unit",
            configuration_code="FW-6",
            circuits=1,
            weight=Quantity(value=2460, unit="kg"),
            weight_basis="operating",
            length=Quantity(value=4230, unit="mm"),
            width=Quantity(value=1800, unit="mm"),
            height=Quantity(value=2110, unit="mm"),
            voltage=Quantity(value=480, unit="V"),
            phases=3,
            full_load_amps=Quantity(value=126, unit="A"),
            mca=Quantity(value=140, unit="A"),
            mocp=Quantity(value=175, unit="A"),
            power_input=Quantity(value=148, unit="kW"),
            refrigerant_type="R-513A",
            refrigerant_charge=Quantity(value=99, unit="kg"),
            cooling_capacity=Quantity(value=525, unit="kW"),
            rating_conditions=ahu_rating,
            evidence_ids=_sourced(
                store, project.id, "CH-02", "Halden-HC-560A-Submittal-SYNTHETIC", 1,
                {
                    "weight": (2460, "kg"), "length": (4230, "mm"), "width": (1800, "mm"),
                    "height": (2110, "mm"), "full_load_amps": (126, "A"), "mca": (140, "A"),
                    "power_input": (148, "kW"), "refrigerant_charge": (99, "kg"),
                    "cooling_capacity": (525, "kW"),
                },
            ),
        ),
    )

    # --- Case C: PDU-3, vendor data incomplete ----------------------------
    pdu_old = Equipment(
        project_id=project.id,
        tag="PDU-3",
        name="Power distribution unit PDU-3 (existing)",
        discipline=Discipline.ELECTRICAL,
        configuration=EquipmentConfiguration(
            manufacturer="Ferrous Power",
            model_number="FP-2000",
            equipment_type="power_distribution_unit",
            weight=Quantity(value=1850, unit="kg"),
            weight_basis="operating",
            length=Quantity(value=2100, unit="mm"),
            width=Quantity(value=1100, unit="mm"),
            height=Quantity(value=2200, unit="mm"),
            voltage=Quantity(value=480, unit="V"),
            phases=3,
            full_load_amps=Quantity(value=2400, unit="A"),
            evidence_ids=_sourced(
                store, project.id, "PDU-3", "Ferrous-FP-2000-Datasheet-SYNTHETIC", 1,
                {
                    "weight": (1850, "kg"), "length": (2100, "mm"), "width": (1100, "mm"),
                    "height": (2200, "mm"), "full_load_amps": (2400, "A"),
                },
            ),
        ),
    )
    pdu_new = Equipment(
        project_id=project.id,
        tag="PDU-3",
        name="Power distribution unit PDU-3 (proposed, incomplete submittal)",
        discipline=Discipline.ELECTRICAL,
        configuration=EquipmentConfiguration(
            manufacturer="Kestrel Energy",
            model_number="KE-2100",
            equipment_type="power_distribution_unit",
            # Weight, weight basis, dimensions and current are absent from the
            # submittal on purpose — this case must land on NEEDS INFORMATION.
            voltage=Quantity(value=480, unit="V"),
            phases=3,
            evidence_ids={},
        ),
    )

    for equipment in (ch01_old, ch01_new, ch02_old, ch02_new, pdu_old, pdu_new):
        store.put(C.EQUIPMENT, equipment, project_id=project.id)

    changes = [
        EquipmentChange(
            project_id=project.id,
            title="Chiller substitution - VX-1150 offered for NT-1100",
            reason="Original model quoted at a 26-week lead time; contractor proposes an "
            "alternate with equivalent nameplate capacity.",
            equipment_tag="CH-01",
            site_id=sites[1].id,
            existing_equipment_id=ch01_old.id,
            proposed_equipment_id=ch01_new.id,
            submitted_by="Mechanical subcontractor (synthetic)",
        ),
        EquipmentChange(
            project_id=project.id,
            title="Fan-wall unit revision - HC-560A supersedes HC-560",
            reason="Manufacturer running change; same series, minor coil revision.",
            equipment_tag="CH-02",
            existing_equipment_id=ch02_old.id,
            proposed_equipment_id=ch02_new.id,
            submitted_by="Manufacturer notice (synthetic)",
        ),
        EquipmentChange(
            project_id=project.id,
            title="PDU substitution - KE-2100 offered for FP-2000",
            reason="Alternate vendor proposed; submittal received without physical or "
            "electrical data sheets.",
            equipment_tag="PDU-3",
            existing_equipment_id=pdu_old.id,
            proposed_equipment_id=pdu_new.id,
            submitted_by="Electrical subcontractor (synthetic)",
        ),
    ]
    for change in changes:
        store.put(C.CHANGES, change, project_id=project.id)

    assumptions = [
        Assumption(
            project_id=project.id,
            statement="Roof dunnage at CH-01 is designed for a 4,850 kg operating weight per unit",
            discipline=Discipline.STRUCTURAL,
            depends_on_fields=["weight", "support_point_load_max"],
            equipment_tag="CH-01",
        ),
        Assumption(
            project_id=project.id,
            statement="CH-01 feeder and protection are sized for 265 A MCA / 350 A MOCP",
            discipline=Discipline.ELECTRICAL,
            depends_on_fields=["mca", "mocp", "full_load_amps", "voltage", "phases"],
            equipment_tag="CH-01",
        ),
        Assumption(
            project_id=project.id,
            statement="Chilled-water plant N+1 redundancy assumes 1,050 kW per chiller at 35 degC ambient",
            discipline=Discipline.MECHANICAL,
            depends_on_fields=["cooling_capacity", "rating_conditions", "site_compatibility"],
            equipment_tag="CH-01",
        ),
        Assumption(
            project_id=project.id,
            statement="Refrigerant monitoring is sized for a 210 kg R-134a charge",
            discipline=Discipline.MECHANICAL,
            depends_on_fields=["refrigerant_type", "refrigerant_charge"],
            equipment_tag="CH-01",
        ),
        Assumption(
            project_id=project.id,
            statement="Crane pick radius and roof opening accommodate a 6.8 m long unit",
            discipline=Discipline.INSTALLATION_LOGISTICS,
            depends_on_fields=["length", "width", "height", "footprint_area"],
            equipment_tag="CH-01",
        ),
        Assumption(
            project_id=project.id,
            statement="BMS points list and sequences match the Northwind NT-1100 controller",
            discipline=Discipline.CONTROLS,
            depends_on_fields=["model_identity", "configuration_comparability"],
            equipment_tag="CH-01",
        ),
        Assumption(
            project_id=project.id,
            statement="PDU-3 housekeeping pad is designed for the existing 1,850 kg unit",
            discipline=Discipline.STRUCTURAL,
            depends_on_fields=["weight", "support_point_load_max"],
            equipment_tag="PDU-3",
        ),
    ]
    for assumption in assumptions:
        store.put(C.ASSUMPTIONS, assumption, project_id=project.id)

    log.info(
        "seed complete",
        extra={
            "project_id": project.id,
            "sites": len(sites),
            "changes": len(changes),
            "assumptions": len(assumptions),
        },
    )
    return project


def main() -> None:
    from .logging_conf import configure_logging

    parser = argparse.ArgumentParser(description="Seed the demo database")
    parser.add_argument("--reset", action="store_true", help="wipe existing data first")
    args = parser.parse_args()
    configure_logging(get_settings().log_level)
    project = seed(reset=True if args.reset else True)
    print(f"Seeded demo project {project.id}: {project.name}")
    print(f"Database: {get_settings().db_path}")


if __name__ == "__main__":
    main()
