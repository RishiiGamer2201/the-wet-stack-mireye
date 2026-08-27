"""Orchestrator Agent for During Construction Change Intelligence.

Coordinates:
1. Natural Language Requirement Parsing → Structured Engineering Constraints
2. Equipment Recommendation Engine → Hard Filter + Multi-Criteria Ranking + LLM Narrative
3. One-Click Change Impact Initialization (Recommended Product → 9 Gates + 13 Deltas + Margins + Impact Graph)
4. Action Package Generation (Formal RFIs, Vendor Information Requests, Review Packages)
5. Decision Lineage & Revision Stale Checks
"""

from __future__ import annotations

import json
import logging
import re

from ..adapters.equipment_specs import get_equipment_specs_adapter
from ..adapters.llm import get_llm
from ..domain import (
    DecisionState,
    Discipline,
    Equipment,
    EquipmentChange,
    EquipmentConfiguration,
    Investigation,
    ProductRecommendationResult,
    Project,
    Quantity,
    StructuredConstraint,
    StructuredRequirementSet,
    now,
)
from ..engine import catalog_engine
from ..schemas import ActionPackageResponse
from ..store import C, Store

log = logging.getLogger("change_orchestrator")


# ---------------------------------------------------------------------------
# 1. Natural Language Requirement Parsing
# ---------------------------------------------------------------------------


def parse_natural_language_requirements(
    prompt: str,
    equipment_type: str | None = None,
    project_id: str = "default",
) -> StructuredRequirementSet:
    """Extract structured engineering constraints from a natural language request.

    Deliberately deterministic. The parsing below is regex over the user's own
    words, so a constraint the system acts on is one the user actually typed. A
    language model reading "at least 1400 kW" and returning 1400 would be doing
    the same job less predictably, and the project's rule is that no number
    reaching an engineering check comes from a model.
    """
    constraints: list[StructuredConstraint] = []
    detected_type = equipment_type or "chiller"

    # Rule-based / Regex fallback parsing
    p_lower = prompt.lower()
    if "chiller" in p_lower:
        detected_type = "chiller"
    elif "crah" in p_lower:
        detected_type = "crah"
    elif "ahu" in p_lower:
        detected_type = "ahu"
    elif "cooling tower" in p_lower:
        detected_type = "cooling_tower"
    elif "pump" in p_lower:
        detected_type = "pump"
    elif "transformer" in p_lower:
        detected_type = "transformer"
    elif "ups" in p_lower:
        detected_type = "ups"
    elif "generator" in p_lower or "genset" in p_lower:
        detected_type = "generator"
    elif "switchgear" in p_lower:
        detected_type = "switchgear"
    elif "pdu" in p_lower:
        detected_type = "pdu"
    elif "heat exchanger" in p_lower or "economizer" in p_lower:
        detected_type = "heat_exchanger"

    # Capacity / Power
    cap_match = re.search(r"(?:at least|min|minimum|>=)?\s*(\d+(?:,\d+)*(?:\.\d+)?)\s*(kw|mw|tons?|kva|mva)", p_lower)
    if cap_match:
        val = float(cap_match.group(1).replace(",", ""))
        unit = cap_match.group(2)
        if "mw" in unit:
            val *= 1000.0
            unit = "kW"
        elif "mva" in unit:
            val *= 1000.0
            unit = "kVA"
        elif "kva" in unit:
            unit = "kVA"
        elif "ton" in unit:
            val *= 3.517
            unit = "kW"
        if "kva" in unit.lower() or detected_type == "transformer":
            parameter = "kva_rating"
        elif detected_type == "generator":
            parameter = "standby_rating"
        elif detected_type in {"ups", "pdu"}:
            parameter = "power_capacity"
        else:
            parameter = "cooling_capacity"
        constraints.append(
            StructuredConstraint(parameter=parameter, operator=">=", value=val, unit=unit, priority="mandatory")
        )

    if detected_type == "switchgear":
        amps_match = re.search(r"(\d+(?:,\d+)?)\s*(?:a|amps?|amperes?)\b", p_lower)
        if amps_match:
            constraints.append(
                StructuredConstraint(
                    parameter="bus_current",
                    operator=">=",
                    value=float(amps_match.group(1).replace(",", "")),
                    unit="A",
                    priority="mandatory",
                )
            )

    if detected_type == "pump":
        flow_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:l/s|lps|litres? per second)", p_lower)
        if flow_match:
            constraints.append(
                StructuredConstraint(
                    parameter="flow_rate",
                    operator=">=",
                    value=float(flow_match.group(1)),
                    unit="L/s",
                    priority="mandatory",
                )
            )

    # COP
    cop_match = re.search(r"cop\s*(?:above|at least|>=|>)?\s*(\d+(?:\.\d+)?)", p_lower)
    if cop_match:
        constraints.append(
            StructuredConstraint(parameter="cop", operator=">=", value=float(cop_match.group(1)), unit=None, priority="mandatory")
        )

    # Voltage
    volt_match = re.search(r"(\d{3,5})\s*v(?:olts?)?", p_lower)
    if volt_match:
        constraints.append(
            StructuredConstraint(parameter="voltage", operator="==", value=float(volt_match.group(1)), unit="V", priority="mandatory")
        )

    # Ambient
    amb_match = re.search(r"(?:ambient|temp(?:erature)?)\s*(?:of|up to|max|maximum|<=)?\s*(\d+(?:\.\d+)?)\s*(?:°?c|degc)", p_lower)
    if amb_match:
        constraints.append(
            StructuredConstraint(parameter="max_ambient", operator=">=", value=float(amb_match.group(1)), unit="degC", priority="mandatory")
        )

    # Footprint / Area
    area_match = re.search(r"(?:footprint|area)\s*(?:below|under|max|<=|<)?\s*(\d+(?:\.\d+)?)\s*(?:m2|sqm|m\^2)", p_lower)
    if area_match:
        constraints.append(
            StructuredConstraint(parameter="footprint", operator="<=", value=float(area_match.group(1)), unit="m2", priority="preferred")
        )

    # Weight
    wt_match = re.search(r"(?:weight|mass)\s*(?:under|below|max|<=|<)?\s*(\d+(?:,\d+)?)\s*(?:kg|tons?)", p_lower)
    if wt_match:
        val = float(wt_match.group(1).replace(",", ""))
        constraints.append(
            StructuredConstraint(parameter="weight", operator="<=", value=val, unit="kg", priority="preferred")
        )

    return StructuredRequirementSet(
        project_id=project_id,
        equipment_type=detected_type,
        constraints=constraints,
        original_prompt=prompt,
    )


