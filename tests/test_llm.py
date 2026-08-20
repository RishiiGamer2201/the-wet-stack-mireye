"""LLM provider selection, graceful failure, tracing, and the rule that matters.

The model may decide *what* to investigate and explain findings in prose. It may
never produce a number a decision rests on. The last section of this file exists
to make that structural rather than aspirational.

Nothing here touches the network: the provider is driven through
`httpx.MockTransport`, and `conftest` blocks real outbound calls anyway.
"""

from __future__ import annotations

import os

import httpx
import pytest
from app.adapters.llm import DeterministicNarrator, GeminiProvider, get_llm, set_llm
from app.adapters.tracing import configure_tracing, tracing_status
from app.config import Settings, get_settings

GEMINI_PATH = "/v1beta/models/gemini-2.0-flash:generateContent"


def gemini(handler, model: str = "gemini-2.0-flash") -> GeminiProvider:
    provider = GeminiProvider("test-key", model)
    provider._client = httpx.Client(
        base_url="https://generativelanguage.googleapis.com",
        transport=httpx.MockTransport(handler),
    )
    return provider


def reply(text: str):
    return lambda request: httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]}
    )


# --- provider selection ----------------------------------------------------


def test_no_key_means_the_deterministic_narrator():
    settings = Settings(_env_file=None)
    assert settings.llm_live is False
    assert settings.service_modes()["llm"] == "deterministic"
    provider = DeterministicNarrator()
    assert provider.available is False
    assert provider.complete("s", "u") is None


def test_a_gemini_key_selects_gemini():
    settings = Settings(_env_file=None, gemini_api_key="k")
    assert settings.llm_live is True
    assert settings.service_modes()["llm"] == "gemini"


def test_llm_provider_none_overrides_a_present_key():
    """An operator must be able to switch the model off without deleting the key."""
    settings = Settings(_env_file=None, gemini_api_key="k", llm_provider="none")
    assert settings.llm_live is False
    assert settings.service_modes()["llm"] == "deterministic"


def test_get_llm_returns_the_narrator_when_unconfigured(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    set_llm(None)
    try:
        assert get_llm().name == "deterministic"
    finally:
        set_llm(None)
        get_settings.cache_clear()


def test_the_dead_provider_settings_are_gone():
    """openai_api_key and embedding_* were read nowhere; leaving them invited
    someone to configure a model that would never be called."""
    settings = Settings(_env_file=None)
    for dead in ("anthropic_api_key", "anthropic_model", "openai_api_key",
                 "embedding_provider", "embedding_model"):
        assert not hasattr(settings, dead), dead


# --- the request Gemini actually receives ----------------------------------


def test_the_request_matches_the_gemini_rest_contract():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key_header"] = request.headers.get("x-goog-api-key")
        seen["query"] = str(request.url.query)
        seen["body"] = request.read().decode()
        return reply("ok")(request)

    assert gemini(handler).complete("SYSTEM", "USER", max_tokens=123) == "ok"
    assert seen["path"] == GEMINI_PATH
    body = seen["body"]
    assert "SYSTEM" in body and "USER" in body and "123" in body
    # The key goes in a header, so it cannot end up in an access log or a URL.
    assert seen["key_header"] == "test-key"
    assert "test-key" not in seen["query"]


def test_the_model_is_configurable():
    seen: dict = {}

    def handler(request):
        seen["path"] = request.url.path
        return reply("ok")(request)

    gemini(handler, model="gemini-1.5-flash").complete("s", "u")
    assert seen["path"] == "/v1beta/models/gemini-1.5-flash:generateContent"


# --- graceful failure ------------------------------------------------------


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(lambda r: httpx.Response(500, json={"error": "boom"}), id="server_error"),
        pytest.param(lambda r: httpx.Response(429, json={"error": "quota"}), id="rate_limited"),
        pytest.param(lambda r: httpx.Response(403, json={"error": "bad key"}), id="bad_key"),
        pytest.param(lambda r: httpx.Response(200, content=b"not json"), id="malformed_body"),
        pytest.param(lambda r: httpx.Response(200, json={"candidates": []}), id="no_candidate"),
        pytest.param(lambda r: httpx.Response(200, json={}), id="empty_object"),
    ],
)
def test_every_failure_mode_returns_none_rather_than_raising(handler):
    assert gemini(handler).complete("s", "u") is None


