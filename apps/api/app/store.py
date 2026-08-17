"""Persistence.

A single document-style table keeps the schema out of the way while the domain
model settles; `Store` is the seam a Supabase/Postgres implementation drops into
(see `docs/architecture.md`). All values are Pydantic models serialised to JSON.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T", bound=BaseModel)

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    collection TEXT NOT NULL,
    id         TEXT NOT NULL,
    project_id TEXT,
    parent_id  TEXT,
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (collection, id)
);
CREATE INDEX IF NOT EXISTS idx_records_project ON records(collection, project_id);
CREATE INDEX IF NOT EXISTS idx_records_parent  ON records(collection, parent_id);

CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


class Store:
    """SQLite-backed document store. Thread-safe via a single guarded connection."""

    def __init__(self, path: Path | str | None = None) -> None:
        settings = get_settings()
        self.path = Path(path) if path else settings.db_path
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()  # ponytail: one global lock; fine at demo scale
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # -- records ------------------------------------------------------------
    def put(
        self,
        collection: str,
        obj: BaseModel,
        *,
        project_id: str | None = None,
        parent_id: str | None = None,
    ) -> BaseModel:
        rid = obj.id
        pid = project_id if project_id is not None else getattr(obj, "project_id", None)
        with self._lock:
            self._conn.execute(
                "INSERT INTO records(collection,id,project_id,parent_id,data,updated_at) "
                "VALUES(?,?,?,?,?,datetime('now')) "
                "ON CONFLICT(collection,id) DO UPDATE SET "
                "data=excluded.data, project_id=excluded.project_id, "
                "parent_id=excluded.parent_id, updated_at=datetime('now')",
                (collection, rid, pid, parent_id, obj.model_dump_json()),
            )
            self._conn.commit()
        return obj

    def put_many(self, collection: str, objs: Iterable[BaseModel], **kw) -> None:
        for o in objs:
            self.put(collection, o, **kw)

    def get(self, collection: str, rid: str, model: type[T]) -> T | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM records WHERE collection=? AND id=?", (collection, rid)
            ).fetchone()
        return model.model_validate_json(row["data"]) if row else None

    def list(
        self,
        collection: str,
        model: type[T],
        *,
        project_id: str | None = None,
        parent_id: str | None = None,
    ) -> list[T]:
        sql = "SELECT data FROM records WHERE collection=?"
        args: list[object] = [collection]
        if project_id:
            sql += " AND project_id=?"
            args.append(project_id)
        if parent_id:
            sql += " AND parent_id=?"
            args.append(parent_id)
        sql += " ORDER BY updated_at ASC"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [model.model_validate_json(r["data"]) for r in rows]

    def delete(self, collection: str, rid: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM records WHERE collection=? AND id=?", (collection, rid))
            self._conn.commit()

    def clear(self, collection: str | None = None) -> None:
        with self._lock:
            if collection:
                self._conn.execute("DELETE FROM records WHERE collection=?", (collection,))
            else:
                self._conn.execute("DELETE FROM records")
                self._conn.execute("DELETE FROM cache")
            self._conn.commit()

    def count(self, collection: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) c FROM records WHERE collection=?", (collection,)
            ).fetchone()
        return int(row["c"])

    # -- cache --------------------------------------------------------------
    def cache_get(self, key: str) -> dict | None:
        import time

        with self._lock:
            row = self._conn.execute(
                "SELECT payload, expires_at FROM cache WHERE key=?", (key,)
            ).fetchone()
        if not row:
            return None
        if row["expires_at"] < time.time():
            with self._lock:
                self._conn.execute("DELETE FROM cache WHERE key=?", (key,))
                self._conn.commit()
            return None
        return json.loads(row["payload"])

    def cache_set(self, key: str, payload: dict, ttl_seconds: int) -> None:
        import time

        with self._lock:
            self._conn.execute(
                "INSERT INTO cache(key,payload,expires_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, "
                "expires_at=excluded.expires_at",
                (key, json.dumps(payload, default=str), time.time() + ttl_seconds),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# Collection names used across the app.
class C:
    PROJECTS = "projects"
    SITES = "sites"
    OBSERVATIONS = "observations"
    DOCUMENTS = "documents"
    CHUNKS = "chunks"
    REQUIREMENTS = "requirements"
    EQUIPMENT = "equipment"
    CHANGES = "changes"
    EVIDENCE = "evidence"
    ASSUMPTIONS = "assumptions"
    GAPS = "gaps"
    INVESTIGATIONS = "investigations"
    RANKINGS = "rankings"
    FEATURE_REQUESTS = "feature_requests"


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def set_store(store: Store) -> None:
    """Test hook."""
    global _store
    _store = store
