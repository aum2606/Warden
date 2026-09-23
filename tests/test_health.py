"""Health endpoint tests."""

from http import HTTPStatus

import httpx


async def test_health_returns_status_and_version(client: httpx.AsyncClient) -> None:
    """The health endpoint identifies a ready Warden process."""
    response = await client.get("/health")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok", "version": "0.1.0"}