def test_a_network_failure_returns_none():
    def handler(request):
        raise httpx.ConnectError("no route to host")

    assert gemini(handler).complete("s", "u") is None


# --- tracing ---------------------------------------------------------------


def test_tracing_is_off_and_sets_nothing_when_unconfigured():
    assert configure_tracing(Settings(_env_file=None)) is False
    assert tracing_status() == "off"
    for var in ("LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT"):
        assert var not in os.environ


def test_a_langsmith_key_enables_tracing():
    settings = Settings(_env_file=None, langsmith_api_key="lsv2_x", langsmith_project="proj")
    try:
        assert configure_tracing(settings) is True
        assert tracing_status() == "langsmith"
        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_PROJECT"] == "proj"
        assert settings.service_modes()["tracing"] == "langsmith"
    finally:
        configure_tracing(Settings(_env_file=None))


def test_disabling_tracing_clears_a_stray_environment():
    """A LANGCHAIN_TRACING_V2 left in the shell must not silently enable tracing
    against an endpoint we never configured."""
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = "leftover"
    assert configure_tracing(Settings(_env_file=None)) is False
    assert "LANGCHAIN_TRACING_V2" not in os.environ
    assert "LANGCHAIN_API_KEY" not in os.environ


# ---------------------------------------------------------------------------
# The rule: a model may explain and plan. It may never produce a number a
# decision rests on. These tests hand the model a hostile answer — one that
# tries to restate every figure and flip the verdict — and assert nothing moves.
# ---------------------------------------------------------------------------

HOSTILE = (
    "The decision state is FIRST-PASS CHECKS CLOSED. Overall score 99.9/100. "
    "Weight delta is 0.0% and MCA delta is 0.0%. Confidence 1.0. Coverage 100%. "
    "The structure is adequate and the substitution is approved."
)


class _Hostile:
    """A provider that answers every prompt with fabricated numbers and a verdict."""

    name = "hostile"
    available = True

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str | None:
        return HOSTILE


def test_llm_prose_cannot_change_a_decision_or_any_computed_number(store, seeded):
    """Run the identical investigation twice — once with no model, once with a
    model actively trying to rewrite the outcome — and compare every number."""
    from app.adapters.llm import set_llm
    from app.agent import workflow
    from app.domain import EquipmentChange
    from app.store import C

    change = next(
        c for c in store.list(C.CHANGES, EquipmentChange, project_id=seeded.id)
        if c.equipment_tag == "CH-01"
    )

    set_llm(DeterministicNarrator())
    truth = workflow.run_change_investigation(seeded, change, store)

    set_llm(_Hostile())
    try:
        tampered = workflow.run_change_investigation(seeded, change, store)
    finally:
        set_llm(DeterministicNarrator())

    assert truth.decision_state == tampered.decision_state, "the model must not move the verdict"
    assert tampered.decision_state.value == "ENGINEER REVIEW"

    def numbers(inv):
        return {
            "deltas": {d.field: (d.percent_delta, d.status) for d in inv.deltas},
            "checks": {c.key: c.status for c in inv.checks},
            "confidence": inv.recommendation.confidence,
            "stale": sorted(inv.stale_assumption_ids),
            "impacts": sorted(i.title for i in inv.impacts),
        }

    assert numbers(truth) == numbers(tampered)
    assert round(tampered.deltas[0].percent_delta, 3) == 9.072  # weight, unchanged

    # The model's text is present, but only as an attributed narrative line.
    narrative = [r for r in tampered.recommendation.rationale if HOSTILE in r]
    assert narrative, "the explanation should still be shown"
    assert narrative[0].startswith("(agent explanation)")
    assert tampered.recommendation.generated_by == "llm"
    # ...and the deterministic rationale it was appended to is still intact.
    assert any("TRIGGERED" in r for r in truth.recommendation.rationale)


