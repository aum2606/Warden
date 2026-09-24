"""Loading and condition execution for offline policy decision fixtures."""

from pathlib import Path
from typing import NewType

import yaml
from pydantic import ValidationError

from warden.identity.types import PrincipalKind

from .engine import DecisionResult, PolicyEngine
from .errors import InvalidPolicyFixtureError
from .models import (
    ConditionId,
    PolicyEffect,
    PolicyRuleId,
    PrincipalSelectorId,
    StrictPolicyModel,
    ToolName,
)
from .types import DecisionInput, JsonValue, PolicyBundle, PolicyPrincipal

FixturePrincipal = NewType("FixturePrincipal", str)


class PolicyFixtureInput(StrictPolicyModel):
    """Represent the seven decision inputs serialized in a fixture."""

    principal: FixturePrincipal
    authority_chain: tuple[FixturePrincipal, ...]
    tool: ToolName
    params: dict[str, JsonValue]
    context: dict[str, JsonValue]
    run: dict[str, JsonValue]
    environment: dict[str, JsonValue]


class PolicyFixtureExpectation(StrictPolicyModel):
    """Describe the future effect and current condition expectations."""

    effect: PolicyEffect
    rule: PolicyRuleId
    failed_conditions: tuple[ConditionId, ...]


class PolicyFixture(StrictPolicyModel):
    """Represent one offline policy decision example."""

    name: str
    input: PolicyFixtureInput
    expect: PolicyFixtureExpectation


def load_policy_fixture(path: Path) -> PolicyFixture:
    """Load and validate one offline fixture document."""
    try:
        raw_fixture: object = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PolicyFixture.model_validate(raw_fixture)
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as error:
        raise InvalidPolicyFixtureError(path.name, str(error)) from error


def run_policy_fixture(bundle: PolicyBundle, fixture: PolicyFixture) -> DecisionResult:
    """Evaluate one fixture against a complete policy bundle."""
    decision_input = _decision_input(fixture.input)
    return PolicyEngine(bundle).evaluate(decision_input)


def _decision_input(fixture_input: PolicyFixtureInput) -> DecisionInput:
    return DecisionInput(
        principal=_parse_principal(fixture_input.principal),
        authority_chain=tuple(
            _parse_principal(principal) for principal in fixture_input.authority_chain
        ),
        tool=fixture_input.tool,
        parameters=fixture_input.params,
        context_provenance=fixture_input.context,
        run_metadata=fixture_input.run,
        environment=fixture_input.environment,
    )


def _parse_principal(value: FixturePrincipal) -> PolicyPrincipal:
    kind_value, separator, identifier = value.partition(":")
    if not separator or not identifier:
        message = "principal must use the kind:identifier form"
        raise InvalidPolicyFixtureError(str(value), message)
    try:
        kind = PrincipalKind(kind_value)
    except ValueError as error:
        message = f"unknown principal kind {kind_value!r}"
        raise InvalidPolicyFixtureError(str(value), message) from error
    return PolicyPrincipal(kind=kind, id=PrincipalSelectorId(identifier))
