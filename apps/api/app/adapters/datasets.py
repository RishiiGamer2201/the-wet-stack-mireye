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
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import httpx

from ..config import get_settings
from ..domain import EvidenceRelation

UTC = timezone.utc

#: Distinguishes "cached as no result" from "never asked".
_MISSING = object()

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


#: State FIPS code -> USPS abbreviation. The Census geocoder answers in FIPS and
#: EIA publishes in USPS, so one of them has to be translated.
STATE_FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT",
    "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL",
    "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD",
    "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE",
    "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV",
    "55": "WI", "56": "WY", "60": "AS", "66": "GU", "69": "MP", "72": "PR", "78": "VI",
}


def normalise_county(name: str) -> str:
    """A county name in the form both sources agree on.

    Census says "St. Louis city" and "Doña Ana"; EIA says "St Louis City" and
    "Dona Ana". Without this the join silently misses and the field looks
    unavailable when the data is right there.
    """
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9 ]", " ", text).upper()
    text = re.sub(
        r"\b(COUNTY|PARISH|BOROUGH|CENSUS AREA|MUNICIPALITY|MUNICIPIO|CITY AND BOROUGH)\b",
        " ",
        text,
    )
    return " ".join(text.split())



def _point_to_segment_m(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Shortest distance from a point to a line segment, in metres.

    Inputs are already projected to metres by the caller, so this is plain
    planar geometry.
    """
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _ring_contains(px: float, py: float, ring: list[tuple[float, float]]) -> bool:
    """Ray casting. Used to answer 'is the site inside this area' with 0, not a
    small positive number that would read as 'nearly inside'."""
    inside = False
    for i in range(len(ring)):
        ax, ay = ring[i]
        bx, by = ring[(i + 1) % len(ring)]
        if (ay > py) != (by > py):
            x = ax + (py - ay) * (bx - ax) / (by - ay)
            if x > px:
                inside = not inside
    return inside


def distance_to_rings_km(
    latitude: float, longitude: float, rings: list[list[list[float]]]
) -> float:
    """Distance from a point to the nearest edge of a polygon, or 0 inside it.

    Projects lon/lat to metres about the site (equirectangular). At the tens of
    kilometres this is used over, the error from that projection is far below the
    error from the simplified geometry the service returns.
    """
    scale_y = 111_320.0
    scale_x = scale_y * math.cos(math.radians(latitude))
    px = py = 0.0
    best = float("inf")
    for ring in rings:
        projected = [((x - longitude) * scale_x, (y - latitude) * scale_y) for x, y in ring]
        if len(projected) < 2:
            continue
        if _ring_contains(px, py, projected):
            return 0.0
        for i in range(len(projected)):
            ax, ay = projected[i]
            bx, by = projected[(i + 1) % len(projected)]
            best = min(best, _point_to_segment_m(px, py, ax, ay, bx, by))
    return best / 1000.0 if best < float("inf") else float("inf")


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



class CountyLookup:
    """Coordinates -> US county, from the Census geocoder, cached to disk.

    Shared by every provider that publishes at county level. The Census geocoder
    is free, needs no key, and is the authority on which county a point is in —
    guessing from a bounding box would put a site in the wrong jurisdiction, and
    jurisdiction is the whole join key here.
    """

    API_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
    TIMEOUT_SECONDS = 30.0
    #: Both layers come back in one request, so a site that needs a county for
    #: one dataset already has its tract for another.
    LAYERS = "Counties,Census Tracts"

    def __init__(self, path: Path | None = None, *, allow_fetch: bool = True) -> None:
        self._path = path or (get_settings().data_dir / "datasets" / "county_cache.json")
        self._allow_fetch = allow_fetch
        self._cache: dict | None = None

    def _load(self) -> dict:
        if self._cache is None:
            self._cache = _read_json(BUNDLED_DIR / self._path.name)
            self._cache.update(_read_json(self._path))
        return self._cache

    def county_for(self, latitude: float, longitude: float) -> dict | None:
        """`{"state": "VA", "county": "Loudoun", "fips": "51107", "tract_fips": ...}`.

        None when the point is not in a US county — offshore, abroad, or the
        geocoder could not say. A guess here would put a site in the wrong
        jurisdiction, and jurisdiction is the join key for everything downstream.
        """
        cache = self._load()
        key = f"{latitude:.3f},{longitude:.3f}"
        hit = cache.get(key, _MISSING)
        # An entry cached before tracts were requested has no `tract_fips`, and
        # returning it would report "not covered" forever. Re-fetch instead of
        # trusting a shape that predates the field.
        if hit is not _MISSING and (hit is None or "tract_fips" in hit):
            return hit
        if not self._allow_fetch:
            return hit if hit is not _MISSING else None
        try:
            response = httpx.get(
                self.API_URL,
                params={
                    "x": longitude,
                    "y": latitude,
                    "benchmark": "Public_AR_Current",
                    "vintage": "Current_Current",
                    "layers": self.LAYERS,
                    "format": "json",
                },
                timeout=self.TIMEOUT_SECONDS,
                headers={"User-Agent": "wetstack-mireye/1.0"},
            )
            response.raise_for_status()
            geographies = response.json()["result"]["geographies"]
        except Exception as exc:  # noqa: BLE001 - offshore, abroad, or the service is down
            log.warning("census lookup failed", extra={"error": str(exc)})
            return None

        counties = geographies.get("Counties") or []
        tracts = geographies.get("Census Tracts") or []
        found = None
        if counties:
            row = counties[0]
            found = {
                "state": STATE_FIPS.get(str(row.get("STATE", "")), ""),
                "county": row.get("BASENAME") or "",
                "fips": f"{row.get('STATE', '')}{row.get('COUNTY', '')}",
                "tract_fips": (tracts[0].get("GEOID") if tracts else None),
                "tract": (tracts[0].get("BASENAME") if tracts else None),
            }
        cache[key] = found
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(cache), encoding="utf-8")
        return found


class EIAReliability:
    """Grid reliability from EIA Form EIA-861.

    Every distribution utility in the US reports SAIDI — the average minutes a
    customer was without power in a year — to the EIA. That is real, audited,
    nationwide data, and it is the best public answer to "how reliable is the
    grid here".

    It is not this site's answer. SAIDI is a utility-wide average across a whole
    service territory: a substation-adjacent site and a rural end-of-line site on
    the same utility share one number that describes neither. Worse, a county is
    often served by several utilities and nothing public says which one will
    serve a given parcel — Maricopa County alone spans 10 to 82 minutes a year.

    So this is CONTEXTUAL_PROXY. It reports the *worst* utility in the county,
    because a siting decision that turns on reliability should not be made on the
    most flattering of several possible suppliers, and it names every utility it
    found. The gap stays open until the serving utility provides circuit-level
    history.
    """

    name = "eia_reliability"
    fields = ("grid_reliability_saidi_min",)

    LICENCE = "US Energy Information Administration Form EIA-861, public domain"

    def __init__(self, path: Path | None = None, counties: CountyLookup | None = None) -> None:
        self._path = path or _dataset_path("eia861_reliability.json")
        self._counties = counties or CountyLookup()
        self._payload: dict | None = None

    @property
    def available(self) -> bool:
        return self._path.exists()

    def _load(self) -> dict:
        if self._payload is None:
            self._payload = _read_json(self._path)
        return self._payload

    def values_for(self, latitude: float, longitude: float) -> dict[str, DatasetValue]:
        payload = self._load()
        if not payload:
            log.warning("eia reliability dataset missing", extra={"path": str(self._path)})
            return {}
        county = self._counties.county_for(latitude, longitude)
        if not county or not county.get("state"):
            return {}  # outside the US, or the geocoder could not say

        key = f"{county['state']}|{normalise_county(county['county'])}"
        entries = payload.get("counties", {}).get(key, [])
        served = [payload["utilities"][e] for e in entries if e in payload["utilities"]]
        reporting = [u for u in served if u.get("saidi_without_med") is not None]
        if not reporting:
            # Utilities here filed the form but reported no reliability figures.
            # An absent number is not a good one.
            return {}

        # "With MED" includes Major Event Days, which are dominated by individual
        # storms and are not comparable between utilities. "Without" is the
        # figure that compares.
        worst = max(reporting, key=lambda u: u["saidi_without_med"])
        listing = "; ".join(
            f"{u['utility']} {u['saidi_without_med']} min ({u['ownership']})" for u in reporting
        )
        return {
            "grid_reliability_saidi_min": DatasetValue(
                field_key="grid_reliability_saidi_min",
                value=worst["saidi_without_med"],
                unit="minute",
                source=f"EIA-861 {county['county']} County, {county['state']}",
                source_url="https://www.eia.gov/electricity/data/eia861/",
                licence=self.LICENCE,
                downloaded_at=payload.get("_downloaded_at"),
                detail=f"{len(reporting)} utility(ies) reporting in {county['county']} County, "
                f"{county['state']}: {listing}. Shown: the worst, SAIDI excluding Major "
                "Event Days.",
                confidence=0.6,
                relation=EvidenceRelation.CONTEXTUAL_PROXY,
                relation_note="A utility-wide annual average for a whole county, not this "
                "site's feeder. Which utility serves the parcel is not public, and "
                "reliability varies widely within one territory. Ask the serving utility "
                "for circuit-level outage history.",
            )
        }



class PADUSProtectedAreas:
    """Distance to the nearest protected area, from USGS PAD-US 4.1.

    PAD-US is the national inventory of protected land — every federal, state,
    local and private conservation holding, 298,244 of them. Until now this
    concept was served by a labelled proxy: Mireye's distance to the nearest
    Clean Air Act Class I area, which is a strict subset (national parks and
    large wilderness only). Because the concept scores higher-is-better, that
    proxy made every site look more remote from protected land than it is, which
    is why it was never allowed to populate the field.

    This is the measurement the field asks for, so it is EXACT.
    """

    name = "padus"
    fields = ("protected_area_distance_km",)

    API_URL = (
        "https://services.arcgis.com/v01gqwM5QqNysAAi/ArcGIS/rest/services/"
        "Fee_Managers_PADUS/FeatureServer/0/query"
    )
    LICENCE = "USGS Protected Areas Database of the United States (PAD-US) 4.1, public domain"
    #: Search radius. Nothing within this and the site is not near protected land
    #: in any sense the field is asking about, so it reports nothing rather than
    #: a number that would read as a measured remoteness.
    #: Search rings, smallest first. The service caps a response at a fixed
    #: number of features, so querying a 50 km buffer directly returns *some* 60
    #: of the hundreds of areas in range — not the nearest. Expanding from the
    #: smallest ring that contains anything keeps the answer correct and the
    #: payload small.
    SEARCH_RINGS_KM = (2, 5, 15, 50)
    #: GAP status 1-3 are land with a real protection mandate: 1 and 2 manage for
    #: natural state, 3 is permanent multiple-use protection (national forest,
    #: BLM). Status 4 is open space with *no known mandate*.
    MEANINGFUL_GAP_STATUS = {"1", "2", "3"}
    #: Municipal parks and ball fields are land-use neighbours, not ecological
    #: constraints. Counting a diamond 300 m away as "protected land" would
    #: penalise a site on a concept that means conservation. Filtered on
    #: designation, not manager: PAD-US often records a city park's manager as
    #: UNK, so a manager-type filter silently lets them through.
    #: LP = Local Park, LREC = Local Recreation Area, LOTHER = other local.
    #: LCA (Local Conservation Area) is deliberately *not* here — that one is
    #: conservation land. Excluded areas are still reported in the detail.
    RECREATION_DESIGNATIONS = {"LP", "LREC", "LOTHER"}
    #: Server-side simplification, in degrees (~200 m). Keeps a response near
    #: 20 kB instead of megabytes of coastline, at a stated cost in precision.
    SIMPLIFY_DEGREES = 0.002
    PRECISION_KM = 0.2
    TIMEOUT_SECONDS = 60.0
    PAGE_SIZE = 400

    def __init__(self, path: Path | None = None, *, allow_fetch: bool = True) -> None:
        self._path = path or (get_settings().data_dir / "datasets" / "padus_cache.json")
        self._allow_fetch = allow_fetch
        self._cache: dict | None = None

    @property
    def available(self) -> bool:
        return self._path.exists() or (BUNDLED_DIR / self._path.name).exists()

    def _load_cache(self) -> dict:
        if self._cache is None:
            self._cache = _read_json(BUNDLED_DIR / self._path.name)
            self._cache.update(_read_json(self._path))
        return self._cache

    @staticmethod
    def _key(latitude: float, longitude: float) -> str:
        return f"{latitude:.3f},{longitude:.3f}"

    def _query(self, latitude: float, longitude: float, radius_km: int, **extra) -> dict:
        params = {
            "geometry": json.dumps(
                {"x": longitude, "y": latitude, "spatialReference": {"wkid": 4326}}
            ),
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "outSR": "4326",
            "distance": str(radius_km * 1000),
            "units": "esriSRUnit_Meter",
            "spatialRel": "esriSpatialRelIntersects",
            "f": "json",
            **extra,
        }
        response = httpx.get(
            self.API_URL,
            params=params,
            timeout=self.TIMEOUT_SECONDS,
            headers={"User-Agent": "wetstack-mireye/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise ValueError(f"PAD-US query failed: {payload['error']}")
        return payload

    def _features_within(self, latitude: float, longitude: float, radius_km: int) -> list[dict]:
        """Every area in the ring, paged. Partial results would silently drop the
        nearest one, which is the only feature that matters here."""
        features: list[dict] = []
        offset = 0
        while True:
            page = self._query(
                latitude,
                longitude,
                radius_km,
                outFields="Unit_Nm,Des_Tp,Mang_Type,Mang_Name,GAP_Sts",
                returnGeometry="true",
                maxAllowableOffset=str(self.SIMPLIFY_DEGREES),
                geometryPrecision="5",
                resultOffset=str(offset),
                resultRecordCount=str(self.PAGE_SIZE),
            )
            batch = page.get("features", [])
            features.extend(batch)
            if not page.get("exceededTransferLimit") or not batch:
                return features
            offset += len(batch)

    def _nearest(self, latitude: float, longitude: float, features: list[dict], local: bool):
        best = None
        for feature in features:
            rings = feature.get("geometry", {}).get("rings")
            attributes = feature.get("attributes", {})
            if not rings:
                continue
            if (attributes.get("GAP_Sts") or "").strip() not in self.MEANINGFUL_GAP_STATUS:
                continue
            is_local = (attributes.get("Des_Tp") or "").strip() in self.RECREATION_DESIGNATIONS
            if is_local is not local:
                continue
            distance = distance_to_rings_km(latitude, longitude, rings)
            if best is None or distance < best["distance_km"]:
                best = {
                    "distance_km": round(distance, 2),
                    "unit_name": (attributes.get("Unit_Nm") or "").strip(),
                    "designation": (attributes.get("Des_Tp") or "").strip(),
                    "manager": (attributes.get("Mang_Name") or "").strip(),
                    "manager_type": (attributes.get("Mang_Type") or "").strip(),
                    "gap_status": (attributes.get("GAP_Sts") or "").strip(),
                }
        return best

    def download(self, latitude: float, longitude: float) -> dict | None:
        """Find the nearest protected area, expanding outwards until one appears."""
        nearest = nearest_local = None
        for radius_km in self.SEARCH_RINGS_KM:
            features = self._features_within(latitude, longitude, radius_km)
            nearest = self._nearest(latitude, longitude, features, local=False)
            nearest_local = self._nearest(latitude, longitude, features, local=True)
            # A hit inside the ring is only trustworthy if the whole ring was
            # searched, which it was — so stop at the first ring that has one.
            if nearest is not None:
                break

        result = None
        if nearest is not None:
            result = {**nearest, "nearest_local": nearest_local}

        cache = self._load_cache()
        cache[self._key(latitude, longitude)] = {
            "result": result,
            "queried_at": datetime.now(UTC).isoformat(),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(cache), encoding="utf-8")
        log.info("padus queried", extra={"lat": latitude, "lon": longitude, "found": bool(result)})
        return result

    def values_for(self, latitude: float, longitude: float) -> dict[str, DatasetValue]:
        cache = self._load_cache()
        key = self._key(latitude, longitude)
        entry = cache.get(key)
        if entry is None:
            if not self._allow_fetch:
                return {}
            try:
                self.download(latitude, longitude)
            except Exception as exc:  # noqa: BLE001 - a dead service is a gap, not a crash
                log.warning("padus unavailable", extra={"error": str(exc)})
                return {}
            entry = self._load_cache().get(key)

        nearest = (entry or {}).get("result")
        if not nearest:
            return {}

        gap_status = nearest.get("gap_status")
        return {
            "protected_area_distance_km": DatasetValue(
                field_key="protected_area_distance_km",
                value=nearest["distance_km"],
                unit="km",
                source=f"PAD-US: {nearest['unit_name'] or 'protected area'}",
                source_url="https://www.usgs.gov/programs/gap-analysis-project/science/pad-us-data-download",
                licence=self.LICENCE,
                downloaded_at=(entry or {}).get("queried_at"),
                detail=(
                    f"Nearest protected area: {nearest['unit_name'] or 'unnamed'}"
                    + (f" ({nearest['designation']}" if nearest["designation"] else "")
                    + (f", managed by {nearest['manager']}" if nearest["manager"] else "")
                    + (")" if nearest["designation"] else "")
                    + (f", GAP status {gap_status}" if gap_status else "")
                    + (
                        ". The site is inside this protected area."
                        if nearest["distance_km"] == 0
                        else f". Boundary distance, accurate to about "
                        f"{self.PRECISION_KM} km - the boundary geometry is simplified, so "
                        "a gate within that margin needs the full-resolution polygon."
                    )
                    + (
                        f" Nearer, but excluded as municipal recreation rather than "
                        f"conservation land: {local['unit_name']} at {local['distance_km']} km."
                        if (local := nearest.get("nearest_local"))
                        and local["distance_km"] < nearest["distance_km"]
                        else ""
                    )
                ),
                confidence=0.85,
            )
        }



class FEMANationalRiskIndex:
    """Wildfire risk from the FEMA National Risk Index, per census tract.

    The NRI is FEMA's own baseline risk measurement for every US county and
    tract, built with academia, state and federal partners. It answers a concept
    Mireye's catalog has no equivalent for: the catalog exposes an annual
    wildfire frequency and hazard-zone classes, neither of which is a composite
    index.

    **The score is not a linear hazard rate, and reading it as one is the trap.**
    `WFIR_RISKS` runs 0-100, so it looks directly comparable to any other 0-100
    index, but its distribution is heavily skewed: the median tract FEMA rates
    "Very Low" scores 43.6, and everything from "Relatively Moderate" upwards is
    compressed into 88-100. Scoring it against thresholds meant for an evenly
    spread index would penalise a genuinely safe site by half its wildfire
    points and would not tell "Relatively High" from "Very High" at all.

    So the scoring thresholds in `fields.py` are anchored to FEMA's own published
    class boundaries (68.65 = top of Very Low, 96.26 = start of Relatively High),
    which is why the value can be carried EXACT rather than converted.
    """

    name = "fema_nri"
    fields = ("wildfire_risk_index",)

    LICENCE = "FEMA National Risk Index, public domain (US Government work)"
    RATING_NAMES = {
        "N": "No Rating (no modelled wildfire exposure)",
        "1": "Very Low",
        "2": "Relatively Low",
        "3": "Relatively Moderate",
        "4": "Relatively High",
        "5": "Very High",
    }

    def __init__(self, path: Path | None = None, counties: CountyLookup | None = None) -> None:
        self._path = path or _dataset_path("fema_nri_wildfire.json")
        self._counties = counties or CountyLookup()
        self._payload: dict | None = None

    @property
    def available(self) -> bool:
        return self._path.exists()

    def _load(self) -> dict:
        if self._payload is None:
            self._payload = _read_json(self._path)
        return self._payload

    def values_for(self, latitude: float, longitude: float) -> dict[str, DatasetValue]:
        payload = self._load()
        if not payload:
            log.warning(
                "fema nri dataset missing; run scripts/build_fema_nri.py",
                extra={"path": str(self._path)},
            )
            return {}
        location = self._counties.county_for(latitude, longitude)
        tract_fips = (location or {}).get("tract_fips")
        if not tract_fips:
            return {}  # outside the US, or the geocoder could not place it

        row = payload.get("tracts", {}).get(tract_fips)
        if not row:
            # A tract the NRI does not cover. Absent, not zero — a zero here
            # reads as "no wildfire risk", which is the opposite of unknown.
            return {}

        score, code = row[0], row[1]
        rating = self.RATING_NAMES.get(code, "unknown")
        where = f"census tract {location.get('tract') or tract_fips}"
        if location.get("county"):
            where += f", {location['county']} County, {location['state']}"
        return {
            "wildfire_risk_index": DatasetValue(
                field_key="wildfire_risk_index",
                value=score,
                unit=None,
                source=f"FEMA NRI tract {tract_fips}",
                source_url="https://hazards.fema.gov/nri/map",
                licence=self.LICENCE,
                downloaded_at=payload.get("_downloaded_at"),
                detail=f"FEMA National Risk Index wildfire score {score} for {where}, "
                f"rated {rating}. The score is a composite of expected annual loss, "
                "social vulnerability and community resilience, and its scale is "
                "non-linear — read it against the rating, not as a percentage.",
                confidence=0.85,
            )
        }


_providers: list[DatasetProvider] | None = None


def get_dataset_providers() -> list[DatasetProvider]:
    global _providers
    if _providers is None:
        _providers = [
            PeeringDBFacilities(),
            WaterQualityPortal(),
            EIAReliability(),
            PADUSProtectedAreas(),
            FEMANationalRiskIndex(),
        ]
    return _providers


def set_dataset_providers(providers: list[DatasetProvider] | None) -> None:
    """Test hook."""
    global _providers
    _providers = providers


def dataset_fields() -> set[str]:
    """Field keys served by a public dataset rather than by Mireye."""
    return {f for p in get_dataset_providers() for f in p.fields}
