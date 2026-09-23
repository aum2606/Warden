"""Shared test fixtures."""

from collections.abc import AsyncIterator

import httpx
import pytest

from warden.app import create_app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide an HTTP client for a fresh application instance."""
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
