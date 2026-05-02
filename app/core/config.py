"""Application settings — single source of truth for all configuration.

Loaded once at startup via `lru_cache`. Inject as a FastAPI dependency, never
call ``Settings()`` directly in business code.

Reference: BACKEND_BLUEPRINT.md §5.1.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, Field, MySQLDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # ─── App ──────────────────────────────────────────────────────────────────
    env: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    app_name: str = "pharmacy-api"
    api_v1_prefix: str = "/api/v1"
    admin_v1_prefix: str = "/api/admin/v1"
    base_url: AnyHttpUrl = Field(default="http://localhost:8000")  # type: ignore[assignment]

    # ─── Security ─────────────────────────────────────────────────────────────
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30
    password_pepper: SecretStr
    admin_session_ttl_hours: int = 12

    # ─── Database (MySQL 8) ──────────────────────────────────────────────────
    mysql_dsn: MySQLDsn
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800
    db_echo: bool = False

    # ─── Redis ────────────────────────────────────────────────────────────────
    redis_dsn: RedisDsn

    # ─── i18n ─────────────────────────────────────────────────────────────────
    default_language: Literal["ru", "ky", "en"] = "ru"
    # NoDecode: env source must NOT try to JSON-parse "ru,ky,en"; our validator splits.
    supported_languages: Annotated[tuple[str, ...], NoDecode] = ("ru", "ky", "en")

    # ─── OTP ──────────────────────────────────────────────────────────────────
    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5

    # ─── Rate limits ──────────────────────────────────────────────────────────
    rl_otp_request_per_phone_window_seconds: int = 900
    rl_otp_request_per_phone_max: int = 3

    # ─── External services ───────────────────────────────────────────────────
    sms_provider: Literal["nikita", "fake"] = "fake"
    sms_api_url: AnyHttpUrl | None = None
    sms_api_key: SecretStr | None = None
    sms_sender: str = "Pharmacy"

    payment_provider: Literal["freedom_pay", "fake"] = "fake"
    payment_api_url: AnyHttpUrl | None = None
    payment_merchant_id: str | None = None
    payment_secret: SecretStr | None = None

    storage_endpoint: AnyHttpUrl | None = None
    storage_bucket: str | None = None
    storage_access_key: SecretStr | None = None
    storage_secret_key: SecretStr | None = None
    storage_public_base_url: AnyHttpUrl | None = None

    # ─── Image pipeline (Phase 5 — local disk; Phase 11 wires R2) ────────────
    image_storage_dir: str = "dev/images"
    image_public_base_url: str = "/static/images"
    image_max_bytes: int = 10 * 1024 * 1024  # 10 MB per F-ADM-CAT-002

    sentry_dsn: SecretStr | None = None

    # ─── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: Annotated[list[AnyHttpUrl], NoDecode] = Field(default_factory=list)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors(cls, v: Any) -> Any:
        # Allow comma-separated string in env: "http://a.com,http://b.com"
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                return []
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return v

    @field_validator("supported_languages", mode="before")
    @classmethod
    def _parse_supported_languages(cls, v: Any) -> Any:
        if isinstance(v, str):
            return tuple(lang.strip() for lang in v.split(",") if lang.strip())
        return v


@lru_cache
def get_settings() -> Settings:
    """Read settings once, cached for the life of the process."""
    return Settings()  # values come from env / .env via pydantic-settings
