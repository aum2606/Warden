"""Environment-backed application configuration."""

from typing import Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from warden.capability.types import CAPABILITY_TTL_HARD_CEILING_SECONDS

_MINIMUM_SIGNING_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Load Warden process settings from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://warden:warden@127.0.0.1:5432/warden"
    database_role: str | None = "warden_app"
    log_level: str = "INFO"
    environment: str = "development"
    session_signing_secret: SecretStr
    session_ttl_seconds: int = 28_800
    capability_signing_secret: SecretStr
    capability_ttl_seconds: int = 900
    seed_password: SecretStr | None = None

    @field_validator("session_signing_secret", "capability_signing_secret")
    @classmethod
    def signing_secret_has_sufficient_entropy(cls, secret: SecretStr) -> SecretStr:
        """Reject secrets too short for an HMAC signing key."""
        if len(secret.get_secret_value()) < _MINIMUM_SIGNING_SECRET_LENGTH:
            message = "HMAC signing secrets must contain at least 32 characters"
            raise ValueError(message)
        return secret

    @field_validator("capability_ttl_seconds")
    @classmethod
    def capability_ttl_is_positive_and_bounded(cls, ttl_seconds: int) -> int:
        """Allow operators to shorten but never extend capability lifetime."""
        if not 0 < ttl_seconds <= CAPABILITY_TTL_HARD_CEILING_SECONDS:
            message = (
                "CAPABILITY_TTL_SECONDS must be between 1 and "
                f"{CAPABILITY_TTL_HARD_CEILING_SECONDS}"
            )
            raise ValueError(message)
        return ttl_seconds

    @model_validator(mode="after")
    def capability_key_is_distinct(self) -> Self:
        """Prevent session credentials from signing execution authority."""
        if self.capability_signing_secret == self.session_signing_secret:
            message = "CAPABILITY_SIGNING_SECRET must differ from SESSION_SIGNING_SECRET"
            raise ValueError(message)
        return self
