"""Shared test fixtures."""

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from warden.app import create_app
from warden.capability.records import CapabilityRecord
from warden.config import Settings
from warden.database import AsyncSessionFactory, create_database_engine, create_session_factory

_TEST_SIGNING_SECRET = "test-session-signing-secret-with-32-chars"


@pytest.fixture
def settings() -> Settings:
    """Provide isolated settings with a non-production signing key."""
    return Settings.model_validate(
        {
            "database_url": os.environ.get(
                "TEST_DATABASE_URL",
                "postgresql+asyncpg://warden:warden@127.0.0.1:5432/warden",
            ),
            "environment": "test",
            "log_level": "INFO",
            "session_signing_secret": SecretStr(_TEST_SIGNING_SECRET),
            "session_ttl_seconds": 28_800,
            "capability_signing_secret": SecretStr(
                "test-capability-signing-secret-32-chars",
            ),
            "capability_ttl_seconds": 900,
        },
    )


@pytest.fixture
async def database_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Create a clean identity schema for each database-backed test."""
    engine = create_database_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(CapabilityRecord.metadata.drop_all)
        await connection.run_sync(CapabilityRecord.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(database_engine: AsyncEngine) -> AsyncSessionFactory:
    """Provide sessions bound to the clean test schema."""
    return create_session_factory(database_engine)


@pytest.fixture
async def client(
    settings: Settings,
    session_factory: AsyncSessionFactory,
) -> AsyncIterator[httpx.AsyncClient]:
    """Provide an HTTP client for a fresh application instance."""
    transport = httpx.ASGITransport(app=create_app(settings, session_factory))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
