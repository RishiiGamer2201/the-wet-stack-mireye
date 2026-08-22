"""Runtime configuration. Every external service is optional: when its URL/key is
absent the corresponding adapter falls back to a deterministic local implementation
and the API reports `demo_mode = true`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[1]
#: The checkout root, when the package is running from one. Installed into a
#: container it is not, so this is None rather than an IndexError at import.
_parents = Path(__file__).resolve().parents
REPO_ROOT = _parents[3] if len(_parents) > 3 else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(API_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "The Wet Stack - Mireye API"
    environment: str = "local"
    log_level: str = "INFO"

    # --- storage -----------------------------------------------------------
    data_dir: Path = API_ROOT / "var"
    sqlite_path: Path | None = None
    # When set, the Supabase/Postgres store + pgvector index are used instead of SQLite.
    database_url: str | None = None
    supabase_url: str | None = None
    supabase_service_key: str | None = None

    # --- graph -------------------------------------------------------------
    neo4j_uri: str | None = None
    neo4j_user: str | None = None
    neo4j_password: str | None = None

    # --- redis cache -------------------------------------------------------
    redis_url: str | None = None
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0
    redis_cache_file: Path | None = None
    redis_ttl_seconds: int = 86400 * 7  # 7 days default cache TTL

    # --- mireye ------------------------------------------------------------
    mireye_base_url: str | None = None
    mireye_api_key: str | None = None
    mireye_timeout_seconds: float = 12.0
    mireye_max_retries: int = 2
    mireye_cache_ttl_seconds: int = 900
    #: Mireye bills its `parcel_record` group at 300 credits per location, against
    #: 1 credit for an ordinary field. Those fields stay out of every request
    #: unless this is deliberately turned on.
    mireye_include_parcel_fields: bool = False

    # --- live spend limits -------------------------------------------------
    # Mireye bills per field per location, so an unbounded sweep is an unbounded
    # bill. These caps are conservative on purpose: reaching one records a
    # visible InformationGap rather than failing the run or quietly downgrading
    # evidence, so the analysis stays honest about what it did not look at.
    #: Locations a single investigation may fetch live.
    mireye_max_live_locations: int = 10
    #: Live /v1/fetch calls a single investigation may make, across all locations.
    mireye_max_live_fetches: int = 25
    #: POST /v1/feature-requests is documented but its contract is unverified, so
    #: gaps are recorded locally until someone confirms the real payload.
    mireye_enable_feature_requests: bool = False

    # --- llm ---------------------------------------------------------------
    # The model may plan an investigation and explain findings. It can never
    # produce a score, delta, threshold or decision state — those are
    # deterministic Python, and `test_llm.py` enforces it.
    llm_provider: str = "auto"  # auto | openai | gemini | none
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com"
    openai_model: str = "gpt-4o-mini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    llm_timeout_seconds: float = 30.0

    # --- tracing (LangSmith) -----------------------------------------------
    # Off unless a key is supplied. The workflow already runs on LangGraph, so
    # enabling this traces every Understand -> ... -> Action run with no code
    # change; leaving it unset changes nothing at all.
    langsmith_api_key: str | None = None
    langsmith_project: str = "wetstack-mireye"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # --- uploads -----------------------------------------------------------
    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_upload_types: tuple[str, ...] = ("application/pdf",)

    # --- OCR -----------------------------------------------------------------
    # Only pages with no text layer are ever OCR'd, so a born-digital PDF costs
    # nothing. Needs the `tesseract` binary on the host: without it, a scan is
    # reported as unreadable rather than silently producing no text.
    ocr_enabled: bool = True
    #: Explicit path to the binary when it is installed but not on PATH.
    ocr_tesseract_path: str | None = None
    #: Directory holding `eng.traineddata`. Usually set by the Tesseract install.
    ocr_tessdata_dir: str | None = None
    #: ~1-3 s per page. A 200-page scan would hold the upload request open for
    #: several minutes, so the rest of the document is reported, not attempted.
    ocr_max_pages: int = 30
    #: Rendering resolution. 200 dpi reads 8pt type reliably; 300 is slower and
    #: rarely better on engineering documents.
    ocr_dpi: int = 200

    # --- demo data ---------------------------------------------------------
    # When enabled, an empty store seeds the synthetic demo project on start.
    # Set to False to start with a clean database.
    seed_on_startup: bool = False

    # --- http --------------------------------------------------------------
    #: Comma-separated browser origins allowed to call this API. There is no
    #: wildcard: production must name the frontend origin explicitly.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in ("production", "prod")

    @property
    def cors_origin_list(self) -> list[str]:
        """Explicit origins only. `*` is rejected rather than silently honoured."""
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return [o for o in origins if o != "*"]

    def cors_warnings(self) -> list[str]:
        """Configuration problems worth shouting about at startup, not crashing on:
        a misconfigured demo that still serves /api/health is easier to diagnose
        than one that refuses to boot."""
        problems: list[str] = []
        raw = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if "*" in raw:
            problems.append(
                "CORS_ORIGINS contains '*', which is ignored — list the frontend origin explicitly."
            )
        if not self.cors_origin_list:
            problems.append("CORS_ORIGINS is empty: no browser origin can call this API.")
        if self.is_production:
            local = [o for o in self.cors_origin_list if "localhost" in o or "127.0.0.1" in o]
            if local:
                problems.append(
                    "CORS_ORIGINS still contains development origins in production: "
                    + ", ".join(local)
                )
            if self.database_url and self.seed_on_startup:
                problems.append(
                    "SEED_ON_STARTUP is on while DATABASE_URL is set: synthetic demo data would be "
                    "written to a real database. Set SEED_ON_STARTUP=false."
                )
        return problems

    @property
    def db_path(self) -> Path:
        return self.sqlite_path or (self.data_dir / "wetstack.db")

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def sample_dir(self) -> Path:
        """Where the synthetic demonstration PDFs live.

        The repository's own `sample_data/` when running from a checkout, so the
        committed files are used as-is; otherwise a writable path under DATA_DIR,
        because a container has no checkout and the seed regenerates them.
        """
        if REPO_ROOT is not None and (REPO_ROOT / "sample_data").exists():
            return REPO_ROOT / "sample_data"
        return self.data_dir / "sample_data"

    @property
    def redis_path(self) -> Path:
        return self.redis_cache_file or (self.data_dir / "redis_cache.json")

    @property
    def mireye_live(self) -> bool:
        return bool(self.mireye_base_url and self.mireye_api_key)

    @property
    def neo4j_live(self) -> bool:
        return bool(self.neo4j_uri and self.neo4j_user and self.neo4j_password)

    @property
    def llm_live(self) -> bool:
        if self.llm_provider == "none":
            return False
        return bool(self.openai_api_key or self.gemini_api_key)

    @property
    def llm_name(self) -> str:
        """Which provider will actually be used, not which was configured."""
        if not self.llm_live:
            return "deterministic"
        choice = (self.llm_provider or "auto").strip().lower()
        if choice in ("auto", "openai") and self.openai_api_key:
            return "openai"
        if choice in ("auto", "gemini") and self.gemini_api_key:
            return "gemini"
        return "deterministic"

    @property
    def tracing_live(self) -> bool:
        """LangSmith tracing is opt-in: a key is the switch."""
        return bool(self.langsmith_api_key)

    @property
    def pgvector_live(self) -> bool:
        return bool(self.database_url)

    @property
    def demo_mode(self) -> bool:
        """True when at least one production service is being simulated locally."""
        return not (self.mireye_live and self.neo4j_live and self.pgvector_live)

    def service_modes(self) -> dict[str, str]:
        return {
            "mireye": "live" if self.mireye_live else "mock",
            "graph": "neo4j" if self.neo4j_live else "in_memory",
            "vector": "pgvector" if self.pgvector_live else "lexical_sqlite",
            "store": "postgres" if self.database_url else "sqlite",
            "llm": self.llm_name,
            "tracing": "langsmith" if self.tracing_live else "off",
        }


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s
