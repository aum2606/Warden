"""Domain values exchanged only within the tool broker boundary."""

from dataclasses import dataclass
from typing import NewType
from uuid import UUID

from warden.capability.canonicalization import FingerprintSchema
from warden.capability.types import JsonValue, ToolName

ConnectionProvider = NewType("ConnectionProvider", str)
CredentialReference = NewType("CredentialReference", str)
ExecutionId = NewType("ExecutionId", UUID)
type ConnectorResult = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ToolDescription:
    """Describe one connector tool and its complete fingerprint boundary."""

    name: ToolName
    description: str
    parameter_schema: dict[str, JsonValue]
    fingerprint_schema: FingerprintSchema


@dataclass(frozen=True, slots=True)
class ConnectorInvocation:
    """Retain a fake call without retaining its credential."""

    tool: ToolName
    parameters: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class BrokerResult:
    """Return connector output with its durable execution identifier."""

    execution_id: ExecutionId
    output: ConnectorResult
