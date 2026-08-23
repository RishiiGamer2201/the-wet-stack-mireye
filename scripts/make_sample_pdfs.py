"""Generate a library of synthetic PDFs to exercise document ingestion.

    python scripts/make_sample_pdfs.py [output_dir]

Default output is `sample_data/library/`. Drag any of these into the upload area
on the Project knowledge tab, or attach one in the chat.

Every document is clearly banner-marked synthetic and every model number is
invented. They exist to exercise the extractor across the shapes a real project
throws at it - a spec section, a manufacturer datasheet, a submittal, an
equipment schedule, an RFI, a commissioning report - not to stand in for real
engineering data. Replace them with real documents as soon as you have any; see
docs/datasets.md section 5.

One of them is deliberately a scan with no text layer, so the OCR path gets
exercised too.
"""

from __future__ import annotations

import pathlib
import sys

import pymupdf

BANNER = (
    "SYNTHETIC DEMONSTRATION DOCUMENT - values are invented for the Wet Stack / Mireye\n"
    "prototype and are not real product or project data.\n"
)

DOCUMENTS: dict[str, tuple[str, str, list[str]]] = {
    # filename stem: (title, kind hint for the uploader, pages)
    "Aurora-DC1-Generator-Submittal-SYNTHETIC": (
        "Aurora DC-1 standby generator submittal (synthetic)",
        "submittal",
        [
            f"""{BANNER}
AURORA DC-1 CAMPUS - EQUIPMENT SUBMITTAL
Section 26 32 13 - Engine Generators
Tag: GEN-01    Submittal 26-3213-002    Revision B

PROPOSED EQUIPMENT
Manufacturer: Cascade Power Systems
Model number: CPS-2750-DF
Rating: 2750 kW standby at 0.8 power factor
Voltage: 13800 V, three phase, 60 Hz
Full load amps: 143 A
Minimum circuit ampacity: 179 A
Maximum overcurrent protection: 200 A

PHYSICAL DATA
Operating weight: 31200 kg
Shipping weight: 28900 kg
Overall dimensions: length 7620 mm, width 2290 mm, height 3050 mm
Support point load: 78 kN per corner mount

FUEL AND EMISSIONS
Fuel consumption at full load: 712 L/h diesel
On-site storage: 72 hours at N+1 load
Emissions: EPA Tier 4 Final, NFPA 110 Level 1 emergency standby

NOTES
1. Concrete housekeeping pad by others; see structural drawings S-401.
2. Exhaust silencer supplied loose for field mounting.
""",
            f"""{BANNER}
GEN-01 SUBMITTAL - PAGE 2 - COORDINATION ITEMS

The proposed CPS-2750-DF is 31200 kg operating weight against the 27500 kg
assumed in the basis of design. Support point load increases from 65 kN to
78 kN per mount. Structural review of the generator pad is required before
release for fabrication.

Ambient design dry-bulb temperature at the site: 38 degC.
Derate at 38 degC and 512 m elevation: 4 percent, giving 2640 kW available.

Acoustic data: 78 dB at 7 m with the supplied enclosure.
""",
        ],
    ),
    "Meridian-UPS-M900-Datasheet-SYNTHETIC": (
        "Meridian Power M900 UPS datasheet (synthetic)",
        "manufacturer_datasheet",
        [
            f"""{BANNER}
MERIDIAN POWER - MODEL M900 MODULAR UPS
Technical data sheet (synthetic)

Model number: M900-1200
Configuration: modular, six 200 kW power modules, N+1

ELECTRICAL
Rated output: 1200 kW
Supply voltage: 480 V three phase
Full load amps: 1443 A
Minimum circuit ampacity: 1804 A
Efficiency in double conversion: 96.5 percent
Efficiency in eco mode: 99.0 percent

PHYSICAL
Operating weight: 3180 kg
Overall dimensions: length 2400 mm, width 900 mm, height 2000 mm
Heat rejection at full load: 42 kW

ENVIRONMENT
Ambient operating temperature: 0 degC to 40 degC
Recommended ambient design temperature: 24 degC
Compliance: UL 1778, IEC 62040-3, IEEE 1584 arc flash study required
""",
        ],
    ),
    "Aurora-DC1-CRAH-Schedule-SYNTHETIC": (
        "Aurora DC-1 CRAH equipment schedule (synthetic)",
        "specification",
        [
            f"""{BANNER}
AURORA DC-1 CAMPUS - MECHANICAL EQUIPMENT SCHEDULE
Section 23 81 23 - Computer Room Air Handlers

CRAH-01
  Nominal cooling capacity: 180 kW sensible
  Entering water temperature: 18 degC
  Leaving water temperature: 24 degC
  Airflow: 12500 L/s
  Supply voltage: 480 V
  Full load amps: 32 A
  Operating weight: 1120 kg

CRAH-02
  Nominal cooling capacity: 180 kW sensible
  Entering water temperature: 18 degC
  Leaving water temperature: 24 degC
  Airflow: 12500 L/s
  Supply voltage: 480 V
  Full load amps: 32 A
  Operating weight: 1120 kg

CRAH-03 (redundant unit)
  Nominal cooling capacity: 180 kW sensible
  Operating weight: 1120 kg

GENERAL NOTES
All units certified to AHRI 1360. Ambient dry-bulb temperature at the outdoor
condensing equipment shall not exceed 38 degC. Units shall maintain ASHRAE
TC 9.9 Class A1 conditions in the white space.
""",
        ],
    ),
    "Aurora-DC1-CoolingTower-Submittal-SYNTHETIC": (
        "Aurora DC-1 cooling tower submittal (synthetic)",
        "submittal",
        [
            f"""{BANNER}
AURORA DC-1 CAMPUS - EQUIPMENT SUBMITTAL
Section 23 65 00 - Cooling Towers
Tag: CT-01    Revision A

PROPOSED EQUIPMENT
Manufacturer: Basin Works
Model number: BW-XT-900
Type: induced draft, counterflow, closed circuit

PERFORMANCE
Heat rejection: 3150 kW
Entering water temperature: 35 degC
Leaving water temperature: 29.4 degC
Design wet bulb temperature: 24 degC
Evaporation rate at design: 4.2 L/s
Make-up water requirement: 5.6 L/s at 4 cycles of concentration

PHYSICAL
Operating weight: 14800 kg
Shipping weight: 9200 kg
Overall dimensions: length 7300 mm, width 3660 mm, height 4270 mm
Supply voltage: 480 V
Full load amps: 61 A

WATER TREATMENT
Maximum total dissolved solids in circulating water: 1200 mg/l
Basin heater required below 0 degC ambient.
""",
        ],
    ),
    "Aurora-DC1-Switchgear-Submittal-SYNTHETIC": (
        "Aurora DC-1 medium voltage switchgear submittal (synthetic)",
        "submittal",
        [
            f"""{BANNER}
AURORA DC-1 CAMPUS - EQUIPMENT SUBMITTAL
Section 26 13 00 - Medium Voltage Switchgear
Tag: SWGR-MV-01

PROPOSED EQUIPMENT
Manufacturer: Ridgeline Electric
Model number: RL-MV38-2000
Supply voltage: 13800 V
Continuous current: 2000 A
Short circuit rating: 40 kA symmetrical for 3 seconds

PHYSICAL
Operating weight: 6800 kg
Overall dimensions: length 5200 mm, width 2440 mm, height 2340 mm

PROTECTION
Arc flash study per IEEE 1584 required before energisation.
Relays: microprocessor multifunction, IEC 61850 capable.
Seismic qualification: IBC 2021, Risk Category IV, tested per ICC-ES AC156.
""",
        ],
    ),
    "Aurora-DC1-RFI-014-SYNTHETIC": (
        "Aurora DC-1 RFI 014 chiller pad coordination (synthetic)",
        "other",
        [
            f"""{BANNER}
AURORA DC-1 CAMPUS - REQUEST FOR INFORMATION
RFI 014    Discipline: Mechanical / Structural    Status: Open

SUBJECT
Chiller CH-01 substitution - housekeeping pad and support point load

QUESTION
The proposed substitution for CH-01 has an operating weight of 5290 kg against
the 4850 kg carried in the basis of design, an increase of 440 kg. Support point
load rises accordingly. Please confirm whether the existing 300 mm housekeeping
pad and the roof framing below it remain adequate, or issue revised details.

ATTACHMENTS
Vertex VX-1150 submittal, revision A.

RESPONSE
Pending. Structural engineer of record to review. No fabrication release until
this RFI is closed.
""",
        ],
    ),
    "Aurora-DC1-Commissioning-Report-SYNTHETIC": (
        "Aurora DC-1 commissioning report extract (synthetic)",
        "report",
        [
            f"""{BANNER}
AURORA DC-1 CAMPUS - COMMISSIONING REPORT (EXTRACT)
Level 4 functional performance testing - mechanical plant

CH-01 FUNCTIONAL TEST
Measured net cooling capacity: 1032 kW against 1040 kW scheduled.
Entering water temperature: 12.1 degC
Leaving water temperature: 6.8 degC
Result: pass, within the 2 percent tolerance in specification 23 64 16.

CT-01 FUNCTIONAL TEST
Measured heat rejection: 3095 kW at 23.6 degC wet bulb.
Measured evaporation rate: 4.4 L/s
Result: pass.

GEN-01 LOAD BANK TEST
Four hour test at 2640 kW. Fuel consumption measured at 698 L/h.
Result: pass.

OUTSTANDING ITEMS
1. CRAH-03 airflow measured at 11800 L/s against 12500 L/s scheduled. Retest
   required after filter replacement.
2. Arc flash labels not yet applied to SWGR-MV-01.
""",
        ],
    ),
}

