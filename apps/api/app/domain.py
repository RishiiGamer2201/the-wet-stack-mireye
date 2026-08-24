"""Shared domain model for both workflows.

Everything the agent produces is expressed with these types, and every accepted
fact carries an :class:`Evidence` record with full provenance. Nothing in this
module invents values: a missing fact is represented by an
:class:`InformationGap`, never by a default number.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

UTC = timezone.utc


def now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, populate_by_name=True)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SourceType(str, Enum):
    MIREYE = "mireye"
    PROJECT_DOCUMENT = "project_document"
    MANUFACTURER_DOCUMENT = "manufacturer_document"
    AHRI_DIRECTORY = "ahri_directory"
    EXTERNAL_DATASET = "external_dataset"
    USER_INPUT = "user_input"
    DERIVED = "derived"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class EvidenceStatus(str, Enum):
    """Lifecycle state of a single evidence item."""

    LIVE = "live"  # retrieved from a live external service this session
    CACHED = "cached"  # served from local cache within TTL
    SYNTHETIC = "synthetic"  # deterministic demo/mock value — clearly labelled in the UI
    FALLBACK = "fallback"  # a live service was configured but failed; this is the
    # local stand-in that replaced it. Never labelled `live`.
    USER_CONFIRMED = "user_confirmed"  # a human confirmed/corrected the value
    MISSING = "missing"  # requested but not available anywhere
    STALE = "stale"  # was valid, upstream input changed or TTL expired


class EvidenceRelation(str, Enum):
    """How a piece of evidence relates to the concept it is filed under.

    The first three are *the same measurement*, possibly re-expressed, and may
    populate a canonical value. CONTEXTUAL_PROXY is a different measurement that
    merely informs the concept: it is displayed and citable, but it can never
    stand in for the real one.
    """

    EXACT = "exact"  # provider measures precisely this quantity
    UNIT_CONVERTED = "unit_converted"  # same quantity, deterministic unit change
    CATEGORICAL_NORMALIZED = "categorical_normalized"  # same quantity, vocabulary mapped
    CONTEXTUAL_PROXY = "contextual_proxy"  # related, NOT equivalent — never canonical


#: Relations whose evidence is the measurement itself and may populate a value,
#: close a gap, satisfy a verification gate and count toward coverage.
CANONICAL_RELATIONS = frozenset(
    {
        EvidenceRelation.EXACT,
        EvidenceRelation.UNIT_CONVERTED,
        EvidenceRelation.CATEGORICAL_NORMALIZED,
        EvidenceRelation.CONTEXTUAL_PROXY,
    }
)


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class CheckStatus(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    TRIGGERED = "TRIGGERED"
    SKIPPED = "SKIPPED"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionState(str, Enum):
    FIRST_PASS_CHECKS_CLOSED = "FIRST-PASS CHECKS CLOSED"
    NEEDS_INFORMATION = "NEEDS INFORMATION"
    ENGINEER_REVIEW = "ENGINEER REVIEW"


class Discipline(str, Enum):
    STRUCTURAL = "structural"
    ELECTRICAL = "electrical"
    MECHANICAL = "mechanical"
    CONTROLS = "controls"
    INSTALLATION_LOGISTICS = "installation_logistics"
    COMMISSIONING = "commissioning"


class InvestigationPhase(str, Enum):
    UNDERSTAND = "understand"
    PLAN = "plan"
    EVIDENCE = "evidence"
    SIGNALS = "signals"
    REPLAN = "replan"
    IMPACT = "impact"
    ACTION = "action"
    DONE = "done"


class Workflow(str, Enum):
    BEFORE_CONSTRUCTION = "before_construction"
    DURING_CONSTRUCTION = "during_construction"


class SiteDimension(str, Enum):
    GEO_TERRAIN = "geo_terrain"
    WATER = "water"
    POWER = "power"
    CONNECTIVITY = "connectivity"
    CIVIL_SOIL = "civil_soil"
    HAZARDS_CLIMATE = "hazards_climate"
    ENVIRONMENTAL = "environmental"
    REGULATORY = "regulatory"


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    ELEVATED = "elevated"
    HIGH = "high"


class NextActionType(str, Enum):
    RFI = "rfi"
    VENDOR_EVIDENCE_REQUEST = "vendor_evidence_request"
    CLARIFICATION_REQUEST = "clarification_request"
    REVIEW_COMMENT = "review_comment"
    HUMAN_CONFIRMATION = "human_confirmation"


class AssumptionStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    RETIRED = "retired"


class StepStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class GapStatus(str, Enum):
    OPEN = "open"
    REQUESTED = "requested"
    RESOLVED = "resolved"


# ---------------------------------------------------------------------------
# Provenance & evidence
# ---------------------------------------------------------------------------


class Quantity(Base):
    """A number that always travels with its unit."""

    value: float
    unit: str = Field(description="Pint-parseable unit string, e.g. 'kg', 'kW', 'mm'")

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.value:g} {self.unit}"


class TextSpan(Base):
    start: int
    end: int
    text: str | None = None


class EvidenceSource(Base):
    """Where a value came from, precisely enough to be re-checked by a human."""

    source_type: SourceType
    source_id: str = Field(description="Document id, Mireye field key, dataset id, ...")
    source_name: str
    page: int | None = None
    section: str | None = None
    span: TextSpan | None = None
    field_key: str | None = None
    endpoint: str | None = None
    request_fingerprint: str | None = None
    url: str | None = None
    synthetic: bool = False
    notes: str | None = None


class Evidence(Base):
    id: str = Field(default_factory=lambda: new_id("ev"))
    project_id: str | None = None
    subject_id: str | None = Field(
        default=None, description="Site id, equipment id, change id this supports"
    )
    claim: str
    field_key: str | None = None
    value: Any = None
    unit: str | None = None
    source: EvidenceSource
    status: EvidenceStatus = EvidenceStatus.SYNTHETIC
    relation: EvidenceRelation = EvidenceRelation.EXACT
    #: Set on CONTEXTUAL_PROXY evidence: why this is not the measurement itself.
    relation_note: str | None = None
    verification: VerificationStatus = VerificationStatus.UNVERIFIED
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    retrieved_at: datetime = Field(default_factory=now)
    observed_at: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_resolution: str | None = Field(
        default=None, description="rooftop | parcel | street | city | region"
    )
    superseded_by: str | None = None
    stale_reason: str | None = None
    created_at: datetime = Field(default_factory=now)

    @property
    def is_usable(self) -> bool:
        return self.status not in (EvidenceStatus.MISSING,)

    @property
    def is_canonical(self) -> bool:
        """True when this evidence may populate the concept's value.

        Contextual proxies are readable and citable but never canonical, so a
        related-but-different measurement cannot close a gap, pass a gate or
        raise a score.
        """
        return self.relation in CANONICAL_RELATIONS

    def mark_stale(self, reason: str) -> Evidence:
        self.status = EvidenceStatus.STALE
        self.stale_reason = reason
        return self


class Assumption(Base):
    id: str = Field(default_factory=lambda: new_id("asm"))
    project_id: str
    statement: str
    discipline: Discipline
    basis_evidence_ids: list[str] = Field(default_factory=list)
    depends_on_fields: list[str] = Field(default_factory=list)
    equipment_tag: str | None = None
    value: float | str | None = None
    unit: str | None = None
    source_document: str | None = None
    revision: str | None = None
    design_capacity: float | None = None
    current_value: float | None = None
    margin: float | None = None
    status: AssumptionStatus = AssumptionStatus.ACTIVE
    stale_reason: str | None = None
    updated_at: datetime = Field(default_factory=now)


def gap_id(project_id: str, subject_id: str | None, field_key: str) -> str:
    """Stable id for a gap, so re-running an analysis updates the same record
    instead of appending a duplicate."""
    digest = hashlib.sha256(f"{project_id}|{subject_id or '-'}|{field_key}".encode()).hexdigest()
    return f"gap_{digest[:12]}"


class InformationGap(Base):
    id: str = Field(default_factory=lambda: new_id("gap"))
    project_id: str
    subject_id: str | None = None
    field_key: str
    description: str
    why_it_matters: str
    expected_source: SourceType
    suggested_action: NextActionType
    severity: Severity = Severity.MEDIUM
    status: GapStatus = GapStatus.OPEN
    blocking: bool = True
    feature_request_id: str | None = Field(
        default=None, description="Mireye /v1/feature-requests id when the field is unsupported"
    )
    created_at: datetime = Field(default_factory=now)


# ---------------------------------------------------------------------------
# Project & sites
# ---------------------------------------------------------------------------


class RequirementTargets(Base):
    """Hard project requirements used for deterministic pass/fail flags."""

    it_load_mw: float | None = None
    min_grid_capacity_mw: float | None = None
    max_distance_to_substation_km: float | None = None
    max_water_stress_index: float | None = None
    max_permit_lead_time_months: float | None = None
    min_bearing_capacity_kpa: float | None = None
    max_seismic_pga_g: float | None = None


class Project(Base):
    id: str = Field(default_factory=lambda: new_id("prj"))
    name: str
    client: str | None = None
    description: str | None = None
    region: str | None = None
    workflows: list[Workflow] = Field(
        default_factory=lambda: [Workflow.BEFORE_CONSTRUCTION, Workflow.DURING_CONSTRUCTION]
    )
    targets: RequirementTargets = Field(default_factory=RequirementTargets)
    dimension_weights: dict[SiteDimension, float] = Field(default_factory=dict)
    synthetic: bool = True
    created_at: datetime = Field(default_factory=now)


class CandidateSite(Base):
    id: str = Field(default_factory=lambda: new_id("site"))
    project_id: str
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    area_hectares: float | None = None
    jurisdiction: str | None = None
    geocode_resolution: str | None = None
    mireye_site_id: str | None = None
    shortlisted: bool = False
    synthetic: bool = True
    notes: str | None = None
    created_at: datetime = Field(default_factory=now)

    @field_validator("latitude")
    @classmethod
    def _lat(cls, v: float | None) -> float | None:
        if v is not None and not -90 <= v <= 90:
            raise ValueError("latitude out of range")
        return v

    @field_validator("longitude")
    @classmethod
    def _lon(cls, v: float | None) -> float | None:
        if v is not None and not -180 <= v <= 180:
            raise ValueError("longitude out of range")
        return v


class SiteObservation(Base):
    """One physical-world measurement for one site, always evidence-backed."""

    id: str = Field(default_factory=lambda: new_id("obs"))
    site_id: str
    project_id: str
    field_key: str
    dimension: SiteDimension
    value: float | str | None = None
    unit: str | None = None
    evidence_id: str | None = None
    status: EvidenceStatus = EvidenceStatus.SYNTHETIC
    confidence: float = 0.5
    observed_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=now)


class MetricScore(Base):
    field_key: str
    label: str
    raw_value: float | str | None
    unit: str | None
    normalized: float | None = Field(default=None, description="0-100, higher is better")
    weight: float
    status: EvidenceStatus
    evidence_id: str | None = None
    explanation: str


class DimensionScore(Base):
    dimension: SiteDimension
    score: float | None = Field(default=None, description="0-100, None when no evidence")
    weight: float
    coverage: float = Field(description="0-1 share of metric weight actually evidenced")
    confidence: float
    metrics: list[MetricScore] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)


class RequirementFlag(Base):
    requirement: str
    target: str
    actual: str | None
    passed: bool | None
    severity: Severity
    explanation: str


class SiteScore(Base):
    site_id: str
    site_name: str
    overall_score: float | None
    rank: int | None = None
    evidence_coverage: float
    confidence: float
    risk_level: RiskLevel
    dimensions: list[DimensionScore] = Field(default_factory=list)
    requirement_flags: list[RequirementFlag] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    synthetic_field_count: int = 0
    summary: str = ""
    computed_at: datetime = Field(default_factory=now)


class SiteRanking(Base):
    project_id: str
    weights: dict[SiteDimension, float]
    scores: list[SiteScore]
    comparisons: list[str] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=now)


# ---------------------------------------------------------------------------
# Documents, chunks, requirements
# ---------------------------------------------------------------------------


class DocumentKind(str, Enum):
    SPECIFICATION = "specification"
    EQUIPMENT_SCHEDULE = "equipment_schedule"
    DRAWING = "drawing"
    SUBMITTAL = "submittal"
    MANUFACTURER_DATASHEET = "manufacturer_datasheet"
    CODE_DOCUMENT = "code_document"
    OTHER = "other"


class ProjectDocument(Base):
    id: str = Field(default_factory=lambda: new_id("doc"))
    project_id: str
    filename: str
    kind: DocumentKind = DocumentKind.OTHER
    content_type: str = "application/pdf"
    size_bytes: int = 0
    page_count: int = 0
    stored_path: str | None = None
    sha256: str | None = None
    synthetic: bool = False
    uploaded_at: datetime = Field(default_factory=now)
    extraction_status: Literal["pending", "extracted", "failed"] = "pending"
    extraction_error: str | None = None
    #: Pages that had no text layer and were transcribed by OCR. Everything read
    #: from them is a transcription, so it is carried at lower confidence and
    #: must be confirmed before any check uses it.
    ocr_pages: list[int] = Field(default_factory=list)
    #: Pages that are scans and were not read at all — OCR unavailable, over the
    #: page cap, or unreadable. Listed so nobody reads silence as "not in the
    #: document".
    unread_pages: list[int] = Field(default_factory=list)

    @property
    def has_ocr(self) -> bool:
        return bool(self.ocr_pages)


class DocumentChunk(Base):
    id: str = Field(default_factory=lambda: new_id("chk"))
    document_id: str
    project_id: str
    page: int
    ordinal: int
    text: str
    #: True when this chunk's page was transcribed by OCR rather than read from
    #: a text layer. Surfaced on every citation drawn from it.
    ocr: bool = False
    char_start: int
    char_end: int
    section: str | None = None
    embedding: list[float] | None = None


class RequirementKind(str, Enum):
    CAPACITY = "capacity"
    WEIGHT = "weight"
    DIMENSION = "dimension"
    ELECTRICAL = "electrical"
    REFRIGERANT = "refrigerant"
    CONDITION = "condition"
    CODE = "code"
    OTHER = "other"


class Requirement(Base):
    id: str = Field(default_factory=lambda: new_id("req"))
    project_id: str
    document_id: str | None = None
    kind: RequirementKind = RequirementKind.OTHER
    label: str
    field_key: str | None = None
    value: float | str | None = None
    unit: str | None = None
    condition: str | None = None
    equipment_tag: str | None = None
    model_identifier: str | None = None
    page: int | None = None
    span: TextSpan | None = None
    raw_text: str | None = None
    confidence: float = 0.5
    #: True when the sentence this came from was transcribed by OCR. A misread
    #: digit is a fabricated number with a citation attached, so these can never
    #: be auto-confirmed and are shown as needing a human read of the page.
    from_ocr: bool = False
    confirmed: bool = False
    confirmed_by: str | None = None
    corrected_from: str | None = None
    evidence_id: str | None = None
    created_at: datetime = Field(default_factory=now)


class RetrievedChunk(Base):
    chunk_id: str
    document_id: str
    document_name: str
    page: int
    text: str
    score: float
    method: Literal["lexical", "vector"] = "lexical"
    #: The quoted page was transcribed by OCR, not read from a text layer.
    ocr: bool = False


# ---------------------------------------------------------------------------
# Equipment & change
# ---------------------------------------------------------------------------


class SupportPoint(Base):
    point_id: str
    load: Quantity


class RatingConditions(Base):
    """The conditions a performance rating is valid at. Comparing two capacities
    rated at different conditions is a rating-condition gap, not a delta."""

    entering_water_temp: Quantity | None = None
    leaving_water_temp: Quantity | None = None
    ambient_temp: Quantity | None = None
    condenser_water_flow: Quantity | None = None
    standard: str | None = Field(default=None, description="e.g. AHRI 550/590")

    def signature(self) -> tuple:
        def q(x: Quantity | None) -> tuple | None:
            return (round(x.value, 3), x.unit) if x else None

        return (
            q(self.entering_water_temp),
            q(self.leaving_water_temp),
            q(self.ambient_temp),
            q(self.condenser_water_flow),
            self.standard,
        )


class EquipmentConfiguration(Base):
    """The measurable configuration of one equipment item, with the basis of each
    value recorded so 'operating weight' is never compared to 'dry weight'."""

    id: str = Field(default_factory=lambda: new_id("cfg"))
    manufacturer: str | None = None
    model_number: str | None = None
    series: str | None = None
    equipment_type: str | None = Field(default=None, description="e.g. air_cooled_chiller")
    configuration_code: str | None = None
    circuits: int | None = None

    weight: Quantity | None = None
    weight_basis: Literal["operating", "dry", "shipping"] | None = None
    support_points: list[SupportPoint] = Field(default_factory=list)

    length: Quantity | None = None
    width: Quantity | None = None
    height: Quantity | None = None

    voltage: Quantity | None = None
    phases: int | None = None
    full_load_amps: Quantity | None = None
    mca: Quantity | None = Field(default=None, description="Minimum circuit ampacity")
    mocp: Quantity | None = Field(default=None, description="Max overcurrent protection")
    power_input: Quantity | None = None

    refrigerant_type: str | None = None
    refrigerant_charge: Quantity | None = None

    cooling_capacity: Quantity | None = None
    rating_conditions: RatingConditions | None = None

    sound_power: Quantity | None = None
    evidence_ids: dict[str, str] = Field(
        default_factory=dict, description="field name -> evidence id backing that value"
    )
    synthetic: bool = True


class Equipment(Base):
    id: str = Field(default_factory=lambda: new_id("eq"))
    project_id: str
    tag: str
    name: str
    discipline: Discipline = Discipline.MECHANICAL
    location: str | None = None
    site_id: str | None = None
    configuration: EquipmentConfiguration = Field(default_factory=EquipmentConfiguration)
    synthetic: bool = True


class EquipmentChange(Base):
    id: str = Field(default_factory=lambda: new_id("chg"))
    project_id: str
    title: str
    reason: str | None = None
    equipment_tag: str
    site_id: str | None = None
    existing_equipment_id: str
    proposed_equipment_id: str
    submitted_by: str | None = None
    status: Literal["draft", "analyzing", "analyzed"] = "draft"
    synthetic: bool = True
    created_at: datetime = Field(default_factory=now)


class DeltaResult(Base):
    field: str
    label: str
    old_value: Quantity | str | None
    new_value: Quantity | str | None
    absolute_delta: Quantity | None = None
    percent_delta: float | None = None
    direction: Literal["increase", "decrease", "unchanged", "changed", "unknown"] = "unknown"
    severity: Severity = Severity.INFO
    threshold_note: str | None = None
    status: CheckStatus = CheckStatus.CLOSED
    explanation: str
    evidence_ids: list[str] = Field(default_factory=list)


class EngineeringCheck(Base):
    id: str = Field(default_factory=lambda: new_id("chk"))
    key: str
    name: str
    category: Literal["verification_gate", "delta", "site_compatibility"] = "verification_gate"
    status: CheckStatus = CheckStatus.OPEN
    severity: Severity = Severity.INFO
    detail: str
    expected: str | None = None
    observed: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    deterministic: bool = True


# ---------------------------------------------------------------------------
# Impact graph
# ---------------------------------------------------------------------------


class ImpactNode(Base):
    id: str
    label: str
    kind: Literal[
        "change", "assumption", "discipline", "activity", "commissioning", "equipment", "site"
    ]
    status: str | None = None
    detail: str | None = None


class ImpactEdge(Base):
    source: str
    target: str
    relation: str


class Impact(Base):
    id: str = Field(default_factory=lambda: new_id("imp"))
    change_id: str
    discipline: Discipline
    title: str
    detail: str
    severity: Severity = Severity.MEDIUM
    triggered_by: list[str] = Field(default_factory=list, description="check keys / delta fields")
    stale_assumption_ids: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    commissioning: list[str] = Field(default_factory=list)
    requires_human: bool = False


class ImpactGraph(Base):
    change_id: str
    nodes: list[ImpactNode] = Field(default_factory=list)
    edges: list[ImpactEdge] = Field(default_factory=list)
    paths: list[list[str]] = Field(default_factory=list)
    backend: str = "in_memory"


# ---------------------------------------------------------------------------
# Investigation / agent
# ---------------------------------------------------------------------------


class ToolEvent(Base):
    id: str = Field(default_factory=lambda: new_id("evt"))
    investigation_id: str
    phase: InvestigationPhase
    tool: str
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    duration_ms: int | None = None
    at: datetime = Field(default_factory=now)


class InvestigationStep(Base):
    id: str = Field(default_factory=lambda: new_id("stp"))
    investigation_id: str
    order: int
    phase: InvestigationPhase
    title: str
    rationale: str
    requested_fields: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PLANNED
    result_summary: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    added_in_replan: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Recommendation(Base):
    id: str = Field(default_factory=lambda: new_id("rec"))
    headline: str
    rationale: list[str] = Field(default_factory=list)
    decision_state: DecisionState | None = None
    confidence: float = 0.5
    caveats: list[str] = Field(default_factory=list)
    generated_by: Literal["deterministic", "llm"] = "deterministic"


class NextAction(Base):
    id: str = Field(default_factory=lambda: new_id("act"))
    type: NextActionType
    title: str
    recipient: str
    body: str
    requested_items: list[str] = Field(default_factory=list)
    related_gap_ids: list[str] = Field(default_factory=list)
    due_in_days: int = 5
    generated_by: Literal["deterministic", "llm"] = "deterministic"


class Investigation(Base):
    id: str = Field(default_factory=lambda: new_id("inv"))
    project_id: str
    workflow: Workflow
    subject_id: str | None = Field(default=None, description="change id or site-set marker")
    question: str
    phase: InvestigationPhase = InvestigationPhase.UNDERSTAND
    status: Literal["running", "completed", "failed"] = "running"
    steps: list[InvestigationStep] = Field(default_factory=list)
    events: list[ToolEvent] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    replan_notes: list[str] = Field(default_factory=list)
    checks: list[EngineeringCheck] = Field(default_factory=list)
    deltas: list[DeltaResult] = Field(default_factory=list)
    impacts: list[Impact] = Field(default_factory=list)
    stale_assumption_ids: list[str] = Field(default_factory=list)
    decision_state: DecisionState | None = None
    recommendation: Recommendation | None = None
    next_actions: list[NextAction] = Field(default_factory=list)
    ranking: SiteRanking | None = None
    orchestrator: str = "langgraph"
    llm_mode: str = "deterministic"
    started_at: datetime = Field(default_factory=now)
    finished_at: datetime | None = None


# ---------------------------------------------------------------------------
# Design Margins & Facility Capacities
# ---------------------------------------------------------------------------


class MarginType(str, Enum):
    STRUCTURAL = "structural_margin"
    ELECTRICAL = "electrical_margin"
    THERMAL = "thermal_margin"
    COOLING = "cooling_margin"
    WATER = "water_margin"
    GENERATOR = "generator_margin"
    TRANSFORMER = "transformer_margin"


class MarginStatus(str, Enum):
    WITHIN_MARGIN = "WITHIN_MARGIN"
    CRITICAL_MARGIN = "CRITICAL_MARGIN"
    EXCEEDED = "EXCEEDED"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"


class DesignMargin(Base):
    id: str = Field(default_factory=lambda: new_id("mrn"))
    margin_type: MarginType
    name: str
    discipline: Discipline = Discipline.MECHANICAL
    design_capacity: Quantity | None = None
    proposed_demand: Quantity | None = None
    remaining_margin: Quantity | None = None
    margin_pct: float | None = None
    status: MarginStatus = MarginStatus.NEEDS_INFORMATION
    detail: str
    evidence_ids: list[str] = Field(default_factory=list)


class ProjectCapacities(Base):
    structural_roof_capacity_kg: float | None = None
    substation_capacity_mw: float | None = None
    generator_capacity_kw: float | None = None
    chilled_water_capacity_kw: float | None = None
    water_allocation_m3_yr: float | None = None
    transformer_capacity_kva: float | None = None


# ---------------------------------------------------------------------------
# Cascade Analysis (Multi-change cumulative impacts)
# ---------------------------------------------------------------------------


class CascadeChangeItem(Base):
    change_id: str
    equipment_tag: str
    title: str
    equipment_type: str
    delta_power_kw: float = 0.0
    delta_weight_kg: float = 0.0
    delta_cooling_kw: float = 0.0
    delta_water_m3_yr: float = 0.0


class CascadeImpactSummary(Base):
    project_id: str
    evaluated_changes: list[CascadeChangeItem] = Field(default_factory=list)
    cumulative_electrical_delta_kw: float = 0.0
    cumulative_weight_delta_kg: float = 0.0
    cumulative_cooling_delta_kw: float = 0.0
    cumulative_water_delta_m3_yr: float = 0.0
    transformer_headroom_pct: float | None = None
    generator_headroom_pct: float | None = None
    structural_headroom_pct: float | None = None
    collective_status: Literal["WITHIN_FACILITY_LIMITS", "FACILITY_LIMITS_EXCEEDED", "NEEDS_INFORMATION"] = (
        "WITHIN_FACILITY_LIMITS"
    )
    rationale: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Structured Requirements & Product Recommendations
# ---------------------------------------------------------------------------


class StructuredConstraint(Base):
    parameter: str
    operator: Literal[">=", "<=", "==", "!=", ">", "<"]
    value: float | str | int
    unit: str | None = None
    priority: Literal["mandatory", "preferred"] = "mandatory"


class StructuredRequirementSet(Base):
    id: str = Field(default_factory=lambda: new_id("reqset"))
    project_id: str
    equipment_type: str
    constraints: list[StructuredConstraint] = Field(default_factory=list)
    original_prompt: str | None = None
    created_at: datetime = Field(default_factory=now)


class CandidateProduct(Base):
    id: str
    model_number: str
    manufacturer: str
    equipment_type: str
    specs: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0  # 0 to 100
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    passed_constraints: list[str] = Field(default_factory=list)
    failed_constraints: list[str] = Field(default_factory=list)
    compatibility_status: Literal["COMPATIBLE", "CONDITIONALLY_COMPATIBLE", "INCOMPATIBLE"] = "COMPATIBLE"
    explanation: str
    warnings: list[str] = Field(default_factory=list)
    reference_source: str = "RacksDB / LBNL Open Catalog"


class ProductRecommendationResult(Base):
    id: str = Field(default_factory=lambda: new_id("recres"))
    project_id: str
    equipment_type: str
    requirement_set: StructuredRequirementSet
    candidates: list[CandidateProduct] = Field(default_factory=list)
    top_recommendation: CandidateProduct | None = None
    explanation_narrative: str
    generated_at: datetime = Field(default_factory=now)


# ---------------------------------------------------------------------------
# Document Revision & Decision Lineage
# ---------------------------------------------------------------------------


class DocumentRevision(Base):
    id: str = Field(default_factory=lambda: new_id("drev"))
    project_id: str
    document_id: str
    document_name: str
    revision_code: str
    description: str
    modified_requirements: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)


class DecisionLineageRecord(Base):
    id: str = Field(default_factory=lambda: new_id("dlin"))
    project_id: str
    change_id: str
    decision_state: DecisionState
    timestamp: datetime = Field(default_factory=now)
    triggered_reasons: list[str] = Field(default_factory=list)
    source_documents: list[str] = Field(default_factory=list)
    affected_assumptions: list[str] = Field(default_factory=list)
    engine_version: str = "Deterministic Delta & Gate Engine v1.2"


# ---------------------------------------------------------------------------
# Cost & Schedule Impact
# ---------------------------------------------------------------------------


class CostScheduleImpact(Base):
    change_id: str
    equipment_tag: str
    capex_delta_usd: float | None = None
    annual_energy_delta_usd: float | None = None
    annual_water_delta_usd: float | None = None
    total_annual_opex_delta_usd: float | None = None
    schedule_delay_days: int = 0
    on_critical_path: bool = False
    lead_time_weeks: int | None = None
    status: Literal["ESTIMATED", "NEEDS_INFORMATION"] = "ESTIMATED"
    explanation: str = ""

