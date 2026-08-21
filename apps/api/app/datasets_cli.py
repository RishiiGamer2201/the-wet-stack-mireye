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

from .adapters.datasets import PeeringDBFacilities, WaterQualityPortal, get_dataset_providers
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
    """Pre-query the per-location sources for every site already in the store."""
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
    for site in sites:
        try:
            best = portal.download(site.latitude, site.longitude)
        except Exception as exc:  # noqa: BLE001 - report and carry on to the next site
            print(f"  {site.name}: FAILED ({exc})")
            continue
        print(f"  {site.name}: " + (f"{best['value']} mg/L ({best['date']})" if best else "no reading in range"))


if __name__ == "__main__":
    main()
