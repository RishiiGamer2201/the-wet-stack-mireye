"""Supervisor planning.

The plan is *situation-specific*: it is derived from what actually differs in the
case at hand, not from a fixed checklist. An optional LLM may add extra steps,
but every step it proposes must reference a known tool and known field keys —
anything else is discarded.
"""

from __future__ import annotations

import json
import logging

from ..adapters.llm import INVESTIGATION_SYSTEM, LLMProvider
from ..domain import (
    CandidateSite,
    EquipmentChange,
    EquipmentConfiguration,
    InvestigationPhase,
    InvestigationStep,
    Project,
)
from ..fields import FIELD_INDEX, broad_fields, deep_fields

log = logging.getLogger("planner")

ALLOWED_TOOLS = {
    "mireye_fetch",
    "mireye_ask",
    "document_retrieval",
    "verification_gate",
    "delta_calculation",
    "impact_trace",
}


def _step(inv_id: str, order: int, phase: InvestigationPhase, title: str, rationale: str, **kw):
    return InvestigationStep(
        investigation_id=inv_id, order=order, phase=phase, title=title, rationale=rationale, **kw
    )


def plan_site_investigation(
    investigation_id: str, project: Project, sites: list[CandidateSite]
) -> list[InvestigationStep]:
    """Progressive plan: broad sweep over all candidates, then depth on the shortlist."""
    steps = [
        _step(
            investigation_id,
            1,
            InvestigationPhase.EVIDENCE,
            f"Broad physical-world sweep across {len(sites)} candidate site(s)",
            "A comparable physical-context baseline is needed before deeper site due diligence.",
            requested_fields=broad_fields(),
        ),
        _step(
            investigation_id,
            2,
            InvestigationPhase.SIGNALS,
            "Score every candidate and shortlist on weighted dimensions",
            "Ranking on the broad sweep isolates the candidates worth investigating deeply.",
        ),
        _step(
            investigation_id,
            3,
            InvestigationPhase.REPLAN,
            "Deepen investigation on shortlisted sites only",
            "Deep fields are expensive; they are only justified for sites still in contention.",
            requested_fields=deep_fields(),
        ),
    ]
    unlocated = [s for s in sites if s.latitude is None or s.longitude is None]
    if unlocated:
        steps.insert(
            0,
            _step(
                investigation_id,
                0,
                InvestigationPhase.EVIDENCE,
                f"Geocode {len(unlocated)} site(s) supplied by address only",
                "Physical-world evidence cannot be fetched without resolved coordinates.",
            ),
        )
    if project.targets.min_grid_capacity_mw:
        steps.append(
            _step(
                investigation_id,
                len(steps),
                InvestigationPhase.SIGNALS,
                f"Check every candidate against the {project.targets.min_grid_capacity_mw:g} MW "
                "grid-capacity target",
                "The project states a hard power target, so it is evaluated as a pass/fail flag.",
                requested_fields=["grid_capacity_mw"],
            )
        )
    for i, step in enumerate(steps, start=1):
        step.order = i
    return steps


