"""Stale-assumption propagation, impact derivation and graph traversal."""

from __future__ import annotations

from app.adapters.graphstore import InMemoryGraphStore
from app.domain import (
    Assumption,
    AssumptionStatus,
    CheckStatus,
    DeltaResult,
    Discipline,
    EngineeringCheck,
    Quantity,
    Severity,
)
from app.engine import impact


def delta(field, status=CheckStatus.TRIGGERED, direction="increase", pct=9.0):
    return DeltaResult(
        field=field,
        label=field,
        old_value=Quantity(value=1, unit="kg"),
        new_value=Quantity(value=2, unit="kg"),
        percent_delta=pct,
        direction=direction,
        status=status,
        severity=Severity.HIGH,
        explanation=f"{field} changed by {pct}%",
    )


def check(key, status=CheckStatus.TRIGGERED):
    return EngineeringCheck(
        key=key, name=key, status=status, severity=Severity.HIGH, detail=f"{key} detail"
    )


def assumptions():
    return [
        Assumption(
            project_id="p1", statement="Dunnage sized for 4850 kg", discipline=Discipline.STRUCTURAL,
            depends_on_fields=["weight", "support_point_load_max"], equipment_tag="CH-01",
        ),
        Assumption(
            project_id="p1", statement="Feeder sized for 265 A", discipline=Discipline.ELECTRICAL,
            depends_on_fields=["mca", "mocp"], equipment_tag="CH-01",
        ),
        Assumption(
            project_id="p1", statement="Controls points list matches NT-1100",
            discipline=Discipline.CONTROLS, depends_on_fields=["model_identity"],
            equipment_tag="CH-01",
        ),
    ]


def test_only_affected_assumptions_go_stale():
    items = assumptions()
    stale = impact.mark_stale_assumptions(items, [delta("weight")], [])
    assert [a.statement for a in stale] == ["Dunnage sized for 4850 kg"]
    assert items[1].status == AssumptionStatus.ACTIVE
    assert "Upstream evidence changed" in items[0].stale_reason


def test_unchanged_delta_does_not_stale_anything():
    stale = impact.mark_stale_assumptions(
        assumptions(), [delta("weight", CheckStatus.CLOSED, "unchanged", 0.0)], []
    )
    assert stale == []


def test_stale_is_idempotent():
    items = assumptions()
    impact.mark_stale_assumptions(items, [delta("weight")], [])
    again = impact.mark_stale_assumptions(items, [delta("weight")], [])
    assert again == []


def test_triggered_check_also_stales_assumptions():
    items = assumptions()
    stale = impact.mark_stale_assumptions(items, [], [check("model_identity")])
    assert [a.discipline for a in stale] == [Discipline.CONTROLS]


def test_impacts_cover_the_expected_disciplines():
    items = assumptions()
    deltas = [delta("weight"), delta("mca"), delta("refrigerant_charge"), delta("length")]
    stale = impact.mark_stale_assumptions(items, deltas, [])
    impacts = impact.derive_impacts("chg1", deltas, [], stale)
    disciplines = {i.discipline for i in impacts}
    assert Discipline.STRUCTURAL in disciplines
    assert Discipline.ELECTRICAL in disciplines
    assert Discipline.MECHANICAL in disciplines
    assert Discipline.INSTALLATION_LOGISTICS in disciplines
    structural = next(i for i in impacts if i.discipline == Discipline.STRUCTURAL)
    assert structural.requires_human
    assert "does not assess structural adequacy" in structural.detail
    assert structural.commissioning


def test_no_trigger_means_no_impact():
    assert impact.derive_impacts("chg1", [delta("weight", CheckStatus.CLOSED, "unchanged", 0)], [], []) == []


def test_graph_path_reaches_commissioning():
    items = assumptions()
    deltas = [delta("weight")]
    stale = impact.mark_stale_assumptions(items, deltas, [])
    impacts = impact.derive_impacts("chg1", deltas, [], stale)
    graph = impact.build_graph("chg1", "CH-01 substitution", impacts, stale)
    kinds = {n.kind for n in graph.nodes}
    assert {"change", "assumption", "discipline", "activity", "commissioning"} <= kinds
    assert any(len(p) >= 5 for p in graph.paths)
    relations = {e.relation for e in graph.edges}
    assert {"INVALIDATES", "AFFECTS", "REQUIRES", "VERIFIED_BY"} <= relations


def test_in_memory_graph_store_traversal_round_trip():
    store = InMemoryGraphStore()
    items = assumptions()
    deltas = [delta("weight"), delta("mca")]
    stale = impact.mark_stale_assumptions(items, deltas, [])
    impacts = impact.derive_impacts("chg1", deltas, [], stale)
    store.upsert(impact.build_graph("chg1", "CH-01", impacts, stale))

    traversed = store.traverse("chg1")
    assert traversed is not None
    assert traversed.backend == "in_memory"
    assert any(n.kind == "commissioning" for n in traversed.nodes)
    assert store.traverse("does-not-exist") is None


def test_graph_reflects_a_different_change():
    store = InMemoryGraphStore()
    items = assumptions()
    small = [delta("length", pct=1.0)]
    stale = impact.mark_stale_assumptions(items, small, [])
    impacts = impact.derive_impacts("chg2", small, [], stale)
    store.upsert(impact.build_graph("chg2", "CH-02", impacts, stale))
    graph = store.traverse("chg2")
    assert not any(n.kind == "discipline" and "Structural" in n.label for n in graph.nodes)
