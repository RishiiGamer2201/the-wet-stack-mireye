"""OCR of scanned pages.

The rule these tests defend: OCR widens what the system can *read*, and changes
nothing about what it is allowed to *believe*. A transcribed number is marked at
every level it travels through and is never a confirmed value.

Tests that need Tesseract skip when the host has none, so the suite passes on a
machine without it — but the marking rules below are asserted either way.
"""

from __future__ import annotations

import pymupdf
import pytest
from app.domain import DocumentKind, Evidence, Requirement, VerificationStatus
from app.seed import write_sample_pdf
from app.services.ingest import (
    chunk_pages,
    evidence_for_requirement,
    extract_requirements,
    ingest_pdf,
    ocr_available,
)
from app.store import C

SPEC_LINE = "CH-55 net cooling capacity shall be 1,275 kW at 7 C LWT."
WEIGHT_LINE = "Operating weight 9,120 kg. Full load amps 410 A at 480 V."

needs_tesseract = pytest.mark.skipif(
    not ocr_available(), reason="Tesseract is not installed on this host"
)


def make_scanned_pdf(path, lines: list[str], *, text_page_first: bool = True):
    """A PDF whose second page is an image of text — a scan, with no text layer."""
    source = pymupdf.open()
    page = source.new_page()
    for i, line in enumerate(lines):
        page.insert_text((60, 90 + i * 26), line, fontsize=12)

    out = pymupdf.open()
    if text_page_first:
        out.new_page().insert_text((60, 90), "This page has a real text layer.", fontsize=12)
    pixmap = source[0].get_pixmap(dpi=200)
    image_page = out.new_page(width=source[0].rect.width, height=source[0].rect.height)
    image_page.insert_image(image_page.rect, pixmap=pixmap)
    out.save(path)
    out.close()
    source.close()
    return path


def test_the_fixture_really_has_no_text_layer(tmp_path):
    """If this fails the other tests prove nothing — they would be reading text."""
    path = make_scanned_pdf(tmp_path / "scan.pdf", [SPEC_LINE])
    with pymupdf.open(path) as doc:
        layers = [len((page.get_text() or "").strip()) for page in doc]
    assert layers[0] > 0 and layers[1] == 0


# --- marking rules: asserted with or without Tesseract ----------------------


def test_a_transcribed_chunk_halves_the_requirement_confidence():
    document = type("Doc", (), {"id": "doc_1", "project_id": "p1"})()
    read, transcribed = chunk_pages(document, [SPEC_LINE], set()), chunk_pages(
        document, [SPEC_LINE], {1}
    )
    from_read = extract_requirements(document, read)
    from_ocr = extract_requirements(document, transcribed)

    assert from_read and from_ocr
    assert from_read[0].value == from_ocr[0].value
    assert from_ocr[0].confidence == pytest.approx(from_read[0].confidence / 2)
    assert from_ocr[0].from_ocr is True and from_read[0].from_ocr is False


def test_a_transcribed_requirement_is_never_confirmed_on_arrival():
    document = type("Doc", (), {"id": "doc_1", "project_id": "p1"})()
    requirements = extract_requirements(document, chunk_pages(document, [SPEC_LINE], {1}))
    assert requirements
    assert all(r.confirmed is False for r in requirements)


def test_evidence_from_ocr_asks_for_a_human_read(seeded):
    from app.domain import ProjectDocument

    document = ProjectDocument(project_id=seeded.id, filename="scan.pdf")
    requirements = extract_requirements(document, chunk_pages(document, [SPEC_LINE], {1}))
    evidence = evidence_for_requirement(requirements[0], document)

    assert evidence.verification is VerificationStatus.NEEDS_REVIEW
    assert "transcription" in (evidence.source.notes or "")
    # Still real evidence with a real citation — it is trust that is reduced,
    # not provenance that is hidden.
    assert evidence.source.page == requirements[0].page
    assert evidence.source.synthetic is False


def test_evidence_from_a_text_layer_is_not_marked_for_review(seeded):
    from app.domain import ProjectDocument

    document = ProjectDocument(project_id=seeded.id, filename="spec.pdf")
    requirements = extract_requirements(document, chunk_pages(document, [SPEC_LINE], set()))
    evidence = evidence_for_requirement(requirements[0], document)
    assert evidence.verification is VerificationStatus.UNVERIFIED
    assert evidence.source.notes is None


