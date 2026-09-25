"""Connection selection and environment-backed secret resolution."""

import os
from collections.abc import Mapping
from typing import Protocol

from pydantic import SecretStr
from sqlalchemy import String, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .errors import BrokerConfigurationError, CredentialResolutionError
from .types import ConnectionProvider, CredentialReference


class ConnectionStore(Protocol):
    """Resolve one active connection reference without loading its secret."""

    async def active_reference(self, provider: ConnectionProvider) -> CredentialReference:
        """Return the sole active reference or fail closed on ambiguity."""
        ...


class CredentialResolver(Protocol):
    """Resolve credential material inside the broker boundary."""

    def resolve(self, reference: CredentialReference) -> SecretStr:
        """Return secret material without exposing it in diagnostics."""
        ...


class SqlAlchemyConnectionStore:
    """Read active credential references from the identity-owned connections table."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Bind lookups to application database sessions."""
        self._session_factory = session_factory

    async def active_reference(self, provider: ConnectionProvider) -> CredentialReference:
        """Require exactly one active connection for a provider."""
        statement = text(
            """
            SELECT credential_ref
            FROM connections
            WHERE provider = :provider AND status = 'active'
            ORDER BY id
            """
        ).columns(credential_ref=String())
        try:
            async with self._session_factory() as session:
                rows = (await session.execute(statement, {"provider": str(provider)})).all()
        except SQLAlchemyError:
            message = f"active {provider!s} connection lookup failed"
            raise CredentialResolutionError(message) from None
        if len(rows) != 1:
            message = f"provider {provider!s} requires exactly one active connection"
            raise BrokerConfigurationError(message)
        return CredentialReference(str(rows[0].credential_ref))


class EnvironmentCredentialResolver:
    """Resolve `env:NAME` references without retaining plaintext secrets."""

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        """Use a supplied environment mapping or the process environment."""
        self._environment = environment if environment is not None else os.environ

    def resolve(self, reference: CredentialReference) -> SecretStr:
        """Resolve one environment reference while naming only its variable."""
        prefix = "env:"
        if not str(reference).startswith(prefix):
            message = "credential reference must use the env: scheme"
            raise CredentialResolutionError(message)
        variable = str(reference)[len(prefix) :]
        if not variable:
            message = "credential environment variable name is missing"
            raise CredentialResolutionError(message)
        value = self._environment.get(variable)
        if value is None or not value:
            message = f"credential environment variable {variable!r} is unavailable"
            raise CredentialResolutionError(message)
        return SecretStr(value)
