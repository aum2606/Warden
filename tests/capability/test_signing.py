"""Capability token signing and configuration tests."""

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from warden.capability.errors import InvalidCapabilityTokenError
from warden.capability.signing import CapabilitySigner
from warden.capability.types import (
    CapabilityClaims,
    CapabilityId,
    CapabilityPrincipal,
    CapabilityToken,
    Fingerprint,
)
from warden.config import CAPABILITY_TTL_HARD_CEILING_SECONDS, Settings
from warden.policy.models import ToolName
from warden.policy.types import DecisionId, RunId, StepId

_KEY = b"capability-test-signing-secret-32-bytes"
_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
_SHORTENED_TTL_SECONDS = 60


def _claims() -> CapabilityClaims:
    return CapabilityClaims(
        cap_id=CapabilityId(UUID("20000000-0000-4000-8000-000000000001")),
        run_id=RunId(UUID("20000000-0000-4000-8000-000000000002")),
        step_id=StepId(UUID("20000000-0000-4000-8000-000000000003")),
        principal=CapabilityPrincipal("agent:ops-worker"),
        authority_chain=(
            CapabilityPrincipal("user:aum"),
            CapabilityPrincipal("agent:orchestrator"),
            CapabilityPrincipal("agent:ops-worker"),
        ),
        tool=ToolName("gmail.send"),
        param_fingerprint=Fingerprint("sha256:" + "a" * 64),
        decision_id=DecisionId(UUID("20000000-0000-4000-8000-000000000004")),
        obligations=({"redact": "params.body"},),
        issued_at=_NOW,
        expires_at=_NOW + timedelta(seconds=900),
        single_use=True,
    )


def test_signed_token_round_trips_every_specified_field() -> None:
    """Compact signing preserves the exact capability claim set."""
    signer = CapabilitySigner(_KEY)

    resolved = signer.verify(signer.sign(_claims()))

    assert resolved == _claims()


def test_signature_without_capability_domain_context_is_rejected() -> None:
    """A valid HMAC from another protocol cannot authenticate as a capability."""
    signer = CapabilitySigner(_KEY)
    token = signer.sign(_claims())
    payload_segment = str(token).split(".")[0]
    undomained_signature = hmac.new(
        _KEY,
        payload_segment.encode(),
        hashlib.sha256,
    ).digest()
    signature_segment = base64.urlsafe_b64encode(undomained_signature).rstrip(b"=").decode()

    with pytest.raises(InvalidCapabilityTokenError, match="signature"):
        signer.verify(CapabilityToken(f"{payload_segment}.{signature_segment}"))


def test_capability_signing_key_is_separate_and_ttl_cannot_exceed_ceiling() -> None:
    """Configuration requires separate key material and permits only shorter TTLs."""
    base = {
        "database_url": "postgresql+asyncpg://warden:warden@database/warden",
        "session_signing_secret": SecretStr("session-signing-secret-with-32-characters"),
        "capability_signing_secret": SecretStr("capability-signing-secret-with-32-characters"),
    }
    settings = Settings.model_validate({**base, "capability_ttl_seconds": _SHORTENED_TTL_SECONDS})

    assert settings.capability_ttl_seconds == _SHORTENED_TTL_SECONDS
    assert settings.capability_signing_secret != settings.session_signing_secret
    with pytest.raises(ValidationError, match="CAPABILITY_TTL_SECONDS"):
        Settings.model_validate(
            {
                **base,
                "capability_ttl_seconds": CAPABILITY_TTL_HARD_CEILING_SECONDS + 1,
            }
        )
    with pytest.raises(ValidationError, match="must differ"):
        Settings.model_validate(
            {
                **base,
                "capability_signing_secret": base["session_signing_secret"],
            }
        )
