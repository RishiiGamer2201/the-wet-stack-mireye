"""Runtime configuration. Every external service is optional: when its URL/key is
absent the corresponding adapter falls back to a deterministic local implementation
and the API reports `demo_mode = true`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]


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

    # --- llm ---------------------------------------------------------------
    llm_provider: str = "auto"  # auto | anthropic | none
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    embedding_provider: str = "auto"  # auto | openai | none
    openai_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"

    # --- uploads -----------------------------------------------------------
    max_upload_bytes: int = 25 * 1024 * 1024
    allowed_upload_types: tuple[str, ...] = ("application/pdf",)

    # --- demo data ---------------------------------------------------------
    # A deployment with an empty store seeds the synthetic demo project on start
    # so the hackathon demo is usable immediately. Turn this off for any
    # deployment pointed at a real database — synthetic engineering data must
    # never be written into one.
    seed_on_startup: bool = True

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
    def mireye_live(self) -> bool:
        return bool(self.mireye_base_url and self.mireye_api_key)

    @property
    def neo4j_live(self) -> bool:
        return bool(self.neo4j_uri and self.neo4j_user and self.neo4j_password)

    @property
    def llm_live(self) -> bool:
        if self.llm_provider == "none":
            return False
        return bool(self.anthropic_api_key)

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
            "llm": "anthropic" if self.llm_live else "deterministic",
        }


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    return s
