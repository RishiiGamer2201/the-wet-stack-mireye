"""Download the public datasets the scoring model uses.

    python -m app.datasets_cli list
    python -m app.datasets_cli download peeringdb
    python -m app.datasets_cli download all
    python -m app.datasets_cli warm          # pre-query per-location sources

Downloading is an explicit act, so an investigation reads what is already on
disk. The Water Quality Portal has no bulk extract and is queried per location;
`warm` fills its cache for every site already in the store, which is worth
running after a deploy that starts on an empty disk.
"""

from __future__ import annotations

import argparse
import sys

from .adapters.datasets import (
    PADUSProtectedAreas,
    PeeringDBFacilities,
    WaterQualityPortal,
    get_dataset_providers,
)
from .logging_conf import configure_logging

DOWNLOADERS = {"peeringdb": PeeringDBFacilities}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["list", "download", "warm"])
    parser.add_argument("name", nargs="?", default="all")
    args = parser.parse_args()
    configure_logging("INFO")

    if args.action == "list":
        for provider in get_dataset_providers():
            state = "downloaded" if getattr(provider, "available", False) else "NOT downloaded"
            print(f"  {provider.name:14} {state:15} serves: {', '.join(provider.fields)}")
        return

    if args.action == "warm":
        _warm()
        return

    names = list(DOWNLOADERS) if args.name == "all" else [args.name]
    for name in names:
        if name not in DOWNLOADERS:
            sys.exit(f"unknown dataset {name!r}; known: {', '.join(DOWNLOADERS)}")
        count = DOWNLOADERS[name]().download()
        print(f"  {name}: {count} records downloaded")


def _warm() -> None:
    """Pre-query the per-location sources for every site already in the store.

    Two of the sources answer per coordinate rather than shipping a national
    table, so a site nobody has asked about yet queries them live on its first
    investigation. Warming moves that cost to deploy time.
    """
    from .adapters.datasets import EIAReliability, FEMANationalRiskIndex
    from .config import get_settings
    from .domain import CandidateSite
    from .store import C, Store

    store = Store(get_settings().sqlite_path)
    sites = [
        s
        for s in store.list(C.SITES, CandidateSite)
        if s.latitude is not None and s.longitude is not None
    ]
    if not sites:
        print("  no located sites in the store; nothing to warm")
        return

    portal = WaterQualityPortal()
    padus = PADUSProtectedAreas()
    reliability = EIAReliability()
    wildfire = FEMANationalRiskIndex()
    for site in sites:
        print(f"  {site.name}")
        try:
            best = portal.download(site.latitude, site.longitude)
            print(
                "     water quality: "
                + (f"{best['value']} mg/L ({best['date']})" if best else "no reading in range")
            )
        except Exception as exc:  # noqa: BLE001 - report and carry on
            print(f"     water quality: FAILED ({exc})")
        try:
            area = padus.download(site.latitude, site.longitude)
            print(
                "     protected area: "
                + (f"{area['distance_km']} km to {area['unit_name']}" if area else "none within range")
            )
        except Exception as exc:  # noqa: BLE001
            print(f"     protected area: FAILED ({exc})")
        # Reliability needs only the county lookup, which caches on first use.
        found = reliability.values_for(site.latitude, site.longitude)
        value = found.get("grid_reliability_saidi_min")
        print(
            "     grid reliability: "
            + (f"{value.value} min/yr (worst utility in county)" if value else "not reported here")
        )
        # Shares the county lookup's cache, so this costs nothing extra.
        found = wildfire.values_for(site.latitude, site.longitude)
        risk = found.get("wildfire_risk_index")
        rating = risk.detail.split("rated ")[-1].rstrip(".") if risk else ""
        print("     wildfire risk: " + (f"{risk.value} ({rating.split('.')[0]})" if risk else "tract not covered"))


if __name__ == "__main__":
    main()
