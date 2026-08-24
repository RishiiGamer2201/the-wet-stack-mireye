"""During Construction — equipment changes, analysis, impact graph."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..adapters.graphstore import get_graph_store
from ..agent import workflow
from ..domain import (
    Assumption,
    CandidateSite,
    Equipment,
    EquipmentChange,
    ImpactGraph,
    Investigation,
    Project,
    Requirement,
    Workflow,
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


@router.get("/impact/{change_id}", response_model=ImpactGraph)
def impact_graph(
    change_id: str, max_depth: int = 5, store: Store = Depends(store_dep)
):
    """Traverse Change → Stale Assumption → Discipline → Activity → Commissioning.

    The in-memory graph store is volatile, so a restart would otherwise turn an
    analysed change with six impacts into "no downstream impact". The analysis
    result itself is durable, so the graph is rebuilt from it on a miss rather
    than reporting an absence that is not true.
    """
    graph_store = get_graph_store()
    graph = graph_store.traverse(change_id, max_depth=max_depth)
    if graph is not None and len(graph.nodes) > 1:
        return graph

    change = store.get(C.CHANGES, change_id, EquipmentChange)
    investigation = _latest_investigation(store, change) if change else None
    if change is None:
        raise HTTPException(status_code=404, detail="change not found")
    if investigation is None:
        # If no investigation yet, return an initial single-node graph for the change
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
