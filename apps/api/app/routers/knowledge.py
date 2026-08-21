import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..adapters.llm import get_llm
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
    AdvisorChatRequest,
    AdvisorChatResponse,
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

SENIOR_CIVIL_EPC_SYSTEM_PROMPT = """You are a Principal Civil, Structural, and EPC Critical Infrastructure Engineer with over 25 years of hands-on experience designing, procuring, permitting, and constructing hyperscale Tier III and Tier IV data center campuses worldwide.

STRICT DOMAIN RESTRICTIONS & SCOPE:
1. You STRICTLY answer questions relating to data center engineering, civil & structural design, power/substation sizing, cooling/HVAC systems (air-cooled, closed-loop, evaporative chillers), geotechnical soil bearing capacity, seismic PGA & liquefaction, FEMA flood plains & stormwater hydrology, wetland environmental permitting, parcel grading (cut & fill), and EPC construction execution.
2. If a user asks about anything unrelated to data centers, civil/structural engineering, or critical facilities (e.g., general programming, cooking, personal advice, non-construction topics), you MUST decline firmly and politely redirect back to data center civil and EPC engineering.
3. Tone: Direct, authoritative, highly technical, analytical, professional, and practical. Reference relevant engineering standards where appropriate (ASHRAE TC 9.9, ASCE 7-22, IBC, AHRI 550/590, NFPA 75/76, IEEE 1584, Uptime Institute Tier Standards).
4. When evaluating candidate sites or answering queries:
   - Identify what is wrong, problematic, or high-risk (e.g., excessive slope requiring retaining walls, high seismic PGA increasing anchor load & structural framing costs, water stress in dry basins, lack of diverse substation feeds, flood plain proximity).
   - Propose clear, actionable civil and EPC engineering improvements and mitigations (e.g., deep driven pile foundations, raised equipment pad elevations above 500-year flood levels, closed-loop adiabatic cooling, dual 230kV ring-bus interconnection, on-site battery ESS/generator reserve, stormwater detention basins).
   - Leverage any provided physical Mireye telemetry (coordinates, elevation, seismic hazard, water index, grid distance) directly in your analysis.
"""


def _build_advisor_prompt(
    payload: AdvisorChatRequest,
    project: Project,
    store: Store,
    mireye_client,
) -> tuple[str, str, list[str]]:
    """Gathers project, site, and live Mireye physical telemetry to build context."""
    context_lines = [f"Project: {project.name} (Client: {project.client or 'Self'}, Region: {project.region or 'Global'})"]
    if project.targets and project.targets.it_load_mw:
        context_lines.append(f"Target IT Load: {project.targets.it_load_mw} MW")

    site_name = "General Project Scope"
    lat, lon = None, None

    if payload.site_id:
        site = store.get(C.SITES, payload.site_id, CandidateSite)
        if site:
            site_name = site.name
            lat, lon = site.latitude, site.longitude
            context_lines.append(f"Active Site: {site.name} (Address: {site.address or 'N/A'}, Lat: {site.latitude}, Lon: {site.longitude}, Area: {site.area_hectares or 'N/A'} ha)")
            if site.notes:
                context_lines.append(f"Site Notes/Specs: {site.notes}")
            # Fetch recent evidence stored for this site
            evidence_list = store.list(
                C.EVIDENCE, Evidence, project_id=project.id, parent_id=site.id
            )
            if evidence_list:
                ev_summary = ", ".join(f"{e.field_key}: {e.value} {e.unit or ''}" for e in evidence_list[:15])
                context_lines.append(f"Stored Physical Telemetry: {ev_summary}")

    if payload.site_context:
        ctx_dump = ", ".join(f"{k}: {v}" for k, v in payload.site_context.items() if v is not None)
        context_lines.append(f"Discovery Context: {ctx_dump}")

    # Query Mireye live for physical context if available
    mireye_facts = []
    if mireye_client:
        try:
            # If coordinates are available or mentioned in question, query Mireye
            mireye_res = mireye_client.ask(payload.message, lat, lon)
            if mireye_res and mireye_res.answer:
                mireye_facts.append(f"Mireye Physical Data: {mireye_res.answer}")
        except Exception as exc:
            log.info("mireye live query skipped in advisor", extra={"error": str(exc)})

    if mireye_facts:
        context_lines.append("=== LIVE MIREYE TELEMETRY ===")
        context_lines.extend(mireye_facts)

    # Include recent chat history
    history_lines = []
    if payload.history:
        for msg in payload.history[-4:]:
            role = "User" if msg.get("role") == "user" else "Senior Civil PE"
            history_lines.append(f"{role}: {msg.get('content', '')}")

    context_text = "\n".join(context_lines)
    history_text = "\n".join(history_lines)
    if history_text:
        history_text = f"\nRECENT CONVERSATION:\n{history_text}\n"

    user_prompt = f"""CONTEXT:
{context_text}
{history_text}
USER QUESTION:
{payload.message}

Please provide your senior civil and EPC engineering assessment, identifying potential issues or risks, and recommending actionable improvements/mitigations."""

    improvements = [
        "Conduct geotechnical CPT borings for soil bearing verification",
        "Establish Finished Floor Elevation (FFE) at minimum BFE + 3.0 ft",
        "Specify closed-loop adiabatic cooling to eliminate municipal water dependency",
        "Secure dual-diverse 230kV utility transmission feeds with on-site substation yard",
    ]

    return user_prompt, site_name, improvements


