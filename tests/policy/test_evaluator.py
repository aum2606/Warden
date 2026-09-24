"""Pure policy condition evaluator tests."""

import ast
from enum import StrEnum
from pathlib import Path

import pytest

from warden.identity.types import PrincipalKind
from warden.policy.evaluator import ConditionResult, evaluate_condition, evaluate_conditions
from warden.policy.models import (
    ConditionId,
    Expression,
    PolicyCondition,
    PolicyEffect,
    PrincipalSelectorId,
    ToolName,
)
from warden.policy.types import DecisionInput, JsonValue, PolicyPrincipal

_EVALUATOR_PATH = Path("src/warden/policy/evaluator.py")
_FORBIDDEN_IMPORTS = frozenset(
    {
        "asyncio",
        "datetime",
        "httpx",
        "os",
        "pathlib",
        "random",
        "requests",
        "socket",
        "sqlalchemy",
        "time",
        "urllib",
    },
)
_FORBIDDEN_CALLS = frozenset({"__import__", "eval", "exec", "open"})


class _ExpectedResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"


def _input(
    *,
    parameters: dict[str, JsonValue] | None = None,
    context: dict[str, JsonValue] | None = None,
    run: dict[str, JsonValue] | None = None,
    environment: dict[str, JsonValue] | None = None,
) -> DecisionInput:
    principal = PolicyPrincipal(PrincipalKind.AGENT, PrincipalSelectorId("ops-worker"))
    return DecisionInput(
        principal=principal,
        authority_chain=(principal,),
        tool=ToolName("test.action"),
        parameters=parameters or {},
        context_provenance=context or {},
        run_metadata=run or {},
        environment=environment or {},
    )


def _condition(expression: str, condition_id: str = "condition") -> PolicyCondition:
    return PolicyCondition(
        id=ConditionId(condition_id),
        expr=Expression(expression),
        on_fail=PolicyEffect.DENY,
    )


@pytest.mark.parametrize(
    ("expression", "parameters", "context", "expected"),
    [
        ('params.name == "warden"', {"name": "warden"}, {}, _ExpectedResult.PASS),
        ('params.name != "other"', {"name": "warden"}, {}, _ExpectedResult.PASS),
        ("params.count < 3", {"count": 2}, {}, _ExpectedResult.PASS),
        ("params.count <= 3", {"count": 3}, {}, _ExpectedResult.PASS),
        ("params.count > 3", {"count": 4}, {}, _ExpectedResult.PASS),
        ("params.count >= 3", {"count": 3}, {}, _ExpectedResult.PASS),
        (
            'params.email endsWith "@acme.example"',
            {"email": "a@acme.example"},
            {},
            _ExpectedResult.PASS,
        ),
        (
            'params.scope in ["run", "agent"]',
            {"scope": "run"},
            {},
            _ExpectedResult.PASS,
        ),
        ("params.value in [1]", {"value": True}, {}, _ExpectedResult.FAIL),
        (
            'context.min_trust >= "internal"',
            {},
            {"min_trust": "trusted"},
            _ExpectedResult.PASS,
        ),
        (
            'context.min_trust >= "internal"',
            {},
            {"min_trust": "untrusted"},
            _ExpectedResult.FAIL,
        ),
        (
            'all(params.to, {. endsWith "@acme.example"})',
            {"to": ["a@acme.example", "b@acme.example"]},
            {},
            _ExpectedResult.PASS,
        ),
        (
            'all(params.to, {. endsWith "@acme.example"})',
            {"to": ["a@acme.example", "b@external.example"]},
            {},
            _ExpectedResult.FAIL,
        ),
    ],
)
def test_evaluator_supports_allowlisted_comparisons(
    expression: str,
    parameters: dict[str, JsonValue],
    context: dict[str, JsonValue],
    expected: _ExpectedResult,
) -> None:
    """Each comparison form evaluates against only supplied input data."""
    result = evaluate_condition(
        _condition(expression), _input(parameters=parameters, context=context)
    )

    assert result.passed is (expected is _ExpectedResult.PASS)


def test_evaluator_supports_boolean_composition_and_parentheses() -> None:
    """Boolean operators have explicit precedence and short-circuit semantics."""
    expression = "(params.count >= 1 and params.count < 3) or not context.requires_review == true"

    result = evaluate_condition(
        _condition(expression),
        _input(parameters={"count": 2}, context={"requires_review": True}),
    )

    assert result.passed is True


def test_evaluator_reads_injected_time_as_data() -> None:
    """Time-dependent conditions receive time through the decision input only."""
    result = evaluate_condition(
        _condition('environment.current_time == "2026-09-24T09:00:00Z"'),
        _input(environment={"current_time": "2026-09-24T09:00:00Z"}),
    )

    assert result.passed is True


@pytest.mark.parametrize(
    "expression",
    [
        "params.missing == true",
        "params.count endsWith 3",
        "all(params.count, {. == 1})",
        "params.count + 1 == 2",
        "params.count",
    ],
)
def test_evaluator_fails_closed_for_missing_invalid_or_wrongly_typed_expressions(
    expression: str,
) -> None:
    """Every expected language failure becomes a failed condition."""
    result = evaluate_condition(
        _condition(expression),
        _input(parameters={"count": 1}),
    )

    assert result.passed is False


def test_evaluator_returns_each_condition_id_and_result_in_document_order() -> None:
    """Decision recording can identify every condition that failed."""
    conditions = (
        _condition("params.count <= 3", "size-bound"),
        _condition('context.min_trust >= "internal"', "clean-provenance"),
    )

    results = evaluate_conditions(
        conditions,
        _input(parameters={"count": 4}, context={"min_trust": "trusted"}),
    )

    assert results == (
        ConditionResult(ConditionId("size-bound"), passed=False),
        ConditionResult(ConditionId("clean-provenance"), passed=True),
    )


def test_evaluator_is_identical_across_repeated_runs_with_same_input() -> None:
    """Repeated evaluation cannot observe a clock, randomness, or external state."""
    condition = _condition('context.min_trust >= "internal" and params.count <= 3')
    decision_input = _input(parameters={"count": 3}, context={"min_trust": "internal"})

    first = evaluate_condition(condition, decision_input)
    repeated = tuple(evaluate_condition(condition, decision_input) for _ in range(20))

    assert all(result == first for result in repeated)


def test_evaluator_module_has_no_io_clock_randomness_or_dynamic_execution_access() -> None:
    """The evaluator's imports and calls exclude ambient or executable capabilities."""
    tree = ast.parse(_EVALUATOR_PATH.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)

    assert imported_roots.isdisjoint(_FORBIDDEN_IMPORTS)
    assert called_names.isdisjoint(_FORBIDDEN_CALLS)
