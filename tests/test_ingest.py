"""Document ingestion, extraction and retrieval (including failure paths)."""

from __future__ import annotations

import pytest
from app.adapters.vectorstore import (
    HybridIndex,
    LexicalIndex,
    LocalVectorIndex,
    get_index,
)
from app.domain import DocumentKind, ProjectDocument, Requirement
from app.seed import write_sample_pdf
from app.services.ingest import (
    IngestionError,
    chunk_pages,
    extract_requirements,
    ingest_pdf,
    validate_upload,
)
from app.store import C

SPEC_TEXT = (
    "Each chiller CH-01 shall provide a minimum net cooling capacity of 1040 kW at the "
    "scheduled conditions. The maximum operating weight for CH-01 shall not exceed 5000 kg. "
    "Minimum circuit ampacity for CH-01 shall not exceed 300 A. "
    "Refrigerant type shall be R-134a."
)


def doc(project_id="p1"):
    return ProjectDocument(project_id=project_id, filename="spec.pdf", kind=DocumentKind.SPECIFICATION)


# --- validation -------------------------------------------------------------


def test_upload_validation_rejects_wrong_type_and_size():
    with pytest.raises(IngestionError):
        validate_upload("x.docx", "application/msword", 100)
    with pytest.raises(IngestionError):
        validate_upload("x.pdf", "application/pdf", 0)
    with pytest.raises(IngestionError):
        validate_upload("x.pdf", "application/pdf", 999_999_999)
    validate_upload("x.pdf", "application/pdf", 1000)


# --- chunking + extraction --------------------------------------------------


def test_chunks_keep_page_and_offsets():
    chunks = chunk_pages(doc(), ["", SPEC_TEXT * 4])
    assert chunks
    assert all(c.page == 2 for c in chunks)
    assert all(c.char_end > c.char_start for c in chunks)
    assert chunks[0].ordinal == 0


def test_requirements_are_extracted_with_value_unit_page_and_span():
    d = doc()
    requirements = extract_requirements(d, chunk_pages(d, [SPEC_TEXT]))
    keys = {r.field_key for r in requirements}
    assert {"cooling_capacity", "operating_weight", "mca"} <= keys
    capacity = next(r for r in requirements if r.field_key == "cooling_capacity")
    assert capacity.value == 1040 and capacity.unit == "kW"
    assert capacity.page == 1 and capacity.span and capacity.span.text
    assert capacity.equipment_tag == "CH-01"
    assert capacity.confirmed is False  # nothing is trusted before confirmation


def test_identifiers_are_not_misread_as_measurements():
    """'R-134a' must not be extracted as '-134 amps', and a code reference keeps its full name."""
    d = doc()
    text = (
        "Refrigerant type shall be R-134a. "
        "All equipment shall comply with AHRI 550/590 certification requirements."
    )
    requirements = extract_requirements(d, chunk_pages(d, [text]))
    refrigerant = next(r for r in requirements if r.field_key == "refrigerant_type")
    assert refrigerant.value == "R-134a" and refrigerant.unit is None
    code = next(r for r in requirements if r.field_key == "code_reference")
    assert code.value == "AHRI 550/590"


def test_extraction_of_a_document_with_no_recognisable_requirement_returns_nothing():
    d = doc()
    text = "This page is about the parking layout and the site fence."
    assert extract_requirements(d, chunk_pages(d, [text])) == []


def test_unreadable_pdf_is_recorded_as_failed(store, tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not really a pdf")
    with pytest.raises(IngestionError):
        ingest_pdf(store, "p1", broken, "broken.pdf")
    documents = store.list(C.DOCUMENTS, ProjectDocument, project_id="p1")
    assert documents and documents[0].extraction_status == "failed"
    assert documents[0].extraction_error


def test_pdf_without_text_is_flagged_not_silently_empty(store, tmp_path):
    blank = write_sample_pdf(tmp_path / "blank.pdf", "blank", [" "])
    document, chunks, requirements = ingest_pdf(store, "p1", blank, "blank.pdf")
    assert chunks == [] and requirements == []
    assert document.extraction_status == "failed"
    assert "OCR" in document.extraction_error


def test_full_ingest_creates_chunks_requirements_and_evidence(store, tmp_path):
    path = write_sample_pdf(tmp_path / "spec.pdf", "spec", [SPEC_TEXT])
    document, chunks, requirements = ingest_pdf(
        store, "p1", path, "spec.pdf", kind=DocumentKind.SPECIFICATION
    )
    assert document.extraction_status == "extracted"
    assert document.sha256 and document.page_count == 1
    assert chunks and requirements
    stored = store.list(C.REQUIREMENTS, Requirement, project_id="p1")
    assert stored and all(r.evidence_id for r in stored)


# --- retrieval --------------------------------------------------------------


def test_lexical_and_vector_retrieval_both_find_the_chunk(store, seeded):
    lexical = LexicalIndex(store).search(seeded.id, "minimum circuit ampacity CH-01", k=3)
    vector = LocalVectorIndex(store).search(seeded.id, "minimum circuit ampacity CH-01", k=3)
    assert lexical and lexical[0].method == "lexical"
    assert vector and vector[0].method == "vector"
    assert all(r.page >= 1 and r.document_name for r in lexical)


def test_hybrid_survives_a_broken_vector_backend(store, seeded):
    class Broken:
        backend = "broken"

        def search(self, *a, **kw):
            raise RuntimeError("pgvector unavailable")

    index = HybridIndex(LexicalIndex(store), Broken())
    results = index.search(seeded.id, "cooling capacity", k=3)
    assert results
    assert index.degraded_reason == "pgvector unavailable"


def test_retrieval_returns_nothing_for_an_empty_project(store):
    assert get_index().search("no-such-project", "anything", k=3) == []
