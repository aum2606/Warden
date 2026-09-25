"""Broker verification, obligation, credential, and execution integration tests."""

import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from warden.broker.connectors import Connector, FakeGitHubConnector, GitHubConnector
from warden.broker.credentials import EnvironmentCredentialResolver, SqlAlchemyConnectionStore
from warden.broker.errors import (
    BrokerConfigurationError,
    CapabilityRejectedError,
    ConnectorInvocationError,
    CredentialResolutionError,
    UnsupportedObligationError,
)
from warden.broker.records import ExecutionRecord, ExecutionRepository, ExecutionStatus
from warden.broker.registry import fingerprint_registry
from warden.broker.service import Broker, BrokerDependencies, CapabilityVerification
from warden.broker.types import ConnectionProvider, CredentialReference
from warden.capability.canonicalization import fingerprint_parameters, fingerprint_value_digest
from warden.capability.records import CapabilityRecord
from warden.capability.rejections import InMemoryRejectionRecorder
from warden.capability.service import CapabilityMinter, CapabilityMintingAuthority
from warden.capability.signing import CapabilitySigner
from warden.capability.types import (
    CapabilityClaims,
    CapabilityId,
    CapabilityPrincipal,
    CapabilityToken,
    JsonValue,
    RejectionReason,
    RunId,
    ToolName,
    VerificationResult,
)
from warden.capability.verification import CapabilityVerifier
from warden.database import AsyncSessionFactory
from warden.identity.models import Connection, Organization
from warden.identity.models import PolicyBundle as StoredPolicyBundle
from warden.identity.types import PrincipalKind
from warden.policy.models import (
    FieldPath,
    PolicyDocument,
    PolicyEffect,
    PolicyEffectMap,
    PolicyMatch,
    PolicyObligation,
    PolicyRuleId,
    PrincipalMatch,
    PrincipalSelectorId,
)
from warden.policy.records import DecisionRecord
from warden.policy.types import DecisionId, PolicyBundle, SourceDigest, StepId

_ORG_ID = UUID("40000000-0000-4000-8000-000000000001")
_BUNDLE_ID = UUID("40000000-0000-4000-8000-000000000002")
_DECISION_ID = UUID("40000000-0000-4000-8000-000000000003")
_CAPABILITY_ID = CapabilityId(UUID("40000000-0000-4000-8000-000000000004"))
_RUN_ID = RunId(UUID("40000000-0000-4000-8000-000000000005"))
_STEP_ID = StepId(UUID("40000000-0000-4000-8000-000000000006"))
_CONNECTION_ID = UUID("40000000-0000-4000-8000-000000000007")
_ISSUED_AT = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
_VERIFY_AT = _ISSUED_AT + timedelta(seconds=1)
_SIGNING_KEY = b"broker-capability-signing-key-32-chars"
_TOOL = ToolName("github.issue.create")
_TOKEN_VALUE = "connector-secret-that-must-not-escape"
_ENVIRONMENT = {"TEST_GITHUB_TOKEN": _TOKEN_VALUE}


def _parameters(repo: str = "aum2606/Warden") -> dict[str, JsonValue]:
    return {
        "repo": repo,
        "title": "Broker-created issue",
        "body": "Full authorized evidence",
    }


