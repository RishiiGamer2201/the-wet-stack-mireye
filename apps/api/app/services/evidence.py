"""Evidence recording, status lifecycle and information gaps."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from ..adapters.mireye import FetchResult, MireyeClient
from ..domain import (
    CandidateSite,
    Evidence,
    EvidenceSource,
    EvidenceStatus,
    InformationGap,
    NextActionType,
    SiteObservation,
    SourceType,
    VerificationStatus,
)
from ..fields import FIELD_INDEX
from ..store import C, Store

log = logging.getLogger("evidence")

#: A cached/live observation older than this is downgraded to STALE.
DEFAULT_MAX_AGE = timedelta(days=180)

STATUS_MAP = {
    "live": EvidenceStatus.LIVE,
    "cached": EvidenceStatus.CACHED,
    "synthetic": EvidenceStatus.SYNTHETIC,
    "missing": EvidenceStatus.MISSING,
}


def evidence_from_field_value(
    project_id: str, site: CandidateSite, value, endpoint: str = "/v1/fetch"
) -> Evidence:
    spec = FIELD_INDEX.get(value.field_key)
    status = STATUS_MAP.get(value.status, EvidenceStatus.SYNTHETIC)
    return Evidence(
        project_id=project_id,
        subject_id=site.id,
        claim=f"{spec.label if spec else value.field_key} at {site.name}",
        field_key=value.field_key,
        value=value.value,
        unit=value.unit,
        source=EvidenceSource(
            source_type=SourceType.MIREYE,
            source_id=value.field_key,
            source_name=f"Mireye {endpoint} ({value.source})",
            field_key=value.field_key,
            endpoint=endpoint,
            synthetic=status == EvidenceStatus.SYNTHETIC,
            notes=value.note,
        ),
        status=status,
        verification=VerificationStatus.UNVERIFIED,
        confidence=value.confidence,
        retrieved_at=value.retrieved_at,
        observed_at=value.observed_at,
        latitude=value.latitude,
        longitude=value.longitude,
        location_resolution=site.geocode_resolution,
    )


def refresh_status(evidence: Evidence, max_age: timedelta = DEFAULT_MAX_AGE) -> Evidence:
    """Age out an observation. A stale item keeps its value but stops being usable
    for scoring at full confidence — it is never silently refreshed."""
    if evidence.status in (EvidenceStatus.MISSING, EvidenceStatus.STALE):
        return evidence
    reference = evidence.observed_at or evidence.retrieved_at
    if reference and reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    if reference and datetime.now(UTC) - reference > max_age:
        evidence.mark_stale(
            f"Observation is older than {max_age.days} days "
            f"(observed {reference.date().isoformat()})."
        )
    return evidence


def gap_for_missing_field(
    project_id: str, site: CandidateSite, field_key: str, feature_request_id: str | None = None
) -> InformationGap:
    spec = FIELD_INDEX.get(field_key)
    label = spec.label if spec else field_key
    return InformationGap(
        project_id=project_id,
        subject_id=site.id,
        field_key=field_key,
        description=f"{label} is not available from Mireye for {site.name}.",
        why_it_matters=(
            spec.description
            if spec
            else "The field is required by the site scoring model."
        )
        + " The dimension score is computed without it and evidence coverage is reduced.",
        expected_source=SourceType.MIREYE,
        suggested_action=NextActionType.CLARIFICATION_REQUEST,
        blocking=False,
        feature_request_id=feature_request_id,
    )


def record_fetch(
    store: Store,
    client: MireyeClient,
    project_id: str,
    site: CandidateSite,
    result: FetchResult,
) -> tuple[list[Evidence], list[SiteObservation], list[InformationGap]]:
    """Persist a /v1/fetch response as evidence + observations, and turn every
    unavailable field into a tracked gap plus a Mireye feature request."""
    evidences: list[Evidence] = []
    observations: list[SiteObservation] = []
    gaps: list[InformationGap] = []

    for key, value in result.values.items():
        ev = refresh_status(evidence_from_field_value(project_id, site, value))
        spec = FIELD_INDEX[key]
        obs = SiteObservation(
            site_id=site.id,
            project_id=project_id,
            field_key=key,
            dimension=spec.dimension,
            value=value.value,
            unit=value.unit,
            evidence_id=ev.id,
            status=ev.status,
            confidence=ev.confidence,
            observed_at=value.observed_at,
            retrieved_at=value.retrieved_at,
        )
        store.put(C.EVIDENCE, ev, project_id=project_id, parent_id=site.id)
        store.put(C.OBSERVATIONS, obs, project_id=project_id, parent_id=site.id)
        evidences.append(ev)
        observations.append(obs)

    for key in result.unavailable:
        feature_request_id = None
        try:
            feature_request_id = client.feature_request(
                key,
                reason=f"Field unavailable for {site.name} ({site.latitude}, {site.longitude})",
                context=f"project={project_id} site={site.id}",
            ).get("id")
        except Exception as exc:  # noqa: BLE001 - a failed feature request must not block
            log.warning("feature request failed", extra={"field": key, "error": str(exc)})
        gap = gap_for_missing_field(project_id, site, key, feature_request_id)
        spec = FIELD_INDEX.get(key)
        missing_ev = Evidence(
            project_id=project_id,
            subject_id=site.id,
            claim=f"{spec.label if spec else key} at {site.name}",
            field_key=key,
            value=None,
            unit=spec.unit if spec else None,
            source=EvidenceSource(
                source_type=SourceType.MIREYE,
                source_id=key,
                source_name="Mireye /v1/fetch",
                field_key=key,
                endpoint="/v1/fetch",
                notes="Field reported unavailable — no value substituted.",
            ),
            status=EvidenceStatus.MISSING,
            confidence=0.0,
        )
        obs = SiteObservation(
            site_id=site.id,
            project_id=project_id,
            field_key=key,
            dimension=spec.dimension if spec else None,
            value=None,
            unit=spec.unit if spec else None,
            evidence_id=missing_ev.id,
            status=EvidenceStatus.MISSING,
            confidence=0.0,
        )
        store.put(C.EVIDENCE, missing_ev, project_id=project_id, parent_id=site.id)
        store.put(C.OBSERVATIONS, obs, project_id=project_id, parent_id=site.id)
        store.put(C.GAPS, gap, project_id=project_id, parent_id=site.id)
        evidences.append(missing_ev)
        observations.append(obs)
        gaps.append(gap)

    return evidences, observations, gaps


def observations_for_site(store: Store, site_id: str, project_id: str) -> list[SiteObservation]:
    """Latest observation per field (later writes win)."""
    rows = store.list(C.OBSERVATIONS, SiteObservation, project_id=project_id, parent_id=site_id)
    latest: dict[str, SiteObservation] = {}
    for obs in rows:
        latest[obs.field_key] = obs
    return list(latest.values())