# ---------------------------------------------------------------------------
# 2. Product Recommendation Engine & LLM Explanation
# ---------------------------------------------------------------------------


def generate_product_recommendations(
    project_id: str,
    equipment_type: str,
    requirement_set: StructuredRequirementSet | None = None,
    custom_weights: dict[str, float] | None = None,
    site_climate_db_c: float | None = None,
    limit: int = 20,
) -> ProductRecommendationResult:
    """Search catalog, deterministically score candidates, and generate explanation."""
    candidates = catalog_engine.search_and_rank_candidates(
        equipment_type=equipment_type,
        requirement_set=requirement_set,
        custom_weights=custom_weights,
        site_climate_db_c=site_climate_db_c,
        limit=limit,
    )

    top = next((candidate for candidate in candidates if candidate.compatibility_status != "INCOMPATIBLE"), None)
    narrative_lines = []
    if top:
        narrative_lines.append(
            f"**Recommended Selection: {top.model_number}** (Overall Compatibility Score: {top.score}/100)."
        )
        narrative_lines.append(f"- **Manufacturer & Source:** {top.manufacturer} ({top.reference_source}).")
        for p in top.passed_constraints[:4]:
            narrative_lines.append(f"- ✓ **Verified Target:** {p}")
        if top.warnings:
            for w in top.warnings:
                narrative_lines.append(f"- ⚠ **Engineering Notice:** {w}")
    else:
        narrative_lines.append("No compatible equipment models found matching the specified constraints.")

    # The model coordinates and explains the deterministic shortlist; it cannot
    # add candidates, alter scores, or write values used by an engineering check.
    llm = get_llm()
    if llm.available and candidates:
        explanation_payload = {
            "equipment_type": equipment_type,
            "constraints": [constraint.model_dump(mode="json") for constraint in (requirement_set.constraints if requirement_set else [])],
            "ranked_candidates": [
                {
                    "model_number": candidate.model_number,
                    "score": candidate.score,
                    "compatibility_status": candidate.compatibility_status,
                    "passed_constraints": candidate.passed_constraints,
                    "failed_constraints": candidate.failed_constraints,
                    "warnings": candidate.warnings,
                }
                for candidate in candidates[:5]
            ],
        }
        coordinated_note = llm.complete(
            system=(
                "You coordinate an equipment-substitution review. Explain only the supplied "
                "deterministic results in plain engineering language. Do not calculate, invent "
                "specifications, change rankings, or claim code compliance. State that synthetic "
                "catalog values require certified manufacturer submittals."
            ),
            user=json.dumps(explanation_payload, separators=(",", ":")),
            max_tokens=900,
        )
        if coordinated_note:
            narrative_lines.extend(["", "**LLM coordination note (explanation only):**", coordinated_note])

    return ProductRecommendationResult(
        project_id=project_id,
        equipment_type=equipment_type,
        requirement_set=requirement_set or StructuredRequirementSet(project_id=project_id, equipment_type=equipment_type),
        candidates=candidates,
        top_recommendation=top,
        explanation_narrative="\n".join(narrative_lines),
    )


