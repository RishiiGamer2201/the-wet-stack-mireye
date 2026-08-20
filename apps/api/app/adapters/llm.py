"""Optional LLM provider with streaming support.

The LLM may decide *what to investigate* and may *explain* findings. It never
produces a number that a decision depends on: scores, deltas, thresholds and
decision states all come from `app.engine`. When no key is configured the
`DeterministicNarrator` is used and the API reports `llm_mode = "deterministic"`.
Providers are interchangeable: adding one is a class satisfying `LLMProvider`.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Iterator, Protocol

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

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str | None: ...
    def complete_stream(self, system: str, user: str, max_tokens: int = 1000) -> Iterator[str]: ...


class DeterministicNarrator:
    """No-op provider. Callers fall back to their deterministic template text."""

    name = "deterministic"
    available = False

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str | None:
        return None

    def complete_stream(self, system: str, user: str, max_tokens: int = 1000) -> Iterator[str]:
        return iter(())


THINKING_HEADROOM_TOKENS = 2000
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = (1.0, 3.0)


class GeminiProvider:
    """Google Gemini via the REST API."""

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

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str | None:
        for attempt in range(_RETRY_ATTEMPTS + 1):
            text, retryable = self._attempt(system, user, max_tokens)
            if text is not None or not retryable or attempt == _RETRY_ATTEMPTS:
                return text
            time.sleep(_RETRY_BACKOFF_SECONDS[attempt])
        return None

    def complete_stream(self, system: str, user: str, max_tokens: int = 1000) -> Iterator[str]:
        # Fallback to single chunk for Gemini or implement stream
        res = self.complete(system, user, max_tokens)
        if res:
            yield res

    def _attempt(self, system: str, user: str, max_tokens: int) -> tuple[str | None, bool]:
        try:
            url = f"/v1beta/models/{self.model}:generateContent?key={self._api_key}"
            payload = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"parts": [{"text": user}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens + THINKING_HEADROOM_TOKENS,
                    "temperature": 0.2,
                },
            }
            response = self._client.post(url, json=payload)
            if response.status_code in _RETRYABLE_STATUS:
                log.warning("gemini throttled, will retry", extra={"status": response.status_code})
                return None, True
            response.raise_for_status()
            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None, False
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
            return (text or None), False
        except Exception as exc:
            log.warning("gemini call failed", extra={"error": str(exc)})
            return None, False


class OpenAIProvider:
    """OpenAI via Chat Completions API with streaming and standard model fallback."""

    name = "openai"
    available = True

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: float = 45.0,
        base_url: str = "https://api.openai.com",
    ) -> None:
        # Fall back if unsupported/unreleased model name is configured
        clean_model = model.strip()
        if clean_model in ("gpt-5.1", "gpt-5", "auto"):
            clean_model = "gpt-4o-mini"
        self.model = clean_model
        self._api_key = api_key
        clean_base = (base_url or "https://api.openai.com").rstrip("/")
        if clean_base.endswith("/v1"):
            clean_base = clean_base[:-3]
        self._client = httpx.Client(
            base_url=clean_base or "https://api.openai.com",
            timeout=timeout,
            headers={
                "content-type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

    def complete(self, system: str, user: str, max_tokens: int = 1000) -> str | None:
        for attempt in range(_RETRY_ATTEMPTS + 1):
            text, retryable = self._attempt(system, user, max_tokens)
            if text is not None or not retryable or attempt == _RETRY_ATTEMPTS:
                return text
            time.sleep(_RETRY_BACKOFF_SECONDS[attempt])
        return None

    def _attempt(self, system: str, user: str, max_tokens: int) -> tuple[str | None, bool]:
        models_to_try = [self.model, "gpt-4o-mini", "gpt-4o"]
        # deduplicate while preserving order
        models_to_try = list(dict.fromkeys(models_to_try))

        for m in models_to_try:
            try:
                response = self._client.post(
                    "/v1/chat/completions",
                    json={
                        "model": m,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "max_tokens": max_tokens,
                        "temperature": 0.3,
                    },
                )
                if response.status_code in _RETRYABLE_STATUS:
                    log.warning("openai throttled, will retry", extra={"status": response.status_code, "model": m})
                    return None, True
                if response.status_code == 404 or response.status_code == 400:
                    # Try next model if model not found
                    log.warning("openai model failed, trying fallback", extra={"status": response.status_code, "model": m})
                    continue
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "").strip()
                    if content:
                        return content, False
            except httpx.HTTPStatusError as exc:
                log.warning("openai request status error", extra={"status": exc.response.status_code, "model": m})
                if exc.response.status_code in _RETRYABLE_STATUS:
                    return None, True
            except Exception as exc:
                log.warning("openai call failed", extra={"error": str(exc), "model": m})
                continue
        return None, False

    def complete_stream(self, system: str, user: str, max_tokens: int = 1200) -> Iterator[str]:
        """Stream chunks from OpenAI chat completions."""
        models_to_try = [self.model, "gpt-4o-mini", "gpt-4o"]
        models_to_try = list(dict.fromkeys(models_to_try))

        for m in models_to_try:
            try:
                with self._client.stream(
                    "POST",
                    "/v1/chat/completions",
                    json={
                        "model": m,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "max_tokens": max_tokens,
                        "temperature": 0.3,
                        "stream": True,
                    },
                ) as response:
                    if response.status_code != 200:
                        continue
                    for line in response.iter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            raw_data = line[6:].strip()
                            if raw_data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(raw_data)
                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content")
                                    if content:
                                        yield content
                            except json.JSONDecodeError:
                                continue
                    return
            except Exception as exc:
                log.warning("streaming chunk error, trying next", extra={"error": str(exc), "model": m})
                continue


_provider: LLMProvider | None = None


def _select(settings) -> LLMProvider:
    choice = (settings.llm_provider or "auto").strip().lower()
    if choice == "none" or not settings.llm_live:
        return DeterministicNarrator()
    if choice in ("auto", "openai") and settings.openai_api_key:
        return OpenAIProvider(
            settings.openai_api_key,
            settings.openai_model or "gpt-4o-mini",
            settings.llm_timeout_seconds,
            getattr(settings, "openai_base_url", "https://api.openai.com"),
        )
    if choice in ("auto", "gemini") and settings.gemini_api_key:
        return GeminiProvider(
            settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_seconds
        )
    log.warning("llm_provider=%s but no matching key is configured", choice)
    return DeterministicNarrator()


def get_llm() -> LLMProvider:
    global _provider
    if _provider is None:
        settings = get_settings()
        _provider = _select(settings)
    return _provider


def set_llm(provider: LLMProvider | None) -> None:
    global _provider
    _provider = provider