def _bundle(*, redact_body: bool = False) -> PolicyBundle:
    obligations = (
        (
            PolicyObligation(
                redact=FieldPath("params.body"),
                unless="approved",
            ),
        )
        if redact_body
        else ()
    )
    rule = PolicyDocument(
        version=1,
        id=PolicyRuleId("github-issue-create"),
        description="Allow a broker test issue",
        priority=100,
        match=PolicyMatch(
            tool=_TOOL,
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
        obligations=obligations,
    )
    return PolicyBundle(rules=(rule,), source_digest=SourceDigest("f" * 64))


async def _seed_allow_decision(
    session_factory: AsyncSessionFactory,
    parameters: Mapping[str, JsonValue],
    *,
    credential_reference: str = "env:TEST_GITHUB_TOKEN",
) -> DecisionRecord:
    decision = DecisionRecord(
        id=_DECISION_ID,
        run_id=_RUN_ID,
        step_id=_STEP_ID,
        bundle_id=_BUNDLE_ID,
        effect=PolicyEffect.ALLOW,
        rule_id="github-issue-create",
        failed_condition_ids=[],
        inputs={
            "principal": "agent:ops-worker",
            "authority_chain": ["user:aum", "agent:orchestrator", "agent:ops-worker"],
            "tool": str(_TOOL),
            "params": dict(parameters),
            "context": {"min_trust": "internal"},
            "run": {"run_id": str(_RUN_ID)},
            "environment": {},
        },
    )
    async with session_factory() as session:
        session.add(Organization(id=_ORG_ID, name="Broker Test", settings={}))
        await session.flush()
        session.add(
            StoredPolicyBundle(
                id=_BUNDLE_ID,
                org_id=_ORG_ID,
                version="fixture",
                git_sha="0" * 40,
                source_digest="f" * 64,
            )
        )
        session.add(
            Connection(
                id=_CONNECTION_ID,
                org_id=_ORG_ID,
                provider="github",
                account_label="test",
                credential_ref=credential_reference,
                scopes=["issues:write", "metadata:read"],
                status="active",
            )
        )
        await session.flush()
        session.add(decision)
        await session.commit()
    return decision


async def _mint_token(
    session_factory: AsyncSessionFactory,
    connector: Connector,
    parameters: Mapping[str, JsonValue],
    *,
    redact_body: bool = False,
) -> tuple[CapabilityToken, CapabilityVerifier]:
    decision = await _seed_allow_decision(session_factory, parameters)
    registry = fingerprint_registry((connector,))
    signer = CapabilitySigner(_SIGNING_KEY)
    authority = CapabilityMintingAuthority(
        signer=signer,
        schemas=registry,
        policy_bundle=_bundle(redact_body=redact_body),
    )
    async with session_factory() as session:
        minted = await CapabilityMinter(
            session,
            authority,
            900,
            clock=lambda: _ISSUED_AT,
        ).mint(decision)
    verifier = CapabilityVerifier(
        session_factory,
        signer,
        registry,
        InMemoryRejectionRecorder(),
        clock=lambda: _VERIFY_AT,
    )
    return minted.token, verifier


def _broker(
    session_factory: AsyncSessionFactory,
    connector: Connector,
    verifier: CapabilityVerification,
    *,
    environment: Mapping[str, str] = _ENVIRONMENT,
) -> Broker:
    return Broker(
        (connector,),
        BrokerDependencies(
            verifier=verifier,
            connection_store=SqlAlchemyConnectionStore(session_factory),
            credential_resolver=EnvironmentCredentialResolver(environment),
            executions=ExecutionRepository(session_factory, clock=lambda: _VERIFY_AT),
        ),
    )


async def test_minted_allow_capability_creates_issue_through_fake_connector(
    session_factory: AsyncSessionFactory,
) -> None:
    """The Session 6 exit flow reaches GitHub only after consuming its capability."""
    connector = FakeGitHubConnector()
    parameters = _parameters()
    token, verifier = await _mint_token(session_factory, connector, parameters)

    result = await _broker(session_factory, connector, verifier).execute(
        token,
        _TOOL,
        parameters,
        _RUN_ID,
    )

    assert result.output["title"] == "Broker-created issue"
    assert connector.invocations[0].parameters == parameters
    async with session_factory() as session:
        capability = await session.scalar(select(CapabilityRecord))
        execution = await session.scalar(select(ExecutionRecord))
    assert capability is not None
    assert capability.consumed_at == _VERIFY_AT
    assert execution is not None
    assert execution.capability_id == capability.id
    assert execution.status is ExecutionStatus.SUCCEEDED
    assert execution.result_digest is not None


async def test_redaction_changes_only_recorded_parameters_and_keeps_canonical_digest(
    session_factory: AsyncSessionFactory,
) -> None:
    """Recording obligations never alter the action delivered to a connector."""
    connector = FakeGitHubConnector()
    parameters = _parameters()
    token, verifier = await _mint_token(
        session_factory,
        connector,
        parameters,
        redact_body=True,
    )

    await _broker(session_factory, connector, verifier).execute(
        token,
        _TOOL,
        parameters,
        _RUN_ID,
    )

    async with session_factory() as session:
        execution = await session.scalar(select(ExecutionRecord))
    assert connector.invocations[0].parameters["body"] == "Full authorized evidence"
    assert execution is not None
    assert execution.parameters["body"] == {
        "marker": "[REDACTED]",
        "digest": str(fingerprint_value_digest(parameters["body"], free_text=True)),
    }
    assert "Full authorized evidence" not in repr(execution.parameters)


class _RejectingVerifier:
    def __init__(self, reason: RejectionReason) -> None:
        self._reason = reason

    async def verify_and_consume(
        self,
        _token: CapabilityToken,
        _parameters: Mapping[str, JsonValue],
        _expected_run_id: RunId,
        _expected_tool: ToolName,
    ) -> VerificationResult:
        return VerificationResult(
            accepted=False,
            capability_id=None,
            rejection=self._reason,
            claims=None,
        )


@pytest.mark.parametrize("reason", list(RejectionReason))
async def test_broker_rejects_each_capability_verification_failure_before_connector(
    session_factory: AsyncSessionFactory,
    reason: RejectionReason,
) -> None:
    """Each ordered verifier failure prevents credentials, records, and invocation."""
    connector = FakeGitHubConnector()
    broker = _broker(session_factory, connector, _RejectingVerifier(reason))

    with pytest.raises(CapabilityRejectedError, match=reason.value):
        await broker.execute(
            CapabilityToken("rejected"),
            _TOOL,
            _parameters(),
            _RUN_ID,
        )

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(ExecutionRecord))
    assert connector.invocations == []
    assert count == 0


