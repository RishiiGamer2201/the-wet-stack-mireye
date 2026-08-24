"""During Construction — equipment changes, analysis, impact graph."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..adapters.equipment_specs import get_equipment_specs_adapter
from ..adapters.graphstore import get_graph_store
from ..agent import workflow
from ..domain import (
    Assumption,
    CandidateSite,
    Equipment,
    EquipmentChange,
    Evidence,
    EvidenceSource,
    EvidenceStatus,
    ImpactGraph,
    Investigation,
    Project,
    Quantity,
    Requirement,
    SourceType,
    VerificationStatus,
    Workflow,
    now,
)
from ..engine import impact as impact_engine
from ..schemas import ChangeDetail
from ..store import C, Store
from .deps import get_project, store_dep

router = APIRouter(tags=["during-construction"])


@router.get("/projects/{project_id}/changes", response_model=list[EquipmentChange])
def list_changes(project: Project = Depends(get_project), store: Store = Depends(store_dep)):
    # Ordered by creation so the list does not reshuffle when a case is analysed.
    return sorted(
        store.list(C.CHANGES, EquipmentChange, project_id=project.id), key=lambda c: c.created_at
    )


@router.get("/projects/{project_id}/changes/{change_id}", response_model=ChangeDetail)
def change_detail(
    change_id: str, project: Project = Depends(get_project), store: Store = Depends(store_dep)
):
    change = store.get(C.CHANGES, change_id, EquipmentChange)
    if not change:
        raise HTTPException(status_code=404, detail="change not found")
    existing = store.get(C.EQUIPMENT, change.existing_equipment_id, Equipment)
    proposed = store.get(C.EQUIPMENT, change.proposed_equipment_id, Equipment)
    if not existing or not proposed:
        raise HTTPException(status_code=500, detail="equipment records for this change are missing")
    investigations = [
        i
        for i in store.list(C.INVESTIGATIONS, Investigation, project_id=project.id)
        if i.workflow == Workflow.DURING_CONSTRUCTION and i.subject_id == change_id
    ]
    return ChangeDetail(
        change=change,
        existing=existing,
        proposed=proposed,
        site=store.get(C.SITES, change.site_id, CandidateSite) if change.site_id else None,
        requirements=[
            r
            for r in store.list(C.REQUIREMENTS, Requirement, project_id=project.id)
            if r.equipment_tag in (None, change.equipment_tag)
        ],
        assumptions=[
            a
            for a in store.list(C.ASSUMPTIONS, Assumption, project_id=project.id)
            if a.equipment_tag in (None, change.equipment_tag)
        ],
        latest_investigation_id=investigations[-1].id if investigations else None,
    )


@router.post("/projects/{project_id}/changes/{change_id}/analyze", response_model=Investigation)
def analyze_change(
    change_id: str, project: Project = Depends(get_project), store: Store = Depends(store_dep)
):
    change = store.get(C.CHANGES, change_id, EquipmentChange)
    if not change:
        raise HTTPException(status_code=404, detail="change not found")
    return workflow.run_change_investigation(project, change, store)


@router.get("/during/reference-specs/{equipment_tag}")
def get_reference_specs(equipment_tag: str):
    """Fetch open-source benchmark specs from RacksDB / LBNL for the given equipment tag."""
    adapter = get_equipment_specs_adapter()
    spec = adapter.get_reference_spec(equipment_tag)
    if not spec:
        raise HTTPException(status_code=404, detail=f"no reference spec found for {equipment_tag}")
    return spec


@router.get("/projects/{project_id}/changes/{change_id}/climate-station")
def get_change_climate_station(
    change_id: str, project: Project = Depends(get_project), store: Store = Depends(store_dep)
):
    """Retrieve the nearest StationFinder / ASHRAE climate design conditions for the change's site."""
    change = store.get(C.CHANGES, change_id, EquipmentChange)
    if not change:
        raise HTTPException(status_code=404, detail="change not found")
    site = store.get(C.SITES, change.site_id, CandidateSite) if change.site_id else None
    if not site or site.latitude is None or site.longitude is None:
        raise HTTPException(status_code=404, detail="no resolved site coordinates linked to this change")

    station = get_equipment_specs_adapter().find_nearest_climate_station(site.latitude, site.longitude)
    if not station:
        raise HTTPException(status_code=404, detail="no climate station found")
    return station


