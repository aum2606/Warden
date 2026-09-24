"""Identity authentication and principal resolution tests."""

from http import HTTPStatus

import httpx
import pytest

from warden.database import AsyncSessionFactory
from warden.identity.api import LoginResponse
from warden.identity.seed import seed_identity
from warden.identity.types import Role

_SEED_PASSWORD = "correct horse battery staple"


@pytest.mark.parametrize(
    ("email", "role"),
    [
        ("owner@warden.local", Role.OWNER),
        ("approver@warden.local", Role.APPROVER),
        ("member@warden.local", Role.MEMBER),
    ],
)
async def test_seeded_user_can_login_and_resolve_current_role(
    client: httpx.AsyncClient,
    session_factory: AsyncSessionFactory,
    email: str,
    role: Role,
) -> None:
    """Every seeded human role produces a session resolving to that role."""
    async with session_factory() as session:
        await seed_identity(session, _SEED_PASSWORD)

    login_response = await client.post(
        "/auth/login",
        json={"email": email, "password": _SEED_PASSWORD},
    )
    login = LoginResponse.model_validate(login_response.json())
    me_response = await client.get(
        "/me",
        headers={"Authorization": f"Bearer {login.access_token}"},
    )

    assert login_response.status_code == HTTPStatus.OK
    assert login.token_type == "bearer"
    assert me_response.status_code == HTTPStatus.OK
    assert me_response.json()["email"] == email
    assert me_response.json()["role"] == role.value


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("missing@warden.local", _SEED_PASSWORD),
        ("owner@warden.local", "incorrect password"),
    ],
)
async def test_login_rejects_unknown_email_and_wrong_password_with_same_response(
    client: httpx.AsyncClient,
    session_factory: AsyncSessionFactory,
    email: str,
    password: str,
) -> None:
    """Login failures do not reveal whether an email exists."""
    async with session_factory() as session:
        await seed_identity(session, _SEED_PASSWORD)

    response = await client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json() == {"detail": "authentication failed"}


async def test_me_rejects_missing_and_invalid_bearer_sessions(client: httpx.AsyncClient) -> None:
    """Principal resolution fails closed without a valid signed session."""
    missing_response = await client.get("/me")
    invalid_response = await client.get(
        "/me",
        headers={"Authorization": "Bearer invalid"},
    )

    assert missing_response.status_code == HTTPStatus.UNAUTHORIZED
    assert invalid_response.status_code == HTTPStatus.UNAUTHORIZED
