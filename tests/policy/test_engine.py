"""Policy effect resolution and fail-closed engine tests."""

from collections.abc import Callable

import pytest

from warden.identity.types import PrincipalKind
from warden.policy.engine import (
    DecisionResult,
    PolicyEngine,
    RuleEvaluation,
    combine_rule_effects,
    evaluate_rule,
)
from warden.policy.evaluator import ConditionResult
from warden.policy.models import (
    ConditionId,
    Expression,
    PolicyCondition,
    PolicyDocument,
    PolicyEffect,
    PolicyEffectMap,
    PolicyMatch,
    PolicyRuleId,
    PrincipalMatch,
    PrincipalSelectorId,
    ToolName,
)
from warden.policy.types import DecisionInput, PolicyBundle, PolicyPrincipal, SourceDigest


class _StageError(Exception):
    pass


def _condition(
    condition_id: str,
    expression: str,
    on_fail: PolicyEffect,
) -> PolicyCondition:
    return PolicyCondition(
        id=ConditionId(condition_id),
        expr=Expression(expression),
        on_fail=on_fail,
    )


def _rule(
    rule_id: str,
    priority: int,
    *conditions: PolicyCondition,
) -> PolicyDocument:
    return PolicyDocument(
        version=1,
        id=PolicyRuleId(rule_id),
        description=f"Rule {rule_id}",
        priority=priority,
        match=PolicyMatch(
            tool=ToolName("test.action"),
            principal=PrincipalMatch(
                kind=PrincipalKind.AGENT,
                id=(PrincipalSelectorId("ops-worker"),),
            ),
        ),
        conditions=conditions,
        effect=PolicyEffectMap(
            when_all_true=PolicyEffect.ALLOW,
            combine="most_restrictive",
        ),
        escalation=None,
        obligations=(),
    )


def _input() -> DecisionInput:
    principal = PolicyPrincipal(PrincipalKind.AGENT, PrincipalSelectorId("ops-worker"))
    return DecisionInput(
        principal=principal,
        authority_chain=(principal,),
        tool=ToolName("test.action"),
        parameters={"allowed": False},
        context_provenance={},
        run_metadata={},
        environment={},
    )


def _bundle(*rules: PolicyDocument) -> PolicyBundle:
    return PolicyBundle(rules=rules, source_digest=SourceDigest("digest"))


def test_rule_allows_when_every_condition_passes() -> None:
    """The successful rule effect is allow when no failure effect applies."""
    rule = _rule(
        "allow-rule",
        100,
        _condition("allowed", "params.allowed == false", PolicyEffect.DENY),
    )

    result = evaluate_rule(rule, _input())

    assert result.effect is PolicyEffect.ALLOW
    assert result.failed_condition_ids == ()


def test_rule_uses_failed_condition_effect() -> None:
    """One failed condition contributes its declared effect."""
    rule = _rule(
        "escalate-rule",
        100,
        _condition("review", "params.allowed == true", PolicyEffect.ESCALATE),
    )

    result = evaluate_rule(rule, _input())

    assert result.effect is PolicyEffect.ESCALATE
    assert result.failed_condition_ids == (ConditionId("review"),)


def test_rule_combines_failed_conditions_by_most_restrictive_effect() -> None:
    """A deny failure dominates an escalation regardless of failure count."""
    rule = _rule(
        "mixed-rule",
        100,
        _condition("review", "params.allowed == true", PolicyEffect.ESCALATE),
        _condition("block", "params.allowed == true", PolicyEffect.DENY),
    )

    result = evaluate_rule(rule, _input())

    assert result.effect is PolicyEffect.DENY
    assert result.failed_condition_ids == (ConditionId("review"), ConditionId("block"))


def test_expression_error_denies_even_when_condition_would_escalate() -> None:
    """A malformed condition cannot turn an evaluation fault into approval work."""
    rule = _rule(
        "broken-rule",
        100,
        _condition("broken", "params.allowed + true", PolicyEffect.ESCALATE),
    )

    result = evaluate_rule(rule, _input())

    assert result.effect is PolicyEffect.DENY
    assert result.failed_condition_ids == (ConditionId("broken"),)


def test_higher_priority_rule_wins_over_more_restrictive_lower_priority_rule() -> None:
    """Priority is resolved before effect restrictiveness."""
    result = combine_rule_effects(
        (
            RuleEvaluation(PolicyRuleId("lower-deny"), 10, PolicyEffect.DENY, ()),
            RuleEvaluation(PolicyRuleId("higher-allow"), 20, PolicyEffect.ALLOW, ()),
        )
    )

    assert result.effect is PolicyEffect.ALLOW
    assert result.rule_id == PolicyRuleId("higher-allow")


def test_equal_priority_conflict_uses_most_restrictive_effect() -> None:
    """A same-priority deny dominates escalation and allow outcomes."""
    result = combine_rule_effects(
        (
            RuleEvaluation(PolicyRuleId("allow"), 20, PolicyEffect.ALLOW, ()),
            RuleEvaluation(PolicyRuleId("escalate"), 20, PolicyEffect.ESCALATE, ()),
            RuleEvaluation(PolicyRuleId("deny"), 20, PolicyEffect.DENY, ()),
        )
    )

    assert result.effect is PolicyEffect.DENY
    assert result.rule_id == PolicyRuleId("deny")


def test_equal_priority_and_effect_tie_uses_rule_id() -> None:
    """Equivalent outcomes select a stable rule identifier."""
    result = combine_rule_effects(
        (
            RuleEvaluation(PolicyRuleId("z-rule"), 20, PolicyEffect.DENY, ()),
            RuleEvaluation(PolicyRuleId("a-rule"), 20, PolicyEffect.DENY, ()),
        )
    )

    assert result.rule_id == PolicyRuleId("a-rule")


def _raise_matcher_error(
    _bundle_value: PolicyBundle,
    _tool: ToolName,
    _principal: PolicyPrincipal,
) -> tuple[PolicyDocument, ...]:
    raise _StageError


def _raise_evaluator_error(
    _conditions: tuple[PolicyCondition, ...],
    _decision_input: DecisionInput,
) -> tuple[ConditionResult, ...]:
    raise _StageError


def _raise_combiner_error(
    _evaluations: tuple[RuleEvaluation, ...],
) -> DecisionResult:
    raise _StageError


@pytest.mark.parametrize(
    ("stage", "engine_factory", "expected_rule"),
    [
        (
            "matcher",
            lambda bundle: PolicyEngine(bundle, matcher=_raise_matcher_error),
            PolicyRuleId("default-deny"),
        ),
        (
            "evaluator",
            lambda bundle: PolicyEngine(bundle, condition_evaluator=_raise_evaluator_error),
            PolicyRuleId("rule"),
        ),
        (
            "combiner",
            lambda bundle: PolicyEngine(bundle, combiner=_raise_combiner_error),
            PolicyRuleId("rule"),
        ),
    ],
)
def test_engine_denies_when_evaluation_stage_raises(
    stage: str,
    engine_factory: Callable[[PolicyBundle], PolicyEngine],
    expected_rule: PolicyRuleId,
) -> None:
    """Matcher, evaluator, and combiner faults all produce named denials."""
    rule = _rule("rule", 100)

    result = engine_factory(_bundle(rule)).evaluate(_input())

    assert stage
    assert result == DecisionResult(
        effect=PolicyEffect.DENY,
        rule_id=expected_rule,
        failed_condition_ids=(ConditionId("evaluation-error"),),
    )
