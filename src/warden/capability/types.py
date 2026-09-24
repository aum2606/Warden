"""Domain types for capability tokens, fingerprints, and verification."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import NewType
from uuid import UUID

from warden.policy.models import ToolName
from warden.policy.types import DecisionId, JsonValue, RunId, StepId

CAPABILITY_TTL_HARD_CEILING_SECONDS = 900
CapabilityId = NewType("CapabilityId", UUID)
CapabilityToken = NewType("CapabilityToken", str)
Fingerprint = NewType("Fingerprint", str)
CapabilityPrincipal = NewType("CapabilityPrincipal", str)


class RejectionReason(StrEnum):
    """First-failure reasons in the verifier's required check order."""

    SIGNATURE = "signature"
    EXPIRY = "expiry"
    CONSUMPTION = "consumption"
    FINGERPRINT = "fingerprint"
    RUN_BINDING = "run_binding"
    TOOL_BINDING = "tool_binding"


@dataclass(frozen=True, slots=True)
class CapabilityClaims:
    """Represent the exact signed fields carried by one capability."""

    cap_id: CapabilityId
    run_id: RunId
    step_id: StepId
    principal: CapabilityPrincipal
    authority_chain: tuple[CapabilityPrincipal, ...]
    tool: ToolName
    param_fingerprint: Fingerprint
    decision_id: DecisionId
    obligations: tuple[dict[str, JsonValue], ...]
    issued_at: datetime
    expires_at: datetime
    single_use: bool


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Return either a verified capability or its first rejection reason."""

    accepted: bool
    capability_id: CapabilityId | None
    rejection: RejectionReason | None


@dataclass(frozen=True, slots=True)
class CapabilityRejection:
    """Capture a failed verification for later audit persistence."""

    capability_id: CapabilityId | None
    reason: RejectionReason
    occurred_at: datetime
