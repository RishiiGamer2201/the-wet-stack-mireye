"""Final decision state and next-action generation (diagram §5, §6, §7).

Precedence, matching the architecture flow:

1. Any blocking OPEN check or gap  → NEEDS INFORMATION   (evidence insufficient)
2. Otherwise any TRIGGERED result  → ENGINEER REVIEW     (judgement needed)
3. Otherwise                       → FIRST-PASS CHECKS CLOSED

"FIRST-PASS CHECKS CLOSED" means the deterministic first-pass checks found no
open item — it is not an engineering approval.
"""

from __future__ import annotations

from ..domain import (
    CheckStatus,
    DecisionState,
    DeltaResult,
    EngineeringCheck,
    GapStatus,
    Impact,
    InformationGap,
    NextAction,
    NextActionType,
    Recommendation,
    Severity,
)

SAFETY_CAVEAT = (
    "This platform performs first-pass deterministic checks only. It flags where "
    "structural, electrical or mechanical coordination is required; it does not assert "
    "structural adequacy and is not professional engineering approval."
)


def decide(
    checks: list[EngineeringCheck],
    deltas: list[DeltaResult],
    gaps: list[InformationGap],
) -> tuple[DecisionState, list[str]]:
    open_checks = [c for c in checks if c.status == CheckStatus.OPEN]
    open_deltas = [d for d in deltas if d.status == CheckStatus.OPEN]
    blocking_gaps = [g for g in gaps if g.blocking and g.status != GapStatus.RESOLVED]
    triggered_checks = [c for c in checks if c.status == CheckStatus.TRIGGERED]
    triggered_deltas = [d for d in deltas if d.status == CheckStatus.TRIGGERED]

    rationale: list[str] = []
    if open_checks or open_deltas or blocking_gaps:
        rationale.append(
            f"{len(open_checks)} verification gate(s) and {len(open_deltas)} delta(s) "
            f"could not be evaluated because required evidence is missing."
        )
        for c in open_checks[:4]:
            rationale.append(f"OPEN - {c.name}: {c.detail}")
        for d in open_deltas[:3]:
            rationale.append(f"OPEN - {d.label}: {d.explanation}")
        return DecisionState.NEEDS_INFORMATION, rationale

    if triggered_checks or triggered_deltas:
        rationale.append(
            f"All required evidence is present, and {len(triggered_checks) + len(triggered_deltas)} "
            "result(s) exceed a deterministic threshold and need engineering judgement."
        )
        for c in triggered_checks[:4]:
            rationale.append(f"TRIGGERED - {c.name}: {c.detail}")
        for d in triggered_deltas[:4]:
            rationale.append(f"TRIGGERED - {d.label}: {d.explanation}")
        return DecisionState.ENGINEER_REVIEW, rationale

    rationale.append(
        f"{sum(1 for c in checks if c.status == CheckStatus.CLOSED)} verification gate(s) and "
        f"{sum(1 for d in deltas if d.status == CheckStatus.CLOSED)} delta(s) closed with no "
        "threshold exceeded and no missing evidence."
    )
    return DecisionState.FIRST_PASS_CHECKS_CLOSED, rationale


def build_recommendation(
    state: DecisionState,
    rationale: list[str],
    checks: list[EngineeringCheck],
    impacts: list[Impact],
    confidence: float,
) -> Recommendation:
    headline = {
        DecisionState.NEEDS_INFORMATION: "Hold - required evidence is missing",
        DecisionState.ENGINEER_REVIEW: "Route to engineer review before approval",
        DecisionState.FIRST_PASS_CHECKS_CLOSED: "First-pass checks closed - ready for engineer sign-off",
    }[state]
    caveats = [SAFETY_CAVEAT]
    if any(i.requires_human for i in impacts):
        disciplines = sorted({i.discipline.value for i in impacts if i.requires_human})
        caveats.append(
            "Human confirmation required from: " + ", ".join(d.replace("_", " ") for d in disciplines) + "."
        )
    if any(c.status == CheckStatus.SKIPPED for c in checks):
        skipped = [c.name for c in checks if c.status == CheckStatus.SKIPPED]
        caveats.append("Not applicable to this case: " + ", ".join(skipped) + ".")
    return Recommendation(
        headline=headline,
        rationale=rationale,
        decision_state=state,
        confidence=round(confidence, 3),
        caveats=caveats,
    )


def _bullet(items: list[str]) -> str:
    return "\n".join(f"  {i}. {t}" for i, t in enumerate(items, start=1))