# ---------------------------------------------------------------------------
# 3. Apply Recommendation to Change Case (One-Click Flow)
# ---------------------------------------------------------------------------


def apply_recommendation_as_change(
    project: Project,
    equipment_tag: str,
    candidate_product_id: str,
    store: Store,
    title: str | None = None,
    reason: str | None = None,
    site_id: str | None = None,
    existing_change_id: str | None = None,
) -> EquipmentChange:
    """Take a recommended catalog product and instantiate or update a change case."""
    adapter = get_equipment_specs_adapter()
    model = adapter.get_model_by_id(candidate_product_id)
    if not model:
        raise ValueError(f"Candidate product '{candidate_product_id}' not found in catalog.")

    # 1. Build Proposed Equipment record
    is_synthetic = bool(model.get("synthetic", False))
    discipline = (
        Discipline.ELECTRICAL
        if model.get("equipment_type") in {"transformer", "ups", "generator", "switchgear", "pdu"}
        else Discipline.MECHANICAL
    )
    p_cfg = EquipmentConfiguration(
        manufacturer=model.get("manufacturer", "Catalog Manufacturer"),
        model_number=model.get("model_number", model.get("id", "Model")),
        equipment_type=model.get("equipment_type", "equipment"),
        weight=Quantity(value=model["weight_kg"], unit="kg") if "weight_kg" in model else None,
        weight_basis="operating",
        length=Quantity(value=model["length_mm"], unit="mm") if "length_mm" in model else None,
        width=Quantity(value=model["width_mm"], unit="mm") if "width_mm" in model else None,
        height=Quantity(value=model["height_mm"], unit="mm") if "height_mm" in model else None,
        voltage=Quantity(value=model["voltage_v"], unit="V") if "voltage_v" in model else None,
        phases=model.get("phases"),
        full_load_amps=Quantity(value=model["full_load_amps_a"], unit="A") if "full_load_amps_a" in model else None,
        mca=Quantity(value=model["mca_a"], unit="A") if "mca_a" in model else None,
        mocp=Quantity(value=model["mocp_a"], unit="A") if "mocp_a" in model else None,
        power_input=Quantity(value=model["power_input_kw"], unit="kW") if "power_input_kw" in model else None,
        cooling_capacity=Quantity(value=model["cooling_capacity_kw"], unit="kW") if "cooling_capacity_kw" in model else None,
        refrigerant_type=model.get("refrigerant_type"),
        refrigerant_charge=Quantity(value=model["refrigerant_charge_kg"], unit="kg") if "refrigerant_charge_kg" in model else None,
        synthetic=is_synthetic,
    )

    proposed_eq = Equipment(
        project_id=project.id,
        tag=f"{equipment_tag}-PROP",
        name=f"Proposed Substitution - {model.get('model_number')}",
        discipline=discipline,
        configuration=p_cfg,
        synthetic=is_synthetic,
    )
    store.put(C.EQUIPMENT, proposed_eq, project_id=project.id)

    # 2. Check if an existing change exists or create a new one
    change = None
    if existing_change_id:
        change = store.get(C.CHANGES, existing_change_id, EquipmentChange)
        if change is None or change.project_id != project.id:
            raise ValueError("Existing change case was not found in this project")

    if not change:
        # Find existing baseline equipment or create a baseline
        existing_eqs = [
            e for e in store.list(C.EQUIPMENT, Equipment, project_id=project.id)
            if e.tag == equipment_tag
        ]
        if existing_eqs:
            existing_eq = existing_eqs[0]
        else:
            # Create standard baseline
            e_cfg = EquipmentConfiguration(
                manufacturer="Specified Baseline",
                model_number="Design-Basis-Spec",
                equipment_type=model.get("equipment_type", "equipment"),
                weight=Quantity(value=model.get("weight_kg", 5000) * 0.95, unit="kg"),
                weight_basis="operating",
                length=Quantity(value=model.get("length_mm", 4000), unit="mm"),
                width=Quantity(value=model.get("width_mm", 2000), unit="mm"),
                height=Quantity(value=model.get("height_mm", 2500), unit="mm"),
                voltage=Quantity(value=480, unit="V"),
                phases=3,
                full_load_amps=Quantity(value=model.get("full_load_amps_a", 250), unit="A"),
                mca=Quantity(value=model.get("mca_a", 310), unit="A"),
                mocp=Quantity(value=model.get("mocp_a", 350), unit="A"),
                power_input=Quantity(value=model.get("power_input_kw", 200), unit="kW"),
                cooling_capacity=Quantity(value=model.get("cooling_capacity_kw", 1200), unit="kW"),
                refrigerant_type=model.get("refrigerant_type", "R-134a"),
                synthetic=True,
            )
            existing_eq = Equipment(
                project_id=project.id,
                tag=equipment_tag,
                name=f"Specified {equipment_tag}",
                discipline=discipline,
                configuration=e_cfg,
                synthetic=True,
            )
            store.put(C.EQUIPMENT, existing_eq, project_id=project.id)

        change = EquipmentChange(
            project_id=project.id,
            title=title or f"Substitution: {model.get('model_number')}",
            reason=reason or f"Recommended substitution from {model.get('manufacturer')} catalog benchmark",
            equipment_tag=equipment_tag,
            site_id=site_id,
            existing_equipment_id=existing_eq.id,
            proposed_equipment_id=proposed_eq.id,
            submitted_by="Mireye Recommendation Coordinator",
            status="draft",
            synthetic=is_synthetic,
        )
    else:
        change.proposed_equipment_id = proposed_eq.id
        change.title = title or f"Substitution: {model.get('model_number')}"
        change.reason = reason or change.reason
        if site_id is not None:
            change.site_id = site_id

    store.put(C.CHANGES, change, project_id=project.id)
    return change


