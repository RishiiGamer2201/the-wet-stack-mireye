"""Evidence provenance, status transitions and Mireye adapter behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.adapters.mireye import (
    FallbackMireyeClient,
    FieldValue,
    LiveMireyeClient,
    MireyeError,
    MireyeUnavailableError,
    MockMireyeClient,
)
from app.config import Settings
from app.domain import CandidateSite, Evidence, EvidenceStatus, SourceType
from app.fields import UnknownFieldError
from app.services import evidence as evidence_service
from app.services.sites import fetch_site_fields
from app.store import C


def site():
    return CandidateSite(
        id="site1", project_id="p1", name="Cascade Flats",
        latitude=47.4235, longitude=-120.3103, geocode_resolution="parcel",
    )


# --- provenance -------------------------------------------------------------


def test_recorded_evidence_keeps_full_provenance(store, seeded):
    client = MockMireyeClient()
    s = store.list(C.SITES, CandidateSite, project_id=seeded.id)[0]
    result = client.fetch(s.latitude, s.longitude, ["elevation_m", "flood_zone"])
    evidences, observations, gaps = evidence_service.record_fetch(
        store, client, seeded.id, s, result
    )
    ev = evidences[0]
    assert ev.source.source_type == SourceType.MIREYE
    assert ev.source.endpoint == "/v1/fetch"
    assert ev.source.field_key == ev.field_key
    assert ev.retrieved_at and ev.observed_at
    assert ev.latitude == s.latitude and ev.location_resolution == "parcel"
    assert ev.status == EvidenceStatus.SYNTHETIC and ev.source.synthetic is True
    assert 0 <= ev.confidence <= 1
    assert len(observations) == 2 and not gaps


def test_unavailable_field_becomes_a_gap_with_a_feature_request(store, seeded):
    client = MockMireyeClient()
    s = next(
        x
        for x in store.list(C.SITES, CandidateSite, project_id=seeded.id)
        if x.name == "Prairie Junction"
    )
    result = client.fetch(s.latitude, s.longitude, ["grid_capacity_mw", "elevation_m"])
    evidences, _, gaps = evidence_service.record_fetch(store, client, seeded.id, s, result)
    assert [g.field_key for g in gaps] == ["grid_capacity_mw"]
    assert gaps[0].feature_request_id
    missing = next(e for e in evidences if e.field_key == "grid_capacity_mw")
    assert missing.status == EvidenceStatus.MISSING and missing.value is None


def test_stale_transition_is_explicit_and_keeps_the_value():
    ev = Evidence(
        claim="old observation",
        source=evidence_service.EvidenceSource(
            source_type=SourceType.MIREYE, source_id="elevation_m", source_name="Mireye"
        ),
        value=320,
        status=EvidenceStatus.CACHED,
        observed_at=datetime.now(UTC) - timedelta(days=400),
    )
    evidence_service.refresh_status(ev)
    assert ev.status == EvidenceStatus.STALE
    assert ev.value == 320
    assert "older than" in ev.stale_reason


def test_missing_evidence_is_never_aged_into_something_else():
    ev = Evidence(
        claim="missing",
        source=evidence_service.EvidenceSource(
            source_type=SourceType.MIREYE, source_id="x", source_name="Mireye"
        ),
        status=EvidenceStatus.MISSING,
        observed_at=datetime.now(UTC) - timedelta(days=999),
    )
    assert evidence_service.refresh_status(ev).status == EvidenceStatus.MISSING


# --- mock adapter -----------------------------------------------------------


def test_mock_is_deterministic_for_the_same_coordinates():
    client = MockMireyeClient()
    a = client.fetch(10.0, 20.0, ["elevation_m"]).values["elevation_m"].value
    b = client.fetch(10.0, 20.0, ["elevation_m"]).values["elevation_m"].value
    assert a == b


def test_unknown_field_is_rejected_not_invented():
    with pytest.raises(UnknownFieldError):
        MockMireyeClient().fetch(47.4, -120.3, ["unicorn_density"])


def test_geocode_returns_resolution_information():
    result = MockMireyeClient().geocode("somewhere unmapped")
    assert result.resolution in ("city", "parcel")
    assert -90 <= result.latitude <= 90


def test_site_apis_round_trip():
    client = MockMireyeClient()
    site_id = client.create_site("S", 47.4, -120.3, None)
    assert client.get_site(site_id)["name"] == "S"
    assert "demo" in client.ask_site(site_id, "flood risk?").answer.lower()
    with pytest.raises(MireyeError):
        client.get_site("nope")


# --- live adapter: retries, failure, fallback -------------------------------


def _live(handler, store, retries=2):
    settings = Settings(
        mireye_base_url="https://mireye.test",
        mireye_api_key="k",
        mireye_max_retries=retries,
        mireye_timeout_seconds=1,
    )
    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="https://mireye.test", transport=transport)
    return LiveMireyeClient(settings, store, client=http)


def test_live_client_retries_then_raises(store):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, json={"error": "unavailable"})

    client = _live(handler, store, retries=2)
    with pytest.raises(MireyeUnavailableError):
        client.geocode("anywhere")
    assert calls["n"] == 3  # initial + 2 retries


def test_live_client_caches_repeat_fetches(store):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if request.url.path == "/v1/meta/fields":
            return httpx.Response(200, json={"fields": [{"key": "elevation_m"}]})
        return httpx.Response(
            200,
            json={
                "results": {
                    "elevation_m": {
                        "value": 321,
                        "unit": "m",
                        "confidence": 0.9,
                        "source": "usgs",
                        "observed_at": "2025-01-01T00:00:00+00:00",
                    }
                },
                "unavailable": [],
            },
        )

    client = _live(handler, store)
    first = client.fetch(47.4, -120.3, ["elevation_m"])
    second = client.fetch(47.4, -120.3, ["elevation_m"])
    assert first.values["elevation_m"].status == "live"
    assert second.values["elevation_m"].status == "cached"
    assert calls["n"] == 2  # meta + one fetch; the second fetch was served from cache


def test_live_client_marks_fields_the_server_omits_as_unavailable(store):
    def handler(request):
        if request.url.path == "/v1/meta/fields":
            return httpx.Response(
                200, json={"fields": [{"key": "elevation_m"}, {"key": "flood_zone"}]}
            )
        return httpx.Response(200, json={"results": {}, "unavailable": []})

    result = _live(handler, store).fetch(47.4, -120.3, ["elevation_m", "flood_zone"])
    assert sorted(result.unavailable) == ["elevation_m", "flood_zone"]
    assert not result.values


def test_fallback_client_degrades_to_mock_and_records_the_reason(store):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    fallback = FallbackMireyeClient(_live(handler, store, retries=0), MockMireyeClient())
    result = fallback.fetch(47.4235, -120.3103, ["elevation_m"])
    assert fallback.mode == "degraded_mock"
    assert fallback.degraded_reason
    assert result.values["elevation_m"].status == "synthetic"


def test_service_records_gaps_when_mireye_is_down(store, seeded):
    class Down:
        mode = "live"

        def fetch(self, *a, **kw):
            raise MireyeUnavailableError("service unavailable")

        def feature_request(self, *a, **kw):
            return {"id": None}

    s = store.list(C.SITES, CandidateSite, project_id=seeded.id)[0]
    result = fetch_site_fields(store, Down(), seeded, s, ["elevation_m", "flood_zone"])
    assert result["ok"] is False
    assert len(result["gap_ids"]) == 2
    assert "Mireye unavailable" in result["summary"]


def test_service_records_a_gap_when_a_site_has_no_coordinates(store, seeded):
    s = CandidateSite(project_id=seeded.id, name="No location")
    result = fetch_site_fields(store, MockMireyeClient(), seeded, s, ["elevation_m"])
    assert result["ok"] is False and result["gap_ids"]


def test_field_value_dataclass_carries_status_and_source():
    fv = FieldValue(
        field_key="elevation_m",
        value=1,
        unit="m",
        confidence=0.5,
        observed_at=None,
        retrieved_at=datetime.now(UTC),
        source="test",
        status="live",
    )
    assert fv.endpoint == "/v1/fetch"
