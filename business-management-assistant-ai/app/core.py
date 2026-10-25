"""Settings and database engine construction."""

from typing import Any, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.security import parse_api_keys

SCHEMA_VERSION = "2"
MIN_SECRET_LENGTH = 24


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)  # docker compose passes unset vars as ""

    app_name: str = "Business Management Assistant AI"
    version: str = "0.4.1"
    environment: Literal["sandbox", "staging", "production"] = "sandbox"
    database_url: str = "sqlite:///./business_assistant.db"
    model_policy: str = "provider-neutral"
    models_dir: str = "models"
    static_dir: str | None = None
    enable_docs: bool = False  # always on in sandbox

    # "name:role:secret" entries, comma separated. Empty is allowed only in sandbox (open mode).
    api_keys: str = ""
    require_distinct_reviewer: bool | None = None
    approval_ttl_hours: int = Field(default=72, ge=1, le=24 * 30)
    high_value_threshold: float = Field(default=1000.0, gt=0)
    rate_limit_per_minute: int = Field(default=240, ge=0)

    # Models. Nothing is chosen up front: every reachable model is discovered and used (see docs/models.md).
    # Optional explicit endpoints (JSON array) and/or a single pinned model via the LLM_* variables below.
    llm_endpoints: str = ""
    llm_auto_discover: bool = True  # provider API keys in the environment + well-known local server ports
    llm_prefer: Literal["quality", "local", "hosted"] = "quality"
    llm_allow_hosted: bool = True  # False keeps business data on private/loopback endpoints only
    llm_max_cascade: int = Field(default=3, ge=1, le=8)
    llm_refresh_seconds: float = Field(default=300.0, ge=5)
    llm_scores_path: str = "data/evaluation/scores.json"
    llm_min_plan_score: float = Field(default=0.5, ge=0, le=1)
    llm_provider: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    llm_max_tokens: int = Field(default=800, ge=64, le=8000)
    llm_daily_call_limit: int = Field(default=2000, ge=0)  # 0 disables the cap
    assistant_mode: Literal["rules", "hybrid", "llm"] | None = None  # default: hybrid when models are available

    # Connectors (live only outside sandbox; sandbox always dry-runs).
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_sender: str | None = None
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_allowed_domains: str = ""  # comma separated; required in staging so test mail cannot reach real people
    slack_webhook_url: SecretStr | None = None
    webhook_routes: str = ""  # JSON: [{"prefix": "crm", "url": "https://...", "secret": "16+ chars", "name": "crm"}]
    notify_email: str | None = None  # operator notified when an approval is waiting
    notify_webhook_url: SecretStr | None = None  # Slack-compatible webhook for the same notice
    auto_create_schema: bool | None = None  # default: sandbox only; otherwise run `alembic upgrade head`

    @property
    def is_sandbox(self) -> bool:
        return self.environment == "sandbox"

    @property
    def llm_pinned(self) -> bool:
        return bool(self.llm_model) and (bool(self.llm_base_url) or self.llm_provider == "anthropic")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_endpoints.strip()) or self.llm_pinned or self.llm_auto_discover

    @property
    def effective_assistant_mode(self) -> str:
        if not self.llm_enabled:
            return "rules"
        return self.assistant_mode or "hybrid"

    @property
    def schema_auto_create(self) -> bool:
        return self.auto_create_schema if self.auto_create_schema is not None else self.is_sandbox

    @property
    def distinct_reviewer_required(self) -> bool:
        if self.require_distinct_reviewer is not None:
            return self.require_distinct_reviewer
        return not self.is_sandbox

    def validate_runtime(self) -> None:
        """Fail closed: anything other than sandbox must have authenticated keys."""
        min_length = 0 if self.is_sandbox else MIN_SECRET_LENGTH
        keys = parse_api_keys(self.api_keys, min_secret_length=min_length)
        if not self.is_sandbox and not keys:
            raise RuntimeError(f"ENVIRONMENT={self.environment} requires API_KEYS (name:role:secret, secrets >= {MIN_SECRET_LENGTH} chars)")
        if self.llm_model and not self.llm_pinned:
            raise RuntimeError("LLM_MODEL needs LLM_BASE_URL (or LLM_PROVIDER=anthropic)")
        if self.llm_base_url and not self.llm_model:
            raise RuntimeError("LLM_BASE_URL needs LLM_MODEL (use LLM_ENDPOINTS to discover models instead)")
        if self.llm_provider == "anthropic" and self.llm_model and not self.llm_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic requires LLM_API_KEY")
        if self.assistant_mode in {"hybrid", "llm"} and not self.llm_enabled:
            raise RuntimeError(f"ASSISTANT_MODE={self.assistant_mode} needs LLM_AUTO_DISCOVER, LLM_ENDPOINTS or LLM_MODEL")
        from app.services.connector_setup import build_connectors  # local imports: these modules import Settings
        from app.services.model_setup import explicit_endpoints

        try:
            explicit_endpoints(self)
            build_connectors(self)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        if self.smtp_host and self.environment == "staging" and not self.smtp_allowed_domains.strip():
            raise RuntimeError("SMTP in staging requires SMTP_ALLOWED_DOMAINS so test mail cannot reach real recipients")


def build_engine(url: str) -> Engine:
    kwargs: dict[str, Any] = {"echo": False, "pool_pre_ping": True}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            # Let SQLAlchemy own transactions so SAVEPOINTs behave (see SQLAlchemy "pysqlite savepoints" notes).
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        @event.listens_for(engine, "begin")
        def _sqlite_begin(connection: Any) -> None:
            connection.exec_driver_sql("BEGIN IMMEDIATE")  # take the write lock up front: no read-to-write upgrade failures

    return engine


def init_db(engine: Engine, create: bool = True) -> None:
    """Create tables (sandbox) or verify migrations ran. Refuses a 0.1 database: its schema cannot be upgraded in place."""
    from app.domain import chat_models, models  # noqa: F401  (register tables)

    tables = set(inspect(engine).get_table_names())
    if "goal" in tables and "schemameta" not in tables:
        raise RuntimeError(
            "Found a 0.1 schema (no schemameta table). Back up and remove the old database, "
            "or point DATABASE_URL at a new one; 0.2 changes column types and primary keys."
        )
    if not create and "schemameta" not in tables:
        raise RuntimeError("Database schema is missing. Run `alembic upgrade head` (or set AUTO_CREATE_SCHEMA=true for a throwaway database).")
    if create:
        SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        row = session.get(models.SchemaMeta, "schema_version")
        if row is None:
            session.add(models.SchemaMeta(key="schema_version", value=SCHEMA_VERSION))
            session.commit()
        elif row.value != SCHEMA_VERSION:
            raise RuntimeError(f"Database schema version {row.value} does not match application schema {SCHEMA_VERSION}")
