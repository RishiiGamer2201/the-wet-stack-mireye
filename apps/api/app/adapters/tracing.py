"""LangSmith tracing — opt-in, and inert unless a key is supplied.

The investigation workflow already runs on LangGraph, and LangGraph traces
itself through `langchain-core` whenever the standard environment variables are
present. So "integrating" LangSmith means setting those variables from our own
settings before the graph is built — no decorators, no wrappers, and no change
to any node.

With `LANGSMITH_API_KEY` unset this module sets nothing and does nothing, which
is what keeps the default path free of a network dependency.
"""

from __future__ import annotations

import logging
import os

from ..config import Settings, get_settings

log = logging.getLogger("tracing")

#: The variables langchain-core reads. Set together or not at all.
_TRACING_VARS = ("LANGCHAIN_TRACING_V2", "LANGCHAIN_ENDPOINT", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT")

_configured: bool | None = None


def configure_tracing(settings: Settings | None = None) -> bool:
    """Turn LangSmith tracing on when configured. Returns whether it is active.

    Idempotent: safe to call on every startup and from tests.
    """
    global _configured
    settings = settings or get_settings()

    if not settings.tracing_live:
        # Explicitly clear rather than leave a half-configured state behind, so a
        # stray LANGCHAIN_TRACING_V2 in the shell cannot silently enable tracing
        # against an endpoint we never configured.
        for var in _TRACING_VARS:
            os.environ.pop(var, None)
        _configured = False
        return False

    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key or ""
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    _configured = True
    # Project and endpoint only — never the key.
    log.info(
        "langsmith tracing enabled",
        extra={"project": settings.langsmith_project, "endpoint": settings.langsmith_endpoint},
    )
    return True


def tracing_status() -> str:
    return "langsmith" if _configured else "off"
