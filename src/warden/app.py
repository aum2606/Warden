"""FastAPI application entry point."""

from fastapi import FastAPI

from warden import __version__
from warden.config import Settings
from warden.logging import configure_logging


def create_app() -> FastAPI:
    """Build the HTTP application and its infrastructure-only route."""
    settings = Settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="Warden", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report process health and the running application version."""
        return {"status": "ok", "version": __version__}

    return app
