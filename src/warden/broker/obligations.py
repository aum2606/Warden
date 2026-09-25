"""Recording-only enforcement of capability obligations."""

from collections.abc import Mapping

from warden.capability.canonicalization import FingerprintSchema, fingerprint_value_digest
from warden.capability.types import JsonValue

from .errors import UnsupportedObligationError

_REDACTED_MARKER = "[REDACTED]"


def apply_recording_obligations(
    parameters: Mapping[str, JsonValue],
    obligations: tuple[dict[str, JsonValue], ...],
    fingerprint_schema: FingerprintSchema,
) -> dict[str, JsonValue]:
    """Redact retained parameters while leaving connector parameters untouched."""
    recorded = _copy_mapping(parameters)
    for obligation in obligations:
        if set(obligation) != {"redact", "unless"}:
            message = "broker does not recognize capability obligation"
            raise UnsupportedObligationError(message)
        path = obligation.get("redact")
        unless = obligation.get("unless")
        if not isinstance(path, str) or unless != "approved":
            message = "broker does not recognize capability obligation"
            raise UnsupportedObligationError(message)
        prefix = "params."
        field = path[len(prefix) :] if path.startswith(prefix) else ""
        if not field or "." in field or field not in recorded:
            message = f"redaction path {path!r} cannot be enforced"
            raise UnsupportedObligationError(message)
        if field not in fingerprint_schema.fields:
            message = f"redacted field {field!r} is outside the fingerprint schema"
            raise UnsupportedObligationError(message)
        digest = fingerprint_value_digest(
            recorded[field],
            recipients=field in fingerprint_schema.recipient_fields,
            free_text=field in fingerprint_schema.free_text_fields,
        )
        recorded[field] = {"marker": _REDACTED_MARKER, "digest": str(digest)}
    return recorded


def _copy_mapping(parameters: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: _copy_value(value) for key, value in parameters.items()}


def _copy_value(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _copy_value(item) for key, item in value.items()}
    return value
