"""Command-line entry point for local development seed data."""

import asyncio
from typing import Final

import structlog

from warden.config import Settings
from warden.database import create_database_engine, create_session_factory
from warden.identity.errors import SeedConfigurationError
from warden.identity.seed import seed_identity
from warden.logging import configure_logging

_EVENT: Final = "identity.seeded"


async def _run_seed(settings: Settings) -> None:
    if settings.seed_password is None:
        message = "SEED_PASSWORD must be set"
        raise SeedConfigurationError(message)
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            result = await seed_identity(session, settings.seed_password.get_secret_value())
        structlog.get_logger().info(
            _EVENT,
            org_id=str(result.org_id),
            user_count=len(result.user_ids),
            agent_count=len(result.agent_ids),
        )
    finally:
        await engine.dispose()


def main() -> None:
    """Seed the configured database using environment-provided credentials."""
    settings = Settings.model_validate({})
    configure_logging(settings.log_level)
    asyncio.run(_run_seed(settings))


if __name__ == "__main__":
    main()
