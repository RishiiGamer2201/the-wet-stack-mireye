"""Build the two-page technical document as a .docx.

    python scripts/build_technical_doc.py

Writes `docs/The-Wet-Stack-Mireye-Technical-Document.docx`, matching the layout
of the original submission PDF: a title, bold section headings, bulleted lists,
and a dependency table.

Every figure in the content below was measured from the running system on
2026-08-24. Where the previous draft was wrong, the corrected value is used and
the correction is noted in `docs/technical-doc-corrections.md`.
"""

from __future__ import annotations

import pathlib

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

OUT = pathlib.Path("docs/The-Wet-Stack-Mireye-Technical-Document.docx")

ACCENT = RGBColor(0x0F, 0x6D, 0x78)
INK = RGBColor(0x1A, 0x1A, 0x1A)


def heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(7)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = ACCENT


def body(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    add_rich(p, text)


def bullet(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    add_rich(p, text)


def numbered(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="List Number")
    p.paragraph_format.space_after = Pt(2)
    add_rich(p, text)


def add_rich(paragraph, text: str) -> None:
    """Render **bold** and `code` spans.

    Word has no markdown, so backticks would otherwise print literally. Code
    spans become Consolas runs and the ticks are dropped.
    """
    for i, chunk in enumerate(text.split("**")):
        if not chunk:
            continue
        bold = i % 2 == 1
        for j, part in enumerate(chunk.split("`")):
            if not part:
                continue
            run = paragraph.add_run(part)
            run.bold = bold
            if j % 2 == 1:
                run.font.name = "Consolas"
                run.font.size = Pt(8)
            else:
                run.font.size = Pt(9)


# ---------------------------------------------------------------------------
# Content. Everything verified 2026-08-24 against the running system.
# ---------------------------------------------------------------------------

SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "What We're Building",
        [
            ("body",
             "The Wet Stack is a construction and EPC intelligence layer built on **Mireye**, "
             "covering the two moments where a data center gets decided: once at site selection, "
             "and again every time equipment is substituted mid-build. Both decisions run on "
             "physical facts. Our job is to make every one of those facts traceable back to the "
             "Mireye record it came from, rather than quietly backfilled."),
            ("body",
             "AI agents plan investigations and write explanations; a deterministic Python layer "
             "performs every calculation, unit conversion, gate check and score. A regression "
             "test enforces this: there is no path by which the model can emit a number."),
        ],
    ),
    (
        "How We Use Mireye",
        [
            ("body",
             "Mireye is the ground truth for the entire product. Of **3,819 evidence records** "
             "currently in the system, **3,435 come from the live Mireye API**, drawn through it "
             "from USGS, FEMA, NREL, EIA, NOAA, EPA, NRCS and FCC."),
            ("bullet",
             "**Catalog-driven, not guessed** - we read `/v1/meta/fields` and bind our 30 "
             "concepts to the live catalog's **310 fields** by name. 11 map exactly, 6 need a "
             "unit conversion applied at the boundary, 3 are labelled contextual proxies, and 2 "
             "sit in the billed `parcel_record` group and are opt-in."),
            ("bullet",
             "**We corrected the contract against the live service** - our first integration got "
             "five things wrong: catalog entries key on `name` not `key`; geocode returns "
             "`lat`/`lng`/`accuracy_type`; `/v1/fetch` takes coordinates or an address but never "
             "both; absence arrives as `value: null` inside `fields{}`, not a separate list; and "
             "`confidence` is a word, not a float. All five are written up in "
             "`docs/mireye-contract.md`."),
            ("bullet",
             "**We respect what it costs** - Mireye bills per field per location and "
             "`parcel_record` is 300 credits, so responses are cached against the catalog's own "
             "`ttl_seconds` and a budget caps spend per investigation. Hitting the cap is not an "
             "error: unqueried sites record a gap saying so, rather than presenting partial "
             "coverage as complete."),
            ("bullet",
             "**Endpoints in use** - `/v1/meta/fields`, `/v1/geocode` and `/v1/fetch` for "
             "anything that feeds a score; `/v1/ask` for exploratory questions only. A test fails "
             "if the scoring path ever calls `/v1/ask`, because prose must never become a number "
             "in a calculation."),
            ("bullet",
             "**Where Mireye has no equivalent, we say so** - 14 of our 30 concepts have no "
             "catalog field. Six are filled from public datasets; the rest stay open with a named "
             "next action, and are filed back as feature requests."),
        ],
    ),
    (
        "Architecture & Core Stack",
        [
            ("bullet",
             "**Backend** - FastAPI + Pydantic v2 for the API and schema layer, Pint for "
             "unit-safe physical and electrical arithmetic, LangGraph for multi-step agent "
             "orchestration, PyMuPDF for PDF ingestion and OCR, Redis for caching Mireye "
             "responses, Neo4j for impact-graph traversal, Postgres/pgvector for optional "
             "live-mode vector storage."),
            ("bullet",
             "**Frontend** - React 18 + TypeScript on Vite, Tailwind for the design system, "
             "Recharts for engineering margin visualisation, Leaflet for GIS site mapping."),
            ("bullet",
             "**Four agents** - Change Orchestrator (substitution lifecycle), Site Intelligence "
             "Supervisor (LangGraph state machine across 8 dimensions), Project Knowledge / "
             "Document MCP agent (submittal search with page-level citations), and a Requirement "
             "Parser that turns plain-language equipment asks into structured physics and "
             "electrical constraints."),
            ("bullet",
             "**Both workflows run the same seven-step loop** - Understand, Plan, Evidence, "
             "Signals, Replan, Impact, Action - spanning **30 tracked concepts across 8 "
             "dimensions**: terrain, water, power, connectivity, civil, hazards, environmental "
             "and regulatory."),
        ],
    ),
    (
        "Evidence Integrity",
        [
            ("body",
             "The system is built on one rule: what was not measured stays unmeasured. It is "
             "never rounded to zero and never quietly replaced by a nearby measurement. Three "
             "mechanisms enforce it."),
            ("bullet",
             "**Relevance validation** - a value sharing a unit with the one required but not its "
             "meaning is stored as `CONTEXTUAL_PROXY`: cited and visible, but unable to fill the "
             "field, close its gap or pass a gate. Mireye's 0.4% design **wet-bulb** against our "
             "**dry-bulb** requirement is the reference case, both in Celsius. Enforcing it "
             "dropped coverage from **0.348 to 0.259** and left the decision unchanged. That drop "
             "is the system being honest."),
            ("bullet",
             "**Gaps become actions** - a concept with no source is flagged **MISSING** with the "
             "action that would resolve it, such as commissioning a geotechnical survey. Eight "
             "such concepts are deliberately kept because each produces an action; six others "
             "were removed because they produced noise without one."),
            ("bullet",
             "**OCR discipline** - values read by OCR are recorded at half confidence and flagged "
             "for manual verification, because a misread digit is a fabricated figure with a "
             "citation attached."),
        ],
    ),
    (
        "What's Actually Built and Live",
        [
            ("body", "**Change Intelligence (during construction)**"),
            ("bullet",
             "**9 deterministic verification gates** - manufacturer comparability, voltage and "
             "phase match, refrigerant suitability, rated ambient against the site's ASHRAE "
             "extremes taken from Mireye, footprint boundary, structural floor loading and others."),
            ("bullet",
             "**15 Pint-checked deltas** across weight, maximum support point load, length, "
             "width, height, footprint area, voltage, phases, FLA, MCA, MOCP, power input, "
             "refrigerant type, refrigerant charge and cooling capacity."),
            ("bullet",
             "Design margins, cost and schedule impact, cascade loading across concurrent "
             "changes, catalog ranking across **11 equipment classes**, a dependency impact graph, "
             "and an RFI and action-package generator with citation export."),
            ("bullet",
             "**Every case resolves deterministically to one of three states**: NEEDS "
             "INFORMATION, ENGINEER REVIEW, or first-pass checks closed."),
            ("body", "**Site Intelligence (before construction)**"),
            ("bullet",
             "Deterministic, explainable scoring across all 8 dimensions, every score carrying "
             "its Mireye citation and an explicit list of open data gaps. On the demo project: 9 "
             "candidate sites, 200 open gaps of which 9 are blocking."),
            ("body", "**Live system numbers**"),
            ("bullet",
             "**3,435 live Mireye evidence records**, and **97.8% of all 3,819 records are real "
             "sourced data** rather than synthetic."),
            ("bullet",
             "**5 contract mismatches** found and fixed against the live Mireye service."),
            ("bullet", "**277 tests passing**; lint and typecheck clean."),
            ("bullet",
             "**5 public datasets wired in** alongside Mireye, covering 6 concepts the catalog "
             "does not serve: PeeringDB, EPA/USGS Water Quality Portal, USGS PAD-US, EIA-861 and "
             "the FEMA National Risk Index."),
        ],
    ),
    (
        "Impact - What the System Has Already Caught",
        [
            ("bullet",
             "**Harbour Point, VA** - groundwater at 6,610 mg/L total dissolved solids, which is "
             "brackish and directly changes the cooling design. It would have been invisible "
             "behind a placeholder value."),
            ("bullet",
             "**Rio Verde Mesa, AZ** - rated Very High for wildfire and sitting inside Tonto "
             "National Forest, confirmed by two independent datasets. It also corrected our own "
             "earlier error, which had reported the site as 4 km from a shooting range because a "
             "capped query never returned the national forest it sits in."),
            ("bullet",
             "**FEMA scale correction** - FEMA's wildfire index runs 0 to 100, but its own Very "
             "Low band has a median of 43.6, nowhere near zero. Scored linearly, every safe site "
             "in the country would have lost half its wildfire points. Thresholds now follow "
             "FEMA's published bands, with a test that fails if a future release moves them."),
            ("body",
             "**Why it matters:** a hyperscale site is a $1-3 billion commitment made on the "
             "weakest evidence in the project's lifecycle. The cost of choosing badly is not the "
             "land; it is the brackish water or wildfire exposure found after the option is "
             "signed. During construction, this identifies which discipline needs review while "
             "explicitly declining to claim adequacy. That refusal is what makes it usable by "
             "someone carrying real liability."),
        ],
    ),
    (
        "Plan for the Next Days",
        [
            ("bullet",
             "Replace the remaining 84 synthetic document records with AHRI-certified ratings and "
             "manufacturer submittals, through the upload and OCR path already built."),
            ("bullet",
             "Bring in 4 more public sources: WRI Aqueduct, USGS 3DEP, USDA CropScape, NOAA ISD."),
            ("bullet",
             "File the concepts Mireye does not yet serve back as feature requests, so the "
             "catalog and the model converge rather than diverge."),
            ("bullet",
             "Move to a production architecture: Kafka, Redis, Postgres and a projection-based "
             "impact graph, designed in `docs/production-lld.md`."),
        ],
    ),
    (
        "Implementation Detail",
        [
            ("body",
             "**Decision precedence** (`change_orchestrator.py`) - every case walks the same "
             "three checks, in order, before it can close:"),
            ("number",
             "A required parameter is missing or unevidenced, giving **NEEDS INFORMATION** and "
             "opening an information gap."),
            ("number",
             "Otherwise a verification gate fails, a delta threshold is breached, or a site "
             "design limit taken from Mireye is exceeded, giving **ENGINEER REVIEW** and "
             "triggering impact-graph traversal."),
            ("number", "Otherwise first-pass checks are closed, within all design limits."),
            ("body",
             "**Catalog engine** (`catalog_engine.py`) weights the 11 equipment classes: capacity "
             "25%, energy efficiency 20%, electrical compatibility 15%, climate fit 10%, "
             "footprint 10%, then water efficiency, cost, maintenance and project compatibility "
             "at 5% each. A criterion with an unknown input is not scored and the total "
             "renormalises, so a product with no published capacity cannot out-rank one that "
             "simply scores badly."),
            ("body",
             "**Cascade engine** (`cascade.py`) aggregates concurrent changes on electrical load, "
             "structural weight and cooling duty against substation, generator and roof-steel "
             "headroom. Headroom is a fraction of a capacity, so where the facility's capacity is "
             "not stated it returns **NEEDS_INFORMATION** and names what is missing, rather than "
             "issuing a structural verdict against an assumed building."),
            ("body",
             "**Core module map** - `gates.py` (9 gates), `deltas.py` / `units.py` (15 deltas), "
             "`margins.py`, `impact.py`, `cost_schedule.py`, and `adapters/mireye.py` (typed "
             "contract, caching, credit budget). Agents: `change_orchestrator.py`, `workflow.py` "
             "/ `planner.py`, `knowledge_agent.py`."),
        ],
    ),
]

