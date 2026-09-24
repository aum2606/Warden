"""Authentication queries and principal resolution."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import InvalidCredentialsError, InvalidSessionError
from .models import User
from .security import SessionTokenService, verify_password
from .types import OrgId, Principal, PrincipalId, PrincipalKind, UserId


async def authenticate_user(session: AsyncSession, email: str, password: str) -> Principal:
    """Resolve valid credentials to a typed human principal."""
    normalized_email = email.strip().lower()
    user = await session.scalar(select(User).where(User.email == normalized_email))
    if user is None or not verify_password(user.password_hash, password):
        message = "email or password is invalid"
        raise InvalidCredentialsError(message)
    return _principal_from_user(user)


async def resolve_session_principal(
    session: AsyncSession,
    token_service: SessionTokenService,
    token: str,
) -> Principal:
    """Resolve a signed token against current persisted user state."""
    resolved = token_service.resolve(token)
    if resolved.principal_id.kind is not PrincipalKind.USER:
        message = "session does not identify a human principal"
        raise InvalidSessionError(message)
    user = await session.get(User, resolved.principal_id.value)
    if user is None or user.org_id != resolved.org_id:
        message = "session principal no longer exists"
        raise InvalidSessionError(message)
    return _principal_from_user(user)


def _principal_from_user(user: User) -> Principal:
    user_id = UserId(user.id)
    return Principal(
        id=PrincipalId.for_user(user_id),
        org_id=OrgId(user.org_id),
        email=user.email,
        role=user.role,
    )