def _claims(obligations: tuple[dict[str, JsonValue], ...]) -> CapabilityClaims:
    connector = FakeGitHubConnector()
    registry = fingerprint_registry((connector,))
    return CapabilityClaims(
        cap_id=_CAPABILITY_ID,
        run_id=_RUN_ID,
        step_id=_STEP_ID,
        principal=CapabilityPrincipal("agent:ops-worker"),
        authority_chain=(CapabilityPrincipal("agent:ops-worker"),),
        tool=_TOOL,
        param_fingerprint=fingerprint_parameters(_TOOL, _parameters(), registry),
        decision_id=DecisionId(_DECISION_ID),
        obligations=obligations,
        issued_at=_ISSUED_AT,
        expires_at=_ISSUED_AT + timedelta(seconds=900),
        single_use=True,
    )


class _AcceptedVerifier:
    def __init__(self, claims: CapabilityClaims) -> None:
        self._claims = claims

    async def verify_and_consume(
        self,
        _token: CapabilityToken,
        _parameters: Mapping[str, JsonValue],
        _expected_run_id: RunId,
        _expected_tool: ToolName,
    ) -> VerificationResult:
        return VerificationResult(
            accepted=True,
            capability_id=self._claims.cap_id,
            rejection=None,
            claims=self._claims,
        )


async def test_unrecognized_obligation_denies_before_connector_invocation(
    session_factory: AsyncSessionFactory,
) -> None:
    """The broker never silently skips an obligation it cannot enforce."""
    connector = FakeGitHubConnector()
    broker = _broker(
        session_factory,
        connector,
        _AcceptedVerifier(_claims(({"rate_limit": 1},))),
    )

    with pytest.raises(UnsupportedObligationError, match="does not recognize"):
        await broker.execute(
            CapabilityToken("accepted"),
            _TOOL,
            _parameters(),
            _RUN_ID,
        )

    assert connector.invocations == []


class _LeakingConnector(FakeGitHubConnector):
    async def invoke(
        self,
        _tool: ToolName,
        _params: Mapping[str, JsonValue],
        credential: SecretStr,
    ) -> dict[str, JsonValue]:
        message = f"connector exposed {credential!s} {_TOKEN_VALUE}"
        raise RuntimeError(message)


async def test_connector_failure_is_sanitized_in_exception_and_execution_record(
    session_factory: AsyncSessionFactory,
) -> None:
    """Even a faulty connector cannot propagate credential material through errors."""
    connector = _LeakingConnector()
    parameters = _parameters()
    token, verifier = await _mint_token(session_factory, connector, parameters)

    with pytest.raises(ConnectorInvocationError) as captured:
        await _broker(session_factory, connector, verifier).execute(
            token,
            _TOOL,
            parameters,
            _RUN_ID,
        )

    async with session_factory() as session:
        execution = await session.scalar(select(ExecutionRecord))
    assert _TOKEN_VALUE not in str(captured.value)
    assert captured.value.__cause__ is None
    assert execution is not None
    assert execution.status is ExecutionStatus.FAILED
    assert execution.error == "connector invocation failed"
    assert _TOKEN_VALUE not in repr(execution.error)


