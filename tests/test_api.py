"""API contract tests and one end-to-end happy path per workflow."""

from __future__ import annotations

from app.domain import CandidateSite, EquipmentChange
from app.store import C


def project_id(api) -> str:
    return api.get("/api/projects").json()[0]["id"]


# --- basics -----------------------------------------------------------------


def test_health_ready_and_meta(api):
    assert api.get("/api/health").json()["status"] == "ok"
    ready = api.get("/api/ready").json()
    assert ready["ready"] is True
    assert "mireye" in ready["checks"]
    meta = api.get("/api/meta").json()
    assert meta["demo_mode"] is True
    assert meta["services"]["mireye"] == "mock"
    assert meta["mireye_field_count"] > 20
    assert "not professional engineering approval" in meta["disclaimer"]


def test_openapi_is_generated(api):
    schema = api.get("/openapi.json").json()
    assert "/api/projects/{project_id}/ranking" in schema["paths"]


def test_startup_autoseeds_a_demo_project(api):
    projects = api.get("/api/projects").json()
    assert len(projects) == 1 and projects[0]["synthetic"] is True


def test_unknown_project_returns_a_helpful_404(api):
    response = api.get("/api/projects/prj_missing")
    assert response.status_code == 404
    assert "seed" in response.json()["detail"]


def test_mireye_field_catalog_endpoint(api):
    body = api.get("/api/mireye/fields").json()
    assert body["count"] > 20
    assert all("key" in f for f in body["fields"])


# --- validation -------------------------------------------------------------


def test_site_creation_requires_a_location(api):
    response = api.post(f"/api/projects/{project_id(api)}/sites", json={"name": "Nowhere"})
    assert response.status_code == 422


def test_site_creation_rejects_impossible_coordinates(api):
    response = api.post(
        f"/api/projects/{project_id(api)}/sites",
        json={"name": "Off world", "latitude": 130, "longitude": 0},
    )
    assert response.status_code == 422