# --- end to end, needs the binary -------------------------------------------


@needs_tesseract
def test_a_scanned_page_is_read_and_labelled(store, tmp_path):
    path = make_scanned_pdf(tmp_path / "scan.pdf", [SPEC_LINE, WEIGHT_LINE])
    document, chunks, requirements = ingest_pdf(
        store, "p1", path, "scan.pdf", kind=DocumentKind.SUBMITTAL
    )

    assert document.extraction_status == "extracted"
    assert document.ocr_pages == [2], "page 2 is the scan"
    assert document.unread_pages == []
    assert document.has_ocr
    assert "OCR" in (document.extraction_error or ""), "the warning travels with the document"

    by_page = {chunk.page: chunk.ocr for chunk in chunks}
    assert by_page[1] is False and by_page[2] is True

    capacity = next(r for r in requirements if r.field_key == "cooling_capacity")
    assert capacity.value == 1275.0 and capacity.unit == "kW"
    assert capacity.from_ocr is True and capacity.confirmed is False


@needs_tesseract
def test_a_born_digital_pdf_is_not_ocrd(store, tmp_path):
    """OCR is per page and only where there is no text layer, so a normal
    document costs nothing and is not marked."""
    path = write_sample_pdf(tmp_path / "spec.pdf", "spec", [SPEC_LINE])
    document, chunks, _ = ingest_pdf(store, "p1", path, "spec.pdf")
    assert document.ocr_pages == [] and document.unread_pages == []
    assert document.extraction_error is None
    assert all(chunk.ocr is False for chunk in chunks)


@needs_tesseract
def test_the_page_cap_reports_what_it_did_not_read(store, tmp_path, monkeypatch):
    """Silence about an unread page reads as 'not in the document'."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "ocr_max_pages", 1)

    source = pymupdf.open()
    for i in range(2):
        page = source.new_page()
        page.insert_text((60, 90), f"Scanned page {i + 1}: {SPEC_LINE}", fontsize=12)
    out = pymupdf.open()
    for i in range(2):
        pixmap = source[i].get_pixmap(dpi=150)
        page = out.new_page(width=source[i].rect.width, height=source[i].rect.height)
        page.insert_image(page.rect, pixmap=pixmap)
    path = tmp_path / "long-scan.pdf"
    out.save(path)
    out.close()
    source.close()

    document, _, _ = ingest_pdf(store, "p1", path, "long-scan.pdf")
    assert document.ocr_pages == [1]
    assert document.unread_pages == [2]
    assert "limit was reached" in (document.extraction_error or "")


@needs_tesseract
def test_a_search_hit_says_it_was_transcribed(store, tmp_path):
    path = make_scanned_pdf(tmp_path / "scan.pdf", [SPEC_LINE])
    ingest_pdf(store, "p1", path, "scan.pdf")

    from app.adapters.vectorstore import get_index

    hits = get_index().search("p1", "CH-55 net cooling capacity", k=5)
    scanned = [hit for hit in hits if hit.page == 2]
    assert scanned, "the transcribed page is searchable"
    assert scanned[0].ocr is True


def test_ocr_off_reports_the_scan_rather_than_reading_it(store, tmp_path, monkeypatch):
    """With OCR disabled the behaviour is the old one, stated plainly."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ocr_enabled", False)
    path = make_scanned_pdf(tmp_path / "scan.pdf", [SPEC_LINE], text_page_first=False)

    document, chunks, requirements = ingest_pdf(store, "p1", path, "scan.pdf")
    assert document.extraction_status == "failed"
    assert chunks == [] and requirements == []
    assert "not enabled on this host" in document.extraction_error


def test_no_orphan_requirements_are_stored_for_an_unreadable_scan(store, tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ocr_enabled", False)
    path = make_scanned_pdf(tmp_path / "scan.pdf", [SPEC_LINE], text_page_first=False)
    ingest_pdf(store, "p1", path, "scan.pdf")

    assert store.list(C.REQUIREMENTS, Requirement, project_id="p1") == []
    assert store.list(C.EVIDENCE, Evidence, project_id="p1") == []
