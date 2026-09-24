"""Password and signed-session primitives for identity authentication."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import BaseModel, ValidationError

from .errors import InvalidSessionError
from .types import OrgId, Principal, PrincipalId

_ALGORITHM: Final = "HS256"
_ISSUER: Final = "warden"
_AUDIENCE: Final = "warden-api"
_PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password with Argon2id and a per-password random salt."""
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a password while treating malformed hashes as authentication failure."""
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


class _SessionClaims(BaseModel):
    sub: str
    org_id: UUID
    iat: int
    exp: int
    iss: str
    aud: str


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    """Verified identity carried by a signed session token."""

    principal_id: PrincipalId
    org_id: OrgId


class SessionTokenService:
    """Issue and verify short-lived HMAC-signed session tokens."""

    def __init__(self, signing_secret: str, ttl: timedelta) -> None:
        """Configure token signing with a secret and positive lifetime."""
        if not signing_secret:
            message = "session signing secret cannot be empty"
            raise ValueError(message)
        if ttl <= timedelta(0):
            message = "session TTL must be positive"
            raise ValueError(message)
        self._signing_secret = signing_secret
        self._ttl = ttl

    @property
    def ttl_seconds(self) -> int:
        """Return the configured session lifetime in whole seconds."""
        return int(self._ttl.total_seconds())

    def issue(self, principal: Principal, *, now: datetime | None = None) -> str:
        """Create a token bound to one user principal and organization."""
        issued_at = now or datetime.now(UTC)
        expires_at = issued_at + self._ttl
        payload = {
            "sub": str(principal.id),
            "org_id": str(principal.org_id),
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "iss": _ISSUER,
            "aud": _AUDIENCE,
        }
        return jwt.encode(payload, self._signing_secret, algorithm=_ALGORITHM)

    def resolve(self, token: str) -> ResolvedSession:
        """Verify a token and return its typed identity claims."""
        try:
            raw_claims: object = jwt.decode(
                token,
                self._signing_secret,
                algorithms=[_ALGORITHM],
                audience=_AUDIENCE,
                issuer=_ISSUER,
            )
            claims = _SessionClaims.model_validate(raw_claims)
            principal_id = PrincipalId.parse(claims.sub)
        except (jwt.InvalidTokenError, ValidationError, ValueError) as error:
            message = "session token is invalid"
            raise InvalidSessionError(message) from error
        return ResolvedSession(
            principal_id=principal_id,
            org_id=OrgId(claims.org_id),
        )
