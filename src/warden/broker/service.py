"""Capability-gated orchestration of credentials, connectors, and records."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from warden.capability.canonicalization import (
    FingerprintSchemaRegistry,
    fingerprint_parameters,
)
from warden.capability.types import (
    CapabilityClaims,
    CapabilityToken,
    JsonValue,
    RunId,
    ToolName,
    VerificationResult,
)

from .connectors import Connector
from .credentials import ConnectionStore, CredentialResolver
from .errors import (
    BrokerConfigurationError,
    CapabilityRejectedError,
    ConnectorInvocationError,
)
from .obligations import apply_recording_obligations
from .records import ExecutionRepository
from .registry import connector_map
from .types import BrokerResult, ConnectionProvider, ExecutionId


class CapabilityVerification(Protocol):
    """Expose only the consuming verification operation needed by the broker."""

    async def verify_and_consume(
        self,
        token: CapabilityToken,
        parameters: Mapping[str, JsonValue],
        expected_run_id: RunId,
        expected_tool: ToolName,
    ) -> VerificationResult:
        """Consume a valid capability or return its first rejection reason."""
        ...


@dataclass(frozen=True, slots=True)
class BrokerDependencies:
    """Group security-sensitive broker services for explicit composition."""

    verifier: CapabilityVerification
    connection_store: ConnectionStore
    credential_resolver: CredentialResolver
    executions: ExecutionRepository


class Broker:
    """Provide the only path from an authorized action to a connector."""

    def __init__(
        self,
        connectors: tuple[Connector, ...],
        dependencies: BrokerDependencies,
    ) -> None:
        """Index connector ownership and bind verification and credential services."""
        self._connectors = connector_map(connectors)
        self._dependencies = dependencies

    async def execute(
        self,
        token: CapabilityToken,
        tool: ToolName,
        parameters: Mapping[str, JsonValue],
        run_id: RunId,
    ) -> BrokerResult:
        """Verify, consume, redact records, resolve credentials, and invoke."""
        bound_parameters = _copy_mapping(parameters)
        verification = await self._dependencies.verifier.verify_and_consume(
            token,
            bound_parameters,
            run_id,
            tool,
        )
        if not verification.accepted:
            reason = (
                verification.rejection.value if verification.rejection is not None else "unknown"
            )
            message = f"capability rejected at {reason} check"
            raise CapabilityRejectedError(message)
        claims = _require_claims(verification)
        connector = self._connectors.get(tool)
        if connector is None:
            message = f"no connector owns tool {tool!s}"
            raise BrokerConfigurationError(message)
        description = next(
            (description for description in connector.describe() if description.name == tool),
            None,
        )
        if description is None:
            message = f"connector description for tool {tool!s} disappeared"
            raise BrokerConfigurationError(message)
        connector_registry = FingerprintSchemaRegistry(
            {description.name: description.fingerprint_schema}
        )
        connector_fingerprint = fingerprint_parameters(
            tool,
            bound_parameters,
            connector_registry,
        )
        if connector_fingerprint != claims.param_fingerprint:
            message = "verified fingerprint differs from connector declaration"
            raise BrokerConfigurationError(message)
        recorded_parameters = apply_recording_obligations(
            bound_parameters,
            claims.obligations,
            description.fingerprint_schema,
        )
        provider = ConnectionProvider(str(tool).split(".", maxsplit=1)[0])
        reference = await self._dependencies.connection_store.active_reference(provider)
        credential = self._dependencies.credential_resolver.resolve(reference)
        execution = await self._dependencies.executions.start(
            claims.cap_id,
            tool,
            recorded_parameters,
        )
        try:
            output = await connector.invoke(tool, bound_parameters, credential)
        except Exception:  # noqa: BLE001 - connector failures must not expose secret payloads.
            await self._dependencies.executions.fail(ExecutionId(execution.id))
            message = "connector invocation failed"
            raise ConnectorInvocationError(message) from None
        await self._dependencies.executions.succeed(ExecutionId(execution.id), output)
        return BrokerResult(execution_id=ExecutionId(execution.id), output=output)


def _require_claims(verification: VerificationResult) -> CapabilityClaims:
    if verification.claims is None:
        message = "accepted capability verification omitted authenticated claims"
        raise BrokerConfigurationError(message)
    return verification.claims


def _copy_mapping(parameters: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: _copy_value(value) for key, value in parameters.items()}


def _copy_value(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _copy_value(item) for key, item in value.items()}
    return value
