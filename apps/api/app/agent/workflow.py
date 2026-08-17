"""LangGraph investigation workflow.

    Understand → Plan → Evidence → Signals → Replan → Impact → Action

`Replan` can loop back into `Evidence` once, which is what makes the
investigation progressive rather than a fixed checklist. If LangGraph is not
importable the same node functions run through `_sequential_fallback`, so the
product behaves identically.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..adapters.graphstore import GraphStore, get_graph_store
from ..adapters.llm import INVESTIGATION_SYSTEM, LLMProvider, get_llm
from ..adapters.mireye import MireyeClient, get_mireye_client
from ..adapters.vectorstore import get_index
from ..domain import (
    Assumption,
    CandidateSite,
    CheckStatus,
    DecisionState,
    Equipment,
    EquipmentChange,
    Evidence,
    EvidenceStatus,
    GapStatus,
    InformationGap,
    Investigation,
    InvestigationPhase,
    NextAction,
    NextActionType,
    Project,
    Recommendation,
    Requirement,
    Severity,
    SiteDimension,
    StepStatus,
    ToolEvent,
    Workflow,
)
from ..engine.decisions import SAFETY_CAVEAT
from ..fields import DIMENSION_LABELS, deep_fields
from ..services import changes as change_service
from ..services import sites as site_service
from ..store import C, Store, get_store
from . import planner

log = logging.getLogger("agent")


@dataclass
class Context:
    store: Store
    client: MireyeClient
    graph_store: GraphStore
    llm: LLMProvider
    project: Project
    investigation: Investigation
    sites: list[CandidateSite] = field(default_factory=list)
    shortlisted: list[CandidateSite] = field(default_factory=list)
    change: EquipmentChange | None = None
    analysis: change_service.ChangeAnalysis | None = None
    replans: int = 0
    weights: dict[SiteDimension, float] | None = None
    #: One live-spend budget for the whole investigation, so the broad and deep
    #: passes cannot each spend the full allowance.
    budget: site_service.LiveBudget | None = None

    # -- recording ----------------------------------------------------------
    def event(self, phase: InvestigationPhase, tool: str, summary: str, detail=None, ok=True, ms=None):
        evt = ToolEvent(
            investigation_id=self.investigation.id,
            phase=phase,
            tool=tool,
            summary=summary,
            detail=detail or {},
            ok=ok,
            duration_ms=ms,
        )
        self.investigation.events.append(evt)
        return evt

    def phase(self, phase: InvestigationPhase) -> None:
        self.investigation.phase = phase
        self.save()

    def step(self, order: int):
        return next((s for s in self.investigation.steps if s.order == order), None)

    def save(self) -> None:
        self.store.put(C.INVESTIGATIONS, self.investigation, project_id=self.project.id)


def _start(ctx: Context, step_titles: list[str]) -> None:
    for s in ctx.investigation.steps:
        if s.title in step_titles:
            s.status = StepStatus.RUNNING
            s.started_at = datetime.now(UTC)


def _finish(ctx: Context, step, summary: str, status=StepStatus.COMPLETED, **ids) -> None:
    if not step:
        return
    step.status = status
    step.result_summary = summary
    step.finished_at = datetime.now(UTC)
    step.evidence_ids += ids.get("evidence_ids", [])
    step.gap_ids += ids.get("gap_ids", [])


# ---------------------------------------------------------------------------
# Before Construction nodes
# ---------------------------------------------------------------------------


def site_understand(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.UNDERSTAND)
    located = sum(1 for s in ctx.sites if s.latitude is not None)
    ctx.event(
        InvestigationPhase.UNDERSTAND,
        "context_read",
        f"Understood the question over {len(ctx.sites)} candidate site(s); "
        f"{located} already have coordinates.",
        {
            "targets": ctx.project.targets.model_dump(exclude_none=True),
            "weights": {k.value: v for k, v in (ctx.weights or {}).items()},
        },
    )
    return ctx


def site_plan(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.PLAN)
    ctx.investigation.steps = planner.plan_site_investigation(
        ctx.investigation.id, ctx.project, ctx.sites
    )
    ctx.event(
        InvestigationPhase.PLAN,
        "supervisor_plan",
        f"Planned {len(ctx.investigation.steps)} step(s) for this specific candidate set.",
        {"steps": [s.title for s in ctx.investigation.steps]},
    )
    ctx.save()
    return ctx


def site_evidence(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.EVIDENCE)
    geocode_step = next(
        (s for s in ctx.investigation.steps if s.title.startswith("Geocode")), None
    )
    if geocode_step:
        geocode_step.status = StepStatus.RUNNING
        resolved = 0
        for site in ctx.sites:
            if site.latitude is None and site.address:
                site_service.resolve_site_location(ctx.client, site)
                ctx.store.put(C.SITES, site, project_id=ctx.project.id)
                resolved += 1
        _finish(ctx, geocode_step, f"Resolved coordinates for {resolved} site(s).")
        ctx.event(
            InvestigationPhase.EVIDENCE, "mireye_geocode", f"Geocoded {resolved} site(s)."
        )

    step = next((s for s in ctx.investigation.steps if s.title.startswith("Broad")), None)
    if step:
        step.status = StepStatus.RUNNING
        started = time.perf_counter()
        results = site_service.broad_pass(
            ctx.store, ctx.client, ctx.project, ctx.sites, ctx.budget
        )
        evidence_ids = [i for r in results for i in r["evidence_ids"]]
        gap_ids = [i for r in results for i in r["gap_ids"]]
        for r in results:
            ctx.event(InvestigationPhase.EVIDENCE, "mireye_fetch", r["summary"], r["detail"], r["ok"])
        _finish(
            ctx,
            step,
            f"Broad sweep complete: {len(evidence_ids)} evidence item(s), {len(gap_ids)} gap(s).",
            evidence_ids=evidence_ids,
            gap_ids=gap_ids,
        )
        ctx.investigation.evidence_ids += evidence_ids
        ctx.investigation.gap_ids += gap_ids
        ctx.event(
            InvestigationPhase.EVIDENCE,
            "mireye_fetch",
            f"Broad pass over {len(ctx.sites)} site(s) finished.",
            ms=int((time.perf_counter() - started) * 1000),
        )
    ctx.save()
    return ctx


def site_signals(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.SIGNALS)
    step = next((s for s in ctx.investigation.steps if s.title.startswith("Score every")), None)
    if step:
        step.status = StepStatus.RUNNING
    ranking = site_service.score_sites(ctx.store, ctx.project, ctx.sites, ctx.weights)
    ctx.investigation.ranking = ranking
    ctx.shortlisted = site_service.shortlist(ctx.store, ranking, ctx.sites, top_n=2)
    leader = ranking.scores[0] if ranking.scores else None
    _finish(
        ctx,
        step,
        f"Ranked {len(ranking.scores)} site(s); shortlisted "
        f"{', '.join(s.name for s in ctx.shortlisted) or 'none'}.",
    )

    target_step = next(
        (
            s
            for s in ctx.investigation.steps
            if s.phase == InvestigationPhase.SIGNALS and s.status == StepStatus.PLANNED
        ),
        None,
    )
    if target_step:
        passes = [
            f"{sc.site_name}: "
            + ", ".join(
                f"{f.requirement} {'PASS' if f.passed else 'FAIL' if f.passed is False else 'UNKNOWN'}"
                for f in sc.requirement_flags
            )
            for sc in ranking.scores
        ]
        failing = sum(
            1 for sc in ranking.scores if any(f.passed is False for f in sc.requirement_flags)
        )
        _finish(
            ctx,
            target_step,
            f"{failing} of {len(ranking.scores)} candidate(s) miss at least one hard project target.",
        )
        ctx.event(
            InvestigationPhase.SIGNALS,
            "requirement_check",
            target_step.result_summary,
            {"per_site": passes},
        )
    ctx.event(
        InvestigationPhase.SIGNALS,
        "scoring_engine",
        f"Leader: {leader.site_name} at {leader.overall_score}/100 "
        f"({leader.evidence_coverage:.0%} evidence coverage)." if leader else "No site could be scored.",
        {
            "ranking": [
                {"name": s.site_name, "score": s.overall_score, "risk": s.risk_level.value}
                for s in ranking.scores
            ]
        },
    )
    ctx.save()
    return ctx


def site_replan(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.REPLAN)
    ctx.replans += 1
    step = next((s for s in ctx.investigation.steps if s.title.startswith("Deepen")), None)
    if step:
        step.status = StepStatus.RUNNING
    note = (
        f"Broad pass separated the field; deepening only on "
        f"{', '.join(s.name for s in ctx.shortlisted)} with {len(deep_fields())} additional field(s)."
    )
    ctx.investigation.replan_notes.append(note)
    results = site_service.deep_pass(
        ctx.store, ctx.client, ctx.project, ctx.shortlisted, ctx.budget
    )
    evidence_ids = [i for r in results for i in r["evidence_ids"]]
    gap_ids = [i for r in results for i in r["gap_ids"]]
    for r in results:
        ctx.event(InvestigationPhase.REPLAN, "mireye_fetch", r["summary"], r["detail"], r["ok"])
    _finish(ctx, step, f"Deep pass added {len(evidence_ids)} evidence item(s).",
            evidence_ids=evidence_ids, gap_ids=gap_ids)
    ctx.investigation.evidence_ids += evidence_ids
    ctx.investigation.gap_ids += gap_ids

    ranking = site_service.score_sites(ctx.store, ctx.project, ctx.sites, ctx.weights)
    ctx.investigation.ranking = ranking
    ctx.event(
        InvestigationPhase.REPLAN,
        "scoring_engine",
        "Re-scored candidates with the deeper evidence set.",
        {"comparisons": ranking.comparisons},
    )
    ctx.save()
    return ctx


def site_impact(ctx: Context) -> Context:
    """For site selection the 'impact' phase consolidates risk and what is missing."""
    ctx.phase(InvestigationPhase.IMPACT)
    gaps = [
        g
        for g in ctx.store.list(C.GAPS, InformationGap, project_id=ctx.project.id)
        if g.status != GapStatus.RESOLVED
    ]
    ranking = ctx.investigation.ranking
    unverified = (
        [f.requirement for f in ranking.scores[0].requirement_flags if f.passed is None]
        if ranking and ranking.scores
        else []
    )
    ctx.event(
        InvestigationPhase.IMPACT,
        "gap_analysis",
        f"{len(gaps)} open information gap(s); {len(unverified)} project target(s) "
        "cannot be verified on the leading site.",
        {"unverified_targets": unverified, "gap_fields": sorted({g.field_key for g in gaps})},
    )
    ctx.save()
    return ctx


def site_action(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.ACTION)
    ranking = ctx.investigation.ranking
    gaps = [
        g
        for g in ctx.store.list(C.GAPS, InformationGap, project_id=ctx.project.id)
        if g.status != GapStatus.RESOLVED
    ]
    if not ranking or not ranking.scores or ranking.scores[0].overall_score is None:
        ctx.investigation.decision_state = DecisionState.NEEDS_INFORMATION
        ctx.investigation.recommendation = Recommendation(
            headline="No candidate could be scored",
            rationale=["No usable physical-world evidence was retrieved for any candidate site."],
            decision_state=DecisionState.NEEDS_INFORMATION,
            confidence=0.0,
            caveats=[SAFETY_CAVEAT],
        )
        ctx.save()
        return ctx

    leader = ranking.scores[0]
    failed = [f for f in leader.requirement_flags if f.passed is False]
    unverified = [f for f in leader.requirement_flags if f.passed is None]
    blocking = [g for g in gaps if g.blocking]

    if blocking or unverified:
        state = DecisionState.NEEDS_INFORMATION
    elif failed or leader.risk_level.value in ("elevated", "high"):
        state = DecisionState.ENGINEER_REVIEW
    else:
        state = DecisionState.FIRST_PASS_CHECKS_CLOSED

    rationale = [leader.summary] + ranking.comparisons[:2]
    if unverified:
        rationale.append(
            "Cannot verify against project target(s): " + ", ".join(f.requirement for f in unverified) + "."
        )
    for f in failed:
        rationale.append(f.explanation)
    weakest = min(
        (d for d in leader.dimensions if d.score is not None), key=lambda d: d.score, default=None
    )
    if weakest:
        rationale.append(
            f"Weakest dimension for {leader.site_name}: {DIMENSION_LABELS[weakest.dimension]} "
            f"at {weakest.score:.0f}/100 — {'; '.join(weakest.concerns[:2]) or 'no metric below 55'}"
        )

    recommendation = Recommendation(
        headline=f"{leader.site_name} leads on the current weights "
        f"({leader.overall_score:.1f}/100, {leader.risk_level.value} risk)",
        rationale=rationale,
        decision_state=state,
        confidence=leader.confidence,
        caveats=[
            SAFETY_CAVEAT,
            f"{leader.synthetic_field_count} field(s) for the leading site are synthetic demo "
            "values and must be replaced with live evidence before any real decision.",
        ],
    )
    recommendation = _llm_explain(ctx, recommendation)

    actions: list[NextAction] = []
    by_field: dict[str, list[InformationGap]] = {}
    for g in gaps:
        by_field.setdefault(g.suggested_action.value, []).append(g)
    for action_value, items in by_field.items():
        actions.append(
            NextAction(
                type=NextActionType(action_value),
                title=f"{action_value.replace('_', ' ').title()} — close {len(items)} site evidence gap(s)",
                recipient="Site selection / due-diligence team",
                body=(
                    "The following physical-world facts are unavailable and are blocking or "
                    "weakening the site comparison:\n\n"
                    + "\n".join(f"  - {g.description} ({g.why_it_matters})" for g in items[:12])
                    + "\n\nNo value has been assumed for any of them.\n\n"
                    + SAFETY_CAVEAT
                ),
                requested_items=[g.field_key for g in items],
                related_gap_ids=[g.id for g in items],
            )
        )
    if state != DecisionState.NEEDS_INFORMATION:
        actions.append(
            NextAction(
                type=NextActionType.HUMAN_CONFIRMATION,
                title=f"Confirm {leader.site_name} as the preferred candidate",
                recipient="Project director",
                body=(
                    f"{leader.site_name} ranks first at {leader.overall_score:.1f}/100 with "
                    f"{leader.evidence_coverage:.0%} evidence coverage.\n\n"
                    + "\n".join(ranking.comparisons[:2])
                    + "\n\n"
                    + SAFETY_CAVEAT
                ),
            )
        )

    ctx.investigation.decision_state = state
    ctx.investigation.recommendation = recommendation
    ctx.investigation.next_actions = actions
    ctx.investigation.gap_ids = sorted({*ctx.investigation.gap_ids, *(g.id for g in gaps)})
    ctx.event(
        InvestigationPhase.ACTION,
        "decision_engine",
        f"Decision: {state.value}. {len(actions)} next action(s) generated.",
        {"decision": state.value},
    )
    ctx.phase(InvestigationPhase.DONE)
    return ctx


# ---------------------------------------------------------------------------
# During Construction nodes
# ---------------------------------------------------------------------------


def change_understand(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.UNDERSTAND)
    change = ctx.change
    existing = ctx.store.get(C.EQUIPMENT, change.existing_equipment_id, Equipment)
    proposed = ctx.store.get(C.EQUIPMENT, change.proposed_equipment_id, Equipment)
    ctx.event(
        InvestigationPhase.UNDERSTAND,
        "context_read",
        f"{change.equipment_tag}: {existing.configuration.manufacturer} "
        f"{existing.configuration.model_number} → {proposed.configuration.manufacturer} "
        f"{proposed.configuration.model_number}.",
        {"reason": change.reason, "site_linked": bool(change.site_id)},
    )
    return ctx


def change_plan(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.PLAN)
    change = ctx.change
    existing = ctx.store.get(C.EQUIPMENT, change.existing_equipment_id, Equipment)
    proposed = ctx.store.get(C.EQUIPMENT, change.proposed_equipment_id, Equipment)
    ctx.investigation.steps = planner.plan_change_investigation(
        ctx.investigation.id,
        change,
        existing.configuration,
        proposed.configuration,
        has_site=bool(change.site_id),
        llm=ctx.llm,
    )
    ctx.event(
        InvestigationPhase.PLAN,
        "supervisor_plan",
        f"Planned {len(ctx.investigation.steps)} step(s) specific to this substitution.",
        {"steps": [s.title for s in ctx.investigation.steps]},
    )
    ctx.save()
    return ctx


def change_evidence(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.EVIDENCE)
    change = ctx.change
    for step in ctx.investigation.steps:
        if step.phase != InvestigationPhase.EVIDENCE:
            continue
        step.status = StepStatus.RUNNING
        step.started_at = datetime.now(UTC)

        if step.title.startswith("Read project requirements"):
            requirements = [
                r
                for r in ctx.store.list(C.REQUIREMENTS, Requirement, project_id=ctx.project.id)
                if r.equipment_tag in (None, change.equipment_tag)
            ]
            confirmed = sum(1 for r in requirements if r.confirmed)
            hits = get_index().search(
                ctx.project.id, f"{change.equipment_tag} capacity weight electrical requirement", k=4
            )
            _finish(
                ctx,
                step,
                f"{len(requirements)} extracted requirement(s), {confirmed} engineer-confirmed; "
                f"{len(hits)} supporting chunk(s) retrieved.",
                evidence_ids=[r.evidence_id for r in requirements if r.evidence_id],
            )
            ctx.event(
                InvestigationPhase.EVIDENCE,
                "document_retrieval",
                step.result_summary,
                {"citations": [f"{h.document_name} p.{h.page}" for h in hits]},
            )
        elif step.title.startswith("Fetch site design conditions"):
            site = ctx.store.get(C.SITES, change.site_id, CandidateSite)
            result = site_service.fetch_site_fields(
                ctx.store, ctx.client, ctx.project, site, step.requested_fields
            )
            _finish(
                ctx,
                step,
                result["summary"],
                status=StepStatus.COMPLETED if result["ok"] else StepStatus.BLOCKED,
                evidence_ids=result["evidence_ids"],
                gap_ids=result["gap_ids"],
            )
            ctx.investigation.evidence_ids += result["evidence_ids"]
            ctx.investigation.gap_ids += result["gap_ids"]
            ctx.event(
                InvestigationPhase.EVIDENCE, "mireye_fetch", result["summary"], result["detail"], result["ok"]
            )
        else:
            hits = get_index().search(ctx.project.id, step.title, k=3)
            _finish(
                ctx,
                step,
                f"{len(hits)} document chunk(s) retrieved"
                + (f": {', '.join(f'{h.document_name} p.{h.page}' for h in hits)}" if hits else "."),
            )
            ctx.event(
                InvestigationPhase.EVIDENCE,
                "document_retrieval",
                step.result_summary,
                {"query": step.title, "method": [h.method for h in hits]},
            )
    ctx.save()
    return ctx


def change_signals(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.SIGNALS)
    step = next(
        (s for s in ctx.investigation.steps if s.title.startswith("Run verification gates")), None
    )
    if step:
        step.status = StepStatus.RUNNING
    ctx.analysis = change_service.analyze_change(
        ctx.store, ctx.graph_store, ctx.project, ctx.change
    )
    a = ctx.analysis
    ctx.investigation.checks = a.checks
    ctx.investigation.deltas = a.deltas
    counts = {
        s.value: sum(1 for c in a.checks if c.status == s)
        for s in (CheckStatus.CLOSED, CheckStatus.OPEN, CheckStatus.TRIGGERED, CheckStatus.SKIPPED)
    }
    _finish(ctx, step, f"Gates: {counts}. {len(a.deltas)} delta(s) computed.")
    ctx.event(
        InvestigationPhase.SIGNALS,
        "verification_gate",
        f"Verification gates: {counts['CLOSED']} closed, {counts['OPEN']} open, "
        f"{counts['TRIGGERED']} triggered, {counts['SKIPPED']} skipped.",
        {"checks": [{"key": c.key, "status": c.status.value} for c in a.checks]},
    )
    ctx.event(
        InvestigationPhase.SIGNALS,
        "delta_calculation",
        "Deterministic deltas computed in Pint-checked units.",
        {
            "triggered": [d.label for d in a.deltas if d.status == CheckStatus.TRIGGERED],
            "open": [d.label for d in a.deltas if d.status == CheckStatus.OPEN],
        },
    )
    ctx.save()
    return ctx


def change_replan(ctx: Context) -> Context:
    """Add a targeted step for whatever the gates could not evaluate."""
    ctx.phase(InvestigationPhase.REPLAN)
    ctx.replans += 1
    open_checks = [c for c in ctx.analysis.checks if c.status == CheckStatus.OPEN]
    open_deltas = [d for d in ctx.analysis.deltas if d.status == CheckStatus.OPEN]
    note = (
        f"{len(open_checks)} gate(s) and {len(open_deltas)} delta(s) could not be evaluated; "
        "adding targeted evidence requests instead of assuming values."
    )
    ctx.investigation.replan_notes.append(note)
    order = len(ctx.investigation.steps)
    for c in open_checks:
        order += 1
        ctx.investigation.steps.append(
            planner._step(
                ctx.investigation.id,
                order,
                InvestigationPhase.REPLAN,
                f"Obtain evidence for: {c.name}",
                c.detail,
            )
        )
        ctx.investigation.steps[-1].added_in_replan = True
        ctx.investigation.steps[-1].status = StepStatus.BLOCKED
        ctx.investigation.steps[-1].result_summary = "Blocked pending external evidence."
        ctx.investigation.steps[-1].gap_ids = c.gap_ids
    ctx.event(
        InvestigationPhase.REPLAN,
        "supervisor_replan",
        note,
        {"open_checks": [c.key for c in open_checks], "open_deltas": [d.field for d in open_deltas]},
    )
    ctx.save()
    return ctx


def change_impact(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.IMPACT)
    step = next((s for s in ctx.investigation.steps if s.title.startswith("Trace downstream")), None)
    if step:
        step.status = StepStatus.RUNNING
    a = ctx.analysis
    ctx.investigation.impacts = a.impacts
    ctx.investigation.stale_assumption_ids = [s.id for s in a.stale]
    _finish(
        ctx,
        step,
        f"{len(a.impacts)} downstream impact(s) across "
        f"{len({i.discipline for i in a.impacts})} discipline(s); {len(a.stale)} assumption(s) "
        "marked stale.",
    )
    ctx.event(
        InvestigationPhase.IMPACT,
        "impact_trace",
        step.result_summary if step else "Impact traced.",
        {
            "disciplines": sorted({i.discipline.value for i in a.impacts}),
            "stale": [s.statement for s in a.stale],
            "graph_backend": a.graph.backend if a.graph else "n/a",
        },
    )
    ctx.save()
    return ctx


def change_action(ctx: Context) -> Context:
    ctx.phase(InvestigationPhase.ACTION)
    a = ctx.analysis
    ctx.investigation.decision_state = a.decision
    ctx.investigation.recommendation = _llm_explain(ctx, a.recommendation)
    ctx.investigation.next_actions = a.next_actions
    ctx.investigation.gap_ids = sorted({*ctx.investigation.gap_ids, *(g.id for g in a.gaps)})
    ctx.event(
        InvestigationPhase.ACTION,
        "decision_engine",
        f"Decision: {a.decision.value}. {len(a.next_actions)} next action(s) generated.",
        {"decision": a.decision.value, "confidence": a.confidence},
    )
    ctx.phase(InvestigationPhase.DONE)
    return ctx


# ---------------------------------------------------------------------------
# LLM explanation (never numeric)
# ---------------------------------------------------------------------------


def _llm_explain(ctx: Context, recommendation: Recommendation | None) -> Recommendation | None:
    if recommendation is None or not ctx.llm.available:
        return recommendation
    facts = "\n".join(f"- {r}" for r in recommendation.rationale)
    text = ctx.llm.complete(
        INVESTIGATION_SYSTEM,
        "Explain the following already-computed engineering findings to a project team in at "
        "most 4 sentences. Do not add, change or recompute any number, and do not state any "
        "fact that is not listed.\n\n"
        f"Decision state: {recommendation.decision_state.value if recommendation.decision_state else 'n/a'}\n"
        f"Findings:\n{facts}",
        max_tokens=400,
    )
    if text:
        recommendation.rationale.append(f"(agent explanation) {text.strip()}")
        recommendation.generated_by = "llm"
    return recommendation


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

SITE_NODES: list[tuple[str, Callable[[Context], Context]]] = [
    ("understand", site_understand),
    ("plan", site_plan),
    ("evidence", site_evidence),
    ("signals", site_signals),
    ("replan", site_replan),
    ("impact", site_impact),
    ("action", site_action),
]

CHANGE_NODES: list[tuple[str, Callable[[Context], Context]]] = [
    ("understand", change_understand),
    ("plan", change_plan),
    ("evidence", change_evidence),
    ("signals", change_signals),
    ("replan", change_replan),
    ("impact", change_impact),
    ("action", change_action),
]


def _needs_replan(ctx: Context) -> str:
    """Replan only when the signals phase found something unresolved (and once)."""
    if ctx.replans >= 1:
        return "impact"
    if ctx.investigation.workflow == Workflow.BEFORE_CONSTRUCTION:
        return "replan" if ctx.shortlisted else "impact"
    a = ctx.analysis
    unresolved = any(c.status == CheckStatus.OPEN for c in a.checks) or any(
        d.status == CheckStatus.OPEN for d in a.deltas
    )
    return "replan" if unresolved else "impact"


def _build_langgraph(nodes):
    from langgraph.graph import END, StateGraph

    builder = StateGraph(dict)
    for name, fn in nodes:
        builder.add_node(name, lambda state, _fn=fn: {"ctx": _fn(state["ctx"])})
    builder.set_entry_point("understand")
    builder.add_edge("understand", "plan")
    builder.add_edge("plan", "evidence")
    builder.add_edge("evidence", "signals")
    builder.add_conditional_edges(
        "signals",
        lambda state: _needs_replan(state["ctx"]),
        {"replan": "replan", "impact": "impact"},
    )
    builder.add_edge("replan", "impact")
    builder.add_edge("impact", "action")
    builder.add_edge("action", END)
    return builder.compile()


def _sequential_fallback(nodes, ctx: Context) -> Context:
    by_name = dict(nodes)
    for name in ("understand", "plan", "evidence", "signals"):
        ctx = by_name[name](ctx)
    if _needs_replan(ctx) == "replan":
        ctx = by_name["replan"](ctx)
    ctx = by_name["impact"](ctx)
    return by_name["action"](ctx)


def _run(nodes, ctx: Context) -> Context:
    try:
        app = _build_langgraph(nodes)
        ctx.investigation.orchestrator = "langgraph"
        result: dict[str, Any] = app.invoke({"ctx": ctx})
        return result["ctx"]
    except ImportError:  # pragma: no cover - langgraph is a declared dependency
        log.warning("langgraph unavailable, running sequential fallback")
        ctx.investigation.orchestrator = "sequential_fallback"
        return _sequential_fallback(nodes, ctx)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _new_investigation(project: Project, workflow: Workflow, question: str, subject_id=None):
    llm = get_llm()
    return Investigation(
        project_id=project.id,
        workflow=workflow,
        subject_id=subject_id,
        question=question,
        llm_mode=llm.name,
    )


def run_site_investigation(
    project: Project,
    sites: list[CandidateSite],
    weights: dict[SiteDimension, float] | None = None,
    store: Store | None = None,
) -> Investigation:
    store = store or get_store()
    investigation = _new_investigation(
        project,
        Workflow.BEFORE_CONSTRUCTION,
        f"Which of {len(sites)} candidate site(s) best fits {project.name}?",
    )
    client = get_mireye_client()
    ctx = Context(
        store=store,
        client=client,
        graph_store=get_graph_store(),
        llm=get_llm(),
        project=project,
        investigation=investigation,
        sites=sites,
        weights=weights,
        budget=site_service.LiveBudget(client),
    )
    ctx.save()
    try:
        ctx = _run(SITE_NODES, ctx)
        ctx.investigation.status = "completed"
    except Exception as exc:  # noqa: BLE001 - surface failure in the UI, do not crash the API
        log.exception("site investigation failed")
        ctx.investigation.status = "failed"
        ctx.event(ctx.investigation.phase, "error", str(exc), ok=False)
    ctx.investigation.finished_at = datetime.now(UTC)
    ctx.save()
    return ctx.investigation


def run_change_investigation(
    project: Project, change: EquipmentChange, store: Store | None = None
) -> Investigation:
    store = store or get_store()
    investigation = _new_investigation(
        project,
        Workflow.DURING_CONSTRUCTION,
        f"What are the implications of '{change.title}' on {change.equipment_tag}?",
        subject_id=change.id,
    )
    ctx = Context(
        store=store,
        client=get_mireye_client(),
        graph_store=get_graph_store(),
        llm=get_llm(),
        project=project,
        investigation=investigation,
        change=change,
    )
    ctx.save()
    try:
        ctx = _run(CHANGE_NODES, ctx)
        ctx.investigation.status = "completed"
    except Exception as exc:  # noqa: BLE001
        log.exception("change investigation failed")
        ctx.investigation.status = "failed"
        ctx.event(ctx.investigation.phase, "error", str(exc), ok=False)
    ctx.investigation.finished_at = datetime.now(UTC)
    ctx.save()
    return ctx.investigation


def evidence_bundle(store: Store, project_id: str) -> list[Evidence]:
    return store.list(C.EVIDENCE, Evidence, project_id=project_id)


__all__ = [
    "Context",
    "run_site_investigation",
    "run_change_investigation",
    "evidence_bundle",
    "Assumption",
    "EvidenceStatus",
    "Severity",
]
