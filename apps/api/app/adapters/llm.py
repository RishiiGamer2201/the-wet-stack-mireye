"""Optional LLM provider.

The LLM may decide *what to investigate* and may *explain* findings. It never
produces a number that a decision depends on: scores, deltas, thresholds and
decision states all come from `app.engine`. When no key is configured the
`DeterministicNarrator` is used and the API reports `llm_mode = "deterministic"`.
Providers are interchangeable: adding one is a class satisfying `LLMProvider`.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from ..config import get_settings

log = logging.getLogger("llm")

INVESTIGATION_SYSTEM = (
    "You are the supervisor agent of an EPC data-center intelligence platform. "
    "You decide which evidence an investigation needs and you explain findings in "
    "plain engineering language. You never invent numeric values, never assert "
    "structural adequacy, and never state a fact that is not in the provided evidence. "
    "Answer concisely."
)


class LLMProvider(Protocol):
    name: str
    available: bool

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str | None: ...


class DeterministicNarrator:
    """No-op provider. Callers fall back to their deterministic template text."""

    name = "deterministic"
    available = False

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str | None:
        return None


class GeminiProvider:
    """Google Gemini via the REST API.

    Deliberately thin: one text-in, text-out call. The model is never handed a
    number to compute and its output is never parsed into one — callers append
    it as prose (`_llm_explain`) or validate it against the field catalog
    (`_llm_extra_steps`). Any failure returns None so the deterministic pipeline
    continues untouched.
    """

    name = "gemini"
    available = True

    def __init__(self, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.model = model
        self._api_key = api_key
        self._client = httpx.Client(
            base_url="https://generativelanguage.googleapis.com",
            timeout=timeout,
            headers={"content-type": "application/json"},
        )

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str | None:
        try:
            response = self._client.post(
                f"/v1beta/models/{self.model}:generateContent",
                # The key travels as a header, not in the URL, so it cannot leak
                # into an access log or an exception message.
                headers={"x-goog-api-key": self._api_key},
                json={
                    "system_instruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
                },
            )
            response.raise_for_status()
            candidates = response.json().get("candidates") or []
            if not candidates:
                log.warning("gemini returned no candidate", extra={"model": self.model})
                return None
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts) or None
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            # An LLM failure must never block the deterministic pipeline.
            log.warning("llm call failed, falling back", extra={"error": str(exc)})
            return None


_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _provider
    if _provider is None:
        settings = get_settings()
        if settings.llm_live:
            _provider = GeminiProvider(
                settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_seconds
            )
        else:
            _provider = DeterministicNarrator()
    return _provider


def set_llm(provider: LLMProvider | None) -> None:
    global _provider
    _provider = provider