def build_next_actions(
    state: DecisionState,
    change_title: str,
    equipment_tag: str,
    gaps: list[InformationGap],
    checks: list[EngineeringCheck],
    impacts: list[Impact],
) -> list[NextAction]:
    """Turn findings into the concrete request that unblocks them."""
    actions: list[NextAction] = []
    open_gaps = [g for g in gaps if g.status != GapStatus.RESOLVED]

    by_action: dict[NextActionType, list[InformationGap]] = {}
    for g in open_gaps:
        by_action.setdefault(g.suggested_action, []).append(g)

    recipients = {
        NextActionType.VENDOR_EVIDENCE_REQUEST: "Equipment vendor / manufacturer representative",
        NextActionType.RFI: "Design team (Architect / Engineer of Record)",
        NextActionType.CLARIFICATION_REQUEST: "Project controls / site survey team",
        NextActionType.REVIEW_COMMENT: "Submittal reviewer",
        NextActionType.HUMAN_CONFIRMATION: "Engineer of Record",
    }

    for action_type, items in by_action.items():
        requested = [f"{g.description} ({g.why_it_matters})" for g in items]
        actions.append(
            NextAction(
                type=action_type,
                title=f"{action_type.value.replace('_', ' ').title()} - {equipment_tag}: {change_title}",
                recipient=recipients[action_type],
                body=(
                    f"Regarding equipment {equipment_tag} ({change_title}), first-pass automated "
                    f"verification could not be closed. The following items are required before the "
                    f"substitution can be evaluated:\n\n{_bullet(requested)}\n\n"
                    "Please supply the source document or dataset for each item, including the "
                    "rating conditions each value is stated at.\n\n" + SAFETY_CAVEAT
                ),
                requested_items=requested,
                related_gap_ids=[g.id for g in items],
                due_in_days=5 if action_type != NextActionType.RFI else 10,
            )
        )

    if state == DecisionState.ENGINEER_REVIEW:
        triggered = [c for c in checks if c.status == CheckStatus.TRIGGERED]
        points = [f"{c.name}: {c.detail}" for c in triggered] + [
            f"{i.discipline.value.replace('_', ' ').title()}: {i.title}" for i in impacts
        ]
        actions.append(
            NextAction(
                type=NextActionType.REVIEW_COMMENT,
                title=f"Review comment - {equipment_tag}: {change_title}",
                recipient=recipients[NextActionType.REVIEW_COMMENT],
                body=(
                    f"Automated first-pass verification of {equipment_tag} completed with evidence "
                    f"present, but the following results exceed coordination thresholds and require "
                    f"engineering judgement:\n\n{_bullet(points)}\n\n" + SAFETY_CAVEAT
                ),
                requested_items=points,
                due_in_days=5,
            )
        )
        actions.append(
            NextAction(
                type=NextActionType.HUMAN_CONFIRMATION,
                title=f"Engineer confirmation required - {equipment_tag}",
                recipient=recipients[NextActionType.HUMAN_CONFIRMATION],
                body=(
                    "Confirm the extracted requirements and accept or reject the substitution. "
                    "Deterministic checks and downstream impacts are attached.\n\n" + SAFETY_CAVEAT
                ),
                due_in_days=3,
            )
        )

    if state == DecisionState.FIRST_PASS_CHECKS_CLOSED:
        actions.append(
            NextAction(
                type=NextActionType.HUMAN_CONFIRMATION,
                title=f"Engineer sign-off - {equipment_tag}: {change_title}",
                recipient=recipients[NextActionType.HUMAN_CONFIRMATION],
                body=(
                    f"All first-pass verification gates for {equipment_tag} closed with no missing "
                    "evidence and no threshold exceeded. Engineer sign-off is still required to "
                    "approve the substitution.\n\n" + SAFETY_CAVEAT
                ),
                due_in_days=3,
            )
        )
    return actions


def severity_weight(sev: Severity) -> int:
    return {
        Severity.INFO: 0,
        Severity.LOW: 1,
        Severity.MEDIUM: 2,
        Severity.HIGH: 3,
        Severity.CRITICAL: 4,
    }[sev]


def decision_confidence(
    checks: list[EngineeringCheck], deltas: list[DeltaResult], synthetic_share: float
) -> float:
    """Confidence in the *decision*, not in the equipment.

    Falls with unevaluated checks and with the share of synthetic demo evidence.
    """
    total = len(checks) + len(deltas)
    if not total:
        return 0.0
    evaluated = sum(1 for c in checks if c.status != CheckStatus.OPEN) + sum(
        1 for d in deltas if d.status != CheckStatus.OPEN
    )
    base = evaluated / total
    return round(max(0.0, min(1.0, base * (1 - 0.35 * synthetic_share))), 3)