@router.post("/projects/{project_id}/advisor/chat", response_model=AdvisorChatResponse)
def advisor_chat(
    payload: AdvisorChatRequest,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    """Consult the Senior Civil & Structural EPC Engineer AI Advisor (Synchronous)."""
    llm = get_llm()
    mireye_client = get_mireye_client()
    user_prompt, site_name, improvements = _build_advisor_prompt(payload, project, store, mireye_client)

    reply = None
    if llm and llm.available:
        reply = llm.complete(system=SENIOR_CIVIL_EPC_SYSTEM_PROMPT, user=user_prompt, max_tokens=1200)

    if not reply:
        q_lower = payload.message.lower()
        if "flood" in q_lower or "water" in q_lower:
            reply = f"**Senior Civil EPC Assessment for {site_name}:**\n\n1. **Hydrology & Flood Risk**: Check FEMA 100-yr and 500-yr base flood elevations (BFE). All critical switchgear, diesel generators, and IT floor slabs must be established at minimum BFE + 3.0 ft finished floor elevation (FFE).\n2. **Stormwater & Drainage**: Require on-site retention/detention basins designed for a 100-year, 24-hour storm event with redundant culvert outfalls.\n3. **Cooling Infrastructure**: In water-stressed basins, specify closed-loop air-cooled chillers with adiabatic pre-cooling pads rather than open evaporative cooling towers."
        elif "seismic" in q_lower or "earthquake" in q_lower:
            reply = f"**Senior Civil EPC Assessment for {site_name}:**\n\n1. **Seismic Hazard**: Review ASCE 7-22 Peak Ground Acceleration (PGA) and Risk Category IV design parameters.\n2. **Structural Anchoring & Base Isolation**: Heavy equipment (chillers, 2.5 MW generators, 480V UPS battery skids) requires OSHPD/IBC pre-approved seismic snubber mounts and positive bolting into 12\"+ post-tensioned reinforced concrete slabs.\n3. **Soil Geotechnics**: Perform deep borehole CPT testing to rule out liquefaction potential in alluvial soil layers."
        elif "power" in q_lower or "grid" in q_lower or "substation" in q_lower:
            reply = f"**Senior Civil EPC Assessment for {site_name}:**\n\n1. **Grid Interconnection**: Target dual-fed, diverse 115kV or 230kV transmission lines from separate utility substations with automated high-speed transfer switching (ATS/STS).\n2. **Substation Civil Yard**: Allocate minimum 3 to 5 acres for dedicated on-site step-down transformers (230kV to 34.5kV/13.8kV) with concrete blast deflection containment walls and oil-catchment fire basins.\n3. **Reserve Generation**: Plan N+1 or 2N diesel/HVO generator enclosures with 48 to 72 hours of on-site bulk fuel storage capacity."
        else:
            reply = f"**Senior Civil EPC Assessment for {site_name}:**\n\nFrom a master-planning and EPC constructability perspective:\n1. **Site Civil Grading & Cut/Fill**: Minimize cut-and-fill imbalance across the parcel. Any slope exceeding 3% will require engineered tiered pads and soil retaining walls, adding $1.2M–$3.5M to civil site preparation.\n2. **Geotechnical Foundations**: Prioritize drilled shaft piers or spread footings bearing on minimum 4,000 psf allowable soil capacity to support dense server rack column point loads (up to 250–350 lbs/sq ft).\n3. **Permitting & Utility Easements**: Secure heavy-haul transportation routing for oversized electrical transformers and verify local stormwater/wetland permits with county civil authorities early."

    return AdvisorChatResponse(
        reply=reply,
        site_name=site_name,
        engineer_role="Principal Civil & Structural EPC Engineer",
        suggested_improvements=improvements,
        mode=getattr(llm, "name", "deterministic"),
        disclaimer="Advisory engineering opinion. Certified drawings and structural calculations require PE stamp.",
    )


@router.post("/projects/{project_id}/advisor/chat/stream")
def advisor_chat_stream(
    payload: AdvisorChatRequest,
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    """Stream response from Senior Civil EPC Advisor with Mireye telemetry integration."""
    llm = get_llm()
    mireye_client = get_mireye_client()
    user_prompt, site_name, improvements = _build_advisor_prompt(payload, project, store, mireye_client)

    def event_stream():
        has_streamed = False
        if llm and llm.available:
            try:
                for chunk in llm.complete_stream(system=SENIOR_CIVIL_EPC_SYSTEM_PROMPT, user=user_prompt, max_tokens=1200):
                    if chunk:
                        has_streamed = True
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            except Exception as exc:
                log.warning("error in advisor complete_stream", extra={"error": str(exc)})

        # If LLM didn't stream or is not available, stream the deterministic fallback chunk-by-chunk
        if not has_streamed:
            q_lower = payload.message.lower()
            if "flood" in q_lower or "water" in q_lower:
                text = f"**Senior Civil EPC Assessment for {site_name}:**\n\n1. **Hydrology & Flood Risk**: Check FEMA 100-yr and 500-yr base flood elevations (BFE). All critical switchgear, diesel generators, and IT floor slabs must be established at minimum BFE + 3.0 ft finished floor elevation (FFE).\n2. **Stormwater & Drainage**: Require on-site retention/detention basins designed for a 100-year, 24-hour storm event with redundant culvert outfalls.\n3. **Cooling Infrastructure**: In water-stressed basins, specify closed-loop air-cooled chillers with adiabatic pre-cooling pads rather than open evaporative cooling towers."
            elif "seismic" in q_lower or "earthquake" in q_lower:
                text = f"**Senior Civil EPC Assessment for {site_name}:**\n\n1. **Seismic Hazard**: Review ASCE 7-22 Peak Ground Acceleration (PGA) and Risk Category IV design parameters.\n2. **Structural Anchoring & Base Isolation**: Heavy equipment (chillers, 2.5 MW generators, 480V UPS battery skids) requires OSHPD/IBC pre-approved seismic snubber mounts and positive bolting into 12\"+ post-tensioned reinforced concrete slabs.\n3. **Soil Geotechnics**: Perform deep borehole CPT testing to rule out liquefaction potential in alluvial soil layers."
            elif "power" in q_lower or "grid" in q_lower or "substation" in q_lower:
                text = f"**Senior Civil EPC Assessment for {site_name}:**\n\n1. **Grid Interconnection**: Target dual-fed, diverse 115kV or 230kV transmission lines from separate utility substations with automated high-speed transfer switching (ATS/STS).\n2. **Substation Civil Yard**: Allocate minimum 3 to 5 acres for dedicated on-site step-down transformers (230kV to 34.5kV/13.8kV) with concrete blast deflection containment walls and oil-catchment fire basins.\n3. **Reserve Generation**: Plan N+1 or 2N diesel/HVO generator enclosures with 48 to 72 hours of on-site bulk fuel storage capacity."
            else:
                text = f"**Senior Civil EPC Assessment for {site_name}:**\n\nFrom a master-planning and EPC constructability perspective:\n1. **Site Civil Grading & Cut/Fill**: Minimize cut-and-fill imbalance across the parcel. Any slope exceeding 3% will require engineered tiered pads and soil retaining walls, adding $1.2M–$3.5M to civil site preparation.\n2. **Geotechnical Foundations**: Prioritize drilled shaft piers or spread footings bearing on minimum 4,000 psf allowable soil capacity to support dense server rack column point loads (up to 250–350 lbs/sq ft).\n3. **Permitting & Utility Easements**: Secure heavy-haul transportation routing for oversized electrical transformers and verify local stormwater/wetland permits with county civil authorities early."

            # Emit in readable words
            words = text.split(" ")
            for i in range(0, len(words), 3):
                chunk = " ".join(words[i:i+3]) + " "
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                time.sleep(0.04)

        # End of stream event with metadata
        yield f"data: {json.dumps({'done': True, 'improvements': improvements, 'mode': getattr(llm, 'name', 'deterministic')})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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

    upload_dir = settings.upload_dir.resolve()
    target = (upload_dir / f"{project.id}_{filename}").resolve()
    # `safe_filename` already removed every path separator; this second check is
    # the one that actually touches the filesystem, so it is the one that must be
    # true. Uploads are ephemeral on Render — see docs/deployment.md.
    if target.parent != upload_dir:
        log.error("upload path escaped the upload directory", extra={"filename": filename})
        raise HTTPException(status_code=422, detail="invalid filename")
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