# ---------------------------------------------------------------------------
# 4. Action Package Generator (RFIs, Vendor Requests, Review Packages)
# ---------------------------------------------------------------------------


def generate_action_package(
    change: EquipmentChange,
    investigation: Investigation,
    action_type: str = "rfi",
    recipient: str | None = None,
    notes: str | None = None,
) -> ActionPackageResponse:
    """Generate structured markdown documentation package for engineering communication."""
    tag = change.equipment_tag
    dec_state = investigation.decision_state or DecisionState.ENGINEER_REVIEW
    triggered_deltas = [d for d in investigation.deltas if d.status.value == "TRIGGERED"]
    open_checks = [c for c in investigation.checks if c.status.value == "OPEN"]

    if action_type.lower() == "rfi":
        title = f"RFI #{tag}-001: Equipment Substitution Coordination for {tag}"
        target_recipient = recipient or "Engineer of Record (EOR) / Lead Mechanical Engineer"
        body = f"""# Request for Information (RFI)
**Subject:** Technical Submittal Coordination for {tag} — {change.title}  
**Project Reference:** {change.project_id}  
**To:** {target_recipient}  
**Date:** {now().strftime('%Y-%m-%d')}  
**Status:** High Priority Coordination  

---

### 1. Description of Proposed Change
The contractor proposes substituting specified equipment with **{change.title}**.  
Preliminary verification indicates the change is in state **`{dec_state.value}`**.

### 2. Engineering Deltas Requiring Confirmation
"""
        for d in triggered_deltas:
            pct_str = f" ({d.percent_delta:+.1f}% delta)" if d.percent_delta is not None else ""
            body += f"- **{d.label}:** Baseline `{d.old_value}` → Proposed `{d.new_value}`{pct_str}. *{d.explanation}*\n"
        if not triggered_deltas:
            body += "- All primary physical and thermodynamic deltas remain within first-pass coordination thresholds.\n"

        body += """
### 3. Information Required from EOR
1. Confirm structural roof beam and isolator pad capacity for the revised load distribution.
2. Confirm upstream feeder circuit breaker and cable tray fill for the revised MCA/MOCP ratings.
3. Confirm control sequence and BACnet/Modbus point mapping compatibility.

### 4. Attached Evidence
- Ingested vendor technical data and the Mireye synthetic prototype equipment catalog.
"""
        requested_items = [
            "Structural pad and beam calculation sign-off",
            "Electrical feeder sizing and breaker coordination confirmation",
            "BMS controls point list sign-off",
        ]

    elif action_type.lower() == "vendor_request":
        title = f"Vendor Evidence Request: Technical Submittal Package for {tag}"
        target_recipient = recipient or "Equipment Manufacturer / Technical Sales Engineer"
        body = f"""# Vendor Evidence & Clarification Request
**To:** {target_recipient}  
**Equipment Tag:** {tag}  
**Date:** {now().strftime('%Y-%m-%d')}  

---

### Mandatory Data Gaps to Close
The submittal for **{change.title}** cannot be cleared for engineering approval due to the following open items:
"""
        for c in open_checks:
            body += f"- **{c.name}:** {c.detail}\n"
        if not open_checks:
            body += "- Full certified performance curves at AHRI 550/590 rated entering/leaving water conditions.\n"
            body += "- Sound power spectrum (dBA across 63Hz - 8kHz octave bands).\n"

        body += """
Please furnish certified factory submittals within 5 business days to avoid construction schedule impacts.
"""
        requested_items = [
            "AHRI certified rating sheet with exact EWT/LWT conditions",
            "Point-load diagram indicating exact operating vs dry corner weights",
            "Factory acoustic test report",
        ]

    else:  # review_package
        title = f"Engineering Review Package: Technical Change Summary for {tag}"
        target_recipient = recipient or "Lead Commissioning & EPC Project Director"
        body = f"""# Engineering Change Review Package
**Subject:** Submittal Verification & Cascade Impact Summary — {tag}  
**Decision Verdict:** **`{dec_state.value}`**  

---

### Executive Summary
{investigation.recommendation.headline if investigation.recommendation else 'Verification analysis complete.'}

### Downstream Engineering Impacts
"""
        for imp in investigation.impacts:
            body += f"#### [{imp.discipline.value.upper()}] {imp.title}\n{imp.detail}\n"
            for act in imp.activities:
                body += f"  - [ ] {act}\n"

        requested_items = [
            "Inter-discipline coordination sign-off (Structural, Electrical, Mechanical)",
            "Stale assumption verification log update",
        ]

    return ActionPackageResponse(
        action_type=action_type,
        title=title,
        recipient=target_recipient,
        body_markdown=body,
        requested_items=requested_items,
        citations=[],
        due_in_days=5,
    )
