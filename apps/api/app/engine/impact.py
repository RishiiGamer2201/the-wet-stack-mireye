"""Impact tracing and stale-assumption propagation.

Relationship path (diagram §3B / day 11):

    Change → Stale Assumption → Discipline → Activity → Commissioning

Impacts are produced from the *results* of the deterministic checks, so the graph
changes when the equipment change changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain import (
    Assumption,
    AssumptionStatus,
    CheckStatus,
    DeltaResult,
    Discipline,
    EngineeringCheck,
    Impact,
    ImpactEdge,
    ImpactGraph,
    ImpactNode,
    Severity,
)


@dataclass(frozen=True)
class ImpactRule:
    key: str
    triggers: tuple[str, ...]
    discipline: Discipline
    title: str
    detail: str
    activities: tuple[str, ...]
    commissioning: tuple[str, ...]
    requires_human: bool = False
    severity: Severity = Severity.MEDIUM


RULES: tuple[ImpactRule, ...] = (
    ImpactRule(
        key="structural_coordination",
        triggers=("weight", "support_point_load_max"),
        discipline=Discipline.STRUCTURAL,
        title="Structural coordination required",
        detail=(
            "Equipment load has increased beyond the coordination threshold. This platform "
            "flags that structural coordination is required; it does not assess structural "
            "adequacy and does not constitute engineering approval."
        ),
        activities=(
            "Issue revised equipment load schedule to the structural engineer of record",
            "Re-check dunnage / housekeeping pad and supporting steel against the new loads",
            "Confirm anchorage and seismic restraint design for the proposed unit",
        ),
        commissioning=("Structural sign-off recorded before the unit is set",),
        requires_human=True,
        severity=Severity.HIGH,
    ),
    ImpactRule(
        key="electrical_capacity",
        triggers=("mca", "mocp", "full_load_amps", "power_input", "voltage", "phases"),
        discipline=Discipline.ELECTRICAL,
        title="Electrical distribution review",
        detail="The proposed unit's electrical demand differs from the design basis.",
        activities=(
            "Re-verify feeder ampacity, conduit fill and voltage drop for the new MCA",
            "Confirm overcurrent protection against the new MOCP",
            "Update panel schedule and load calculations",
        ),
        commissioning=("Electrical acceptance test against the revised feeder schedule",),
        severity=Severity.HIGH,
    ),
    ImpactRule(
        key="mechanical_performance",
        triggers=("cooling_capacity", "rating_conditions", "capacity_requirement", "site_compatibility"),
        discipline=Discipline.MECHANICAL,
        title="Cooling performance re-evaluation",
        detail=(
            "Rated capacity or the conditions it is rated at have changed, so the design "
            "cooling duty and redundancy scheme must be re-checked at site conditions."
        ),
        activities=(
            "Re-run the cooling load and N+1 redundancy check with the proposed unit",
            "Obtain a selection re-rated at project design conditions",
            "Verify hydronic flow, pressure drop and pump head against the new unit",
        ),
        commissioning=("Capacity verification test at design conditions",),
        requires_human=True,
        severity=Severity.HIGH,
    ),
    ImpactRule(
        key="refrigerant_safety",
        triggers=("refrigerant_type", "refrigerant_charge"),
        discipline=Discipline.MECHANICAL,
        title="Refrigerant handling and safety review",
        detail="Refrigerant type or charge has changed, affecting safety and monitoring provisions.",
        activities=(
            "Re-check machine-room ventilation and refrigerant monitoring per ASHRAE 15",
            "Confirm refrigerant safety classification against the space classification",
            "Update leak-detection set points and service procedures",
        ),
        commissioning=("Refrigerant leak test and charge verification recorded",),
        severity=Severity.HIGH,
    ),
    ImpactRule(
        key="installation_logistics",
        triggers=("length", "width", "height", "footprint_area"),
        discipline=Discipline.INSTALLATION_LOGISTICS,
        title="Installation and rigging coordination",
        detail="Physical envelope has changed, affecting access, clearance and rigging.",
        activities=(
            "Re-check rigging path, crane pick radius and delivery route",
            "Verify service and code clearances around the revised footprint",
            "Update the equipment pad / curb layout drawing",
        ),
        commissioning=("Pre-installation dimensional survey signed off",),
        severity=Severity.MEDIUM,
    ),
    ImpactRule(
        key="controls_integration",
        triggers=(
            "model_identity",
            "configuration_comparability",
            "mca",
            "cooling_capacity",
            "refrigerant_type",
        ),
        discipline=Discipline.CONTROLS,
        title="Controls and BMS integration review",
        detail="A different unit changes the points list, protocol map and control sequences.",
        activities=(
            "Reconcile the BMS points list with the proposed unit's controller",
            "Update sequences of operation and alarm limits",
            "Confirm communication protocol and gateway requirements",
        ),
        commissioning=("Point-to-point verification and sequence-of-operation test",),
        severity=Severity.MEDIUM,
    ),
)


def _triggered_keys(deltas: list[DeltaResult], checks: list[EngineeringCheck]) -> dict[str, str]:
    """field/check key -> the sentence explaining why it fired."""
    fired: dict[str, str] = {}
    for d in deltas:
        if d.status == CheckStatus.TRIGGERED:
            fired[d.field] = d.explanation
    for c in checks:
        if c.status == CheckStatus.TRIGGERED:
            fired[c.key] = c.detail
    return fired


def mark_stale_assumptions(
    assumptions: list[Assumption],
    deltas: list[DeltaResult],
    checks: list[EngineeringCheck],
) -> list[Assumption]:
    """An assumption goes STALE when any field it depends on has actually changed.

    Returns the assumptions that transitioned in this run.
    """
    fired = _triggered_keys(deltas, checks)
    changed_fields = {
        d.field for d in deltas if d.direction in ("increase", "decrease", "changed")
    } | set(fired)
    transitioned: list[Assumption] = []
    for a in assumptions:
        hits = [f for f in a.depends_on_fields if f in changed_fields]
        if not hits or a.status == AssumptionStatus.STALE:
            continue
        a.status = AssumptionStatus.STALE
        a.stale_reason = "Upstream evidence changed: " + "; ".join(
            fired.get(h, f"{h} changed") for h in hits
        )
        transitioned.append(a)
    return transitioned


def derive_impacts(
    change_id: str,
    deltas: list[DeltaResult],
    checks: list[EngineeringCheck],
    stale: list[Assumption],
) -> list[Impact]:
    fired = _triggered_keys(deltas, checks)
    impacts: list[Impact] = []
    for rule in RULES:
        hits = [k for k in rule.triggers if k in fired]
        if not hits:
            continue
        related = [
            a.id for a in stale if set(a.depends_on_fields) & set(hits)
        ] or [a.id for a in stale if a.discipline == rule.discipline]
        impacts.append(
            Impact(
                change_id=change_id,
                discipline=rule.discipline,
                title=rule.title,
                detail=rule.detail + " Triggered by: " + "; ".join(fired[k] for k in hits),
                severity=rule.severity,
                triggered_by=hits,
                stale_assumption_ids=related,
                activities=list(rule.activities),
                commissioning=list(rule.commissioning),
                requires_human=rule.requires_human,
            )
        )
    return impacts


def build_graph(
    change_id: str,
    change_label: str,
    impacts: list[Impact],
    assumptions: list[Assumption],
    backend: str = "in_memory",
) -> ImpactGraph:
    """Materialise Change → Assumption → Discipline → Activity → Commissioning."""
    nodes: dict[str, ImpactNode] = {}
    edges: list[ImpactEdge] = []
    paths: list[list[str]] = []
    by_id = {a.id: a for a in assumptions}

    root = f"change:{change_id}"
    nodes[root] = ImpactNode(id=root, label=change_label, kind="change", status="analyzed")

    for imp in impacts:
        disc = f"discipline:{imp.discipline.value}"
        nodes.setdefault(
            disc,
            ImpactNode(
                id=disc,
                label=imp.discipline.value.replace("_", " ").title(),
                kind="discipline",
                status=imp.severity.value,
                detail=imp.title,
            ),
        )
        upstream = [root]
        for aid in imp.stale_assumption_ids:
            a = by_id.get(aid)
            if not a:
                continue
            nid = f"assumption:{aid}"
            nodes.setdefault(
                nid,
                ImpactNode(
                    id=nid, label=a.statement, kind="assumption", status=a.status.value,
                    detail=a.stale_reason,
                ),
            )
            edges.append(ImpactEdge(source=root, target=nid, relation="INVALIDATES"))
            edges.append(ImpactEdge(source=nid, target=disc, relation="AFFECTS"))
            upstream.append(nid)
        if len(upstream) == 1:
            edges.append(ImpactEdge(source=root, target=disc, relation="AFFECTS"))

        for activity in imp.activities:
            aid = f"activity:{imp.discipline.value}:{abs(hash(activity)) % 10**8}"
            nodes.setdefault(aid, ImpactNode(id=aid, label=activity, kind="activity"))
            edges.append(ImpactEdge(source=disc, target=aid, relation="REQUIRES"))
            for comm in imp.commissioning:
                cid = f"commissioning:{abs(hash(comm)) % 10**8}"
                nodes.setdefault(cid, ImpactNode(id=cid, label=comm, kind="commissioning"))
                edges.append(ImpactEdge(source=aid, target=cid, relation="VERIFIED_BY"))
                start = upstream[1] if len(upstream) > 1 else root
                path = [root] + ([start] if start != root else []) + [disc, aid, cid]
                paths.append(path)

    unique_edges = list({(e.source, e.target, e.relation): e for e in edges}.values())
    return ImpactGraph(
        change_id=change_id,
        nodes=list(nodes.values()),
        edges=unique_edges,
        paths=paths,
        backend=backend,
    )
