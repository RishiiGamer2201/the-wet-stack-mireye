from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
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
from app.config import get_settings  # noqa: E402
from app.domain import CandidateSite, EquipmentChange, Project  # noqa: E402
from app.seed import seed  # noqa: E402
from app.store import C, Store, set_store  # noqa: E402


@pytest.fixture(autouse=True)
def _no_outbound_provider_calls(request, monkeypatch):
    """Fail loudly if a test tries to reach a real provider.

    Every contract expectation is pinned against recorded fixtures, so a socket
    opening to api.mireye.com means a test would bill real credits. Tests that
    supply their own `httpx.MockTransport` are unaffected — this only blocks the
    real network path. The opt-in live module is exempt.
    """
    if "live" in request.node.nodeid and "RUN_MIREYE_LIVE_TESTS" in os.environ:
        return

    # Blank every real provider credential for the duration of the test. A
    # developer's .env must never decide what a test does — before this, adding a
    # GEMINI_API_KEY locally flipped an unrelated test from pass to fail.
    for var in ("GEMINI_API_KEY", "LANGSMITH_API_KEY", "MIREYE_API_KEY", "MIREYE_BASE_URL"):
        monkeypatch.setenv(var, "")
    get_settings.cache_clear()

    real_send = httpx.HTTPTransport.handle_request

    def guarded(self, http_request):
        raise AssertionError(
            "a test attempted a real outbound HTTP request to "
            f"{http_request.url.host} — provider calls cost credits. "
            "Use a fixture from tests/fixtures/ or httpx.MockTransport."
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded)
    _ = real_send


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    """Isolated store + deterministic adapters for every test.

    DATA_DIR is redirected at tmp_path so an upload test never writes into the
    developer's real `apps/api/var/uploads`.
    """
    monkeypatch.setenv("MIREYE_BASE_URL", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "var"))
    monkeypatch.setenv("REDIS_CACHE_FILE", str(tmp_path / "var" / "redis_cache.json"))
    monkeypatch.setenv("SEED_ON_STARTUP", "true")
    get_settings.cache_clear()
    from app.adapters.rediscache import RedisCacheManager, set_redis_cache
    rc = RedisCacheManager()
    rc._redis_connected = False
    rc._redis_client = None
    rc._file_path = tmp_path / "var" / "redis_cache.json"
    rc._file_cache = {}
    set_redis_cache(rc)
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
    set_redis_cache(None)
    s.close()
    get_settings.cache_clear()


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
