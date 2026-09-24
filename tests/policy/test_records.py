"""Append-only decision recording and database permission tests."""

from collections.abc import Callable
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from warden.config import Settings
from warden.database import AsyncSessionFactory, create_database_engine
from warden.identity.models import Organization
from warden.identity.models import PolicyBundle as StoredPolicyBundle
from warden.identity.types import PrincipalKind
from warden.policy.engine import DecisionResult, PolicyEngine, RuleEvaluation
from warden.policy.evaluator import ConditionResult
from warden.policy.models import (
    ConditionId,
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
from warden.policy.records import (
    DecisionCoordinates,
    DecisionRecord,
    DecisionRepository,
    evaluate_and_record,
)
from warden.policy.types import (
    DecisionInput,
    PolicyBundle,
    PolicyBundleId,
    PolicyPrincipal,
    RunId,
    SourceDigest,
    StepId,
)

_ORG_ID = UUID("10000000-0000-4000-8000-000000000001")
_BUNDLE_ID = PolicyBundleId(UUID("10000000-0000-4000-8000-000000000002"))
_RUN_ID = RunId(UUID("10000000-0000-4000-8000-000000000003"))
_STEP_ID = StepId(UUID("10000000-0000-4000-8000-000000000004"))


class _StageError(Exception):
    """Represent an injected policy-stage failure."""


def _rule() -> PolicyDocument:
    return PolicyDocument(
        version=1,
        id=PolicyRuleId("record-rule"),
        description="Rule used to exercise decision recording",
        priority=100,
        match=PolicyMatch(
            tool=ToolName("test.record"),
            principal=PrincipalMatch(
                kind=PrincipalKind.AGENT,
                id=(PrincipalSelectorId("ops-worker"),),
            ),
        ),
        conditions=(),
        effect=PolicyEffectMap(
            when_all_true=PolicyEffect.ALLOW,
            combine="most_restrictive",
        ),
        escalation=None,
        obligations=(),
    )


def _bundle() -> PolicyBundle:
    return PolicyBundle(rules=(_rule(),), source_digest=SourceDigest("f" * 64))


def _input() -> DecisionInput:
    principal = PolicyPrincipal(PrincipalKind.AGENT, PrincipalSelectorId("ops-worker"))
    return DecisionInput(
        principal=principal,
        authority_chain=(
            PolicyPrincipal(PrincipalKind.USER, PrincipalSelectorId("aum")),
            principal,
        ),
        tool=ToolName("test.record"),
        parameters={"target": "example"},
        context_provenance={"min_trust": "internal"},
        run_metadata={"run_id": str(_RUN_ID), "prior_denials": 0},
        environment={"current_time": "2026-09-24T09:00:00Z"},
    )


async def _add_bundle(session_factory: AsyncSessionFactory) -> None:
    async with session_factory() as session:
        session.add(Organization(id=_ORG_ID, name="Policy Test", settings={}))
        session.add(
            StoredPolicyBundle(
                id=_BUNDLE_ID,
                org_id=_ORG_ID,
                version="fixture",
                git_sha="0" * 40,
                source_digest="f" * 64,
            )
        )
        await session.commit()


async def test_repository_stores_effect_rule_failures_inputs_and_bundle(
    session_factory: AsyncSessionFactory,
) -> None:
    """A recorded decision contains every field required for replay."""
    await _add_bundle(session_factory)
    decision_input = _input()
    result = DecisionResult(
        effect=PolicyEffect.DENY,
        rule_id=PolicyRuleId("record-rule"),
        failed_condition_ids=(ConditionId("blocked"),),
    )
    async with session_factory() as session:
        record = await DecisionRepository(session).append(
            run_id=_RUN_ID,
            step_id=_STEP_ID,
            bundle_id=_BUNDLE_ID,
            decision_input=decision_input,
            result=result,
        )
    async with session_factory() as session:
        stored = await session.get(DecisionRecord, record.id)

    assert stored is not None
    assert stored.effect is PolicyEffect.DENY
    assert stored.rule_id == "record-rule"
    assert stored.failed_condition_ids == ["blocked"]
    assert stored.bundle_id == _BUNDLE_ID
    assert stored.inputs == {
        "principal": "agent:ops-worker",
        "authority_chain": ["user:aum", "agent:ops-worker"],
        "tool": "test.record",
        "params": {"target": "example"},
        "context": {"min_trust": "internal"},
        "run": {"run_id": str(_RUN_ID), "prior_denials": 0},
        "environment": {"current_time": "2026-09-24T09:00:00Z"},
    }


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
    "engine_factory",
    [
        pytest.param(
            lambda bundle: PolicyEngine(bundle, matcher=_raise_matcher_error),
            id="matcher",
        ),
        pytest.param(
            lambda bundle: PolicyEngine(bundle, condition_evaluator=_raise_evaluator_error),
            id="evaluator",
        ),
        pytest.param(
            lambda bundle: PolicyEngine(bundle, combiner=_raise_combiner_error),
            id="combiner",
        ),
    ],
)
async def test_evaluation_stage_failure_records_a_denial(
    session_factory: AsyncSessionFactory,
    engine_factory: Callable[[PolicyBundle], PolicyEngine],
) -> None:
    """Every raised decision-stage failure is durably denied before returning."""
    await _add_bundle(session_factory)
    async with session_factory() as session:
        record = await evaluate_and_record(
            engine_factory(_bundle()),
            DecisionRepository(session),
            DecisionCoordinates(_RUN_ID, _STEP_ID, _BUNDLE_ID),
            _input(),
        )
    async with session_factory() as session:
        decision_count = await session.scalar(select(func.count()).select_from(DecisionRecord))

    assert record.effect is PolicyEffect.DENY
    assert record.failed_condition_ids == ["evaluation-error"]
    assert decision_count == 1


async def _configure_application_role(database_engine: AsyncEngine) -> None:
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = 'warden_app'
                    ) THEN
                        CREATE ROLE warden_app NOLOGIN;
                    END IF;
                END
                $$
                """
            )
        )
        await connection.execute(text("GRANT warden_app TO CURRENT_USER"))
        await connection.execute(text("GRANT USAGE ON SCHEMA public TO warden_app"))
        await connection.execute(text("GRANT SELECT, INSERT ON decisions TO warden_app"))
        await connection.execute(text("REVOKE UPDATE ON decisions FROM warden_app"))


async def test_application_role_cannot_modify_decision_at_database_level(
    settings: Settings,
    database_engine: AsyncEngine,
    session_factory: AsyncSessionFactory,
) -> None:
    """PostgreSQL rejects mutation even when an application query attempts it."""
    await _add_bundle(session_factory)
    async with session_factory() as session:
        await DecisionRepository(session).append(
            run_id=_RUN_ID,
            step_id=_STEP_ID,
            bundle_id=_BUNDLE_ID,
            decision_input=_input(),
            result=DecisionResult(PolicyEffect.ALLOW, PolicyRuleId("record-rule"), ()),
        )
    await _configure_application_role(database_engine)
    restricted_engine = create_database_engine(settings.database_url, "warden_app")
    try:
        async with restricted_engine.connect() as connection:
            with pytest.raises(DBAPIError, match="permission denied"):
                await connection.execute(text("UPDATE decisions SET effect = 'deny'"))
        async with restricted_engine.connect() as connection:
            with pytest.raises(DBAPIError, match="permission denied"):
                await connection.execute(text("DELETE FROM decisions"))
    finally:
        await restricted_engine.dispose()
