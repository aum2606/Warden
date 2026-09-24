"""Environment-backed application configuration."""

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MINIMUM_SIGNING_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Load Warden process settings from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://warden:warden@127.0.0.1:5432/warden"
    log_level: str = "INFO"
    environment: str = "development"
    session_signing_secret: SecretStr
    session_ttl_seconds: int = 28_800
    seed_password: SecretStr | None = None

    @field_validator("session_signing_secret")
    @classmethod
    def signing_secret_has_sufficient_entropy(cls, secret: SecretStr) -> SecretStr:
        """Reject session secrets too short for an HMAC signing key."""
        if len(secret.get_secret_value()) < _MINIMUM_SIGNING_SECRET_LENGTH:
            message = "SESSION_SIGNING_SECRET must contain at least 32 characters"
            raise ValueError(message)
        return secret