@pytest.mark.parametrize("connection_count", [0, 2])
async def test_connection_lookup_requires_exactly_one_active_github_connection(
    session_factory: AsyncSessionFactory,
    connection_count: int,
) -> None:
    """Missing and ambiguous credential routing both fail closed."""
    async with session_factory() as session:
        session.add(Organization(id=_ORG_ID, name="Connection Test", settings={}))
        await session.flush()
        for index in range(connection_count):
            session.add(
                Connection(
                    org_id=_ORG_ID,
                    provider="github",
                    account_label=f"account-{index}",
                    credential_ref=f"env:GITHUB_TOKEN_{index}",
                    scopes=[],
                    status="active",
                )
            )
        await session.commit()

    with pytest.raises(BrokerConfigurationError, match="exactly one"):
        await SqlAlchemyConnectionStore(session_factory).active_reference(
            ConnectionProvider("github")
        )


def test_missing_environment_credential_names_reference_but_never_value() -> None:
    """Credential diagnostics may identify configuration but contain no secret."""
    resolver = EnvironmentCredentialResolver({})

    with pytest.raises(CredentialResolutionError, match="MISSING_GITHUB_TOKEN") as captured:
        resolver.resolve(CredentialReference("env:MISSING_GITHUB_TOKEN"))

    assert _TOKEN_VALUE not in str(captured.value)


async def test_execution_capability_foreign_key_is_non_nullable_in_database(
    session_factory: AsyncSessionFactory,
) -> None:
    """PostgreSQL cannot represent an execution without a capability."""
    column = ExecutionRecord.__table__.c.capability_id

    assert column.nullable is False
    assert {key.target_fullname for key in column.foreign_keys} == {"capabilities.id"}
    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    """
                    INSERT INTO executions (
                        id, capability_id, tool, parameters, started_at, status
                    ) VALUES (
                        :id, NULL, :tool, CAST(:parameters AS jsonb), :started_at, :status
                    )
                    """
                ),
                {
                    "id": UUID("40000000-0000-4000-8000-000000000099"),
                    "tool": str(_TOOL),
                    "parameters": "{}",
                    "started_at": _VERIFY_AT,
                    "status": ExecutionStatus.STARTED.value,
                },
            )


@pytest.mark.live
async def test_live_configured_broker_creates_issue_in_real_repository(
    session_factory: AsyncSessionFactory,
) -> None:
    """Opt-in smoke test runs the same minted-capability flow against GitHub."""
    credential = os.environ.get("WARDEN_LIVE_GITHUB_TOKEN")
    repository = os.environ.get("WARDEN_LIVE_GITHUB_REPOSITORY")
    if credential is None and repository is None:
        pytest.skip("live GitHub credential and repository are not configured")
    assert credential is not None
    assert repository is not None
    parameters = _parameters(repository)
    async with httpx.AsyncClient(base_url="https://api.github.com", timeout=30.0) as client:
        connector = GitHubConnector(client)
        decision = await _seed_allow_decision(
            session_factory,
            parameters,
            credential_reference="env:WARDEN_LIVE_GITHUB_TOKEN",
        )
        registry = fingerprint_registry((connector,))
        signer = CapabilitySigner(_SIGNING_KEY)
        authority = CapabilityMintingAuthority(signer, registry, _bundle())
        async with session_factory() as session:
            minted = await CapabilityMinter(
                session,
                authority,
                900,
                clock=lambda: _ISSUED_AT,
            ).mint(decision)
        verifier = CapabilityVerifier(
            session_factory,
            signer,
            registry,
            InMemoryRejectionRecorder(),
            clock=lambda: _VERIFY_AT,
        )
        result = await _broker(
            session_factory,
            connector,
            verifier,
            environment=os.environ,
        ).execute(minted.token, _TOOL, parameters, _RUN_ID)

    assert result.output["html_url"]
