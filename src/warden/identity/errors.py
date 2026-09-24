"""Exceptions owned by the identity module."""


class IdentityError(Exception):
    """Base class for identity module failures."""


class InvalidCredentialsError(IdentityError):
    """Raised when credentials do not identify an authenticated user."""


class InvalidSessionError(IdentityError):
    """Raised when a session token cannot resolve to an active principal."""


class SeedConfigurationError(IdentityError):
    """Raised when required seed configuration is unavailable."""
