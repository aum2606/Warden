"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from warden import __version__
from warden.config import Settings
from warden.database import AsyncSessionFactory, create_database_engine, create_session_factory
from warden.identity.api import create_identity_router
from warden.identity.security import SessionTokenService
from warden.logging import configure_logging
from warden.policy.api import create_policy_router
from warden.policy.engine import PolicyEngine
from warden.policy.loader import load_policy_bundle

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

    from warden.policy.types import PolicyBundle


def create_app(
    settings: Settings | None = None,
    session_factory: AsyncSessionFactory | None = None,
    policy_bundle: PolicyBundle | None = None,
) -> FastAPI:
    """Build the HTTP application with identity and policy infrastructure."""
    resolved_settings = settings or Settings.model_validate({})
    configure_logging(resolved_settings.log_level)

    owned_engine: AsyncEngine | None = None
    if session_factory is None:
        owned_engine = create_database_engine(
            resolved_settings.database_url,
            resolved_settings.database_role,
        )
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
    resolved_bundle = policy_bundle or load_policy_bundle(Path("policies"))
    app.include_router(create_policy_router(PolicyEngine(resolved_bundle)))

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report process health and the running application version."""
        return {"status": "ok", "version": __version__}

    return app