#: Rendered to an image so it has no text layer, to exercise the OCR path.
SCANNED = (
    "Aurora-DC1-Scanned-Field-Markup-SYNTHETIC",
    "Aurora DC-1 scanned field markup (synthetic, no text layer)",
    f"""{BANNER}
AURORA DC-1 CAMPUS - FIELD MARKUP (SCANNED)
Section 23 64 16 - Air-Cooled Chillers

CH-04 net cooling capacity shall be 1180 kW at 7 degC leaving water.
Operating weight 5410 kg. Full load amps 385 A at 480 V.
Support point load 21 kN per mount.

Marked up on site 14 March. Confirm against manufacturer submittal before use.
""",
)


def write_pdf(path: pathlib.Path, title: str, pages: list[str]) -> None:
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_textbox(
            pymupdf.Rect(50, 50, 545, 780), body, fontsize=10, fontname="helv", align=0
        )
    doc.set_metadata({"title": title, "subject": "synthetic demonstration document"})
    doc.save(str(path))
    doc.close()


def write_scanned_pdf(path: pathlib.Path, title: str, body: str) -> None:
    """Render text to an image so the resulting page has no text layer."""
    source = pymupdf.open()
    page = source.new_page()
    page.insert_textbox(
        pymupdf.Rect(50, 50, 545, 780), body, fontsize=11, fontname="helv", align=0
    )
    # 150 dpi keeps the file a few MB while staying comfortably readable by
    # Tesseract; 200 dpi produced an 11 MB page for no accuracy gain.
    pixmap = page.get_pixmap(dpi=150)

    out = pymupdf.open()
    scanned = out.new_page(width=page.rect.width, height=page.rect.height)
    scanned.insert_image(scanned.rect, pixmap=pixmap)
    out.set_metadata({"title": title, "subject": "synthetic demonstration document"})
    out.save(str(path))
    out.close()
    source.close()


def main() -> None:
    out_dir = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("sample_data/library")
    out_dir.mkdir(parents=True, exist_ok=True)

    for stem, (title, kind, pages) in DOCUMENTS.items():
        path = out_dir / f"{stem}.pdf"
        write_pdf(path, title, pages)
        print(f"  {path.name:52} {kind:22} {path.stat().st_size / 1024:6.0f} kB")

    stem, title, body = SCANNED
    path = out_dir / f"{stem}.pdf"
    write_scanned_pdf(path, title, body)
    print(f"  {path.name:52} {'submittal (scan)':22} {path.stat().st_size / 1024:6.0f} kB")

    print(f"\n{len(DOCUMENTS) + 1} documents written to {out_dir}")
    print("Upload them from the Project knowledge tab, or attach one in the chat.")


if __name__ == "__main__":
    main()