def test_geocoding_fills_coordinates_from_an_address(api):
    response = api.post(
        f"/api/projects/{project_id(api)}/sites",
        json={"name": "Address only", "address": "1 Industrial Way, Somewhere"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["latitude"] is not None and body["geocode_resolution"]


def test_negative_weights_are_rejected(api):
    response = api.patch(
        f"/api/projects/{project_id(api)}", json={"dimension_weights": {"power": -1}}
    )
    assert response.status_code == 422


def test_search_requires_a_real_query(api):
    assert api.get(f"/api/projects/{project_id(api)}/search?q=+").status_code == 422


def test_upload_rejects_a_non_pdf(api):
    response = api.post(
        f"/api/projects/{project_id(api)}/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 422


def test_impact_graph_404s_before_analysis(api):
    assert api.get("/api/impact/chg_never_analysed").status_code == 404


# --- end to end: Before Construction ----------------------------------------


def test_before_construction_end_to_end(api, store):
    pid = project_id(api)
    sites = api.get(f"/api/projects/{pid}/sites").json()
    assert len(sites) >= 3

    investigation = api.post(f"/api/projects/{pid}/investigations/site", json={}).json()
    assert investigation["status"] == "completed"
    assert investigation["phase"] == "done"
    assert [s["phase"] for s in investigation["steps"]]
    assert investigation["replan_notes"]
    assert investigation["decision_state"] in (
        "FIRST-PASS CHECKS CLOSED",
        "NEEDS INFORMATION",
        "ENGINEER REVIEW",
    )
    ranking = investigation["ranking"]
    assert ranking["scores"][0]["rank"] == 1
    assert ranking["comparisons"]
    assert investigation["recommendation"]["headline"]
    assert investigation["next_actions"]

    # evidence is traceable
    evidence = api.get(f"/api/projects/{pid}/evidence").json()
    assert evidence and all(e["source"]["source_type"] for e in evidence)
    one = api.get(f"/api/evidence/{evidence[0]['id']}").json()
    assert one["id"] == evidence[0]["id"]

    # information gaps are visible
    gaps = api.get(f"/api/projects/{pid}/gaps").json()
    assert gaps and all(g["why_it_matters"] for g in gaps)
    resolved = api.patch(
        f"/api/projects/{pid}/gaps/{gaps[0]['id']}", json={"status": "requested"}
    ).json()
    assert resolved["status"] == "requested"


def test_weight_change_recomputes_the_ranking(api):
    pid = project_id(api)
    api.post(f"/api/projects/{pid}/investigations/site", json={})
    power_heavy = api.post(
        f"/api/projects/{pid}/ranking",
        json={"weights": {d: 0.1 for d in ["geo_terrain", "water", "connectivity", "civil_soil",
                                           "hazards_climate", "environmental", "regulatory"]}
        | {"power": 6.0}},
    ).json()
    water_heavy = api.post(
        f"/api/projects/{pid}/ranking",
        json={"weights": {d: 0.1 for d in ["geo_terrain", "power", "connectivity", "civil_soil",
                                           "hazards_climate", "environmental", "regulatory"]}
        | {"water": 6.0}},
    ).json()
    assert power_heavy["ranking"]["scores"][0]["overall_score"] != (
        water_heavy["ranking"]["scores"][0]["overall_score"]
    )
    assert power_heavy["explanation"]


def test_what_if_override_changes_the_score_and_is_recorded_as_user_evidence(api):
    pid = project_id(api)
    api.post(f"/api/projects/{pid}/investigations/site", json={})
    sites = api.get(f"/api/projects/{pid}/sites").json()
    target = next(s for s in sites if s["name"] == "Delta Fields")
    before = api.post(f"/api/projects/{pid}/ranking", json={}).json()["ranking"]
    before_score = next(s for s in before["scores"] if s["site_id"] == target["id"])["overall_score"]

    response = api.post(
        f"/api/projects/{pid}/sites/{target['id']}/override",
        json={"field_key": "grid_capacity_mw", "value": 450, "note": "utility letter received"},
    ).json()
    after = next(s for s in response["ranking"]["scores"] if s["site_id"] == target["id"])
    assert after["overall_score"] > before_score
    assert response["explanation"]

    evidence = api.get(
        f"/api/projects/{pid}/evidence",
        params={"subject_id": target["id"], "field_key": "grid_capacity_mw"},
    ).json()
    assert any(e["status"] == "user_confirmed" for e in evidence)
    assert any(e["superseded_by"] for e in evidence)


def test_override_of_an_unknown_field_is_rejected(api):
    pid = project_id(api)
    sites = api.get(f"/api/projects/{pid}/sites").json()
    response = api.post(
        f"/api/projects/{pid}/sites/{sites[0]['id']}/override",
        json={"field_key": "vibes_index", "value": 1},
    )
    assert response.status_code == 422


# --- end to end: During Construction ----------------------------------------


def _change_by_tag(api, pid, tag):
    return next(c for c in api.get(f"/api/projects/{pid}/changes").json() if c["equipment_tag"] == tag)


def test_during_construction_end_to_end(api):
    pid = project_id(api)
    change = _change_by_tag(api, pid, "CH-01")

    detail = api.get(f"/api/projects/{pid}/changes/{change['id']}").json()
    assert detail["existing"]["configuration"]["model_number"] == "NT-1100"
    assert detail["proposed"]["configuration"]["model_number"] == "VX-1150"
    assert detail["assumptions"]

    investigation = api.post(f"/api/projects/{pid}/changes/{change['id']}/analyze", json={}).json()
    assert investigation["status"] == "completed"
    assert investigation["decision_state"] == "ENGINEER REVIEW"

    statuses = {c["key"]: c["status"] for c in investigation["checks"]}
    assert statuses["site_compatibility"] == "TRIGGERED"
    assert statuses["model_identity"] == "CLOSED"

    weight = next(d for d in investigation["deltas"] if d["field"] == "weight")
    assert weight["status"] == "TRIGGERED"
    assert round(weight["percent_delta"], 2) == 9.07

    disciplines = {i["discipline"] for i in investigation["impacts"]}
    assert {"structural", "electrical", "mechanical", "controls"} <= disciplines
    assert investigation["stale_assumption_ids"]
    assert any(a["type"] == "review_comment" for a in investigation["next_actions"])
    assert any("structural adequacy" in c for c in investigation["recommendation"]["caveats"])

    graph = api.get(f"/api/impact/{change['id']}").json()
    assert {n["kind"] for n in graph["nodes"]} >= {
        "change", "assumption", "discipline", "activity", "commissioning"
    }
    assert graph["paths"]


def test_like_for_like_change_closes_first_pass(api):
    pid = project_id(api)
    change = _change_by_tag(api, pid, "CH-02")
    investigation = api.post(f"/api/projects/{pid}/changes/{change['id']}/analyze", json={}).json()
    assert investigation["decision_state"] == "FIRST-PASS CHECKS CLOSED"
    assert investigation["impacts"] == []
    assert any(a["type"] == "human_confirmation" for a in investigation["next_actions"])


def test_incomplete_submittal_needs_information(api):
    pid = project_id(api)
    change = _change_by_tag(api, pid, "PDU-3")
    investigation = api.post(f"/api/projects/{pid}/changes/{change['id']}/analyze", json={}).json()
    assert investigation["decision_state"] == "NEEDS INFORMATION"
    assert any(s["added_in_replan"] for s in investigation["steps"])
    gaps = api.get(f"/api/projects/{pid}/gaps").json()
    assert any(g["subject_id"] == change["id"] for g in gaps)
    assert any(a["type"] == "vendor_evidence_request" for a in investigation["next_actions"])


# --- documents & requirements -----------------------------------------------


def test_requirement_confirmation_updates_evidence_status(api):
    pid = project_id(api)
    requirements = api.get(f"/api/projects/{pid}/requirements").json()
    target = next(r for r in requirements if r["field_key"] == "cooling_capacity")
    updated = api.patch(
        f"/api/projects/{pid}/requirements/{target['id']}",
        json={"value": 1045, "unit": "kW", "confirmed": True, "confirmed_by": "EOR"},
    ).json()
    assert updated["confirmed"] is True
    assert updated["corrected_from"] == str(target["value"])
    evidence = api.get(f"/api/evidence/{updated['evidence_id']}").json()
    assert evidence["status"] == "user_confirmed"
    assert evidence["value"] == 1045


def test_document_upload_and_retrieval(api, tmp_path):
    from app.seed import write_sample_pdf

    pid = project_id(api)
    path = write_sample_pdf(
        tmp_path / "extra.pdf",
        "extra",
        ["Unit AHU-9 shall provide a minimum net cooling capacity of 300 kW."],
    )
    response = api.post(
        f"/api/projects/{pid}/documents",
        files={"file": ("extra.pdf", path.read_bytes(), "application/pdf")},
        data={"kind": "specification"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["chunk_count"] >= 1
    assert any(r["field_key"] == "cooling_capacity" for r in body["requirements"])

    chunks = api.get(
        f"/api/projects/{pid}/documents/{body['document']['id']}/chunks"
    ).json()
    assert chunks and chunks[0]["embedding"] is None

    results = api.get(f"/api/projects/{pid}/search", params={"q": "AHU-9 cooling capacity"}).json()
    assert results["results"] and results["backend"]


def test_ask_endpoint_is_labelled_exploratory(api):
    pid = project_id(api)
    body = api.post(
        f"/api/projects/{pid}/ask", json={"question": "Is this site prone to flooding?"}
    ).json()
    assert body["mode"] == "mock"
    assert "Exploratory" in body["disclaimer"]


def test_seed_and_reset_endpoints(api, store):
    pid = project_id(api)
    assert api.post("/api/admin/reset").status_code == 200
    assert api.get("/api/projects").json() == []
    seeded = api.post("/api/admin/seed").json()
    assert seeded["project_id"] != pid
    assert store.list(C.SITES, CandidateSite, project_id=seeded["project_id"])
    assert store.list(C.CHANGES, EquipmentChange, project_id=seeded["project_id"])
