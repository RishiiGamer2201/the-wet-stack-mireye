"""API request/response schemas (typed contracts shared with the frontend)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .domain import (
    Assumption,
    CandidateSite,
    DocumentChunk,
    DocumentKind,
    Equipment,
    EquipmentChange,
    Evidence,
    ImpactGraph,
    InformationGap,
    Investigation,
    Project,
    ProjectDocument,
    Requirement,
    RequirementTargets,
    RetrievedChunk,
    SiteDimension,
    SiteRanking,
)


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    hint: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class ReadyResponse(BaseModel):
    ready: bool
    checks: dict[str, str]


class MetaResponse(BaseModel):
    app_name: str
    environment: str
    demo_mode: bool
    services: dict[str, str]
    mireye_field_count: int
    dimension_weights: dict[str, float]
    dimension_labels: dict[str, str]
    disclaimer: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    client: str | None = None
    description: str | None = None
    region: str | None = None
    targets: RequirementTargets = Field(default_factory=RequirementTargets)
    dimension_weights: dict[SiteDimension, float] | None = None


class ProjectUpdate(BaseModel):
    targets: RequirementTargets | None = None
    dimension_weights: dict[SiteDimension, float] | None = None


class ProjectDetail(BaseModel):
    project: Project
    sites: list[CandidateSite]
    documents: list[ProjectDocument]
    changes: list[EquipmentChange]
    requirement_count: int
    evidence_count: int
    open_gap_count: int


class SiteCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    area_hectares: float | None = Field(default=None, gt=0)
    jurisdiction: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _location_present(self):
        if not self.address and (self.latitude is None or self.longitude is None):
            raise ValueError("provide an address, or both latitude and longitude")
        return self


class RunSiteInvestigation(BaseModel):
    site_ids: list[str] | None = Field(
        default=None, description="Defaults to every candidate site on the project"
    )
    weights: dict[SiteDimension, float] | None = None


class RankingRequest(BaseModel):
    weights: dict[SiteDimension, float] | None = None
    site_ids: list[str] | None = None


class OverrideRequest(BaseModel):
    field_key: str
    value: float | str
    note: str | None = None


class WhatIfResponse(BaseModel):
    ranking: SiteRanking
    changed_from: SiteRanking | None = None
    explanation: list[str] = Field(default_factory=list)


class RequirementUpdate(BaseModel):
    value: float | str | None = None
    unit: str | None = None
    condition: str | None = None
    equipment_tag: str | None = None
    confirmed: bool = True
    confirmed_by: str | None = None


class SearchResponse(BaseModel):
    query: str
    backend: str
    results: list[RetrievedChunk]


class UploadResponse(BaseModel):
    document: ProjectDocument
    chunk_count: int
    requirements: list[Requirement]
    warning: str | None = None


class ChangeDetail(BaseModel):
    change: EquipmentChange
    existing: Equipment
    proposed: Equipment
    site: CandidateSite | None
    requirements: list[Requirement]
    assumptions: list[Assumption]
    latest_investigation_id: str | None = None


class ConstructionPlanRequest(BaseModel):
    """User-owned design basis for a first-pass construction equipment plan."""

    site_id: str
    it_load_mw: float = Field(gt=0, le=500)
    redundancy: Literal["N", "N+1", "2N"] = "N+1"
    target_pue: float = Field(default=1.35, ge=1.0, le=3.0)
    utilization_pct: float = Field(default=70.0, gt=0, le=100)
    annual_operating_hours: float = Field(default=8760.0, gt=0, le=8760)
    electricity_rate_usd_kwh: float = Field(default=0.085, ge=0, le=5)
    cooling_strategy: Literal["water_cooled", "hybrid_economizer"] = "water_cooled"
    voltage_v: int = Field(default=480, ge=120, le=35_000)
    budget_usd: float | None = Field(default=None, gt=0)
    contingency_pct: float = Field(default=15.0, ge=0, le=50)
    requirements_note: str | None = Field(default=None, max_length=2000)


class ConstructionPlanItem(BaseModel):
    category: str
    label: str
    model_id: str
    model_number: str
    manufacturer: str
    quantity: int
    duty_per_unit: float | None = None
    duty_unit: str | None = None
    power_input_per_unit_kw: float | None = None
    connected_power_kw: float
    estimated_cost_low_usd: float
    estimated_cost_high_usd: float
    cost_basis: str
    lead_time_weeks: int
    description: str
    source: str
    synthetic_cost: bool = True


class ConstructionWorkPackage(BaseModel):
    sequence: int
    name: str
    scope: str
    depends_on: list[str] = Field(default_factory=list)


class SitePlanningConstraint(BaseModel):
    field_key: str
    label: str
    value: float | str
    unit: str | None = None
    status: str
    source: str


class ConstructionPlanTotals(BaseModel):
    peak_facility_power_kw: float
    it_power_kw: float
    facility_overhead_kw: float
    annual_energy_kwh: float
    annual_energy_cost_usd: float
    annual_water_m3: float | None = None
    equipment_cost_low_usd: float
    equipment_cost_high_usd: float
    contingency_pct: float
    plan_cost_low_usd: float
    plan_cost_high_usd: float
    budget_usd: float | None = None
    budget_status: Literal["WITHIN_RANGE", "BELOW_RANGE", "NOT_PROVIDED"]


class ConstructionPlanResponse(BaseModel):
    project_id: str
    site: CandidateSite
    design_basis: dict[str, Any]
    site_constraints: list[SitePlanningConstraint]
    equipment_schedule: list[ConstructionPlanItem]
    work_packages: list[ConstructionWorkPackage]
    totals: ConstructionPlanTotals
    warnings: list[str]
    data_sources: list[str]


class InvestigationSummary(BaseModel):
    id: str
    workflow: str
    question: str
    phase: str
    status: str
    decision_state: str | None
    started_at: Any
    finished_at: Any


class EvidenceQuery(BaseModel):
    subject_id: str | None = None
    field_key: str | None = None
    status: str | None = None


class GapUpdate(BaseModel):
    status: str


class AskRequest(BaseModel):
    question: str = Field(min_length=4, max_length=500)
    site_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    citations: list[dict[str, Any]]
    confidence: float
    mode: str
    disclaimer: str


class AdvisorChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    site_id: str | None = None
    site_context: dict[str, Any] | None = None
    history: list[dict[str, str]] | None = None


class AdvisorChatResponse(BaseModel):
    reply: str
    #: Which site the advice is scoped to. Engineering advice without a subject
    #: is advice about nothing in particular.
    site_name: str | None = None
    engineer_role: str = "Principal Civil & Structural EPC Engineer"
    suggested_improvements: list[str] = []
    mode: str = "llm"
    disclaimer: str = "Advisory engineering opinion. Certified drawings and structural calculations require PE stamp."


class CitationSchema(BaseModel):
    source_type: str
    title: str
    detail: str
    url: str | None = None
    page: int | None = None
    chunk_id: str | None = None
    coordinates: str | None = None


class ToolTraceSchema(BaseModel):
    tool: str
    title: str
    input_params: dict[str, Any] = Field(default_factory=dict)
    output_summary: str
    duration_ms: int = 0
    ok: bool = True


class TellMeInsightsSchema(BaseModel):
    key_findings: list[str] = Field(default_factory=list)
    risks_identified: list[str] = Field(default_factory=list)
    standards_compliance: list[str] = Field(default_factory=list)
    actionable_mitigations: list[str] = Field(default_factory=list)


class KnowledgeAgentRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2500)
    site_id: str | None = None
    enabled_tools: list[str] | None = None  # ["documents", "web", "mireye", "project"]
    history: list[dict[str, str]] | None = None


class KnowledgeAgentResponse(BaseModel):
    answer: str
    tell_me: TellMeInsightsSchema
    citations: list[CitationSchema] = Field(default_factory=list)
    tool_traces: list[ToolTraceSchema] = Field(default_factory=list)
    site_name: str | None = None
    mode: str = "llm"
    disclaimer: str


class MCPToolSchema(BaseModel):
    name: str
    description: str
    inputSchema: dict[str, Any]


class MCPRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class MCPRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: Any = None
    error: dict[str, Any] | None = None


class SeedResponse(BaseModel):
    project_id: str
    project_name: str
    message: str


class RequirementParseRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    equipment_type: str | None = None


class RecommendationSearchRequest(BaseModel):
    equipment_type: str
    constraints: list[dict[str, Any]] | None = None
    weights: dict[str, float] | None = None
    site_id: str | None = None


class ApplyRecommendationRequest(BaseModel):
    equipment_tag: str
    candidate_product_id: str
    title: str | None = None
    reason: str | None = None
    site_id: str | None = None
    existing_change_id: str | None = None


class CascadeAnalysisRequest(BaseModel):
    change_ids: list[str] | None = None


class ActionPackageRequest(BaseModel):
    change_id: str
    action_type: str = "rfi"  # "rfi" | "vendor_request" | "review_package"
    recipient: str | None = None
    notes: str | None = None


class ActionPackageResponse(BaseModel):
    action_type: str
    title: str
    recipient: str
    body_markdown: str
    requested_items: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    due_in_days: int = 5


__all__ = [name for name in dir() if name[0].isupper()] + [
    "Evidence",
    "InformationGap",
    "Investigation",
    "ImpactGraph",
    "DocumentChunk",
    "DocumentKind",
]

