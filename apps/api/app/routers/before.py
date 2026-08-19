"""Before Construction — candidate sites, investigation, ranking, what-if."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from ..adapters.mireye import MireyeError, get_mireye_client
from ..agent import workflow
from ..domain import CandidateSite, Investigation, Project, Workflow
from ..fields import UnknownFieldError
from ..schemas import (
    OverrideRequest,
    RankingRequest,
    RunSiteInvestigation,
    SiteCreate,
    WhatIfResponse,
)
from ..services import sites as site_service
from ..store import C, Store
from .deps import get_project, store_dep

router = APIRouter(prefix="/projects/{project_id}", tags=["before-construction"])


@router.get("/sites", response_model=list[CandidateSite])
def list_sites(project: Project = Depends(get_project), store: Store = Depends(store_dep)):
    return store.list(C.SITES, CandidateSite, project_id=project.id)


@router.post("/sites", response_model=CandidateSite, status_code=201)
def create_site(
    payload: SiteCreate,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    site = CandidateSite(
        project_id=project.id,
        name=payload.name,
        address=payload.address,
        latitude=payload.latitude,
        longitude=payload.longitude,
        area_hectares=payload.area_hectares,
        jurisdiction=payload.jurisdiction,
        notes=payload.notes,
        synthetic=False,
        geocode_resolution="parcel" if payload.latitude is not None else None,
    )
    if site.latitude is None:
        try:
            site_service.resolve_site_location(get_mireye_client(), site)
        except MireyeError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"geocoding failed: {exc}. Enter coordinates directly to continue.",
            ) from exc
    store.put(C.SITES, site, project_id=project.id)
    return site


@router.delete("/sites/{site_id}", status_code=204)
def delete_site(
    site_id: str, project: Project = Depends(get_project), store: Store = Depends(store_dep)
):
    site = store.get(C.SITES, site_id, CandidateSite)
    if site is None or site.project_id != project.id:
        raise HTTPException(status_code=404, detail="site not found on this project")
    store.delete(C.SITES, site_id)


@router.post("/investigations/site", response_model=Investigation)
def run_site_investigation(
    payload: RunSiteInvestigation,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    sites = store.list(C.SITES, CandidateSite, project_id=project.id)
    if payload.site_ids:
        sites = [s for s in sites if s.id in payload.site_ids]
    if not sites:
        raise HTTPException(status_code=422, detail="no candidate sites to investigate")
    # Real user-added sites come first, so they are always investigated within budget
    sites.sort(key=lambda s: (s.synthetic, s.created_at or datetime.min))
    weights = payload.weights or project.dimension_weights or None
    return workflow.run_site_investigation(project, sites, weights, store)


@router.get("/investigations", response_model=list[Investigation])
def list_investigations(
    workflow_filter: str | None = None,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    from datetime import datetime
    items = store.list(C.INVESTIGATIONS, Investigation, project_id=project.id)
    if workflow_filter:
        items = [i for i in items if i.workflow == Workflow(workflow_filter)]
    items.sort(key=lambda i: i.started_at or datetime.min, reverse=True)
    return items


@router.get("/investigations/{investigation_id}", response_model=Investigation)
def get_investigation(
    investigation_id: str,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    investigation = store.get(C.INVESTIGATIONS, investigation_id, Investigation)
    if not investigation:
        raise HTTPException(status_code=404, detail="investigation not found")
    return investigation


@router.post("/ranking", response_model=WhatIfResponse)
def recompute_ranking(
    payload: RankingRequest,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    """Deterministic re-scoring against the stored evidence — this is the what-if
    entry point for weight changes."""
    sites = store.list(C.SITES, CandidateSite, project_id=project.id)
    if payload.site_ids:
        sites = [s for s in sites if s.id in payload.site_ids]
    if not sites:
        raise HTTPException(status_code=422, detail="no candidate sites")
    baseline = site_service.score_sites(store, project, sites, project.dimension_weights or None)
    updated = site_service.score_sites(store, project, sites, payload.weights)
    explanation = []
    before = {s.site_id: s.rank for s in baseline.scores}
    for score in updated.scores:
        if before.get(score.site_id) != score.rank:
            explanation.append(
                f"{score.site_name}: rank {before.get(score.site_id)} → {score.rank} "
                f"(score {score.overall_score})"
            )
    if not explanation:
        explanation.append("Weight change did not alter the ranking order.")
    return WhatIfResponse(ranking=updated, changed_from=baseline, explanation=explanation)


@router.post("/sites/{site_id}/override", response_model=WhatIfResponse)
def override_site_value(
    site_id: str,
    payload: OverrideRequest,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    """Record a user-supplied site value as USER_CONFIRMED evidence and re-rank."""
    site = store.get(C.SITES, site_id, CandidateSite)
    if not site:
        raise HTTPException(status_code=404, detail="site not found")
    sites = store.list(C.SITES, CandidateSite, project_id=project.id)
    baseline = site_service.score_sites(store, project, sites, project.dimension_weights or None)
    try:
        site_service.override_observation(
            store,
            project,
            site,
            payload.field_key,
            payload.value,
            payload.note or "What-if override entered by the user",
        )
    except UnknownFieldError as exc:
        raise HTTPException(
            status_code=422, detail=f"unknown field '{payload.field_key}'"
        ) from exc
    updated = site_service.score_sites(store, project, sites, project.dimension_weights or None)
    before = {s.site_id: (s.rank, s.overall_score) for s in baseline.scores}
    explanation = []
    for score in updated.scores:
        prev = before.get(score.site_id)
        if prev and (prev[0] != score.rank or prev[1] != score.overall_score):
            explanation.append(
                f"{score.site_name}: score {prev[1]} → {score.overall_score}, "
                f"rank {prev[0]} → {score.rank}"
            )
    if not explanation:
        explanation.append("The override did not change any score.")
    return WhatIfResponse(ranking=updated, changed_from=baseline, explanation=explanation)
