"""Connector discovery and capability fingerprint registry construction."""

from collections.abc import Iterable

from warden.capability.canonicalization import FingerprintSchemaRegistry
from warden.capability.types import ToolName

from .connectors import Connector
from .errors import BrokerConfigurationError


def fingerprint_registry(connectors: Iterable[Connector]) -> FingerprintSchemaRegistry:
    """Build the operational registry exclusively from connector declarations."""
    schemas = {}
    for connector in connectors:
        for description in connector.describe():
            if description.name in schemas:
                message = f"tool {description.name!s} is declared by multiple connectors"
                raise BrokerConfigurationError(message)
            schemas[description.name] = description.fingerprint_schema
    if not schemas:
        message = "at least one connector tool must be declared"
        raise BrokerConfigurationError(message)
    return FingerprintSchemaRegistry(schemas)


def connector_map(connectors: Iterable[Connector]) -> dict[ToolName, Connector]:
    """Index connectors by tool while rejecting ambiguous ownership."""
    indexed: dict[ToolName, Connector] = {}
    for connector in connectors:
        for description in connector.describe():
            if description.name in indexed:
                message = f"tool {description.name!s} is declared by multiple connectors"
                raise BrokerConfigurationError(message)
            indexed[description.name] = connector
    if not indexed:
        message = "at least one connector tool must be declared"
        raise BrokerConfigurationError(message)
    return indexed
