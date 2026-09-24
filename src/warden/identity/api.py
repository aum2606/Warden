"""HTTP routes and request dependencies owned by identity."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .auth import authenticate_user, resolve_session_principal
from .errors import InvalidCredentialsError, InvalidSessionError
from .security import SessionTokenService
from .types import Principal, Role

_bearer = HTTPBearer(auto_error=False)
_SessionFactory = async_sessionmaker[AsyncSession]


class LoginRequest(BaseModel):
    """Credentials accepted by the login endpoint."""

    email: str
    password: SecretStr


class LoginResponse(BaseModel):
    """A signed bearer session and its lifetime."""

    access_token: str
    token_type: str
    expires_in: int


class PrincipalResponse(BaseModel):
    """The current authenticated principal exposed by the API."""

    id: str
    org_id: str
    email: str
    role: Role


def create_identity_router(
    session_factory: _SessionFactory,
    token_service: SessionTokenService,
) -> APIRouter:
    """Create identity routes bound to process infrastructure."""
    router = APIRouter()

    async def current_principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> Principal:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise _unauthorized()
        try:
            async with session_factory() as session:
                return await resolve_session_principal(
                    session,
                    token_service,
                    credentials.credentials,
                )
        except InvalidSessionError as error:
            raise _unauthorized() from error

    @router.post("/auth/login")
    async def login(payload: LoginRequest) -> LoginResponse:
        """Authenticate a user and issue a signed bearer session."""
        try:
            async with session_factory() as session:
                principal = await authenticate_user(
                    session,
                    payload.email,
                    payload.password.get_secret_value(),
                )
        except InvalidCredentialsError as error:
            raise _unauthorized() from error
        return LoginResponse(
            access_token=token_service.issue(principal),
            token_type="bearer",  # noqa: S106 - This is an OAuth scheme name, not a secret.
            expires_in=token_service.ttl_seconds,
        )

    @router.get("/me")
    async def me(principal: Annotated[Principal, Depends(current_principal)]) -> PrincipalResponse:
        """Return identity and current role for the bearer principal."""
        return PrincipalResponse(
            id=str(principal.id),
            org_id=str(principal.org_id),
            email=principal.email,
            role=principal.role,
        )

    return router


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication failed",
        headers={"WWW-Authenticate": "Bearer"},
    )
