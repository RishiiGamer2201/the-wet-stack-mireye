"""Document ingestion: PDF -> page-aware text -> chunks -> candidate requirements.

Extraction is regex + keyword based and deliberately conservative: it proposes
requirements with a confidence and a source span, and a human confirms or
corrects them before they are used in any check (`confirmed = True`).
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..adapters.vectorstore import LocalVectorIndex, PgVectorIndex, get_index
from ..config import get_settings
from ..domain import (
    DocumentChunk,
    DocumentKind,
    Evidence,
    EvidenceSource,
    EvidenceStatus,
    ProjectDocument,
    Requirement,
    RequirementKind,
    SourceType,
    TextSpan,
)
from ..store import C, Store

log = logging.getLogger("ingest")

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150

EQUIPMENT_TAG_RE = re.compile(r"\b([A-Z]{2,4}-\d{1,3}[A-Z]?)\b")
MODEL_RE = re.compile(r"\b(?:model|type)\s*(?:no\.?|number)?[:\s]+([A-Z0-9][A-Z0-9\-/\.]{3,})", re.I)
NUMBER_UNIT_RE = re.compile(
    r"(?P<value>-?\d[\d,]*\.?\d*)\s*(?P<unit>kW|kg|lb|lbs|tons?|RT|mm|in\.?|ft|A|amps?|V|volts?|"
    r"°?C|°?F|degC|degF|kPa|psi|L/s|gpm|Hz|dB|MW|m2|m²)\b",
    re.I,
)
#: Refrigerant designations and code references are identifiers, not measurements —
#: matching them with NUMBER_UNIT_RE would read "R-134a" as "-134 amps".
REFRIGERANT_RE = re.compile(r"\bR-?\d{2,4}[a-zA-Z]{0,2}\b")
CODE_REF_RE = re.compile(r"\b(?:ASHRAE|NFPA|IBC|AHRI|ASCE|IEEE|UL)\s*\d+(?:[./-]\d+)*\b", re.I)

#: keyword -> (field_key, requirement kind, canonical unit hint)
REQUIREMENT_KEYWORDS: list[tuple[re.Pattern, str, RequirementKind, str | None]] = [
    (re.compile(r"cooling capacity|net capacity|refrigeration capacity", re.I),
     "cooling_capacity", RequirementKind.CAPACITY, "kW"),
    (re.compile(r"operating weight", re.I), "operating_weight", RequirementKind.WEIGHT, "kg"),
    (re.compile(r"shipping weight|dry weight", re.I), "dry_weight", RequirementKind.WEIGHT, "kg"),
    (re.compile(r"support point load|point load|corner load", re.I),
     "support_point_load", RequirementKind.WEIGHT, "kN"),
    (re.compile(r"minimum circuit ampacity|\bMCA\b", re.I), "mca", RequirementKind.ELECTRICAL, "A"),
    (re.compile(r"maximum overcurrent|\bMOCP\b", re.I), "mocp", RequirementKind.ELECTRICAL, "A"),
    (re.compile(r"full load amps|\bFLA\b", re.I),
     "full_load_amps", RequirementKind.ELECTRICAL, "A"),
    (re.compile(r"supply voltage|nominal voltage|service voltage", re.I),
     "voltage", RequirementKind.ELECTRICAL, "V"),
    (re.compile(r"refrigerant charge", re.I),
     "refrigerant_charge", RequirementKind.REFRIGERANT, "kg"),
    (re.compile(r"refrigerant type|refrigerant\s*[:=]", re.I),
     "refrigerant_type", RequirementKind.REFRIGERANT, None),
    (re.compile(r"entering water temperature|\bEWT\b", re.I),
     "entering_water_temp", RequirementKind.CONDITION, "degC"),
    (re.compile(r"leaving water temperature|\bLWT\b", re.I),
     "leaving_water_temp", RequirementKind.CONDITION, "degC"),
    (re.compile(r"ambient (?:design )?(?:dry.?bulb|temperature)", re.I),
     "ambient_temp", RequirementKind.CONDITION, "degC"),
    (re.compile(r"length|width|height|overall dimensions", re.I),
     "dimension", RequirementKind.DIMENSION, "mm"),
    (re.compile(r"ASHRAE \d+|NFPA \d+|IBC \d{4}|AHRI \d+", re.I),
     "code_reference", RequirementKind.CODE, None),
]

UNIT_NORMALISATION = {
    "lbs": "lb", "amps": "amp", "amp": "amp", "a": "A", "volts": "V", "volt": "V",
    "tons": "refrigeration_ton", "ton": "refrigeration_ton", "rt": "refrigeration_ton",
    "°c": "degC", "c": "degC", "°f": "degF", "f": "degF", "in.": "inch", "in": "inch",
    "m2": "m ** 2", "m²": "m ** 2", "gpm": "gallon / minute", "l/s": "liter / second",
}


class IngestionError(ValueError):
    pass


def safe_filename(filename: str) -> str:
    """Strip any directory component from a client-supplied filename.

    An upload named `../../x.pdf` must never be able to write outside the upload
    directory, so only the final path segment is ever used.
    """
    name = PurePosixPath(PureWindowsPath(filename or "").as_posix()).name
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).lstrip(". ").strip()
    return name[:120] or "upload.pdf"


def validate_upload(filename: str, content_type: str, size: int) -> None:
    settings = get_settings()
    if content_type not in settings.allowed_upload_types:
        raise IngestionError(
            f"unsupported content type {content_type!r}; allowed: "
            f"{', '.join(settings.allowed_upload_types)}"
        )
    if size <= 0:
        raise IngestionError("uploaded file is empty")
    if size > settings.max_upload_bytes:
        raise IngestionError(
            f"file is {size} bytes; the limit is {settings.max_upload_bytes} bytes"
        )
    if not filename.lower().endswith(".pdf"):
        raise IngestionError("only .pdf files are accepted")


def extract_pages(path: Path) -> list[str]:
    """Page-aware text extraction. Raises IngestionError on an unreadable file."""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise IngestionError("PyMuPDF is not installed") from exc
    try:
        # Opened from a byte stream, not the path: PyMuPDF keeps a file handle on a
        # failed open (so the rejected upload could not be deleted on Windows), and
        # the resulting error message would carry the server's absolute path.
        with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as doc:
            return [page.get_text() or "" for page in doc]
    except Exception as exc:  # noqa: BLE001 - corrupt/encrypted PDFs land here
        detail = str(exc).replace(str(path), path.name)
        raise IngestionError(f"could not read PDF: {detail}") from exc


def chunk_pages(document: ProjectDocument, pages: list[str]) -> list[DocumentChunk]:
    """Split each page into overlapping chunks, keeping page-relative offsets."""
    chunks: list[DocumentChunk] = []
    ordinal = 0
    for page_number, text in enumerate(pages, start=1):
        cleaned = re.sub(r"[ \t]+", " ", text).strip()
        if not cleaned:
            continue
        start = 0
        while start < len(cleaned):
            end = min(start + CHUNK_SIZE, len(cleaned))
            if end < len(cleaned):
                boundary = cleaned.rfind(". ", start + CHUNK_SIZE // 2, end)
                if boundary != -1:
                    end = boundary + 1
            body = cleaned[start:end].strip()
            if body:
                chunks.append(
                    DocumentChunk(
                        document_id=document.id,
                        project_id=document.project_id,
                        page=page_number,
                        ordinal=ordinal,
                        text=body,
                        char_start=start,
                        char_end=end,
                    )
                )
                ordinal += 1
            if end >= len(cleaned):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def _normalise_unit(unit: str) -> str:
    key = unit.strip().lower()
    return UNIT_NORMALISATION.get(key, unit.strip())


def extract_requirements(
    document: ProjectDocument, chunks: list[DocumentChunk]
) -> list[Requirement]:
    """Propose requirements from chunk text. Nothing here is trusted until confirmed."""
    requirements: list[Requirement] = []
    seen: set[tuple] = set()
    for chunk in chunks:
        for line in chunk.text.split("\n"):
            for sentence in re.split(r"(?<=[.;])\s+", line):
                if not sentence.strip():
                    continue
                for pattern, field_key, kind, unit_hint in REQUIREMENT_KEYWORDS:
                    match = pattern.search(sentence)
                    if not match:
                        continue
                    tag = EQUIPMENT_TAG_RE.search(sentence)
                    model = MODEL_RE.search(sentence)
                    value: float | str | None = None
                    unit: str | None = None
                    if field_key == "refrigerant_type":
                        found = REFRIGERANT_RE.search(sentence)
                        value = found.group(0) if found else None
                    elif field_key == "code_reference":
                        found = CODE_REF_RE.search(sentence)
                        value = found.group(0) if found else None
                    else:
                        number = NUMBER_UNIT_RE.search(sentence)
                        if number:
                            value = float(number.group("value").replace(",", ""))
                            unit = _normalise_unit(number.group("unit"))
                    if value is None:
                        continue
                    key = (field_key, str(value), unit, tag.group(1) if tag else None)
                    if key in seen:
                        continue
                    seen.add(key)
                    offset = chunk.text.find(sentence)
                    requirements.append(
                        Requirement(
                            project_id=document.project_id,
                            document_id=document.id,
                            kind=kind,
                            label=match.group(0).strip().title(),
                            field_key=field_key,
                            value=value,
                            unit=unit or unit_hint,
                            equipment_tag=tag.group(1) if tag else None,
                            model_identifier=model.group(1) if model else None,
                            page=chunk.page,
                            span=TextSpan(
                                start=chunk.char_start + max(offset, 0),
                                end=chunk.char_start + max(offset, 0) + len(sentence),
                                text=sentence.strip(),
                            ),
                            raw_text=sentence.strip(),
                            confidence=0.55 if unit else 0.4,
                        )
                    )
    return requirements


def evidence_for_requirement(requirement: Requirement, document: ProjectDocument) -> Evidence:
    return Evidence(
        project_id=requirement.project_id,
        subject_id=requirement.equipment_tag,
        claim=f"{requirement.label} = {requirement.value} {requirement.unit or ''}".strip(),
        field_key=requirement.field_key,
        value=requirement.value,
        unit=requirement.unit,
        source=EvidenceSource(
            source_type=(
                SourceType.MANUFACTURER_DOCUMENT
                if document.kind == DocumentKind.MANUFACTURER_DATASHEET
                else SourceType.PROJECT_DOCUMENT
            ),
            source_id=document.id,
            source_name=document.filename,
            page=requirement.page,
            span=requirement.span,
            field_key=requirement.field_key,
            synthetic=document.synthetic,
        ),
        status=EvidenceStatus.SYNTHETIC if document.synthetic else EvidenceStatus.LIVE,
        confidence=requirement.confidence,
    )


def ingest_pdf(
    store: Store,
    project_id: str,
    path: Path,
    filename: str,
    kind: DocumentKind = DocumentKind.OTHER,
    synthetic: bool = False,
) -> tuple[ProjectDocument, list[DocumentChunk], list[Requirement]]:
    """Full ingestion path. On extraction failure the document is persisted with
    `extraction_status = "failed"` so the UI can show what went wrong."""
    data = path.read_bytes()
    document = ProjectDocument(
        project_id=project_id,
        filename=filename,
        kind=kind,
        size_bytes=len(data),
        stored_path=str(path),
        sha256=hashlib.sha256(data).hexdigest(),
        synthetic=synthetic,
    )
    try:
        pages = extract_pages(path)
    except IngestionError as exc:
        document.extraction_status = "failed"
        document.extraction_error = str(exc)
        store.put(C.DOCUMENTS, document, project_id=project_id)
        raise

    document.page_count = len(pages)
    chunks = chunk_pages(document, pages)
    if not chunks:
        document.extraction_status = "failed"
        document.extraction_error = (
            "No extractable text found. The PDF is probably a scan; OCR is not enabled."
        )
        store.put(C.DOCUMENTS, document, project_id=project_id)
        return document, [], []

    index = get_index()
    embedder = getattr(index, "vector", None)
    for chunk in chunks:
        if isinstance(embedder, LocalVectorIndex):
            embedder.embed_chunk(chunk)
        store.put(C.CHUNKS, chunk, project_id=project_id, parent_id=document.id)
        if isinstance(embedder, PgVectorIndex):
            try:
                embedder.upsert(chunk, document.filename)
            except Exception as exc:  # noqa: BLE001 - degrade to lexical retrieval
                log.warning("pgvector upsert failed", extra={"error": str(exc)})

    requirements = extract_requirements(document, chunks)
    for requirement in requirements:
        ev = evidence_for_requirement(requirement, document)
        requirement.evidence_id = ev.id
        store.put(C.EVIDENCE, ev, project_id=project_id, parent_id=document.id)
        store.put(C.REQUIREMENTS, requirement, project_id=project_id, parent_id=document.id)

    document.extraction_status = "extracted"
    store.put(C.DOCUMENTS, document, project_id=project_id)
    log.info(
        "document ingested",
        extra={
            "document_id": document.id,
            "pages": document.page_count,
            "chunks": len(chunks),
            "requirements": len(requirements),
        },
    )
    return document, chunks, requirements
