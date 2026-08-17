"""Optional LLM provider.

The LLM may decide *what to investigate* and may *explain* findings. It never
produces a number that a decision depends on: scores, deltas, thresholds and
decision states all come from `app.engine`. When no key is configured the
`DeterministicNarrator` is used and the API reports `llm_mode = "deterministic"`.
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


class AnthropicProvider:
    name = "anthropic"
    available = True

    def __init__(self, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.model = model
        self._client = httpx.Client(
            base_url="https://api.anthropic.com",
            timeout=timeout,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str | None:
        try:
            response = self._client.post(
                "/v1/messages",
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            response.raise_for_status()
            blocks = response.json().get("content", [])
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text") or None
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            # An LLM failure must never block the deterministic pipeline.
            log.warning("llm call failed, falling back", extra={"error": str(exc)})
            return None


_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    global _provider
    if _provider is None:
        settings = get_settings()
        if settings.llm_live:
            _provider = AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
        else:
            _provider = DeterministicNarrator()
    return _provider


def set_llm(provider: LLMProvider | None) -> None:
    global _provider
    _provider = provider
