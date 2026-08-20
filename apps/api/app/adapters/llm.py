"""Optional LLM provider.

The LLM may decide *what to investigate* and may *explain* findings. It never
produces a number that a decision depends on: scores, deltas, thresholds and
decision states all come from `app.engine`. When no key is configured the
`DeterministicNarrator` is used and the API reports `llm_mode = "deterministic"`.
Providers are interchangeable: adding one is a class satisfying `LLMProvider`.
"""

from __future__ import annotations

import logging
import time
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


#: Gemini 3.x reasons internally before emitting a visible token, and those
#: thinking tokens are drawn from the SAME `maxOutputTokens` budget as the
#: answer. Measured on this app's real prompts: ~1400-1600 thinking tokens
#: before any prose appears. Callers ask for the visible length they want and
#: the adapter adds this headroom, so no caller has to know the quirk exists.
THINKING_HEADROOM_TOKENS = 3000

#: 429 is the free tier throttling; 5xx is a busy model. Both are worth one or
#: two short retries, and nothing else is.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = (1.0, 3.0)


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
        """Ask the model, retrying briefly through free-tier throttling.

        The free tier returns 429 readily and 503 when a model is busy. Both are
        transient, and without a retry a single demo click silently drops to the
        deterministic text. Retries are deliberately few and short: an
        explanation is worth a couple of seconds, never a hung request.
        """
        for attempt in range(_RETRY_ATTEMPTS + 1):
            text, retryable = self._attempt(system, user, max_tokens)
            if text is not None or not retryable or attempt == _RETRY_ATTEMPTS:
                return text
            time.sleep(_RETRY_BACKOFF_SECONDS[attempt])
        return None

    def _attempt(self, system: str, user: str, max_tokens: int) -> tuple[str | None, bool]:
        """Returns (text, retryable). `retryable` is only true for throttling."""
        try:
            response = self._client.post(
                f"/v1beta/models/{self.model}:generateContent",
                # The key travels as a header, not in the URL, so it cannot leak
                # into an access log or an exception message.
                headers={"x-goog-api-key": self._api_key},
                json={
                    "system_instruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {
                        # visible budget + room to think, see THINKING_HEADROOM_TOKENS
                        "maxOutputTokens": max_tokens + THINKING_HEADROOM_TOKENS,
                        "temperature": 0.2,
                    },
                },
            )
            if response.status_code in _RETRYABLE_STATUS:
                log.warning(
                    "gemini throttled, will retry",
                    extra={"status": response.status_code, "model": self.model},
                )
                return None, True
            response.raise_for_status()
            payload = response.json()
            candidates = payload.get("candidates") or []
            if not candidates:
                log.warning("gemini returned no candidate", extra={"model": self.model})
                return None, False
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            # Gemini 3.x reasons before it writes, and those thinking tokens come
            # out of the same budget. A truncated answer reads like a confident
            # sentence that stops mid-clause, which is worse next to engineering
            # findings than no answer at all — so discard it and let the caller
            # fall back to its deterministic text.
            if candidates[0].get("finishReason") == "MAX_TOKENS":
                thoughts = (payload.get("usageMetadata") or {}).get("thoughtsTokenCount")
                log.warning(
                    "gemini answer truncated by the token budget; discarding it",
                    extra={"model": self.model, "thinking_tokens": thoughts, "text_chars": len(text)},
                )
                return None, False
            return (text or None), False
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            # An LLM failure must never block the deterministic pipeline.
            log.warning("llm call failed, falling back", extra={"error": str(exc)})
            return None, False


class OpenAIProvider:
    """OpenAI via the Responses API.

    Same contract as every other provider: text in, text out, `None` on any
    failure so the deterministic pipeline continues untouched. The model is
    never handed a number to compute and its output is never parsed into one.

    Uses `/v1/responses` rather than `/v1/chat/completions` because the current
    reasoning models are built around it; `max_output_tokens` there covers
    reasoning *and* the visible answer, exactly like Gemini, so the same
    headroom applies.
    """

    name = "openai"
    available = True

    def __init__(self, api_key: str, model: str, timeout: float = 60.0) -> None:
        self.model = model
        self._api_key = api_key
        self._client = httpx.Client(
            base_url="https://api.openai.com",
            timeout=timeout,
            headers={"content-type": "application/json"},
        )

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str | None:
        for attempt in range(_RETRY_ATTEMPTS + 1):
            text, retryable = self._attempt(system, user, max_tokens)
            if text is not None or not retryable or attempt == _RETRY_ATTEMPTS:
                return text
            time.sleep(_RETRY_BACKOFF_SECONDS[attempt])
        return None

    def _attempt(self, system: str, user: str, max_tokens: int) -> tuple[str | None, bool]:
        try:
            response = self._client.post(
                "/v1/responses",
                # Per request, not on the client: auth that lives on the client
                # disappears silently if the client is ever swapped.
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model,
                    "instructions": system,
                    "input": user,
                    "max_output_tokens": max_tokens + THINKING_HEADROOM_TOKENS,
                },
            )
            if response.status_code in _RETRYABLE_STATUS:
                log.warning(
                    "openai throttled, will retry",
                    extra={"status": response.status_code, "model": self.model},
                )
                return None, True
            response.raise_for_status()
            payload = response.json()

            text = (payload.get("output_text") or "").strip()
            if not text:
                # output_text is a convenience field; fall back to walking the
                # structured output so a reasoning item alone is not mistaken
                # for an answer.
                chunks = []
                for item in payload.get("output", []):
                    for part in item.get("content", []) or []:
                        if part.get("type") in ("output_text", "text"):
                            chunks.append(part.get("text", ""))
                text = "".join(chunks).strip()

            if payload.get("status") == "incomplete":
                reason = (payload.get("incomplete_details") or {}).get("reason")
                log.warning(
                    "openai answer incomplete; discarding it",
                    extra={"model": self.model, "reason": reason, "text_chars": len(text)},
                )
                return None, False
            if not text:
                log.warning("openai returned no text", extra={"model": self.model})
                return None, False
            return text, False
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            log.warning("llm call failed, falling back", extra={"error": str(exc)})
            return None, False


_provider: LLMProvider | None = None


def _select(settings) -> LLMProvider:
    """Pick a provider from configuration.

    `auto` prefers OpenAI when both keys are present; naming a provider
    explicitly always wins, and `none` disables the model without anyone having
    to delete a key.
    """
    choice = (settings.llm_provider or "auto").strip().lower()
    if choice == "none" or not settings.llm_live:
        return DeterministicNarrator()
    if choice in ("auto", "openai") and settings.openai_api_key:
        return OpenAIProvider(
            settings.openai_api_key, settings.openai_model, settings.llm_timeout_seconds
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
