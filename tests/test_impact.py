"""Stale-assumption propagation, impact derivation and graph traversal."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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

REPO_ROOT = Path(__file__).resolve().parents[1]


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
    """Re-analysing the same change must report the same invalidated assumptions,
    without rewriting the reason or the timestamp of one already marked stale."""
    items = assumptions()
    first = impact.mark_stale_assumptions(items, [delta("weight")], [])
    reason, updated = first[0].stale_reason, first[0].updated_at
    again = impact.mark_stale_assumptions(items, [delta("weight")], [])
    assert [a.id for a in again] == [a.id for a in first]
    assert again[0].stale_reason == reason
    assert again[0].updated_at == updated
    assert items[1].status == AssumptionStatus.ACTIVE


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


def test_node_ids_are_stable_across_processes():
    """`hash()` is salted per process; the graph must be reproducible."""
    items, deltas = assumptions(), [delta("weight")]
    stale = impact.mark_stale_assumptions(items, deltas, [])
    impacts = impact.derive_impacts("chg1", deltas, [], stale)
    # Assumption ids are per-record uuids; only the derived ids must be stable.
    derived = lambda g: sorted(  # noqa: E731
        n.id for n in g.nodes if n.kind in ("activity", "commissioning", "discipline")
    )
    ids = derived(impact.build_graph("chg1", "CH-01", impacts, stale))
    assert ids == derived(impact.build_graph("chg1", "CH-01", impacts, stale))
    assert any(i.startswith("activity:structural:") for i in ids)
    # Recomputed in a fresh interpreter with a different PYTHONHASHSEED.
    code = (
        f"import sys; sys.path.insert(0, r'{REPO_ROOT}');"
        "from tests.test_impact import assumptions, delta;"
        "from app.engine import impact;"
        "i=assumptions(); d=[delta('weight')];"
        "s=impact.mark_stale_assumptions(i,d,[]);"
        "im=impact.derive_impacts('chg1',d,[],s);"
        "g=impact.build_graph('chg1','CH-01',im,s);"
        "print('\\n'.join(sorted(n.id for n in g.nodes "
        "if n.kind in ('activity','commissioning','discipline'))))"
    )
    env = {**os.environ, "PYTHONHASHSEED": "12345", "PYTHONPATH": str(REPO_ROOT / "apps" / "api")}
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(REPO_ROOT)
    )
    assert out.returncode == 0, out.stderr
    assert sorted(out.stdout.split()) == sorted(ids)


def test_reanalysis_replaces_a_change_subgraph_instead_of_growing_it():
    store = InMemoryGraphStore()
    items, deltas = assumptions(), [delta("weight"), delta("mca")]
    stale = impact.mark_stale_assumptions(items, deltas, [])
    impacts = impact.derive_impacts("chg1", deltas, [], stale)
    store.upsert(impact.build_graph("chg1", "CH-01", impacts, stale))
    first = store.traverse("chg1")

    # Same analysis run again: identical graph, not a bigger one.
    store.upsert(impact.build_graph("chg1", "CH-01", impacts, stale))
    assert len(store.traverse("chg1").edges) == len(first.edges)

    # The evidence is corrected and nothing is triggered any more.
    store.upsert(impact.build_graph("chg1", "CH-01", [], []))
    after = store.traverse("chg1")
    assert after.edges == [] and [n.kind for n in after.nodes] == ["change"]


def test_graph_reflects_a_different_change():
    store = InMemoryGraphStore()
    items = assumptions()
    small = [delta("length", pct=1.0)]
    stale = impact.mark_stale_assumptions(items, small, [])
    impacts = impact.derive_impacts("chg2", small, [], stale)
    store.upsert(impact.build_graph("chg2", "CH-02", impacts, stale))
    graph = store.traverse("chg2")
    assert not any(n.kind == "discipline" and "Structural" in n.label for n in graph.nodes)
