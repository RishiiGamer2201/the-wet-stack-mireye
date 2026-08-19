"""Before Construction — site investigation, scoring and what-if."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..adapters.mireye import MireyeClient, MireyeError
from ..config import get_settings
from ..domain import (
    CandidateSite,
    Evidence,
    EvidenceSource,
    EvidenceStatus,
    InformationGap,
    NextActionType,
    Project,
    SiteDimension,
    SiteObservation,
    SiteRanking,
    SiteScore,
    SourceType,
    VerificationStatus,
    gap_id,
)
from ..engine import scoring
from ..fields import DEFAULT_DIMENSION_WEIGHTS, UnknownFieldError, broad_fields, deep_fields
from ..store import C, Store
from .evidence import observations_for_site, put_gap, record_fetch

UTC = timezone.utc

log = logging.getLogger("sites")


def resolve_site_location(client: MireyeClient, site: CandidateSite) -> CandidateSite:
    """Geocode when only an address was given. Never invents coordinates."""
    if site.latitude is not None and site.longitude is not None:
        site.geocode_resolution = site.geocode_resolution or "parcel"
        return site
    if not site.address:
        return site
    result = client.geocode(site.address)
    site.latitude = result.latitude
    site.longitude = result.longitude
    site.geocode_resolution = result.resolution
    return site


def fetch_site_fields(
    store: Store,
    client: MireyeClient,
    project: Project,
    site: CandidateSite,
    field_keys: list[str],
) -> dict:
    """One Mireye /fetch round-trip recorded as evidence. Returns a tool-event dict."""
    if site.latitude is None or site.longitude is None:
        gap = InformationGap(
            id=gap_id(project.id, site.id, "coordinates"),
            project_id=project.id,
            subject_id=site.id,
            field_key="coordinates",
            description=f"{site.name} has no resolved coordinates.",
            why_it_matters="No physical-world evidence can be fetched without a location.",
            expected_source=SourceType.USER_INPUT,
            suggested_action=NextActionType.CLARIFICATION_REQUEST,
        )
        put_gap(store, gap, parent_id=site.id)
        return {
            "ok": False,
            "summary": f"{site.name}: no coordinates — 1 gap recorded, no values assumed.",
            "detail": {"gap_ids": [gap.id]},
            "evidence_ids": [],
            "gap_ids": [gap.id],
        }
    try:
        result = client.fetch(site.latitude, site.longitude, field_keys, site.mireye_site_id)
    except UnknownFieldError as exc:
        return {
            "ok": False,
            "summary": f"{site.name}: rejected unsupported field request ({exc}).",
            "detail": {"error": str(exc)},
            "evidence_ids": [],
            "gap_ids": [],
        }
    except MireyeError as exc:
        gaps = []
        for key in field_keys:
            gap = InformationGap(
                id=gap_id(project.id, site.id, key),
                project_id=project.id,
                subject_id=site.id,
                field_key=key,
                description=f"Mireye is unavailable, so {key} could not be retrieved for {site.name}.",
                why_it_matters="Scoring proceeds without this field and coverage is reduced.",
                expected_source=SourceType.MIREYE,
                suggested_action=NextActionType.CLARIFICATION_REQUEST,
                blocking=False,
            )
            put_gap(store, gap, parent_id=site.id)
            gaps.append(gap)
        log.warning("mireye fetch failed", extra={"site": site.id, "error": str(exc)})
        return {
            "ok": False,
            "summary": f"{site.name}: Mireye unavailable ({exc}); "
            f"{len(gaps)} field(s) recorded as gaps rather than assumed.",
            "detail": {"error": str(exc)},
            "evidence_ids": [],
            "gap_ids": [g.id for g in gaps],
        }

    evidences, observations, gaps = record_fetch(store, client, project.id, site, result)
    synthetic = sum(1 for e in evidences if e.status == EvidenceStatus.SYNTHETIC)
    return {
        "ok": True,
        "summary": (
            f"{site.name}: {len(observations) - len(gaps)} field(s) retrieved "
            f"({synthetic} synthetic), {len(gaps)} unavailable."
        ),
        "detail": {
            "mode": result.mode,
            "latency_ms": result.latency_ms,
            "fields": list(result.values),
            "unavailable": result.unavailable,
        },
        "evidence_ids": [e.id for e in evidences],
        "gap_ids": [g.id for g in gaps],
    }


class LiveBudget:
    """Caps live provider spend for one investigation.

    Mireye bills per field per location, so an unbounded sweep is an unbounded
    bill. Reaching a cap is not an error: the remaining sites record an
    InformationGap saying they were not looked at, which keeps the analysis
    honest instead of silently presenting partial coverage as complete.

    Mock mode is free, so the budget only binds when the client is live.
    """

    def __init__(self, client: MireyeClient, settings=None) -> None:
        settings = settings or get_settings()
        self.enforced = getattr(client, "mode", "mock") != "mock"
        self.max_locations = settings.mireye_max_live_locations
        self.max_fetches = settings.mireye_max_live_fetches
        self.locations: set[str] = set()
        self.fetches = 0

    def check(self, site: CandidateSite) -> str | None:
        """None when the fetch may proceed, otherwise why it may not."""
        if not self.enforced:
            return None
        if self.fetches >= self.max_fetches:
            return (
                f"the live fetch limit for this investigation ({self.max_fetches}) was reached"
            )
        if site.id not in self.locations and len(self.locations) >= self.max_locations:
            return (
                f"the live location limit for this investigation ({self.max_locations}) was reached"
            )
        return None

    def spend(self, site: CandidateSite) -> None:
        self.locations.add(site.id)
        self.fetches += 1


def _skipped_for_budget(
    store: Store, project: Project, site: CandidateSite, field_keys: list[str], reason: str
) -> dict:
    """Record why a site was not queried, as gaps rather than as absent data."""
    gaps = []
    for key in field_keys:
        gap = InformationGap(
            id=gap_id(project.id, site.id, key),
            project_id=project.id,
            subject_id=site.id,
            field_key=key,
            description=f"{key} was not requested for {site.name}: {reason}.",
            why_it_matters="No physical-world evidence was retrieved, so this field is "
            "excluded from the score and coverage is reduced. Raise the limit or "
            "investigate fewer sites at a time to close it.",
            expected_source=SourceType.MIREYE,
            suggested_action=NextActionType.CLARIFICATION_REQUEST,
            blocking=False,
        )
        put_gap(store, gap, parent_id=site.id)
        gaps.append(gap)
    log.warning("live budget reached", extra={"site": site.id, "reason": reason})
    return {
        "ok": False,
        "summary": f"{site.name}: not queried — {reason}; {len(gaps)} field(s) recorded as gaps.",
        "detail": {"reason": reason, "fields": field_keys},
        "evidence_ids": [],
        "gap_ids": [g.id for g in gaps],
    }


def _pass(store, client, project, sites, field_keys, budget: LiveBudget | None):
    budget = budget or LiveBudget(client)
    results = []
    for site in sites:
        reason = budget.check(site)
        if reason:
            results.append(_skipped_for_budget(store, project, site, field_keys, reason))
            continue
        budget.spend(site)
        results.append(fetch_site_fields(store, client, project, site, field_keys))
    return results


def broad_pass(
    store: Store,
    client: MireyeClient,
    project: Project,
    sites: list[CandidateSite],
    budget: LiveBudget | None = None,
):
    return _pass(store, client, project, sites, broad_fields(), budget)


def deep_pass(
    store: Store,
    client: MireyeClient,
    project: Project,
    sites: list[CandidateSite],
    budget: LiveBudget | None = None,
):
    return _pass(store, client, project, sites, deep_fields(), budget)


def score_sites(
    store: Store,
    project: Project,
    sites: list[CandidateSite],
    weights: dict[SiteDimension, float] | None = None,
) -> SiteRanking:
    weights = weights or project.dimension_weights or dict(DEFAULT_DIMENSION_WEIGHTS)
    scores: list[SiteScore] = []
    for site in sites:
        observations = observations_for_site(store, site.id, project.id)
        scores.append(
            scoring.score_site(project, site.id, site.name, observations, weights)
        )
    ranked = scoring.rank(scores)
    comparisons = [
        scoring.compare(ranked[i], ranked[i + 1], weights)
        for i in range(min(len(ranked) - 1, 3))
        if ranked[i].overall_score is not None
    ]
    # The ranking is derived state: it is stored on the investigation that produced
    # it, not as a standalone record, so it can never drift from its evidence.
    return SiteRanking(
        project_id=project.id, weights=weights, scores=ranked, comparisons=comparisons
    )


def shortlist(store: Store, ranking: SiteRanking, sites: list[CandidateSite], top_n: int = 2):
    """Mark the top N scored sites as shortlisted and persist the flag."""
    by_id = {s.id: s for s in sites}
    chosen: list[CandidateSite] = []
    for score in ranking.scores:
        site = by_id.get(score.site_id)
        if not site:
            continue
        site.shortlisted = score.rank is not None and score.rank <= top_n
        store.put(C.SITES, site, project_id=site.project_id)
        if site.shortlisted:
            chosen.append(site)
    return chosen


def override_observation(
    store: Store,
    project: Project,
    site: CandidateSite,
    field_key: str,
    value: float | str,
    note: str = "What-if override entered by the user",
) -> tuple[Evidence, SiteObservation]:
    """Record a user-supplied value as USER_CONFIRMED evidence.

    The previous evidence is superseded rather than deleted, so the provenance
    trail keeps both.
    """
    from ..fields import spec as field_spec

    fs = field_spec(field_key)
    previous = [
        e
        for e in store.list(C.EVIDENCE, Evidence, project_id=project.id, parent_id=site.id)
        if e.field_key == field_key and e.superseded_by is None
    ]
    ev = Evidence(
        project_id=project.id,
        subject_id=site.id,
        claim=f"{fs.label} at {site.name} (user override)",
        field_key=field_key,
        value=value,
        unit=fs.unit,
        source=EvidenceSource(
            source_type=SourceType.USER_INPUT,
            source_id=site.id,
            source_name="What-if override",
            field_key=field_key,
            notes=note,
        ),
        status=EvidenceStatus.USER_CONFIRMED,
        verification=VerificationStatus.VERIFIED,
        confidence=0.95,
        retrieved_at=datetime.now(UTC),
        latitude=site.latitude,
        longitude=site.longitude,
    )
    for old in previous:
        old.superseded_by = ev.id
        store.put(C.EVIDENCE, old, project_id=project.id, parent_id=site.id)
    obs = SiteObservation(
        site_id=site.id,
        project_id=project.id,
        field_key=field_key,
        dimension=fs.dimension,
        value=value,
        unit=fs.unit,
        evidence_id=ev.id,
        status=EvidenceStatus.USER_CONFIRMED,
        confidence=0.95,
    )
    store.put(C.EVIDENCE, ev, project_id=project.id, parent_id=site.id)
    store.put(C.OBSERVATIONS, obs, project_id=project.id, parent_id=site.id)
    return ev, obs
