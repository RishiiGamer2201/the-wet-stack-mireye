"""Evidence recording, status lifecycle and information gaps."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ..adapters.mireye import FetchResult, MireyeClient
from ..domain import (
    CandidateSite,
    Evidence,
    EvidenceRelation,
    EvidenceSource,
    EvidenceStatus,
    InformationGap,
    NextActionType,
    SiteObservation,
    SourceType,
    VerificationStatus,
    gap_id,
)
from ..fields import FIELD_INDEX
from ..store import C, Store

UTC = timezone.utc

log = logging.getLogger("evidence")

#: A cached/live observation older than this is downgraded to STALE.
DEFAULT_MAX_AGE = timedelta(days=180)

STATUS_MAP = {
    "live": EvidenceStatus.LIVE,
    "cached": EvidenceStatus.CACHED,
    "synthetic": EvidenceStatus.SYNTHETIC,
    "fallback": EvidenceStatus.FALLBACK,
    "missing": EvidenceStatus.MISSING,
}

#: Statuses whose values did not come from a real observation.
NOT_OBSERVED = (EvidenceStatus.SYNTHETIC, EvidenceStatus.FALLBACK)


def evidence_from_field_value(
    project_id: str, site: CandidateSite, value, endpoint: str = "/v1/fetch"
) -> Evidence:
    spec = FIELD_INDEX.get(value.field_key)
    status = STATUS_MAP.get(value.status, EvidenceStatus.SYNTHETIC)

    # Keep what the provider actually said next to the value scoring uses, so a
    # converted number can always be traced back to its source reading.
    relation = getattr(value, "relation", EvidenceRelation.EXACT)
    provider_field = getattr(value, "provider_field", None)
    notes = value.note
    if relation == EvidenceRelation.CONTEXTUAL_PROXY:
        notes = f"CONTEXTUAL EVIDENCE - does not populate this field. {notes or ''}".strip()
    if provider_field:
        raw = getattr(value, "provider_value", None)
        raw_unit = getattr(value, "provider_unit", None) or ""
        confidence_word = getattr(value, "provider_confidence", None)
        trace = f"Provider field '{provider_field}' = {raw} {raw_unit}".strip()
        if confidence_word:
            trace += f" (provider confidence: {confidence_word})"
        notes = f"{trace}. {notes}" if notes else trace

    return Evidence(
        project_id=project_id,
        subject_id=site.id,
        claim=f"{spec.label if spec else value.field_key} at {site.name}",
        field_key=value.field_key,
        value=value.value,
        unit=value.unit,
        source=EvidenceSource(
            source_type=SourceType.MIREYE,
            source_id=provider_field or value.field_key,
            source_name=f"Mireye {endpoint} ({value.source})",
            field_key=value.field_key,
            endpoint=endpoint,
            url=getattr(value, "provider_source_url", None),
            synthetic=status in NOT_OBSERVED,
            notes=notes,
        ),
        status=status,
        relation=relation,
        relation_note=spec.provider_note if relation == EvidenceRelation.CONTEXTUAL_PROXY else None,
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
    project_id: str,
    site: CandidateSite,
    field_key: str,
    feature_request_id: str | None = None,
    *,
    proxy_only: bool = False,
) -> InformationGap:
    spec = FIELD_INDEX.get(field_key)
    label = spec.label if spec else field_key
    if proxy_only and spec:
        description = (
            f"{label} is not measured by Mireye for {site.name}. A related reading "
            f"('{spec.provider_field}') is recorded as context but is a different "
            "quantity, so it does not close this gap."
        )
    else:
        description = f"{label} is not available from Mireye for {site.name}."
    return InformationGap(
        id=gap_id(project_id, site.id, field_key),
        project_id=project_id,
        subject_id=site.id,
        field_key=field_key,
        description=description,
        why_it_matters=(
            spec.description
            if spec
            else "The field is required by the site scoring model."
        )
        + " The dimension score is computed without it and evidence coverage is reduced."
        + (f" {spec.provider_note}" if proxy_only and spec and spec.provider_note else ""),
        expected_source=SourceType.MIREYE,
        suggested_action=NextActionType.CLARIFICATION_REQUEST,
        blocking=False,
        feature_request_id=feature_request_id,
    )


def put_gap(store: Store, gap: InformationGap, *, parent_id: str | None = None) -> InformationGap:
    """Persist a gap under its stable id, keeping any human triage already applied.

    Gap ids are derived from (project, subject, field), so re-running an analysis
    updates the same record. A gap a user already marked *requested* or *resolved*
    keeps that status and its original creation time.
    """
    existing = store.get(C.GAPS, gap.id, InformationGap)
    if existing is not None:
        gap.status = existing.status
        gap.created_at = existing.created_at
        gap.feature_request_id = gap.feature_request_id or existing.feature_request_id
    store.put(C.GAPS, gap, project_id=gap.project_id, parent_id=parent_id)
    return gap


def record_fetch(
    store: Store,
    client: MireyeClient,
    project_id: str,
    site: CandidateSite,
    result: FetchResult,
) -> tuple[list[Evidence], list[SiteObservation], list[InformationGap]]:
    """Persist a /v1/fetch response as evidence + observations, and turn every
    unavailable field into a tracked gap plus a recorded feature request.

    A CONTEXTUAL_PROXY reading is stored as evidence — it is real, sourced and
    worth showing — but no `SiteObservation` is created for it. Observations are
    what scoring, coverage and the verification gates read, so withholding one is
    what stops a related-but-different measurement from populating a canonical
    value, closing its gap or passing a gate. The concept therefore stays
    missing, exactly as if the provider had nothing at all.
    """
    evidences: list[Evidence] = []
    observations: list[SiteObservation] = []
    gaps: list[InformationGap] = []
    proxy_keys: list[str] = []

    for key, value in result.values.items():
        ev = refresh_status(evidence_from_field_value(project_id, site, value))
        spec = FIELD_INDEX[key]
        store.put(C.EVIDENCE, ev, project_id=project_id, parent_id=site.id)
        evidences.append(ev)

        if not ev.is_canonical:
            proxy_keys.append(key)
            continue

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
        store.put(C.OBSERVATIONS, obs, project_id=project_id, parent_id=site.id)
        observations.append(obs)

    # A concept that only received a proxy is still missing its own measurement.
    for key in proxy_keys + list(result.unavailable):
        if key not in FIELD_INDEX:
            # A live service may report a field we do not model. Record nothing
            # rather than fabricating an observation with no dimension.
            log.warning("unavailable field is not in the catalog", extra={"field": key})
            continue
        feature_request_id = None
        try:
            feature_request_id = client.feature_request(
                key,
                reason=f"Field unavailable for {site.name} ({site.latitude}, {site.longitude})",
                context=f"project={project_id} site={site.id}",
            ).get("id")
        except Exception as exc:  # noqa: BLE001 - a failed feature request must not block
            log.warning("feature request failed", extra={"field": key, "error": str(exc)})
        spec = FIELD_INDEX[key]
        is_proxy_only = key in proxy_keys
        gap = gap_for_missing_field(project_id, site, key, feature_request_id, proxy_only=is_proxy_only)
        missing_ev = Evidence(
            project_id=project_id,
            subject_id=site.id,
            claim=f"{spec.label} at {site.name}",
            field_key=key,
            value=None,
            unit=spec.unit,
            source=EvidenceSource(
                source_type=SourceType.MIREYE,
                source_id=key,
                source_name="Mireye /v1/fetch",
                field_key=key,
                endpoint="/v1/fetch",
                notes=(
                    "Only contextual evidence is available for this concept — see the "
                    f"'{spec.provider_field}' record. No value substituted."
                    if is_proxy_only
                    else "Field reported unavailable - no value substituted."
                ),
            ),
            status=EvidenceStatus.MISSING,
            confidence=0.0,
        )
        obs = SiteObservation(
            site_id=site.id,
            project_id=project_id,
            field_key=key,
            dimension=spec.dimension,
            value=None,
            unit=spec.unit,
            evidence_id=missing_ev.id,
            status=EvidenceStatus.MISSING,
            confidence=0.0,
        )
        store.put(C.EVIDENCE, missing_ev, project_id=project_id, parent_id=site.id)
        store.put(C.OBSERVATIONS, obs, project_id=project_id, parent_id=site.id)
        put_gap(store, gap, parent_id=site.id)
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
