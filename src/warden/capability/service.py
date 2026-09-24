"""Capability minting from recorded allow decisions."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from warden.policy.models import PolicyEffect, PolicyRuleId, ToolName
from warden.policy.records import DecisionRecord
from warden.policy.types import DecisionId, JsonValue, PolicyBundle, RunId, StepId

from .canonicalization import FingerprintSchemaRegistry, fingerprint_parameters
from .errors import CapabilityMintingError, CapabilityPersistenceError
from .records import CapabilityRecord
from .signing import CapabilitySigner
from .types import (
    CAPABILITY_TTL_HARD_CEILING_SECONDS,
    CapabilityClaims,
    CapabilityId,
    CapabilityPrincipal,
    CapabilityToken,
)

type Clock = Callable[[], datetime]


def server_time() -> datetime:
    """Read the process clock in UTC for capability lifetime enforcement."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class MintedCapability:
    """Return signed claims together with their compact transport token."""

    claims: CapabilityClaims
    token: CapabilityToken


@dataclass(frozen=True, slots=True)
class CapabilityMintingAuthority:
    """Group trusted inputs that determine the content of minted capabilities."""

    signer: CapabilitySigner
    schemas: FingerprintSchemaRegistry
    policy_bundle: PolicyBundle


class CapabilityMinter:
    """Mint and persist capabilities only from recorded allow decisions."""

    def __init__(
        self,
        session: AsyncSession,
        authority: CapabilityMintingAuthority,
        ttl_seconds: int,
        clock: Clock = server_time,
    ) -> None:
        """Bind trusted signing, schema, policy, lifetime, and clock dependencies."""
        self._session = session
        self._authority = authority
        if not 0 < ttl_seconds <= CAPABILITY_TTL_HARD_CEILING_SECONDS:
            message = "capability lifetime is outside its hard safety bound"
            raise CapabilityMintingError(message)
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    async def mint(self, decision: DecisionRecord) -> MintedCapability:
        """Persist and sign a parameter-bound capability for one allow decision."""
        if decision.effect is not PolicyEffect.ALLOW:
            message = "capabilities may be minted only for allow decisions"
            raise CapabilityMintingError(message)

        principal = _require_string(decision.inputs, "principal")
        authority_chain = _require_string_list(decision.inputs, "authority_chain")
        tool = ToolName(_require_string(decision.inputs, "tool"))
        parameters = _require_parameters(decision.inputs)
        fingerprint = fingerprint_parameters(tool, parameters, self._authority.schemas)
        obligations = self._obligations_for(PolicyRuleId(decision.rule_id))
        issued_at = self._clock()
        _require_aware_time(issued_at)
        claims = CapabilityClaims(
            cap_id=CapabilityId(uuid4()),
            run_id=RunId(decision.run_id),
            step_id=StepId(decision.step_id),
            principal=CapabilityPrincipal(principal),
            authority_chain=tuple(CapabilityPrincipal(value) for value in authority_chain),
            tool=tool,
            param_fingerprint=fingerprint,
            decision_id=DecisionId(decision.id),
            obligations=obligations,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=self._ttl_seconds),
            single_use=True,
        )
        record = CapabilityRecord(
            id=claims.cap_id,
            decision_id=claims.decision_id,
            run_id=claims.run_id,
            principal=claims.principal,
            tool=claims.tool,
            param_fingerprint=claims.param_fingerprint,
            obligations=[dict(value) for value in claims.obligations],
            issued_at=claims.issued_at,
            expires_at=claims.expires_at,
            consumed_at=None,
        )
        self._session.add(record)
        try:
            await self._session.commit()
        except SQLAlchemyError as error:
            await self._session.rollback()
            message = "capability could not be appended"
            raise CapabilityPersistenceError(message) from error
        return MintedCapability(claims=claims, token=self._authority.signer.sign(claims))

    def _obligations_for(
        self,
        rule_id: PolicyRuleId,
    ) -> tuple[dict[str, JsonValue], ...]:
        rule = next(
            (rule for rule in self._authority.policy_bundle.rules if rule.id == rule_id),
            None,
        )
        if rule is None:
            message = f"decision rule {rule_id!s} is absent from the active policy bundle"
            raise CapabilityMintingError(message)
        return tuple(
            {"redact": str(obligation.redact), "unless": obligation.unless}
            for obligation in rule.obligations
        )


def _require_string(values: Mapping[str, object], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str):
        message = f"decision input {field!r} must be a string"
        raise CapabilityMintingError(message)
    return value


def _require_string_list(values: Mapping[str, object], field: str) -> tuple[str, ...]:
    value = values.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        message = f"decision input {field!r} must be a string list"
        raise CapabilityMintingError(message)
    return tuple(item for item in value if isinstance(item, str))


def _require_parameters(values: Mapping[str, object]) -> Mapping[str, JsonValue]:
    value = values.get("params")
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        message = "decision input 'params' must be a JSON object"
        raise CapabilityMintingError(message)
    return value


def _require_aware_time(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        message = "capability server clock must return a timezone-aware timestamp"
        raise CapabilityMintingError(message)
