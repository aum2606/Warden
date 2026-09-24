"""HTTP inspection and side-effect-free simulation for policy bundles."""

from fastapi import APIRouter
from pydantic import field_validator

from warden.identity.types import PrincipalKind

from .engine import PolicyEngine
from .models import (
    ConditionId,
    PolicyDocument,
    PolicyEffect,
    PolicyRuleId,
    PrincipalSelectorId,
    StrictPolicyModel,
    ToolName,
)
from .types import (
    DecisionInput,
    JsonValue,
    PolicyPrincipal,
    PolicyPrincipalReference,
    SourceDigest,
)


class PolicySimulationRequest(StrictPolicyModel):
    """Carry the seven explicit inputs accepted by the policy simulator."""

    principal: PolicyPrincipalReference
    authority_chain: tuple[PolicyPrincipalReference, ...]
    tool: ToolName
    params: dict[str, JsonValue]
    context: dict[str, JsonValue]
    run: dict[str, JsonValue]
    environment: dict[str, JsonValue]

    @field_validator("principal")
    @classmethod
    def principal_uses_policy_reference_form(
        cls,
        value: PolicyPrincipalReference,
    ) -> PolicyPrincipalReference:
        """Reject principals that cannot be resolved without external state."""
        _parse_principal(value)
        return value

    @field_validator("authority_chain")
    @classmethod
    def authority_chain_uses_policy_reference_form(
        cls,
        values: tuple[PolicyPrincipalReference, ...],
    ) -> tuple[PolicyPrincipalReference, ...]:
        """Validate every authority-chain link at the API boundary."""
        for value in values:
            _parse_principal(value)
        return values


class PolicyDecisionResponse(StrictPolicyModel):
    """Expose an evaluated effect and the rule evidence behind it."""

    effect: PolicyEffect
    rule_id: PolicyRuleId
    failed_condition_ids: tuple[ConditionId, ...]
    bundle_digest: SourceDigest


class PolicyBundleResponse(StrictPolicyModel):
    """Expose the complete current bundle and its stable identity."""

    version: int
    digest: SourceDigest
    rules: tuple[PolicyDocument, ...]


def create_policy_router(engine: PolicyEngine) -> APIRouter:
    """Create policy routes bound to one atomically loaded current bundle."""
    router = APIRouter(prefix="/policies", tags=["policies"])

    @router.get("")
    async def get_policies() -> PolicyBundleResponse:
        """Return the current validated bundle with version and digest."""
        bundle = engine.bundle
        return PolicyBundleResponse(
            version=bundle.rules[0].version,
            digest=bundle.source_digest,
            rules=bundle.rules,
        )

    @router.post("/simulate")
    async def simulate(payload: PolicySimulationRequest) -> PolicyDecisionResponse:
        """Evaluate hypothetical inputs without recording or minting anything."""
        result = engine.evaluate(_decision_input(payload))
        return PolicyDecisionResponse(
            effect=result.effect,
            rule_id=result.rule_id,
            failed_condition_ids=result.failed_condition_ids,
            bundle_digest=engine.bundle.source_digest,
        )

    return router


def _decision_input(payload: PolicySimulationRequest) -> DecisionInput:
    return DecisionInput(
        principal=_parse_principal(payload.principal),
        authority_chain=tuple(_parse_principal(value) for value in payload.authority_chain),
        tool=payload.tool,
        parameters=payload.params,
        context_provenance=payload.context,
        run_metadata=payload.run,
        environment=payload.environment,
    )


def _parse_principal(value: PolicyPrincipalReference) -> PolicyPrincipal:
    kind_value, separator, identifier = str(value).partition(":")
    if not separator or not identifier:
        message = "principal must use the kind:identifier form"
        raise ValueError(message)
    try:
        kind = PrincipalKind(kind_value)
    except ValueError as error:
        message = f"unknown principal kind {kind_value!r}"
        raise ValueError(message) from error
    return PolicyPrincipal(kind=kind, id=PrincipalSelectorId(identifier))
