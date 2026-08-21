"""Public-dataset adapters.

Mireye is the physical-world layer, but its catalog does not cover every concept
the scoring model needs. Rather than leave those permanently missing — or worse,
fill them with a proxy — some can be served from public datasets that are free,
citable and downloadable.

Each adapter here follows the same rules as the Mireye adapter:

  * it serves the *actual* measurement or it serves nothing;
  * a value it cannot produce becomes an InformationGap, never a default;
  * every value carries its source, licence, download date and coordinates.

Most of this data is downloaded once into `DATA_DIR/datasets/` and read from
disk after that, so an investigation never depends on a third party being up.
The Water Quality Portal is the exception: no practical bulk extract exists, so
it is queried per location and the answer cached to disk. A failed query returns
nothing and the concept stays a gap, exactly as if it had never been asked.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import httpx

from ..config import get_settings
from ..domain import EvidenceRelation

UTC = timezone.utc

log = logging.getLogger("datasets")

#: Datasets small enough to ship with the code live here, so a fresh deploy on an
#: empty disk still has them. DATA_DIR wins when a newer download exists there.
BUNDLED_DIR = Path(__file__).resolve().parent.parent / "data" / "datasets"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _dataset_path(filename: str) -> Path:
    downloaded = get_settings().data_dir / "datasets" / filename
    if downloaded.exists():
        return downloaded
    bundled = BUNDLED_DIR / filename
    return bundled if bundled.exists() else downloaded

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance. Good to ~0.5% at these ranges, which is far tighter
    than the siting decisions it informs."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass
class DatasetValue:
    """One value from a public dataset, with everything needed to cite it."""

    field_key: str
    value: float | str | None
    unit: str | None
    source: str
    source_url: str
    licence: str
    downloaded_at: str | None
    detail: str | None = None
    confidence: float = 0.9
    #: EXACT populates the concept. CONTEXTUAL_PROXY is a real, cited, *different*
    #: measurement: readable, but it never fills the value or closes the gap.
    relation: EvidenceRelation = EvidenceRelation.EXACT
    relation_note: str | None = None


class DatasetProvider(Protocol):
    name: str
    fields: tuple[str, ...]

    def values_for(self, latitude: float, longitude: float) -> dict[str, DatasetValue]: ...


class PeeringDBFacilities:
    """Interconnection facilities from PeeringDB.

    PeeringDB is the industry's own registry of where networks physically meet.
    `/api/fac` returns facilities with coordinates and, per facility, how many
    internet exchanges, networks and carriers are present.

    This serves *distance to the nearest facility hosting an internet exchange* —
    a measured distance, not a stand-in for latency. Latency depends on the route
    and the carrier, so `latency_to_ix_ms` stays an open gap; claiming distance
    answers it would be the same mistake as reading wet-bulb as dry-bulb.
    """

    name = "peeringdb"
    fields = ("distance_to_ix_km", "ix_facility_carrier_count")

    API_URL = "https://www.peeringdb.com/api/fac"
    LICENCE = "PeeringDB, CC-BY 4.0"
    #: Beyond this there is no meaningful interconnection story to tell, and a
    #: number would imply a precision the concept does not have.
    MAX_USEFUL_KM = 400.0

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _dataset_path("peeringdb_facilities.json")
        self._payload: dict | None = None

    # -- data ---------------------------------------------------------------
    def download(self, country: str = "US", timeout: float = 120.0) -> int:
        """Fetch the dataset to disk. Explicit, never triggered by a request.

        Always writes under DATA_DIR, never over the bundled copy, so a download
        is a local override that a `git checkout` can never silently undo.
        """
        response = httpx.get(self.API_URL, params={"country": country, "limit": 0}, timeout=timeout)
        response.raise_for_status()
        rows = response.json()["data"]
        facilities = [
            {
                k: f.get(k)
                for k in (
                    "id",
                    "name",
                    "city",
                    "state",
                    "latitude",
                    "longitude",
                    "ix_count",
                    "net_count",
                    "carrier_count",
                )
            }
            for f in rows
            if f.get("latitude") and f.get("longitude")
        ]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "_source": f"PeeringDB /api/fac?country={country}",
                    "_url": self.API_URL,
                    "_licence": self.LICENCE,
                    "_downloaded_at": datetime.now(UTC).isoformat(),
                    "facilities": facilities,
                }
            ),
            encoding="utf-8",
        )
        self._payload = None
        log.info(
            "peeringdb downloaded", extra={"facilities": len(facilities), "path": str(self._path)}
        )
        return len(facilities)

    @property
    def available(self) -> bool:
        return self._path.exists()

    def _load(self) -> dict:
        if self._payload is None:
            if not self._path.exists():
                raise FileNotFoundError(
                    f"{self._path} is missing. Run `python -m app.datasets_cli download peeringdb`."
                )
            self._payload = json.loads(self._path.read_text(encoding="utf-8"))
        return self._payload

    # -- lookup -------------------------------------------------------------
    def values_for(self, latitude: float, longitude: float) -> dict[str, DatasetValue]:
        try:
            payload = self._load()
        except (FileNotFoundError, ValueError) as exc:
            log.warning("peeringdb unavailable", extra={"error": str(exc)})
            return {}

        exchanges = [
            f
            for f in payload["facilities"]
            if (f.get("ix_count") or 0) > 0 and f.get("latitude") and f.get("longitude")
        ]
        if not exchanges:
            return {}

        nearest, distance = None, float("inf")
        for facility in exchanges:
            d = haversine_km(
                latitude, longitude, float(facility["latitude"]), float(facility["longitude"])
            )
            if d < distance:
                nearest, distance = facility, d

        if nearest is None or distance > self.MAX_USEFUL_KM:
            # Genuinely far from any exchange. Report nothing rather than a number
            # that would score as if it were a near miss.
            return {}

        downloaded = payload.get("_downloaded_at")
        cite = f"{nearest['name']} ({nearest.get('city') or '?'}, {nearest.get('state') or '?'})"
        values = {
            "distance_to_ix_km": DatasetValue(
                field_key="distance_to_ix_km",
                value=round(distance, 3),
                unit="km",
                source=f"PeeringDB facility {nearest['id']}",
                source_url=f"https://www.peeringdb.com/fac/{nearest['id']}",
                licence=self.LICENCE,
                downloaded_at=downloaded,
                detail=f"Nearest facility hosting an internet exchange: {cite}; "
                f"{nearest.get('ix_count')} exchange(s), {nearest.get('net_count')} network(s).",
            )
        }
        carriers = nearest.get("carrier_count")
        if carriers is not None:
            values["ix_facility_carrier_count"] = DatasetValue(
                field_key="ix_facility_carrier_count",
                value=float(carriers),
                unit=None,
                source=f"PeeringDB facility {nearest['id']}",
                source_url=f"https://www.peeringdb.com/fac/{nearest['id']}",
                licence=self.LICENCE,
                downloaded_at=downloaded,
                detail=f"Carriers present at {cite}.",
            )
        return values


class WaterQualityPortal:
    """Measured total dissolved solids from the EPA/USGS Water Quality Portal.

    The Portal aggregates water-sample results from USGS, EPA and state agencies.
    A query returns real laboratory results from real monitoring stations, which
    is the closest public evidence there is to what a site would actually pump.

    It is *not* the site's water. The sample came from someone else's well some
    kilometres away, so every value here is CONTEXTUAL_PROXY: it informs the
    recommendation, is shown with its station, date and distance, and never fills
    `water_quality_tds_mg_l` or closes its gap. Only a sample from the site's own
    supply can do that, which is exactly why the gap stays open.
    """

    name = "water_quality_portal"
    fields = ("water_quality_tds_mg_l",)

    API_URL = "https://www.waterqualitydata.us/data/Result/search"
    LICENCE = "EPA/USGS Water Quality Portal, public domain (US Government work)"
    SEARCH_RADIUS_KM = 40
    #: Older than this and the reading describes an aquifer that may have moved on.
    STALE_AFTER_YEARS = 15
    TIMEOUT_SECONDS = 30.0

    def __init__(self, path: Path | None = None, *, allow_fetch: bool = True) -> None:
        self._path = path or (get_settings().data_dir / "datasets" / "wqp_tds_cache.json")
        self._allow_fetch = allow_fetch
        self._cache: dict | None = None

    # -- cache ---------------------------------------------------------------
    def _load_cache(self) -> dict:
        """Bundled answers first, then anything queried since on this disk.

        Writes always go to DATA_DIR, so caching a query never edits the checkout.
        """
        if self._cache is None:
            self._cache = _read_json(BUNDLED_DIR / self._path.name)
            self._cache.update(_read_json(self._path))
        return self._cache

    def _save_cache(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._cache), encoding="utf-8")

    @property
    def available(self) -> bool:
        return self._path.exists()

    @staticmethod
    def _key(latitude: float, longitude: float) -> str:
        # ~100 m. Two sites this close share an aquifer, so they share the answer.
        return f"{latitude:.3f},{longitude:.3f}"

    # -- data ----------------------------------------------------------------
    def download(self, latitude: float, longitude: float) -> dict | None:
        """Query the Portal for one location and cache the result."""
        params = {
            "lat": f"{latitude}",
            "long": f"{longitude}",
            "within": str(self.SEARCH_RADIUS_KM),
            "characteristicName": "Total dissolved solids",
            "mimeType": "csv",
            "dataProfile": "resultPhysChem",
            "startDateLo": "01-01-2005",
        }
        response = httpx.get(
            self.API_URL,
            params=params,
            timeout=self.TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "wetstack-mireye/1.0"},
        )
        response.raise_for_status()
        best = self._best_result(response.text)
        cache = self._load_cache()
        cache[self._key(latitude, longitude)] = {
            "result": best,
            "queried_at": datetime.now(UTC).isoformat(),
        }
        self._save_cache()
        log.info("wqp queried", extra={"lat": latitude, "lon": longitude, "found": bool(best)})
        return best

    @staticmethod
    def _best_result(csv_text: str) -> dict | None:
        """Most recent mg/L reading. Never an average across stations: different
        wells sample different aquifers and their mean describes none of them."""
        best: dict | None = None
        for row in csv.DictReader(io.StringIO(csv_text)):
            if (row.get("ResultMeasure/MeasureUnitCode") or "").strip().lower() != "mg/l":
                continue
            raw = (row.get("ResultMeasureValue") or "").strip()
            try:
                value = float(raw)
            except ValueError:
                continue  # a censored result ("<5", "ND") states a limit, not a value
            date = (row.get("ActivityStartDate") or "").strip()
            if best is None or date > best["date"]:
                best = {
                    "value": value,
                    "date": date,
                    "station": row.get("MonitoringLocationIdentifier") or "",
                    "station_name": row.get("MonitoringLocationName") or "",
                    "organization": row.get("OrganizationFormalName") or "",
                }
        return best

    # -- lookup --------------------------------------------------------------
    def values_for(self, latitude: float, longitude: float) -> dict[str, DatasetValue]:
        cache = self._load_cache()
        key = self._key(latitude, longitude)
        entry = cache.get(key)
        if entry is None:
            if not self._allow_fetch:
                return {}
            try:
                self.download(latitude, longitude)
            except Exception as exc:  # noqa: BLE001 - an unreachable portal is a gap, not a crash
                log.warning("water quality portal unavailable", extra={"error": str(exc)})
                return {}
            entry = self._load_cache().get(key)

        best = (entry or {}).get("result")
        if not best:
            # No monitoring station within range reported TDS. Nothing to say.
            return {}

        year = int(best["date"][:4]) if best["date"][:4].isdigit() else 0
        age = datetime.now(UTC).year - year if year else None
        stale = age is not None and age > self.STALE_AFTER_YEARS
        station = best["station_name"] or best["station"]
        return {
            "water_quality_tds_mg_l": DatasetValue(
                field_key="water_quality_tds_mg_l",
                value=best["value"],
                unit="mg/l",
                source=f"Water Quality Portal station {best['station']}",
                source_url=(
                    "https://www.waterqualitydata.us/#siteid=" + best["station"] + "&mimeType=csv"
                ),
                licence=self.LICENCE,
                downloaded_at=(entry or {}).get("queried_at"),
                detail=f"{best['value']} mg/L sampled {best['date']} at {station}"
                + (f" ({best['organization']})" if best["organization"] else "")
                + f", within {self.SEARCH_RADIUS_KM} km of the site."
                + (f" The reading is {age} years old." if stale else ""),
                confidence=0.5 if stale else 0.7,
                relation=EvidenceRelation.CONTEXTUAL_PROXY,
                relation_note="A sample from a nearby monitoring station, not from this "
                "site's supply. It indicates regional groundwater chemistry and cannot "
                "stand in for an analysis of the actual source water.",
            )
        }


_providers: list[DatasetProvider] | None = None


def get_dataset_providers() -> list[DatasetProvider]:
    global _providers
    if _providers is None:
        _providers = [PeeringDBFacilities(), WaterQualityPortal()]
    return _providers


def set_dataset_providers(providers: list[DatasetProvider] | None) -> None:
    """Test hook."""
    global _providers
    _providers = providers


def dataset_fields() -> set[str]:
    """Field keys served by a public dataset rather than by Mireye."""
    return {f for p in get_dataset_providers() for f in p.fields}
