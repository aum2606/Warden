"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import TYPE_CHECKING

from fastapi import FastAPI

from warden import __version__
from warden.config import Settings
from warden.database import AsyncSessionFactory, create_database_engine, create_session_factory
from warden.identity.api import create_identity_router
from warden.identity.security import SessionTokenService
from warden.logging import configure_logging

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine


def create_app(
    settings: Settings | None = None,
    session_factory: AsyncSessionFactory | None = None,
) -> FastAPI:
    """Build the HTTP application with identity infrastructure."""
    resolved_settings = settings or Settings.model_validate({})
    configure_logging(resolved_settings.log_level)

    owned_engine: AsyncEngine | None = None
    if session_factory is None:
        owned_engine = create_database_engine(resolved_settings.database_url)
        session_factory = create_session_factory(owned_engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if owned_engine is not None:
            await owned_engine.dispose()

    app = FastAPI(title="Warden", version=__version__, lifespan=lifespan)
    token_service = SessionTokenService(
        resolved_settings.session_signing_secret.get_secret_value(),
        timedelta(seconds=resolved_settings.session_ttl_seconds),
    )
    app.include_router(create_identity_router(session_factory, token_service))

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report process health and the running application version."""
        return {"status": "ok", "version": __version__}

    return app
