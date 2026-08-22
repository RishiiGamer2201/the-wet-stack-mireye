"""Retrieval over ingested document chunks.

Three layers, chosen automatically:

* `LexicalIndex`      — BM25 over the SQLite chunk store. Always available.
* `LocalVectorIndex`  — deterministic hashed-ngram embeddings + cosine similarity.
                        Gives real vector retrieval with no API key.
* `PgVectorIndex`     — Postgres/pgvector when DATABASE_URL is configured.

`HybridIndex` fuses lexical and vector ranks so a query works whether the useful
signal is an exact token (a model number) or a paraphrase.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter
from typing import Protocol

from ..config import get_settings
from ..domain import DocumentChunk, ProjectDocument, RetrievedChunk
from ..store import C, Store, get_store

log = logging.getLogger("vector")

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-\./]*")
STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "at", "is", "are",
    "be", "with", "by", "as", "shall", "that", "this", "it", "from",
}


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


class Index(Protocol):
    backend: str

    def search(self, project_id: str, query: str, k: int = 5) -> list[RetrievedChunk]: ...


def _doc_names(store: Store, project_id: str) -> dict[str, str]:
    return {d.id: d.filename for d in store.list(C.DOCUMENTS, ProjectDocument, project_id=project_id)}


class LexicalIndex:
    """BM25. ponytail: scores the whole project corpus per query — fine at demo scale."""

    backend = "lexical"
    K1 = 1.5
    B = 0.75

    def __init__(self, store: Store | None = None) -> None:
        self.store = store or get_store()

    def search(self, project_id: str, query: str, k: int = 5) -> list[RetrievedChunk]:
        chunks = self.store.list(C.CHUNKS, DocumentChunk, project_id=project_id)
        if not chunks:
            return []
        names = _doc_names(self.store, project_id)
        docs = [tokenize(c.text) for c in chunks]
        avg_len = sum(len(d) for d in docs) / len(docs)
        df = Counter()
        for d in docs:
            df.update(set(d))
        q_terms = tokenize(query)
        scored: list[tuple[float, DocumentChunk]] = []
        for chunk, tokens in zip(chunks, docs, strict=True):
            tf = Counter(tokens)
            score = 0.0
            for term in q_terms:
                if term not in tf:
                    continue
                idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
                freq = tf[term]
                score += idf * (freq * (self.K1 + 1)) / (
                    freq + self.K1 * (1 - self.B + self.B * len(tokens) / avg_len)
                )
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda x: -x[0])
        return [
            RetrievedChunk(
                chunk_id=c.id,
                document_id=c.document_id,
                document_name=names.get(c.document_id, c.document_id),
                page=c.page,
                text=c.text,
                score=round(s, 4),
                method="lexical",
                ocr=c.ocr,
            )
            for s, c in scored[:k]
        ]


class HashingEmbedder:
    """Deterministic local embedding: hashed character 4-grams + word unigrams.

    Not semantically strong, but it is a genuine dense vector, needs no network,
    and is stable across runs — which is what the offline demo needs.
    """

    dimensions = 256
    provider = "local_hashing"

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        lowered = text.lower()
        grams = [lowered[i : i + 4] for i in range(max(0, len(lowered) - 3))]
        for token in tokenize(text) + grams:
            h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
            vec[h % self.dimensions] += 1.0 if len(token) > 4 else 0.5
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class LocalVectorIndex:
    backend = "local_vector"

    def __init__(self, store: Store | None = None, embedder: HashingEmbedder | None = None) -> None:
        self.store = store or get_store()
        self.embedder = embedder or HashingEmbedder()

    def embed_chunk(self, chunk: DocumentChunk) -> DocumentChunk:
        chunk.embedding = self.embedder.embed(chunk.text)
        return chunk

    def search(self, project_id: str, query: str, k: int = 5) -> list[RetrievedChunk]:
        chunks = self.store.list(C.CHUNKS, DocumentChunk, project_id=project_id)
        embedded = [c for c in chunks if c.embedding]
        if not embedded:
            return []
        names = _doc_names(self.store, project_id)
        qv = self.embedder.embed(query)
        scored = sorted(
            ((cosine(qv, c.embedding), c) for c in embedded), key=lambda x: -x[0]
        )
        return [
            RetrievedChunk(
                chunk_id=c.id,
                document_id=c.document_id,
                document_name=names.get(c.document_id, c.document_id),
                page=c.page,
                text=c.text,
                score=round(s, 4),
                method="vector",
                ocr=c.ocr,
            )
            for s, c in scored[:k]
            if s > 0.01
        ]


class ChromaVectorIndex:
    """ChromaDB-backed vector index with persistent local storage."""

    backend = "chromadb"

    def __init__(self, persist_dir: str | None = None, embedder: HashingEmbedder | None = None) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.embedder = embedder or HashingEmbedder()
        self.persist_dir = persist_dir or str(get_settings().data_dir / "chroma")
        self._client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
        )
        self._collection = self._client.get_or_create_collection(
            name="project_documents",
            metadata={"description": "The Wet Stack Ingested Project Document Chunks"},
        )

    def embed_chunk(self, chunk: DocumentChunk) -> DocumentChunk:
        chunk.embedding = self.embedder.embed(chunk.text)
        return chunk

    def upsert(self, chunk: DocumentChunk, document_name: str) -> None:
        embedding = chunk.embedding or self.embedder.embed(chunk.text)
        metadata = {
            "project_id": chunk.project_id,
            "document_id": chunk.document_id,
            "document_name": document_name,
            "page": chunk.page,
            "ocr": bool(chunk.ocr),
        }
        self._collection.upsert(
            ids=[chunk.id],
            embeddings=[embedding],
            documents=[chunk.text],
            metadatas=[metadata],
        )

    def search(self, project_id: str, query: str, k: int = 5) -> list[RetrievedChunk]:
        query_vec = self.embedder.embed(query)
        res = self._collection.query(
            query_embeddings=[query_vec],
            n_results=max(1, k),
            where={"project_id": project_id},
            include=["documents", "metadatas", "distances"],
        )
        if not res or not res.get("ids") or not res["ids"][0]:
            return []

        out: list[RetrievedChunk] = []
        ids = res["ids"][0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        distances = res.get("distances", [[]])[0] if "distances" in res else [0.0] * len(ids)

        for cid, doc_text, meta, dist in zip(ids, docs, metas, distances, strict=False):
            score = max(0.0, 1.0 - float(dist)) if dist is not None else 0.5
            out.append(
                RetrievedChunk(
                    chunk_id=cid,
                    document_id=str(meta.get("document_id", "")),
                    document_name=str(meta.get("document_name", "")),
                    page=int(meta.get("page", 1)),
                    text=doc_text or "",
                    score=round(score, 4),
                    method="vector(chromadb)",
                    ocr=bool(meta.get("ocr", False)),
                )
            )
        return out


class PgVectorIndex:
    """pgvector-backed retrieval used when DATABASE_URL is configured."""

    backend = "pgvector"

    def __init__(self, dsn: str, embedder: HashingEmbedder | None = None) -> None:
        import psycopg  # lazy: optional dependency

        self._connect = lambda: psycopg.connect(dsn)
        self.embedder = embedder or HashingEmbedder()
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS document_chunks ("
                "id text PRIMARY KEY, project_id text, document_id text, document_name text,"
                f"page int, text text, embedding vector({self.embedder.dimensions}),"
                "ocr boolean DEFAULT false)"
            )
            conn.commit()

    def upsert(self, chunk: DocumentChunk, document_name: str) -> None:
        vector = chunk.embedding or self.embedder.embed(chunk.text)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO document_chunks VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (id) DO UPDATE SET text=EXCLUDED.text, "
                "embedding=EXCLUDED.embedding, ocr=EXCLUDED.ocr",
                (
                    chunk.id, chunk.project_id, chunk.document_id, document_name,
                    chunk.page, chunk.text, str(vector), chunk.ocr,
                ),
            )
            conn.commit()

    def search(self, project_id: str, query: str, k: int = 5) -> list[RetrievedChunk]:
        vector = str(self.embedder.embed(query))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, document_id, document_name, page, text, "
                "1 - (embedding <=> %s::vector) AS score, ocr FROM document_chunks "
                "WHERE project_id = %s ORDER BY embedding <=> %s::vector LIMIT %s",
                (vector, project_id, vector, k),
            ).fetchall()
        return [
            RetrievedChunk(
                chunk_id=r[0], document_id=r[1], document_name=r[2], page=r[3],
                text=r[4], score=round(float(r[5]), 4), method="vector",
                ocr=bool(r[6]),
            )
            for r in rows
        ]


class HybridIndex:
    """Reciprocal-rank fusion of a lexical (BM25) and a vector index (Chroma/pgvector/local).

    If the vector side raises (service down, driver missing) the lexical result is
    returned and the degradation is logged — retrieval never hard-fails.
    """

    backend = "hybrid"

    def __init__(self, lexical: Index, vector: Index | None) -> None:
        self.lexical = lexical
        self.vector = vector
        self.backend = f"hybrid({lexical.backend}+{vector.backend})" if vector else lexical.backend
        self.degraded_reason: str | None = None

    def search(self, project_id: str, query: str, k: int = 5) -> list[RetrievedChunk]:
        lex = self.lexical.search(project_id, query, k=k * 2)
        vec: list[RetrievedChunk] = []
        if self.vector:
            try:
                vec = self.vector.search(project_id, query, k=k * 2)
            except Exception as exc:  # noqa: BLE001 - degrade, do not fail retrieval
                self.degraded_reason = str(exc)
                log.warning("vector index unavailable", extra={"error": str(exc)})
        if not vec:
            return lex[:k]
        fused: dict[str, tuple[float, RetrievedChunk]] = {}
        for rank_list in (lex, vec):
            for rank, item in enumerate(rank_list, start=1):
                prev = fused.get(item.chunk_id)
                bump = 1.0 / (60 + rank)
                if prev:
                    fused[item.chunk_id] = (prev[0] + bump, prev[1])
                else:
                    fused[item.chunk_id] = (bump, item)
        ordered = sorted(fused.values(), key=lambda x: -x[0])
        out = []
        for score, item in ordered[:k]:
            item.score = round(score, 5)
            out.append(item)
        return out


_index: Index | None = None


def get_index() -> Index:
    global _index
    if _index is None:
        settings = get_settings()
        vector: Index | None = None

        if settings.pgvector_live:
            try:
                vector = PgVectorIndex(settings.database_url)
                log.info("using pgvector index")
            except Exception as exc:  # noqa: BLE001
                log.warning("pgvector unavailable", extra={"error": str(exc)})

        if vector is None:
            try:
                vector = ChromaVectorIndex()
                log.info("using ChromaDB vector index")
            except Exception as exc:  # noqa: BLE001
                log.warning("ChromaDB init failed, falling back to LocalVectorIndex", extra={"error": str(exc)})
                vector = LocalVectorIndex()

        _index = HybridIndex(LexicalIndex(), vector)
    return _index


def set_index(index: Index | None) -> None:
    global _index
    _index = index
