from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.adapters.graphstore import InMemoryGraphStore, set_graph_store  # noqa: E402
from app.adapters.llm import DeterministicNarrator, set_llm  # noqa: E402
from app.adapters.mireye import MockMireyeClient, set_mireye_client  # noqa: E402
from app.adapters.vectorstore import (  # noqa: E402
    HybridIndex,
    LexicalIndex,
    LocalVectorIndex,
    set_index,
)
from app.domain import CandidateSite, EquipmentChange, Project  # noqa: E402
from app.seed import seed  # noqa: E402
from app.store import C, Store, set_store  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    """Isolated store + deterministic adapters for every test."""
    monkeypatch.setenv("MIREYE_BASE_URL", "")
    s = Store(tmp_path / "test.db")
    set_store(s)
    set_graph_store(InMemoryGraphStore())
    set_mireye_client(MockMireyeClient())
    set_llm(DeterministicNarrator())
    set_index(HybridIndex(LexicalIndex(s), LocalVectorIndex(s)))
    yield s
    set_store(None)
    set_mireye_client(None)
    set_graph_store(None)
    set_index(None)
    set_llm(None)
    s.close()


@pytest.fixture
def seeded(store: Store) -> Project:
    return seed(store, reset=True)


@pytest.fixture
def sites(store: Store, seeded: Project) -> list[CandidateSite]:
    return store.list(C.SITES, CandidateSite, project_id=seeded.id)


@pytest.fixture
def changes(store: Store, seeded: Project) -> list[EquipmentChange]:
    return store.list(C.CHANGES, EquipmentChange, project_id=seeded.id)


@pytest.fixture
def api(store: Store):
    from app.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as client:
        yield client
