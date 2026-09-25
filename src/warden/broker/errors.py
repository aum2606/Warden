"""Exceptions owned by the broker module."""


class BrokerError(Exception):
    """Base class for broker module failures."""


class BrokerConfigurationError(BrokerError):
    """Report ambiguous connectors or connection configuration."""


class CapabilityRejectedError(BrokerError):
    """Report that capability verification denied broker execution."""


class CredentialResolutionError(BrokerError):
    """Report unavailable connection metadata or secret material."""


class UnsupportedObligationError(BrokerError):
    """Report an obligation the broker cannot enforce safely."""


class ConnectorInvocationError(BrokerError):
    """Report a connector failure without exposing credential material."""


class ExecutionRecordingError(BrokerError):
    """Report a failed execution persistence operation."""