TABLE = [
    ("Layer", "Library", "Version", "Role"),
    ("Backend", "FastAPI", ">=0.110", "Async API layer, OpenAPI contract generation"),
    ("Backend", "Pydantic v2", ">=2.6", "Schema validation and environment config"),
    ("Backend", "Pint", ">=0.23", "Unit-safe physical and electrical arithmetic"),
    ("Backend", "LangGraph", ">=0.2", "Stateful multi-agent orchestration"),
    ("Backend", "PyMuPDF", ">=1.24", "PDF ingestion, table extraction, OCR"),
    ("Backend", "Redis", ">=5.0", "Mireye response cache, keyed on the catalog's own TTLs"),
    ("Backend", "Neo4j / Psycopg 3", ">=5.19 / >=3.1", "Impact graph traversal / Postgres + pgvector"),
    ("Frontend", "React 18 + Vite 6", "-", "Typed UI, Tailwind v4 styling, dev and build tooling"),
]


def main() -> None:
    doc = Document()

    # Word's defaults (1.08 line spacing, 8pt after every paragraph, generous
    # list indents) push this to three pages on their own. Tightened here rather
    # than by cutting content, since the content is the deliverable.
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(9)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(2)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.line_spacing = 1.0

    for style_name in ("List Bullet", "List Number"):
        st = doc.styles[style_name]
        st.font.size = Pt(9)
        st.paragraph_format.space_after = Pt(1)
        st.paragraph_format.space_before = Pt(0)
        st.paragraph_format.line_spacing = 1.0
        st.paragraph_format.left_indent = Pt(14)
        st.paragraph_format.first_line_indent = Pt(-9)

    for section in doc.sections:
        section.top_margin = section.bottom_margin = Pt(34)
        section.left_margin = section.right_margin = Pt(40)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = title.add_run("The Wet Stack")
    run.bold = True
    run.font.size = Pt(17)
    run.font.color.rgb = INK
    run = title.add_run("  /  Mireye")
    run.bold = True
    run.font.size = Pt(17)
    run.font.color.rgb = ACCENT

    sub = doc.add_paragraph()
    sub.paragraph_format.space_after = Pt(5)
    run = sub.add_run(
        "Physical-world intelligence for data-center siting and EPC change control. "
        "Technical document, Round 1."
    )
    run.font.size = Pt(9.5)
    run.italic = True

    for name, blocks in SECTIONS:
        heading(doc, name)
        for kind, text in blocks:
            {"body": body, "bullet": bullet, "number": numbered}[kind](doc, text)

    heading(doc, "Core Dependency Versions")
    table = doc.add_table(rows=1, cols=4)
    table.style = "Light Grid Accent 1"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, text in enumerate(TABLE[0]):
        cell = table.rows[0].cells[i]
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        run.font.size = Pt(9)
    for row in TABLE[1:]:
        cells = table.add_row().cells
        for i, text in enumerate(row):
            cells[i].text = ""
            run = cells[i].paragraphs[0].add_run(text)
            run.font.size = Pt(8)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"wrote {OUT}  ({OUT.stat().st_size / 1024:.0f} kB)")


if __name__ == "__main__":
    main()
