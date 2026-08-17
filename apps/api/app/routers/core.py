"""Health, metadata, projects and demo-data administration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..adapters.graphstore import get_graph_store
from ..adapters.mireye import get_mireye_client
from ..adapters.vectorstore import get_index
from ..config import get_settings
from ..domain import (
    CandidateSite,
    EquipmentChange,
    Evidence,
    GapStatus,
    InformationGap,
    Project,
    ProjectDocument,
    Requirement,
)
from ..engine.decisions import SAFETY_CAVEAT
from ..fields import DEFAULT_DIMENSION_WEIGHTS, DIMENSION_LABELS, FIELDS
from ..schemas import (
    HealthResponse,
    MetaResponse,
    ProjectCreate,
    ProjectDetail,
    ProjectUpdate,
    ReadyResponse,
    SeedResponse,
)
from ..store import C, Store
from .deps import get_project, store_dep

router = APIRouter(tags=["core"])

VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=VERSION)


@router.get("/ready", response_model=ReadyResponse)
def ready(store: Store = Depends(store_dep)) -> ReadyResponse:
    checks: dict[str, str] = {}
    ok = True
    try:
        store.count(C.PROJECTS)
        checks["store"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["store"] = f"error: {exc}"
        ok = False
    try:
        client = get_mireye_client()
        checks["mireye"] = f"ok ({len(client.meta_fields())} fields, mode={client.mode})"
    except Exception as exc:  # noqa: BLE001
        checks["mireye"] = f"degraded: {exc}"
    try:
        checks["graph"] = f"ok ({get_graph_store().backend})"
    except Exception as exc:  # noqa: BLE001
        checks["graph"] = f"degraded: {exc}"
    checks["vector"] = f"ok ({get_index().backend})"
    checks["seeded"] = "yes" if store.count(C.PROJECTS) else "no — POST /api/admin/seed"
    return ReadyResponse(ready=ok, checks=checks)


@router.get("/meta", response_model=MetaResponse)
def meta() -> MetaResponse:
    settings = get_settings()
    # Report the adapters actually in use, not just what configuration asked for:
    # a configured service that failed to connect has already fallen back.
    services = settings.service_modes()
    services["mireye"] = getattr(get_mireye_client(), "mode", services["mireye"])
    services["graph"] = get_graph_store().backend
    services["vector"] = get_index().backend
    return MetaResponse(
        app_name=settings.app_name,
        environment=settings.environment,
        demo_mode=settings.demo_mode,
        services=services,
        mireye_field_count=len(FIELDS),
        dimension_weights={k.value: v for k, v in DEFAULT_DIMENSION_WEIGHTS.items()},
        dimension_labels={k.value: v for k, v in DIMENSION_LABELS.items()},
        disclaimer=SAFETY_CAVEAT,
    )


@router.get("/projects", response_model=list[Project])
def list_projects(store: Store = Depends(store_dep)) -> list[Project]:
    return store.list(C.PROJECTS, Project)


@router.post("/projects", response_model=Project, status_code=201)
def create_project(payload: ProjectCreate, store: Store = Depends(store_dep)) -> Project:
    project = Project(
        name=payload.name,
        client=payload.client,
        description=payload.description,
        region=payload.region,
        targets=payload.targets,
        dimension_weights=payload.dimension_weights or dict(DEFAULT_DIMENSION_WEIGHTS),
        synthetic=False,
    )
    store.put(C.PROJECTS, project, project_id=project.id)
    return project


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def project_detail(
    project: Project = Depends(get_project), store: Store = Depends(store_dep)
) -> ProjectDetail:
    gaps = store.list(C.GAPS, InformationGap, project_id=project.id)
    return ProjectDetail(
        project=project,
        sites=store.list(C.SITES, CandidateSite, project_id=project.id),
        documents=store.list(C.DOCUMENTS, ProjectDocument, project_id=project.id),
        # Same creation order as GET /changes, so the UI does not preselect a
        # different case than the list shows once a change has been analysed.
        changes=sorted(
            store.list(C.CHANGES, EquipmentChange, project_id=project.id),
            key=lambda c: c.created_at,
        ),
        requirement_count=len(store.list(C.REQUIREMENTS, Requirement, project_id=project.id)),
        evidence_count=len(store.list(C.EVIDENCE, Evidence, project_id=project.id)),
        open_gap_count=sum(1 for g in gaps if g.status != GapStatus.RESOLVED),
    )


@router.patch("/projects/{project_id}", response_model=Project)
def update_project(
    payload: ProjectUpdate,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
) -> Project:
    if payload.targets is not None:
        project.targets = payload.targets
    if payload.dimension_weights is not None:
        if any(v < 0 for v in payload.dimension_weights.values()):
            raise HTTPException(status_code=422, detail="dimension weights must be >= 0")
        project.dimension_weights = payload.dimension_weights
    store.put(C.PROJECTS, project, project_id=project.id)
    return project


@router.post("/admin/seed", response_model=SeedResponse)
def seed_demo(store: Store = Depends(store_dep)) -> SeedResponse:
    from ..seed import seed

    project = seed(store, reset=True)
    return SeedResponse(
        project_id=project.id,
        project_name=project.name,
        message="Demo data seeded. All sites, documents and equipment values are synthetic.",
    )


@router.post("/admin/reset", response_model=SeedResponse)
def reset_demo(store: Store = Depends(store_dep)) -> SeedResponse:
    store.clear()
    get_graph_store().clear()
    return SeedResponse(project_id="", project_name="", message="All data cleared.")
