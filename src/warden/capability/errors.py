"""Exceptions owned by the capability module."""


class CapabilityError(Exception):
    """Base class for capability module failures."""


class CanonicalizationError(CapabilityError):
    """Report parameters that cannot be safely fingerprinted."""


class UnregisteredToolError(CanonicalizationError):
    """Report a tool without an explicit fingerprint declaration."""


class CapabilityMintingError(CapabilityError):
    """Report a request that cannot produce a capability."""


class InvalidCapabilityTokenError(CapabilityError):
    """Report a token whose signature or payload cannot be trusted."""


class CapabilityPersistenceError(CapabilityError):
    """Report a capability database operation that failed closed."""


class RejectionRecordingError(CapabilityError):
    """Report a verifier rejection that could not be recorded."""
