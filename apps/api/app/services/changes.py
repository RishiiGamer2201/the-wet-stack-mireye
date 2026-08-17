"""During Construction — equipment change analysis.

Order of operations mirrors the architecture diagram: verification gates run
first (§4A), deterministic deltas second (§4B), then stale-assumption tracking
and impact tracing (§3B), then the decision state and next action (§5–§7).
"""

from __future__ import annotations

import logging

from ..adapters.graphstore import GraphStore
from ..domain import (
    Assumption,
    CandidateSite,
    CheckStatus,
    DecisionState,
    DeltaResult,
    EngineeringCheck,
    Equipment,
    EquipmentChange,
    EvidenceStatus,
    Impact,
    ImpactGraph,
    InformationGap,
    NextAction,
    Project,
    Recommendation,
    Requirement,
    SiteObservation,
)
from ..engine import decisions, gates
from ..engine import deltas as delta_engine
from ..engine import impact as impact_engine
from ..store import C, Store
from .evidence import observations_for_site, put_gap, refresh_status

log = logging.getLogger("changes")


class ChangeAnalysis:
    """Everything one change analysis produces. Persisted onto the Investigation."""

    def __init__(self) -> None:
        self.checks: list[EngineeringCheck] = []
        self.deltas: list[DeltaResult] = []
        self.gaps: list[InformationGap] = []
        self.stale: list[Assumption] = []
        self.impacts: list[Impact] = []
        self.graph: ImpactGraph | None = None
        self.decision: DecisionState = DecisionState.NEEDS_INFORMATION
        self.rationale: list[str] = []
        self.recommendation: Recommendation | None = None
        self.next_actions: list[NextAction] = []
        self.confidence: float = 0.0


def _site_observations(store: Store, project: Project, site_id: str | None) -> dict[str, SiteObservation]:
    if not site_id:
        return {}
    observations = observations_for_site(store, site_id, project.id)
    return {o.field_key: o for o in observations if o.status != EvidenceStatus.MISSING}


def _synthetic_share(store: Store, project: Project, change: EquipmentChange) -> float:
    from ..domain import Evidence

    items = store.list(C.EVIDENCE, Evidence, project_id=project.id)
    relevant = [e for e in items if e.subject_id in (change.equipment_tag, change.site_id, change.id)]
    if not relevant:
        return 1.0
    synthetic = sum(1 for e in relevant if e.status == EvidenceStatus.SYNTHETIC)
    return synthetic / len(relevant)


def analyze_change(
    store: Store,
    graph_store: GraphStore,
    project: Project,
    change: EquipmentChange,
    *,
    persist: bool = True,
) -> ChangeAnalysis:
    analysis = ChangeAnalysis()
    existing = store.get(C.EQUIPMENT, change.existing_equipment_id, Equipment)
    proposed = store.get(C.EQUIPMENT, change.proposed_equipment_id, Equipment)
    if not existing or not proposed:
        raise ValueError("equipment records for this change are missing")

    site = store.get(C.SITES, change.site_id, CandidateSite) if change.site_id else None
    observations = _site_observations(store, project, change.site_id)
    requirements = [
        r
        for r in store.list(C.REQUIREMENTS, Requirement, project_id=project.id)
        if r.equipment_tag in (None, change.equipment_tag)
    ]
    # Only engineer-confirmed requirements gate a decision; unconfirmed ones are
    # still reported so the user can confirm or correct them first.
    confirmed = [r for r in requirements if r.confirmed] or requirements

    # 1. Verification gate — before anything is accepted.
    analysis.checks = gates.run_verification_gates(
        existing.configuration,
        proposed.configuration,
        site=site,
        observations=observations,
        requirements=confirmed,
    )
    analysis.gaps = gates.gaps_from_checks(analysis.checks, project.id, change.id)

    # 2. Deterministic deltas — only for values that are actually comparable.
    blocking_gate = next(
        (
            c
            for c in analysis.checks
            if c.key in ("model_identity", "unit_compatibility") and c.status == CheckStatus.TRIGGERED
        ),
        None,
    )
    analysis.deltas = delta_engine.compute_deltas(existing.configuration, proposed.configuration)
    if blocking_gate:
        for d in analysis.deltas:
            if d.status == CheckStatus.CLOSED:
                d.status = CheckStatus.SKIPPED
                d.explanation += (
                    f" Not accepted: the '{blocking_gate.name}' gate is TRIGGERED, so the "
                    "comparison is not valid."
                )
    analysis.gaps += delta_engine.gaps_from_deltas(analysis.deltas, project.id, change.id)

    # 3. Stale assumptions + impact tracing.
    assumptions = store.list(C.ASSUMPTIONS, Assumption, project_id=project.id)
    relevant = [
        a for a in assumptions if a.equipment_tag in (None, change.equipment_tag)
    ]
    analysis.stale = impact_engine.mark_stale_assumptions(relevant, analysis.deltas, analysis.checks)
    analysis.impacts = impact_engine.derive_impacts(
        change.id, analysis.deltas, analysis.checks, analysis.stale
    )
    analysis.graph = impact_engine.build_graph(
        change.id,
        f"{change.equipment_tag}: {change.title}",
        analysis.impacts,
        analysis.stale,
        backend=graph_store.backend,
    )

    # 4. Decision + next action.
    analysis.confidence = decisions.decision_confidence(
        analysis.checks, analysis.deltas, _synthetic_share(store, project, change)
    )
    analysis.decision, analysis.rationale = decisions.decide(
        analysis.checks, analysis.deltas, analysis.gaps
    )
    structural, reasons = delta_engine.structural_coordination_required(analysis.deltas)
    if structural:
        analysis.rationale.append(
            "Structural coordination is required (not structural adequacy): " + "; ".join(reasons)
        )
    analysis.recommendation = decisions.build_recommendation(
        analysis.decision, analysis.rationale, analysis.checks, analysis.impacts, analysis.confidence
    )
    analysis.next_actions = decisions.build_next_actions(
        analysis.decision,
        change.title,
        change.equipment_tag,
        analysis.gaps,
        analysis.checks,
        analysis.impacts,
    )

    if persist:
        for gap in analysis.gaps:
            put_gap(store, gap, parent_id=change.id)
        for assumption in analysis.stale:
            store.put(C.ASSUMPTIONS, assumption, project_id=project.id)
        graph_store.upsert(analysis.graph)
        change.status = "analyzed"
        store.put(C.CHANGES, change, project_id=project.id)

    log.info(
        "change analysed",
        extra={
            "change_id": change.id,
            "decision": analysis.decision.value,
            "open": sum(1 for c in analysis.checks if c.status == CheckStatus.OPEN),
            "triggered": sum(1 for c in analysis.checks if c.status == CheckStatus.TRIGGERED),
            "impacts": len(analysis.impacts),
        },
    )
    return analysis


def age_change_evidence(store: Store, project: Project) -> int:
    """Re-evaluate the staleness of every stored evidence item. Returns the count
    that transitioned to STALE."""
    from ..domain import Evidence

    transitioned = 0
    for ev in store.list(C.EVIDENCE, Evidence, project_id=project.id):
        before = ev.status
        refresh_status(ev)
        if ev.status != before:
            store.put(C.EVIDENCE, ev, project_id=project.id)
            transitioned += 1
    return transitioned