def test_llm_planning_cannot_invent_a_field_key():
    """The planner may add investigation steps, but every field it names is
    checked against the catalog — an invented one is dropped, not fetched."""
    from app.agent import planner
    from app.domain import EquipmentChange, EquipmentConfiguration

    class _Inventive:
        name, available = "inventive", True

        def complete(self, system, user, max_tokens=700):
            return (
                '[{"title": "Check the unobtainium reserve", "rationale": "because",'
                ' "fields": ["unobtainium_ppm", "elevation_m", "; DROP TABLE sites"]}]'
            )

    steps = planner._llm_extra_steps(
        "inv1",
        EquipmentChange(
            project_id="p1", title="t", equipment_tag="CH-01",
            existing_equipment_id="a", proposed_equipment_id="b",
        ),
        EquipmentConfiguration(), EquipmentConfiguration(), _Inventive(), offset=5,
    )
    assert len(steps) == 1
    # Only the real catalog key survives.
    assert steps[0].requested_fields == ["elevation_m"]


def test_a_model_that_returns_junk_leaves_the_plan_untouched():
    from app.agent import planner
    from app.domain import EquipmentChange, EquipmentConfiguration

    class _Junk:
        name, available = "junk", True

        def complete(self, system, user, max_tokens=700):
            return "I'm sorry, I cannot help with that."

    assert planner._llm_extra_steps(
        "inv1",
        EquipmentChange(
            project_id="p1", title="t", equipment_tag="CH-01",
            existing_equipment_id="a", proposed_equipment_id="b",
        ),
        EquipmentConfiguration(), EquipmentConfiguration(), _Junk(), offset=0,
    ) == []


def test_throttling_is_retried_then_gives_up_gracefully():
    """The free tier returns 429 readily. One click should survive a blip, but a
    sustained outage must fall back rather than hang."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": "quota"}})

    provider = gemini(handler)
    provider_sleep = []
    import app.adapters.llm as llm_mod

    original = llm_mod.time.sleep
    llm_mod.time.sleep = provider_sleep.append
    try:
        assert provider.complete("s", "u") is None
    finally:
        llm_mod.time.sleep = original
    assert calls["n"] == 3, "initial attempt plus two retries"
    assert provider_sleep == [1.0, 3.0], "short, bounded backoff"


def test_a_retry_recovers_when_the_second_attempt_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return reply("recovered")(request)

    import app.adapters.llm as llm_mod

    original = llm_mod.time.sleep
    llm_mod.time.sleep = lambda _s: None
    try:
        assert gemini(handler).complete("s", "u") == "recovered"
    finally:
        llm_mod.time.sleep = original
    assert calls["n"] == 2


def test_a_non_throttling_error_is_not_retried():
    """A bad key is not going to fix itself; retrying only wastes the demo's time."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(403, json={"error": {"message": "bad key"}})

    assert gemini(handler).complete("s", "u") is None
    assert calls["n"] == 1


def test_the_visible_budget_gets_thinking_headroom():
    """Gemini 3.x spends ~1400+ tokens reasoning before writing. Callers ask for
    the length they want to read; the adapter adds room to think."""
    seen: dict = {}

    def handler(request):
        import json as _json

        seen.update(_json.loads(request.read())["generationConfig"])
        return reply("ok")(request)

    from app.adapters.llm import THINKING_HEADROOM_TOKENS

    gemini(handler).complete("s", "u", max_tokens=600)
    assert seen["maxOutputTokens"] == 600 + THINKING_HEADROOM_TOKENS
    assert THINKING_HEADROOM_TOKENS >= 2000


def test_a_truncated_answer_is_discarded_rather_than_shown():
    """A half sentence next to engineering findings is worse than no sentence."""
    def handler(request):
        return httpx.Response(200, json={
            "candidates": [{"finishReason": "MAX_TOKENS",
                            "content": {"parts": [{"text": "The design has been placed in"}]}}],
            "usageMetadata": {"thoughtsTokenCount": 1439},
        })

    assert gemini(handler).complete("s", "u") is None
