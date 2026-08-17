"""API request/response schemas (typed contracts shared with the frontend)."""

from __future__ import annotations

from typing import Any

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


class SeedResponse(BaseModel):
    project_id: str
    project_name: str
    message: str


__all__ = [name for name in dir() if name[0].isupper()] + [
    "Evidence",
    "InformationGap",
    "Investigation",
    "ImpactGraph",
    "DocumentChunk",
    "DocumentKind",
]