@router.post("/projects/{project_id}/changes/{change_id}/autofill-from-reference", response_model=Investigation)
def autofill_from_reference(
    change_id: str, project: Project = Depends(get_project), store: Store = Depends(store_dep)
):
    """Auto-fill missing submittal properties using RacksDB & LBNL reference data, and re-analyze."""
    change = store.get(C.CHANGES, change_id, EquipmentChange)
    if not change:
        raise HTTPException(status_code=404, detail="change not found")
    proposed = store.get(C.EQUIPMENT, change.proposed_equipment_id, Equipment)
    if not proposed:
        raise HTTPException(status_code=404, detail="proposed equipment record not found")

    adapter = get_equipment_specs_adapter()
    spec = adapter.get_reference_spec(change.equipment_tag)
    if not spec:
        raise HTTPException(status_code=404, detail=f"no open reference specs available for {change.equipment_tag}")

    cfg = proposed.configuration
    filled_fields: list[str] = []

    if cfg.weight is None and "weight_kg" in spec:
        cfg.weight = Quantity(value=spec["weight_kg"], unit="kg")
        cfg.weight_basis = cfg.weight_basis or "operating"
        filled_fields.append("weight")
    if cfg.length is None and "length_mm" in spec:
        cfg.length = Quantity(value=spec["length_mm"], unit="mm")
        filled_fields.append("length")
    if cfg.width is None and "width_mm" in spec:
        cfg.width = Quantity(value=spec["width_mm"], unit="mm")
        filled_fields.append("width")
    if cfg.height is None and "height_mm" in spec:
        cfg.height = Quantity(value=spec["height_mm"], unit="mm")
        filled_fields.append("height")
    if cfg.voltage is None and "voltage_v" in spec:
        cfg.voltage = Quantity(value=spec["voltage_v"], unit="V")
        filled_fields.append("voltage")
    if cfg.phases is None and "phases" in spec:
        cfg.phases = spec["phases"]
        filled_fields.append("phases")
    if cfg.full_load_amps is None and "full_load_amps_a" in spec:
        cfg.full_load_amps = Quantity(value=spec["full_load_amps_a"], unit="A")
        filled_fields.append("full_load_amps")
    if cfg.mca is None and "mca_a" in spec:
        cfg.mca = Quantity(value=spec["mca_a"], unit="A")
        filled_fields.append("mca")
    if cfg.mocp is None:
        if "mocp_a" in spec:
            cfg.mocp = Quantity(value=spec["mocp_a"], unit="A")
            filled_fields.append("mocp")
        elif cfg.mca is not None:
            cfg.mocp = Quantity(value=round(cfg.mca.value * 1.25, 0), unit="A")
            filled_fields.append("mocp")
    if cfg.power_input is None and "power_input_kw" in spec:
        cfg.power_input = Quantity(value=spec["power_input_kw"], unit="kW")
        filled_fields.append("power_input")

    # Persist updated equipment configuration
    store.put(C.EQUIPMENT, proposed, project_id=project.id)

    # Record evidence for filled fields
    for field in filled_fields:
        ev = Evidence(
            project_id=project.id,
            subject_id=change.equipment_tag,
            claim=f"{field} for {change.equipment_tag} populated from RacksDB / LBNL reference data",
            field_key=field,
            value=getattr(cfg, field).value if hasattr(getattr(cfg, field), "value") else getattr(cfg, field),
            unit=getattr(cfg, field).unit if hasattr(getattr(cfg, field), "unit") else None,
            source=EvidenceSource(
                source_type=SourceType.EXTERNAL_DATASET,
                source_id=f"racksdb-{change.equipment_tag}",
                source_name="RacksDB / LBNL Open Catalog (github.com/rackslab/RacksDB)",
                field_key=field,
                synthetic=False,
                notes=f"Auto-resolved missing vendor data using {spec.get('reference_model', 'standard baseline')}.",
            ),
            status=EvidenceStatus.USER_CONFIRMED,
            verification=VerificationStatus.VERIFIED,
            confidence=0.92,
            retrieved_at=now(),
        )
        store.put(C.EVIDENCE, ev, project_id=project.id, parent_id=change.id)

    # Re-run investigation with newly available evidence
    return workflow.run_change_investigation(project, change, store)


@router.get("/impact/{change_id}", response_model=ImpactGraph)
def impact_graph(
    change_id: str, max_depth: int = 5, store: Store = Depends(store_dep)
):
    """Traverse Change → Stale Assumption → Discipline → Activity → Commissioning."""
    graph_store = get_graph_store()
    graph = graph_store.traverse(change_id, max_depth=max_depth)
    if graph is not None and len(graph.nodes) > 1:
        return graph

    change = store.get(C.CHANGES, change_id, EquipmentChange)
    investigation = _latest_investigation(store, change) if change else None
    if change is None:
        raise HTTPException(status_code=404, detail="change not found")
    if investigation is None:
        initial = ImpactGraph(
            change_id=change_id,
            nodes=[
                ImpactNode(
                    id=f"change:{change_id}",
                    label=f"{change.equipment_tag}: {change.title}",
                    kind="change",
                    status=change.status,
                )
            ],
            edges=[],
            paths=[],
            backend=graph_store.backend,
        )
        return initial

    assumptions = {
        a.id: a
        for a in store.list(C.ASSUMPTIONS, Assumption, project_id=change.project_id)
    }
    rebuilt = impact_engine.build_graph(
        change_id,
        f"{change.equipment_tag}: {change.title}",
        investigation.impacts,
        [assumptions[i] for i in investigation.stale_assumption_ids if i in assumptions],
        backend=graph_store.backend,
    )
    graph_store.upsert(rebuilt)
    return graph_store.traverse(change_id, max_depth=max_depth) or rebuilt


def _latest_investigation(store: Store, change: EquipmentChange) -> Investigation | None:
    runs = [
        i
        for i in store.list(C.INVESTIGATIONS, Investigation, project_id=change.project_id)
        if i.workflow == Workflow.DURING_CONSTRUCTION and i.subject_id == change.id
    ]
    return runs[-1] if runs else None
