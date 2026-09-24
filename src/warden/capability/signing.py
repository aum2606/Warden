"""Domain-separated compact HMAC signing for capability claims."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from warden.policy.models import ToolName
from warden.policy.types import DecisionId, JsonValue, RunId, StepId

from .errors import InvalidCapabilityTokenError
from .types import (
    CapabilityClaims,
    CapabilityId,
    CapabilityPrincipal,
    CapabilityToken,
    Fingerprint,
)

_SIGNING_CONTEXT: Final = b"warden.capability.v1\x00"


class _ClaimsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    cap_id: str
    run_id: str
    step_id: str
    principal: str
    authority_chain: tuple[str, ...]
    tool: str
    param_fingerprint: str
    decision_id: str
    obligations: tuple[dict[str, JsonValue], ...]
    issued_at: datetime
    expires_at: datetime
    single_use: Literal[True]

    @field_validator("issued_at", "expires_at")
    @classmethod
    def timestamp_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            message = "capability timestamps must be timezone-aware"
            raise ValueError(message)
        return value.astimezone(UTC)


class CapabilitySigner:
    """Sign and authenticate capability payloads with a dedicated HMAC key."""

    def __init__(self, key: bytes) -> None:
        """Copy key material and reject an empty signing secret."""
        if not key:
            message = "capability signing key must not be empty"
            raise ValueError(message)
        self._key = bytes(key)

    def sign(self, claims: CapabilityClaims) -> CapabilityToken:
        """Return a compact payload and domain-separated HMAC signature."""
        payload = _claims_payload(claims)
        payload_segment = _base64url_encode(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        signature = hmac.new(
            self._key,
            _SIGNING_CONTEXT + payload_segment.encode(),
            hashlib.sha256,
        ).digest()
        return CapabilityToken(f"{payload_segment}.{_base64url_encode(signature)}")

    def verify(self, token: CapabilityToken) -> CapabilityClaims:
        """Authenticate a compact token before parsing any claim as trusted."""
        try:
            payload_segment, signature_segment = str(token).split(".")
            supplied_signature = _base64url_decode(signature_segment)
        except (ValueError, UnicodeError) as error:
            message = "capability token is malformed"
            raise InvalidCapabilityTokenError(message) from error
        expected_signature = hmac.new(
            self._key,
            _SIGNING_CONTEXT + payload_segment.encode(),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            message = "capability signature is invalid"
            raise InvalidCapabilityTokenError(message)
        try:
            model = _ClaimsModel.model_validate_json(_base64url_decode(payload_segment))
            return _claims_from_model(model)
        except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            message = "capability payload is invalid"
            raise InvalidCapabilityTokenError(message) from error


def _claims_payload(claims: CapabilityClaims) -> dict[str, object]:
    return {
        "cap_id": str(claims.cap_id),
        "run_id": str(claims.run_id),
        "step_id": str(claims.step_id),
        "principal": str(claims.principal),
        "authority_chain": [str(principal) for principal in claims.authority_chain],
        "tool": str(claims.tool),
        "param_fingerprint": str(claims.param_fingerprint),
        "decision_id": str(claims.decision_id),
        "obligations": list(claims.obligations),
        "issued_at": _format_timestamp(claims.issued_at),
        "expires_at": _format_timestamp(claims.expires_at),
        "single_use": claims.single_use,
    }


def _claims_from_model(model: _ClaimsModel) -> CapabilityClaims:
    return CapabilityClaims(
        cap_id=CapabilityId(UUID(model.cap_id)),
        run_id=RunId(UUID(model.run_id)),
        step_id=StepId(UUID(model.step_id)),
        principal=CapabilityPrincipal(model.principal),
        authority_chain=tuple(CapabilityPrincipal(value) for value in model.authority_chain),
        tool=ToolName(model.tool),
        param_fingerprint=Fingerprint(model.param_fingerprint),
        decision_id=DecisionId(UUID(model.decision_id)),
        obligations=model.obligations,
        issued_at=model.issued_at,
        expires_at=model.expires_at,
        single_use=model.single_use,
    )


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        message = "capability timestamps must be timezone-aware"
        raise ValueError(message)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        message = "capability token contains invalid base64url"
        raise InvalidCapabilityTokenError(message) from error