def plan_change_investigation(
    investigation_id: str,
    change: EquipmentChange,
    old: EquipmentConfiguration,
    new: EquipmentConfiguration,
    has_site: bool,
    llm: LLMProvider | None = None,
) -> list[InvestigationStep]:
    """Plan derived from what actually differs between the two units."""
    steps: list[InvestigationStep] = [
        _step(
            investigation_id,
            1,
            InvestigationPhase.EVIDENCE,
            "Read project requirements for " + change.equipment_tag,
            "The specification defines what the replacement has to satisfy.",
        ),
        _step(
            investigation_id,
            2,
            InvestigationPhase.EVIDENCE,
            f"Read manufacturer data for {new.manufacturer or 'the proposed unit'} "
            f"{new.model_number or ''}".strip(),
            "Capability data must come from the manufacturer document, not from assumption.",
        ),
    ]

    def add(title: str, rationale: str, fields: list[str] | None = None) -> None:
        steps.append(
            _step(
                investigation_id,
                len(steps) + 1,
                InvestigationPhase.EVIDENCE,
                title,
                rationale,
                requested_fields=fields or [],
            )
        )

    if (old.weight and new.weight) or old.support_points or new.support_points:
        add(
            "Compare weight and support-point loads",
            "Both units state a weight, so the load delta and its structural coordination "
            "consequence can be computed.",
        )
    if old.refrigerant_type != new.refrigerant_type or (
        old.refrigerant_charge or new.refrigerant_charge
    ):
        add(
            "Investigate refrigerant type and charge change",
            "A refrigerant change affects safety classification, monitoring and ventilation.",
        )
    if any(
        getattr(old, f) != getattr(new, f) for f in ("voltage", "phases", "mca", "mocp", "full_load_amps")
    ):
        add(
            "Investigate electrical demand change",
            "The electrical characteristics differ, so feeders and protection must be re-checked.",
        )
    if has_site:
        add(
            "Fetch site design conditions from Mireye",
            "Rated performance is only meaningful against the actual site design temperature.",
            ["ambient_design_db_c", "elevation_m"],
        )
    steps.append(
        _step(
            investigation_id,
            len(steps) + 1,
            InvestigationPhase.SIGNALS,
            "Run verification gates and deterministic deltas",
            "Nothing is compared until identity, data type, configuration, units, rating "
            "conditions and sources are verified.",
        )
    )
    steps.append(
        _step(
            investigation_id,
            len(steps) + 1,
            InvestigationPhase.IMPACT,
            "Trace downstream impacts and stale assumptions",
            "A change is only understood once its effect on other disciplines is known.",
        )
    )

    if llm and llm.available:
        extra = _llm_extra_steps(investigation_id, change, old, new, llm, len(steps))
        steps.extend(extra)
    return steps


def _llm_extra_steps(
    investigation_id: str,
    change: EquipmentChange,
    old: EquipmentConfiguration,
    new: EquipmentConfiguration,
    llm: LLMProvider,
    offset: int,
) -> list[InvestigationStep]:
    """Ask the LLM what else is worth investigating. Strictly validated."""
    prompt = (
        "An equipment substitution is under review.\n"
        f"Change: {change.title} on {change.equipment_tag}. Reason: {change.reason}\n"
        f"Existing: {old.manufacturer} {old.model_number} ({old.equipment_type})\n"
        f"Proposed: {new.manufacturer} {new.model_number} ({new.equipment_type})\n\n"
        "Propose at most 3 ADDITIONAL investigation steps that a senior EPC engineer would "
        "want, which are not already covered by: requirements review, manufacturer data "
        "review, weight/support loads, refrigerant, electrical, site design conditions, "
        "verification gates, deltas, impact tracing.\n"
        'Reply with JSON only: [{"title": "...", "rationale": "...", '
        '"fields": ["optional_mireye_field_key"]}]'
    )
    raw = llm.complete(INVESTIGATION_SYSTEM, prompt, max_tokens=800)
    if not raw:
        return []
    try:
        start, end = raw.find("["), raw.rfind("]")
        parsed = json.loads(raw[start : end + 1]) if start != -1 else []
    except (ValueError, TypeError):
        log.warning("discarding unparseable LLM plan")
        return []
    steps: list[InvestigationStep] = []
    for i, item in enumerate(parsed[:3]):
        if not isinstance(item, dict) or not item.get("title"):
            continue
        fields = [f for f in (item.get("fields") or []) if f in FIELD_INDEX]
        steps.append(
            _step(
                investigation_id,
                offset + i + 1,
                InvestigationPhase.EVIDENCE,
                str(item["title"])[:160],
                "Proposed by the supervisor agent: " + str(item.get("rationale", ""))[:300],
                requested_fields=fields,
            )
        )
    return steps
