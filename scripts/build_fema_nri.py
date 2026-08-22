"""Extract the wildfire risk index from the FEMA National Risk Index tract table.

    python scripts/build_fema_nri.py [path/to/NRI_Table_CensusTracts.zip]

FEMA blocks automated download from some networks, so the zip is fetched by hand
from <https://hazards.fema.gov/nri/data-resources> ("All Census tracts", Table
Format) and pointed at here. Default path is
`data_downloaded_manually/NRI_Table_CensusTracts.zip`.

The source is 605 MB of CSV with 467 columns for 85,154 tracts. This keeps the
three that answer a field — tract id, wildfire risk score, wildfire rating — and
writes about 2 MB that ships with the wheel.
"""

from __future__ import annotations

import csv
import io
import json
import pathlib
import sys
import zipfile
from datetime import UTC, datetime

CSV_NAME = "NRI_Table_CensusTracts.csv"
DEFAULT_ZIP = pathlib.Path("data_downloaded_manually/NRI_Table_CensusTracts.zip")
OUT = pathlib.Path("apps/api/app/data/datasets/fema_nri_wildfire.json")

#: FEMA's own rating boundaries, measured from the December 2025 v1.20 table and
#: exact to three decimals. They are recorded here because the scoring
#: thresholds in `fields.py` are anchored to them, so a future NRI version that
#: moves them must move those too.
RATING_BOUNDS = {
    "Very Low": (18.441, 68.650),
    "Relatively Low": (68.651, 88.344),
    "Relatively Moderate": (88.345, 96.259),
    "Relatively High": (96.260, 99.061),
    "Very High": (99.062, 100.000),
}

#: Ratings are stored as one character to keep the shipped file small.
RATING_CODES = {
    "No Rating": "N",
    "Very Low": "1",
    "Relatively Low": "2",
    "Relatively Moderate": "3",
    "Relatively High": "4",
    "Very High": "5",
}


def main() -> None:
    source = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ZIP
    if not source.exists():
        sys.exit(
            f"{source} not found. Download 'All Census tracts / Table Format' from "
            "https://hazards.fema.gov/nri/data-resources and pass its path."
        )

    tracts: dict[str, list] = {}
    version = "unknown"
    skipped_no_rating = 0

    with zipfile.ZipFile(source) as archive:
        try:
            info = next(i for i in archive.infolist() if i.filename.endswith("NRI_HazardInfo.csv"))
            hazards = list(csv.DictReader(io.TextIOWrapper(archive.open(info), encoding="utf-8-sig")))
            wildfire = next(h for h in hazards if h.get("Hazard") == "Wildfire")
            version = wildfire.get("NRI_VER", "unknown")
        except (StopIteration, KeyError):
            pass

        with archive.open(CSV_NAME) as handle:
            reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig", newline=""))
            for row in reader:
                fips = (row.get("TRACTFIPS") or "").strip()
                score = (row.get("WFIR_RISKS") or "").strip()
                rating = (row.get("WFIR_RISKR") or "").strip()
                if not fips or not score:
                    continue
                if rating == "No Rating":
                    # No wildfire exposure modelled for this tract. That is a real
                    # answer, not a missing one: score 0 with an explicit rating.
                    skipped_no_rating += 1
                tracts[fips] = [round(float(score), 2), RATING_CODES.get(rating, "N")]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "_source": f"FEMA National Risk Index {version}, census tract table",
                "_url": "https://hazards.fema.gov/nri/data-resources",
                "_licence": "FEMA National Risk Index, public domain (US Government work)",
                "_downloaded_at": datetime.now(UTC).isoformat(),
                "_field": "WFIR_RISKS (Wildfire - Hazard Type Risk Index Score) with WFIR_RISKR",
                "_rating_bounds": RATING_BOUNDS,
                "_note": "Score is a composite of expected annual loss, social vulnerability "
                "and community resilience. Its distribution is heavily skewed: the median "
                "'Very Low' tract scores 43.6, and everything above 'Relatively Moderate' is "
                "compressed into 88-100. Read it against _rating_bounds, never as a linear "
                "0-100 hazard rate.",
                "tracts": tracts,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"tracts: {len(tracts)} ({skipped_no_rating} with no modelled wildfire exposure)")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
