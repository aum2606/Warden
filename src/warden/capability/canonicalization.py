"""Explicit per-tool parameter canonicalization and fingerprinting."""

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, cast

from warden.policy.models import ToolName
from warden.policy.types import JsonValue

from .errors import CanonicalizationError, UnregisteredToolError
from .types import Fingerprint

_WHITESPACE: Final = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class FingerprintSchema:
    """Declare exactly which tool fields bind a capability and how."""

    fields: tuple[str, ...]
    recipient_fields: frozenset[str] = frozenset()
    free_text_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Reject ambiguous or internally inconsistent declarations."""
        field_set = frozenset(self.fields)
        if not self.fields or len(field_set) != len(self.fields):
            message = "fingerprint fields must be non-empty and unique"
            raise ValueError(message)
        specialized = self.recipient_fields | self.free_text_fields
        if not specialized <= field_set:
            message = "specialized fingerprint fields must be declared fields"
            raise ValueError(message)
        if self.recipient_fields & self.free_text_fields:
            message = "a fingerprint field cannot be both recipients and free text"
            raise ValueError(message)


class FingerprintSchemaRegistry:
    """Resolve immutable connector-owned schemas by exact tool name."""

    def __init__(self, schemas: Mapping[ToolName, FingerprintSchema]) -> None:
        """Copy declarations so callers cannot change fingerprint coverage."""
        self._schemas = dict(schemas)

    def schema_for(self, tool: ToolName) -> FingerprintSchema:
        """Return a declaration or fail closed for an unknown tool."""
        schema = self._schemas.get(tool)
        if schema is None:
            message = f"tool {tool!s} has no fingerprint schema"
            raise UnregisteredToolError(message)
        return schema


GITHUB_ISSUE_CREATE_SCHEMA: Final = FingerprintSchema(
    fields=("repo", "title", "body"),
    free_text_fields=frozenset({"body"}),
)
GMAIL_SEND_SCHEMA: Final = FingerprintSchema(
    fields=("to", "subject", "body", "attachment_count"),
    recipient_fields=frozenset({"to"}),
    free_text_fields=frozenset({"body"}),
)
DEFAULT_FINGERPRINT_SCHEMAS: Final = FingerprintSchemaRegistry(
    {
        ToolName("github.issue.create"): GITHUB_ISSUE_CREATE_SCHEMA,
        ToolName("gmail.send"): GMAIL_SEND_SCHEMA,
    }
)


def fingerprint_parameters(
    tool: ToolName,
    parameters: Mapping[str, JsonValue],
    registry: FingerprintSchemaRegistry = DEFAULT_FINGERPRINT_SCHEMAS,
) -> Fingerprint:
    """Hash one tool's explicitly selected and canonicalized parameter values."""
    canonical = canonicalize_parameters(tool, parameters, registry)
    digest = hashlib.sha256(canonical).hexdigest()
    return Fingerprint(f"sha256:{digest}")


def fingerprint_value_digest(
    value: JsonValue,
    *,
    recipients: bool = False,
    free_text: bool = False,
) -> Fingerprint:
    """Digest one value using the same normalization declared for its tool field."""
    if recipients and free_text:
        message = "a fingerprint value cannot be both recipients and free text"
        raise CanonicalizationError(message)
    if recipients:
        canonical: JsonValue = cast("JsonValue", _canonicalize_recipients(value, "value"))
    elif free_text:
        return Fingerprint(_hash_free_text(value, "value"))
    else:
        canonical = _canonicalize_value(value)
    try:
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        message = "fingerprinted value is not a canonical JSON value"
        raise CanonicalizationError(message) from error
    return Fingerprint(f"sha256:{hashlib.sha256(encoded).hexdigest()}")


def canonicalize_parameters(
    tool: ToolName,
    parameters: Mapping[str, JsonValue],
    registry: FingerprintSchemaRegistry = DEFAULT_FINGERPRINT_SCHEMAS,
) -> bytes:
    """Return deterministic JSON bytes for only connector-declared fields."""
    schema = registry.schema_for(tool)
    selected: dict[str, JsonValue] = {}
    for field in schema.fields:
        if field not in parameters:
            message = f"fingerprinted field {field!r} is missing for {tool!s}"
            raise CanonicalizationError(message)
        value = parameters[field]
        if field in schema.recipient_fields:
            selected[field] = cast("JsonValue", _canonicalize_recipients(value, field))
        elif field in schema.free_text_fields:
            selected[field] = _hash_free_text(value, field)
        else:
            selected[field] = _canonicalize_value(value)
    try:
        return json.dumps(
            selected,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        message = "fingerprinted parameters are not canonical JSON values"
        raise CanonicalizationError(message) from error


def _canonicalize_recipients(value: JsonValue, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        message = f"recipient field {field!r} must be a list of strings"
        raise CanonicalizationError(message)
    recipients = (item for item in value if isinstance(item, str))
    return sorted(_normalize_whitespace(item).lower() for item in recipients)


def _hash_free_text(value: JsonValue, field: str) -> str:
    if not isinstance(value, str):
        message = f"free-text field {field!r} must be a string"
        raise CanonicalizationError(message)
    normalized = _normalize_whitespace(value).encode()
    return f"sha256:{hashlib.sha256(normalized).hexdigest()}"


def _canonicalize_value(value: JsonValue) -> JsonValue:
    if isinstance(value, str):
        return _normalize_whitespace(value)
    if isinstance(value, float) and not math.isfinite(value):
        message = "non-finite numbers cannot be fingerprinted"
        raise CanonicalizationError(message)
    if isinstance(value, list):
        return [_canonicalize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonicalize_value(item) for key, item in sorted(value.items())}
    return value


def _normalize_whitespace(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()
