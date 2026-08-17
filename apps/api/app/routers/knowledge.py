"""Documents, requirements, retrieval, evidence, information gaps and Mireye passthrough."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..adapters.mireye import MireyeError, get_mireye_client
from ..adapters.vectorstore import get_index
from ..config import get_settings
from ..domain import (
    Assumption,
    CandidateSite,
    DocumentChunk,
    DocumentKind,
    Evidence,
    GapStatus,
    InformationGap,
    Project,
    ProjectDocument,
    Requirement,
)
from ..engine.decisions import SAFETY_CAVEAT
from ..fields import FIELDS
from ..schemas import (
    AskRequest,
    AskResponse,
    GapUpdate,
    RequirementUpdate,
    SearchResponse,
    UploadResponse,
)
from ..services.ingest import IngestionError, ingest_pdf, safe_filename, validate_upload
from ..store import C, Store
from .deps import get_project, store_dep

log = logging.getLogger("knowledge")
router = APIRouter(tags=["knowledge"])


@router.get("/mireye/fields")
def mireye_fields():
    """The cached Mireye field catalog. The agent may only request these keys."""
    client = get_mireye_client()
    try:
        catalog = client.meta_fields()
    except MireyeError as exc:
        log.warning("field catalog unavailable", extra={"error": str(exc)})
        catalog = [
            {"key": f.key, "label": f.label, "unit": f.unit, "dimension": f.dimension.value}
            for f in FIELDS
        ]
    return {"mode": getattr(client, "mode", "mock"), "count": len(catalog), "fields": catalog}


@router.post("/projects/{project_id}/ask", response_model=AskResponse)
def ask_mireye(
    payload: AskRequest,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    """Exploratory question (Mireye /v1/ask). Never used for scoring or calculation."""
    client = get_mireye_client()
    lat = lon = None
    if payload.site_id:
        site = store.get(C.SITES, payload.site_id, CandidateSite)
        if not site:
            raise HTTPException(status_code=404, detail="site not found")
        lat, lon = site.latitude, site.longitude
    try:
        result = client.ask(payload.question, lat, lon)
    except MireyeError as exc:
        raise HTTPException(status_code=502, detail=f"Mireye ask failed: {exc}") from exc
    return AskResponse(
        answer=result.answer,
        citations=result.citations,
        confidence=result.confidence,
        mode=result.mode,
        disclaimer="Exploratory answer. Scores and engineering checks use /v1/fetch fields only. "
        + SAFETY_CAVEAT,
    )


@router.get("/projects/{project_id}/documents", response_model=list[ProjectDocument])
def list_documents(project: Project = Depends(get_project), store: Store = Depends(store_dep)):
    return store.list(C.DOCUMENTS, ProjectDocument, project_id=project.id)


@router.post("/projects/{project_id}/documents", response_model=UploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    kind: str = Form(default=DocumentKind.OTHER.value),
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    settings = get_settings()
    data = await file.read()
    # The client controls the filename, so it is reduced to a bare name before it
    # is ever joined onto a path — `../../x.pdf` must not escape the upload dir.
    filename = safe_filename(file.filename or "upload.pdf")
    try:
        validate_upload(filename, file.content_type or "", len(data))
        DocumentKind(kind)
    except IngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"unknown document kind '{kind}'; allowed: "
            + ", ".join(k.value for k in DocumentKind),
        ) from exc

    target = settings.upload_dir / f"{project.id}_{filename}"
    target.write_bytes(data)
    try:
        document, chunks, requirements = ingest_pdf(
            store, project.id, target, filename, kind=DocumentKind(kind)
        )
    except IngestionError as exc:
        target.unlink(missing_ok=True)  # do not keep a file we could not read
        raise HTTPException(
            status_code=422, detail=f"extraction failed for {filename}: {exc}"
        ) from exc
    return UploadResponse(
        document=document,
        chunk_count=len(chunks),
        requirements=requirements,
        warning=document.extraction_error,
    )


@router.get("/projects/{project_id}/documents/{document_id}/chunks", response_model=list[DocumentChunk])
def document_chunks(
    document_id: str, project: Project = Depends(get_project), store: Store = Depends(store_dep)
):
    chunks = store.list(C.CHUNKS, DocumentChunk, project_id=project.id, parent_id=document_id)
    for chunk in chunks:
        chunk.embedding = None  # keep the payload small; embeddings stay server-side
    return chunks


@router.get("/projects/{project_id}/requirements", response_model=list[Requirement])
def list_requirements(
    equipment_tag: str | None = None,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    items = store.list(C.REQUIREMENTS, Requirement, project_id=project.id)
    if equipment_tag:
        items = [r for r in items if r.equipment_tag in (None, equipment_tag)]
    return items


@router.patch("/projects/{project_id}/requirements/{requirement_id}", response_model=Requirement)
def confirm_requirement(
    requirement_id: str,
    payload: RequirementUpdate,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    """Human confirmation / correction of an extracted requirement (diagram §6B)."""
    requirement = store.get(C.REQUIREMENTS, requirement_id, Requirement)
    if not requirement or requirement.project_id != project.id:
        raise HTTPException(status_code=404, detail="requirement not found")
    if payload.value is not None and payload.value != requirement.value:
        requirement.corrected_from = str(requirement.value)
        requirement.value = payload.value
    if payload.unit is not None:
        requirement.unit = payload.unit
    if payload.condition is not None:
        requirement.condition = payload.condition
    if payload.equipment_tag is not None:
        requirement.equipment_tag = payload.equipment_tag
    requirement.confirmed = payload.confirmed
    requirement.confirmed_by = payload.confirmed_by or "engineer"
    requirement.confidence = 0.99 if payload.confirmed else requirement.confidence

    if requirement.evidence_id:
        evidence = store.get(C.EVIDENCE, requirement.evidence_id, Evidence)
        if evidence:
            from ..domain import EvidenceStatus, VerificationStatus

            evidence.value = requirement.value
            evidence.unit = requirement.unit
            evidence.status = EvidenceStatus.USER_CONFIRMED
            evidence.verification = VerificationStatus.VERIFIED
            evidence.confidence = requirement.confidence
            store.put(C.EVIDENCE, evidence, project_id=project.id)
    store.put(C.REQUIREMENTS, requirement, project_id=project.id, parent_id=requirement.document_id)
    return requirement


@router.get("/projects/{project_id}/search", response_model=SearchResponse)
def search(q: str, k: int = 5, project: Project = Depends(get_project)):
    if len(q.strip()) < 2:
        raise HTTPException(status_code=422, detail="query must be at least 2 characters")
    index = get_index()
    return SearchResponse(query=q, backend=index.backend, results=index.search(project.id, q, k=k))


@router.get("/projects/{project_id}/evidence", response_model=list[Evidence])
def list_evidence(
    subject_id: str | None = None,
    field_key: str | None = None,
    status: str | None = None,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    items = store.list(C.EVIDENCE, Evidence, project_id=project.id)
    if subject_id:
        items = [e for e in items if e.subject_id == subject_id]
    if field_key:
        items = [e for e in items if e.field_key == field_key]
    if status:
        items = [e for e in items if e.status.value == status]
    return items


@router.get("/evidence/{evidence_id}", response_model=Evidence)
def get_evidence(evidence_id: str, store: Store = Depends(store_dep)):
    evidence = store.get(C.EVIDENCE, evidence_id, Evidence)
    if not evidence:
        raise HTTPException(status_code=404, detail="evidence not found")
    return evidence


@router.get("/projects/{project_id}/gaps", response_model=list[InformationGap])
def list_gaps(
    status: str | None = None,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    items = store.list(C.GAPS, InformationGap, project_id=project.id)
    if status:
        items = [g for g in items if g.status.value == status]
    return items


@router.patch("/projects/{project_id}/gaps/{gap_id}", response_model=InformationGap)
def update_gap(
    gap_id: str,
    payload: GapUpdate,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    gap = store.get(C.GAPS, gap_id, InformationGap)
    if not gap or gap.project_id != project.id:
        raise HTTPException(status_code=404, detail="gap not found")
    try:
        gap.status = GapStatus(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid status '{payload.status}'") from exc
    store.put(C.GAPS, gap, project_id=project.id)
    return gap


@router.get("/projects/{project_id}/assumptions", response_model=list[Assumption])
def list_assumptions(project: Project = Depends(get_project), store: Store = Depends(store_dep)):
    return store.list(C.ASSUMPTIONS, Assumption, project_id=project.id)


@router.get("/sample-documents")
def sample_documents():
    """The synthetic PDFs shipped with the demo, for the upload walkthrough."""
    sample_dir = Path(__file__).resolve().parents[4] / "sample_data"
    return {
        "directory": str(sample_dir),
        "files": sorted(p.name for p in sample_dir.glob("*.pdf")) if sample_dir.exists() else [],
        "note": "All sample documents are synthetic demonstration data.",
    }
