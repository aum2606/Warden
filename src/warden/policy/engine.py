"""Policy rule evaluation, effect combination, and fail-closed decisions."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from .errors import PolicyEvaluationError
from .evaluator import ConditionResult, evaluate_conditions
from .matcher import match_rules
from .models import (
    ConditionId,
    PolicyCondition,
    PolicyDocument,
    PolicyEffect,
    PolicyRuleId,
    ToolName,
)
from .types import DecisionInput, PolicyBundle, PolicyPrincipal

_DEFAULT_DENY_RULE_ID: Final = PolicyRuleId("default-deny")
_EVALUATION_ERROR_ID: Final = ConditionId("evaluation-error")
_EFFECT_RANK: Final = {
    PolicyEffect.ALLOW: 0,
    PolicyEffect.ESCALATE: 1,
    PolicyEffect.DENY: 2,
}

type RuleMatcher = Callable[
    [PolicyBundle, ToolName, PolicyPrincipal],
    tuple[PolicyDocument, ...],
]
type ConditionEvaluator = Callable[
    [tuple[PolicyCondition, ...], DecisionInput],
    tuple[ConditionResult, ...],
]
type EffectCombiner = Callable[[tuple["RuleEvaluation", ...]], "DecisionResult"]


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """Capture one matching rule's effect and condition evidence."""

    rule_id: PolicyRuleId
    priority: int
    effect: PolicyEffect
    failed_condition_ids: tuple[ConditionId, ...]


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Return the selected policy outcome and replayable rule evidence."""

    effect: PolicyEffect
    rule_id: PolicyRuleId
    failed_condition_ids: tuple[ConditionId, ...]


class PolicyEngine:
    """Evaluate a bundle while converting every stage failure into a denial."""

    def __init__(
        self,
        bundle: PolicyBundle,
        *,
        matcher: RuleMatcher = match_rules,
        condition_evaluator: ConditionEvaluator = evaluate_conditions,
        combiner: EffectCombiner | None = None,
    ) -> None:
        """Bind an atomically loaded bundle and replaceable evaluation stages."""
        self._bundle = bundle
        self._matcher = matcher
        self._condition_evaluator = condition_evaluator
        self._combiner = combiner or combine_rule_effects

    @property
    def bundle(self) -> PolicyBundle:
        """Expose the immutable bundle used for decisions and API inspection."""
        return self._bundle

    def evaluate(self, decision_input: DecisionInput) -> DecisionResult:
        """Evaluate an input and return a denial if any decision stage raises."""
        rule_id = _DEFAULT_DENY_RULE_ID
        try:
            rules = self._matcher(
                self._bundle,
                decision_input.tool,
                decision_input.principal,
            )
            _require_matching_rules(rules)
            rule_id = rules[0].id
            evaluations = tuple(
                evaluate_rule(rule, decision_input, self._condition_evaluator) for rule in rules
            )
            return self._combiner(evaluations)
        except Exception:  # noqa: BLE001 - every unexpected decision fault must deny.
            return DecisionResult(
                effect=PolicyEffect.DENY,
                rule_id=rule_id,
                failed_condition_ids=(_EVALUATION_ERROR_ID,),
            )


def _require_matching_rules(rules: tuple[PolicyDocument, ...]) -> None:
    if not rules:
        message = "policy bundle produced no matching rule"
        raise PolicyEvaluationError(message)


def evaluate_rule(
    rule: PolicyDocument,
    decision_input: DecisionInput,
    condition_evaluator: ConditionEvaluator = evaluate_conditions,
) -> RuleEvaluation:
    """Resolve one rule from its independently annotated failed conditions."""
    results = condition_evaluator(rule.conditions, decision_input)
    if len(results) != len(rule.conditions):
        message = "condition evaluator returned an incomplete result set"
        raise PolicyEvaluationError(message)

    failed_pairs = tuple(
        (condition, result)
        for condition, result in zip(rule.conditions, results, strict=True)
        if not result.passed
    )
    failed_ids = tuple(result.id for _, result in failed_pairs)
    if any(result.error for _, result in failed_pairs):
        effect = PolicyEffect.DENY
    elif not failed_pairs:
        effect = PolicyEffect.ALLOW
    else:
        effect = max(
            (PolicyEffect(condition.on_fail) for condition, _ in failed_pairs),
            key=_EFFECT_RANK.__getitem__,
        )
    return RuleEvaluation(
        rule_id=rule.id,
        priority=rule.priority,
        effect=effect,
        failed_condition_ids=failed_ids,
    )


def combine_rule_effects(evaluations: tuple[RuleEvaluation, ...]) -> DecisionResult:
    """Select the highest priority and most restrictive deterministic outcome."""
    if not evaluations:
        message = "cannot combine an empty rule evaluation set"
        raise PolicyEvaluationError(message)
    highest_priority = max(evaluation.priority for evaluation in evaluations)
    highest = tuple(
        evaluation for evaluation in evaluations if evaluation.priority == highest_priority
    )
    most_restrictive = max(_EFFECT_RANK[evaluation.effect] for evaluation in highest)
    finalists = tuple(
        evaluation for evaluation in highest if _EFFECT_RANK[evaluation.effect] == most_restrictive
    )
    selected = min(finalists, key=lambda evaluation: str(evaluation.rule_id))
    return DecisionResult(
        effect=selected.effect,
        rule_id=selected.rule_id,
        failed_condition_ids=selected.failed_condition_ids,
    )
