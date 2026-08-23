import json
import logging
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..adapters.llm import get_llm
from ..adapters.mcp import get_mcp_registry
from ..adapters.mireye import MireyeError, get_mireye_client
from ..adapters.vectorstore import get_index
from ..agent.knowledge_agent import get_knowledge_agent
from ..config import get_settings
from ..domain import (
    Assumption,
    CandidateSite,
    DocumentChunk,
    DocumentKind,
    EquipmentChange,
    Evidence,
    GapStatus,
    InformationGap,
    Project,
    ProjectDocument,
    Requirement,
)
from ..engine.decisions import SAFETY_CAVEAT
from ..fields import FIELD_INDEX, FIELDS
from ..schemas import (
    AdvisorChatRequest,
    AdvisorChatResponse,
    AskRequest,
    AskResponse,
    CitationSchema,
    GapUpdate,
    KnowledgeAgentRequest,
    KnowledgeAgentResponse,
    MCPRpcRequest,
    MCPRpcResponse,
    RequirementUpdate,
    SearchResponse,
    TellMeInsightsSchema,
    ToolTraceSchema,
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



def _resolve_location(
    store: Store, project: Project, site_id: str | None
) -> tuple[float | None, float | None, str]:
    """Coordinates for a Mireye question, and the name of what they describe.

    `/v1/ask` is a question *about a place*, so it needs one. An explicit site
    wins; otherwise the project's first located candidate stands in and is named
    in the answer, so nobody reads a Cascade Flats answer as a Delta Fields one.
    A project with no located site returns no coordinates and the caller reports
    that rather than asking about nowhere.
    """
    if site_id:
        site = store.get(C.SITES, site_id, CandidateSite)
        if not site:
            raise HTTPException(status_code=404, detail="site not found")
        if site.latitude is None or site.longitude is None:
            raise HTTPException(
                status_code=422,
                detail=f"{site.name} has no resolved coordinates; geocode it first.",
            )
        return site.latitude, site.longitude, site.name

    for site in store.list(C.SITES, CandidateSite, project_id=project.id):
        if site.latitude is not None and site.longitude is not None:
            return site.latitude, site.longitude, site.name
    return None, None, project.name


def _retrieved_context(project_id: str, question: str, k: int = 4) -> tuple[str, list[dict]]:
    """Top document chunks for the question, as prompt text plus citations.

    This is what connects an uploaded PDF to the advisor: a specification that
    was ingested five seconds ago is searchable in the same request.
    """
    if len(question.strip()) < 2:
        return "", []
    try:
        hits = get_index().search(project_id, question, k=k)
    except Exception as exc:  # noqa: BLE001 - retrieval is context, never the answer
        log.warning("retrieval failed for advisor", extra={"error": str(exc)})
        return "", []
    if not hits:
        return "", []
    lines, citations = [], []
    for hit in hits:
        lines.append(f"[{hit.document_name} p.{hit.page}] {hit.text.strip()[:700]}")
        citations.append(
            {"source": hit.document_name, "detail": f"page {hit.page}", "chunk_id": hit.chunk_id}
        )
    return "\n\n".join(lines), citations


def _real_next_steps(store: Store, project: Project, site_id: str | None) -> list[str]:
    """Next steps taken from this project's own open gaps.

    The previous four suggestions were the same four strings on every question
    for every site, which reads as advice and is not. These come from gaps the
    investigation actually recorded, so an empty list means nothing is open —
    which is information too.
    """
    gaps = store.list(C.GAPS, InformationGap, project_id=project.id)
    open_gaps = [g for g in gaps if g.status != GapStatus.RESOLVED]
    if site_id:
        scoped = [g for g in open_gaps if g.subject_id == site_id]
        open_gaps = scoped or open_gaps
    # Blocking first, then whatever else is open; one line per distinct concept.
    open_gaps.sort(key=lambda g: (not g.blocking, g.field_key or ""))
    steps, seen = [], set()
    for gap in open_gaps:
        key = gap.field_key or gap.description
        if key in seen:
            continue
        seen.add(key)
        action = (gap.suggested_action.value if gap.suggested_action else "clarification_request")
        steps.append(f"{gap.description} ({action.replace('_', ' ')})")
        if len(steps) == 4:
            break
    return steps


def _deterministic_advice(question: str, site_name: str) -> str:
    """Template advice for when no model is configured.

    One copy. It used to exist twice, word for word, in the blocking and the
    streaming route, so an edit to one silently disagreed with the other.
    """
    q = question.lower()
    if "flood" in q or "water" in q:
        body = (
            "1. **Hydrology & Flood Risk**: Check FEMA 100-yr and 500-yr base flood elevations "
            "(BFE). Critical switchgear, generators and IT floor slabs belong at BFE + 3.0 ft "
            "finished floor elevation.\n"
            "2. **Stormwater & Drainage**: On-site retention/detention designed for a 100-year, "
            "24-hour storm with redundant culvert outfalls.\n"
            "3. **Cooling**: In water-stressed basins, closed-loop air-cooled chillers with "
            "adiabatic pre-cooling rather than open evaporative towers."
        )
    elif "seismic" in q or "earthquake" in q:
        body = (
            "1. **Seismic Hazard**: Review ASCE 7-22 peak ground acceleration and Risk Category "
            "IV design parameters.\n"
            "2. **Anchorage**: Chillers, generators and UPS battery skids need IBC-compliant "
            "seismic snubbers and positive bolting into reinforced slab.\n"
            "3. **Geotechnics**: CPT borings to rule out liquefaction in alluvial layers."
        )
    elif "power" in q or "grid" in q or "substation" in q:
        body = (
            "1. **Interconnection**: Dual-fed diverse 115kV or 230kV transmission from separate "
            "utility substations with high-speed transfer switching.\n"
            "2. **Substation Yard**: 3–5 acres for step-down transformers with blast deflection "
            "walls and oil-catchment basins.\n"
            "3. **Reserve Generation**: N+1 or 2N generator enclosures with 48–72 hours of "
            "on-site fuel."
        )
    else:
        body = (
            "1. **Grading & Cut/Fill**: Minimise cut-and-fill imbalance. Slope above 3% forces "
            "tiered pads and retaining walls.\n"
            "2. **Foundations**: Drilled shaft piers or spread footings sized against a measured "
            "allowable bearing pressure — which needs a geotechnical report, not an estimate.\n"
            "3. **Permitting & Easements**: Secure heavy-haul routing for transformers and "
            "confirm stormwater and wetland permits with the county early."
        )
    return (
        f"**Senior Civil EPC Assessment for {site_name}:**\n\n{body}\n\n"
        "_No language model is configured, so this is template guidance, not an "
        "assessment of this site's evidence._"
    )


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

    lat, lon, site_name = _resolve_location(store, project, payload.site_id)

    if payload.site_id:
        site = store.get(C.SITES, payload.site_id, CandidateSite)
        if site:
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

    # Mireye answers questions about a place, so it is only asked when there is
    # one. Its answer is context for the model, never a calculation.
    if mireye_client and lat is not None and lon is not None:
        try:
            mireye_res = mireye_client.ask(payload.message, lat, lon)
        except Exception as exc:  # noqa: BLE001 - a provider outage must not end the chat
            log.warning("mireye query failed in advisor", extra={"error": str(exc)})
        else:
            if mireye_res and mireye_res.answer:
                label = "MIREYE" if mireye_res.mode == "live" else f"MIREYE ({mireye_res.mode})"
                context_lines.append(f"=== {label} · {site_name} ({lat:.4f}, {lon:.4f}) ===")
                context_lines.append(mireye_res.answer)

    # Whatever has been uploaded to this project, searched for this question.
    retrieved, _citations = _retrieved_context(project.id, payload.message)
    if retrieved:
        context_lines.append("=== PROJECT DOCUMENTS (quote these by page) ===")
        context_lines.append(retrieved)

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

    improvements = _real_next_steps(store, project, payload.site_id)

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
        reply = _deterministic_advice(payload.message, site_name)

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
            text = _deterministic_advice(payload.message, site_name)

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
    lat, lon, where = _resolve_location(store, project, payload.site_id)
    if lat is None or lon is None:
        raise HTTPException(
            status_code=422,
            detail="Mireye answers questions about a place. Add a candidate site with "
            "coordinates, or select one, then ask again.",
        )
    try:
        result = client.ask(payload.question, lat, lon)
    except MireyeError as exc:
        raise HTTPException(status_code=502, detail=f"Mireye ask failed: {exc}") from exc

    citations = list(result.citations)
    citations.insert(
        0, {"source": "location", "detail": f"{where} ({lat:.4f}, {lon:.4f})"}
    )
    return AskResponse(
        answer=result.answer,
        citations=citations,
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
    sample_dir = get_settings().sample_dir
    return {
        "directory": str(sample_dir),
        "files": sorted(p.name for p in sample_dir.glob("*.pdf")) if sample_dir.exists() else [],
        "note": "All sample documents are synthetic demonstration data.",
    }


# ---------------------------------------------------------------------------
# Project Knowledge Autonomous Research Agent Endpoints
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/knowledge/agent/chat", response_model=KnowledgeAgentResponse)
def knowledge_agent_chat(
    payload: KnowledgeAgentRequest,
    project: Project = Depends(get_project),
):
    """Synchronous execution of the autonomous Knowledge & Research Agent."""
    agent = get_knowledge_agent()
    try:
        res = agent.run(
            project_id=project.id,
            message=payload.message,
            site_id=payload.site_id,
            enabled_tools=payload.enabled_tools,
            history=payload.history,
        )
        return KnowledgeAgentResponse(
            answer=res.answer,
            tell_me=TellMeInsightsSchema(
                key_findings=res.tell_me.key_findings,
                risks_identified=res.tell_me.risks_identified,
                standards_compliance=res.tell_me.standards_compliance,
                actionable_mitigations=res.tell_me.actionable_mitigations,
            ),
            citations=[
                CitationSchema(
                    source_type=c.source_type,
                    title=c.title,
                    detail=c.detail,
                    url=c.url,
                    page=c.page,
                    chunk_id=c.chunk_id,
                    coordinates=c.coordinates,
                )
                for c in res.citations
            ],
            tool_traces=[
                ToolTraceSchema(
                    tool=t.tool,
                    title=t.title,
                    input_params=t.input_params,
                    output_summary=t.output_summary,
                    duration_ms=t.duration_ms,
                    ok=t.ok,
                )
                for t in res.tool_traces
            ],
            site_name=res.site_name,
            mode=res.mode,
            disclaimer=res.disclaimer,
        )
    except Exception as exc:
        log.warning("knowledge agent failed", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Knowledge agent error: {exc}") from exc


@router.post("/projects/{project_id}/knowledge/agent/stream")
def knowledge_agent_stream(
    payload: KnowledgeAgentRequest,
    project: Project = Depends(get_project),
):
    """Server-Sent Events (SSE) streaming execution of the Knowledge Agent."""
    agent = get_knowledge_agent()
    return StreamingResponse(
        agent.stream(
            project_id=project.id,
            message=payload.message,
            site_id=payload.site_id,
            enabled_tools=payload.enabled_tools,
            history=payload.history,
        ),
        media_type="text/event-stream",
    )


@router.get("/projects/{project_id}/knowledge/suggestions")
def knowledge_suggestions(
    project: Project = Depends(get_project),
    store: Store = Depends(store_dep),
):
    """Prompt suggestions drawn from what this project actually contains.

    A suggestion that points at data the project does not have wastes the click
    and teaches the reader the agent is guessing, so each one below is backed by
    something already in the store: an uploaded document, an open gap, a pending
    change, a located site.
    """
    sites = store.list(C.SITES, CandidateSite, project_id=project.id)
    documents = [
        d
        for d in store.list(C.DOCUMENTS, ProjectDocument, project_id=project.id)
        if d.extraction_status == "extracted"
    ]
    changes = store.list(C.CHANGES, EquipmentChange, project_id=project.id)
    open_gaps = [
        g
        for g in store.list(C.GAPS, InformationGap, project_id=project.id)
        if g.status != GapStatus.RESOLVED
    ]
    located = [s for s in sites if s.latitude is not None and s.longitude is not None]

    suggestions: list[str] = []

    for document in documents[:2]:
        suggestions.append(f"What are the key requirements in {document.filename}?")

    for change in changes[:2]:
        suggestions.append(
            f"What does the {change.equipment_tag} substitution change, and what is still open?"
        )

    # Gaps are the project's own list of what it does not know. Naming one is the
    # most useful thing to offer, because the answer is an action.
    seen_fields: set[str] = set()
    for gap in open_gaps:
        if not gap.field_key or gap.field_key in seen_fields:
            continue
        seen_fields.add(gap.field_key)
        spec = FIELD_INDEX.get(gap.field_key)
        if not spec:
            continue
        suggestions.append(f"How do we obtain {spec.label.lower()} for this project?")
        if len(seen_fields) == 2:
            break

    if located:
        site = located[0]
        suggestions.append(f"Summarise the physical site constraints at {site.name}.")

    if not suggestions:
        suggestions = [
            "Upload a specification or submittal PDF to get started.",
            "Add a candidate site with coordinates, then ask about its constraints.",
        ]

    return {"suggestions": suggestions[:6]}


# ---------------------------------------------------------------------------
# Model Context Protocol (MCP) Server Endpoints
# ---------------------------------------------------------------------------


@router.get("/mcp/tools", response_model=list[dict])
def list_mcp_tools():
    """Returns available tools conforming to the Model Context Protocol (MCP) specification."""
    registry = get_mcp_registry()
    return registry.list_tools()


@router.post("/mcp/rpc", response_model=MCPRpcResponse)
def handle_mcp_rpc(payload: MCPRpcRequest):
    """JSON-RPC 2.0 endpoint for standard Model Context Protocol (MCP) tool execution."""
    registry = get_mcp_registry()
    if payload.method == "tools/list":
        return MCPRpcResponse(id=payload.id, result={"tools": registry.list_tools()})
    elif payload.method == "tools/call":
        tool_name = payload.params.get("name")
        arguments = payload.params.get("arguments", {})
        if not tool_name:
            return MCPRpcResponse(
                id=payload.id,
                error={"code": -32602, "message": "Missing 'name' in tools/call parameters"},
            )
        result = registry.execute(tool_name, arguments)
        return MCPRpcResponse(id=payload.id, result=result)
    else:
        return MCPRpcResponse(
            id=payload.id,
            error={"code": -32601, "message": f"Method '{payload.method}' not implemented"},
        )
