"""FastAPI application entry point."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .adapters.tracing import configure_tracing
from .config import get_settings
from .engine.decisions import SAFETY_CAVEAT
from .logging_conf import configure_logging
from .routers import before, core, during, knowledge
from .store import C, get_store

log = logging.getLogger("api")

DESCRIPTION = f"""
Data-center construction and EPC intelligence API for **The Wet Stack - Mireye**.

Two workflows share one project context, evidence store and impact graph:

* **Before Construction** - candidate-site intelligence, progressive investigation, ranking.
* **During Construction** - equipment change verification, deltas, impact tracing.

The agent decides *what* to investigate. All unit conversion, scoring, thresholds,
deltas and decision states run in deterministic, tested Python.

{SAFETY_CAVEAT}
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings)
    store = get_store()
    log.info(
        "api starting",
        extra={
            "environment": settings.environment,
            "services": settings.service_modes(),
            "demo_mode": settings.demo_mode,
            "cors_origins": settings.cors_origin_list,
        },
    )
    for problem in settings.cors_warnings():
        log.warning("configuration", extra={"problem": problem})

    # Idempotent by construction: only an empty store is seeded, and the seed is
    # run with reset=False so a restart can never wipe or duplicate existing data.
    # On Render's ephemeral disk this is what makes the demo self-heal after a
    # redeploy; with a real DATABASE_URL it must be turned off (see config).
    if settings.seed_on_startup and store.count(C.PROJECTS) == 0:
        from .seed import seed

        project = seed(store, reset=False)
        log.info("auto-seeded demo project", extra={"project_id": project.id})
    elif store.count(C.PROJECTS) == 0:
        log.warning("store is empty and SEED_ON_STARTUP is disabled; POST /api/admin/seed to load demo data")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "unhandled error",
                extra={"request_id": request_id, "path": request.url.path},
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_error",
                    "detail": "The request failed. See server logs.",
                    "request_id": request_id,
                },
            )
        response.headers["x-request-id"] = request_id
        log.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": int((time.perf_counter() - started) * 1000),
            },
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        # `ctx` can hold a raw exception object, which is not JSON serialisable.
        detail = [
            {k: (str(v) if k == "ctx" else v) for k, v in error.items() if k != "input"}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "detail": detail,
                "hint": "Check the request body against /docs.",
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=422, content={"error": "invalid_request", "detail": str(exc)}
        )

    for router in (core.router, before.router, during.router, knowledge.router):
        app.include_router(router, prefix="/api")

    @app.get("/", include_in_schema=False)
    def root():
        return {
            "name": settings.app_name,
            "docs": "/docs",
            "health": "/api/health",
            "demo_mode": settings.demo_mode,
        }

    return app


app = create_app()
