"""Capability minting, ordered verification, and atomic consumption tests."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from warden.capability.canonicalization import DEFAULT_FINGERPRINT_SCHEMAS
from warden.capability.errors import (
    CapabilityMintingError,
    RejectionRecordingError,
    UnregisteredToolError,
)
from warden.capability.records import CapabilityRecord
from warden.capability.rejections import InMemoryRejectionRecorder
from warden.capability.service import CapabilityMinter, CapabilityMintingAuthority
from warden.capability.signing import CapabilitySigner
from warden.capability.types import CapabilityRejection, CapabilityToken, RejectionReason
from warden.capability.verification import CapabilityVerifier
from warden.config import Settings
from warden.database import AsyncSessionFactory, create_database_engine
from warden.identity.models import Organization
from warden.identity.models import PolicyBundle as StoredPolicyBundle
from warden.policy.loader import load_policy_bundle
from warden.policy.models import PolicyEffect, ToolName
from warden.policy.records import DecisionRecord
from warden.policy.types import JsonValue, RunId

_ORG_ID = UUID("30000000-0000-4000-8000-000000000001")
_BUNDLE_ID = UUID("30000000-0000-4000-8000-000000000002")
_DECISION_ID = UUID("30000000-0000-4000-8000-000000000003")
_RUN_ID = RunId(UUID("30000000-0000-4000-8000-000000000004"))
_OTHER_RUN_ID = RunId(UUID("30000000-0000-4000-8000-000000000005"))
_STEP_ID = UUID("30000000-0000-4000-8000-000000000006")
_ISSUED_AT = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
_VERIFY_AT = _ISSUED_AT + timedelta(seconds=1)
_SIGNING_KEY = b"test-capability-lifecycle-signing-key"
_GMAIL_TOOL = ToolName("gmail.send")
_GITHUB_TOOL = ToolName("github.issue.create")


def _gmail_parameters(recipient: str = "reviewer@acme.example") -> dict[str, JsonValue]:
    return {
        "to": [recipient],
        "subject": "Review evidence",
        "body": "The supporting evidence",
        "attachment_count": 1,
    }


async def _store_decision(
    session_factory: AsyncSessionFactory,
    *,
    effect: PolicyEffect = PolicyEffect.ALLOW,
    tool: ToolName = _GMAIL_TOOL,
    parameters: Mapping[str, JsonValue] | None = None,
    rule_id: str = "gmail-external-send",
) -> DecisionRecord:
    decision = DecisionRecord(
        id=_DECISION_ID,
        run_id=_RUN_ID,
        step_id=_STEP_ID,
        bundle_id=_BUNDLE_ID,
        effect=effect,
        rule_id=rule_id,
        failed_condition_ids=[],
        inputs={
            "principal": "agent:ops-worker",
            "authority_chain": ["user:aum", "agent:orchestrator", "agent:ops-worker"],
            "tool": str(tool),
            "params": dict(parameters or _gmail_parameters()),
            "context": {"min_trust": "internal"},
            "run": {"run_id": str(_RUN_ID)},
            "environment": {},
        },
    )
    async with session_factory() as session:
        session.add(Organization(id=_ORG_ID, name="Capability Test", settings={}))
        session.add(
            StoredPolicyBundle(
                id=_BUNDLE_ID,
                org_id=_ORG_ID,
                version="fixture",
                git_sha="0" * 40,
                source_digest="f" * 64,
            )
        )
        session.add(decision)
        await session.commit()
    return decision


async def _mint(
    session_factory: AsyncSessionFactory,
    *,
    ttl_seconds: int = 900,
) -> tuple[CapabilityToken, CapabilityRecord]:
    decision = await _store_decision(session_factory)
    signer = CapabilitySigner(_SIGNING_KEY)
    authority = CapabilityMintingAuthority(
        signer=signer,
        schemas=DEFAULT_FINGERPRINT_SCHEMAS,
        policy_bundle=load_policy_bundle(Path("policies")),
    )
    async with session_factory() as session:
        minted = await CapabilityMinter(
            session,
            authority,
            ttl_seconds,
            clock=lambda: _ISSUED_AT,
        ).mint(decision)
    async with session_factory() as session:
        record = await session.scalar(select(CapabilityRecord))
    assert record is not None
    return minted.token, record


def _verifier(
    session_factory: AsyncSessionFactory,
    recorder: InMemoryRejectionRecorder,
    at: datetime = _VERIFY_AT,
) -> CapabilityVerifier:
    return CapabilityVerifier(
        session_factory,
        CapabilitySigner(_SIGNING_KEY),
        DEFAULT_FINGERPRINT_SCHEMAS,
        recorder,
        clock=lambda: at,
    )


async def test_minting_persists_exact_allow_claims_and_policy_obligations(
    session_factory: AsyncSessionFactory,
) -> None:
    """An allow decision produces one persisted, signed, parameter-bound capability."""
    token, record = await _mint(session_factory)
    claims = CapabilitySigner(_SIGNING_KEY).verify(token)

    assert claims.cap_id == record.id
    assert claims.decision_id == _DECISION_ID
    assert claims.run_id == _RUN_ID
    assert claims.step_id == _STEP_ID
    assert claims.principal == "agent:ops-worker"
    assert claims.authority_chain[-1] == "agent:ops-worker"
    assert claims.tool == _GMAIL_TOOL
    assert claims.obligations == ({"redact": "params.body", "unless": "approved"},)
    assert claims.expires_at == _ISSUED_AT + timedelta(seconds=900)
    assert claims.single_use is True
    assert record.consumed_at is None


async def test_minting_rejects_a_non_allow_decision(
    session_factory: AsyncSessionFactory,
) -> None:
    """Deny and escalation decisions cannot create execution authority."""
    decision = await _store_decision(session_factory, effect=PolicyEffect.DENY)
    authority = CapabilityMintingAuthority(
        signer=CapabilitySigner(_SIGNING_KEY),
        schemas=DEFAULT_FINGERPRINT_SCHEMAS,
        policy_bundle=load_policy_bundle(Path("policies")),
    )
    async with session_factory() as session:
        with pytest.raises(CapabilityMintingError, match="only for allow"):
            await CapabilityMinter(session, authority, 900).mint(decision)


async def test_minting_fails_closed_for_an_unregistered_tool(
    session_factory: AsyncSessionFactory,
) -> None:
    """No inferred or catch-all fingerprint schema can authorize a new tool."""
    decision = await _store_decision(
        session_factory,
        tool=ToolName("unknown.write"),
        parameters={"target": "production"},
        rule_id="default-deny",
    )
    authority = CapabilityMintingAuthority(
        signer=CapabilitySigner(_SIGNING_KEY),
        schemas=DEFAULT_FINGERPRINT_SCHEMAS,
        policy_bundle=load_policy_bundle(Path("policies")),
    )
    async with session_factory() as session:
        with pytest.raises(UnregisteredToolError, match="no fingerprint schema"):
            await CapabilityMinter(session, authority, 900).mint(decision)


async def test_changed_recipient_fails_fingerprint_and_is_recorded(
    session_factory: AsyncSessionFactory,
) -> None:
    """Changing a recipient invalidates the approval before execution."""
    token, record = await _mint(session_factory)
    recorder = InMemoryRejectionRecorder()

    result = await _verifier(session_factory, recorder).verify_and_consume(
        token,
        _gmail_parameters("outside@example.net"),
        _RUN_ID,
        _GMAIL_TOOL,
    )

    assert result.rejection is RejectionReason.FINGERPRINT
    assert recorder.rejections[0].reason is RejectionReason.FINGERPRINT
    async with session_factory() as session:
        stored = await session.get(CapabilityRecord, record.id)
    assert stored is not None
    assert stored.consumed_at is None


async def test_expired_capability_fails_before_consumption(
    session_factory: AsyncSessionFactory,
) -> None:
    """Server time rejects an expired token without consuming it."""
    token, record = await _mint(session_factory, ttl_seconds=1)
    recorder = InMemoryRejectionRecorder()

    result = await _verifier(
        session_factory,
        recorder,
        at=_ISSUED_AT + timedelta(seconds=1),
    ).verify_and_consume(
        token,
        _gmail_parameters("outside@example.net"),
        _OTHER_RUN_ID,
        _GITHUB_TOOL,
    )

    assert result.rejection is RejectionReason.EXPIRY
    async with session_factory() as session:
        stored = await session.get(CapabilityRecord, record.id)
    assert stored is not None
    assert stored.consumed_at is None


async def test_capability_from_another_run_fails_run_binding(
    session_factory: AsyncSessionFactory,
) -> None:
    """A signed capability cannot transfer to another run."""
    token, _ = await _mint(session_factory)
    recorder = InMemoryRejectionRecorder()

    result = await _verifier(session_factory, recorder).verify_and_consume(
        token,
        _gmail_parameters(),
        _OTHER_RUN_ID,
        _GITHUB_TOOL,
    )

    assert result.rejection is RejectionReason.RUN_BINDING


async def test_named_tool_must_match_invoked_tool(
    session_factory: AsyncSessionFactory,
) -> None:
    """The final binding check rejects an invocation of another tool."""
    token, _ = await _mint(session_factory)
    recorder = InMemoryRejectionRecorder()

    result = await _verifier(session_factory, recorder).verify_and_consume(
        token,
        _gmail_parameters(),
        _RUN_ID,
        _GITHUB_TOOL,
    )

    assert result.rejection is RejectionReason.TOOL_BINDING


async def test_replay_of_consumed_capability_fails_and_is_recorded(
    session_factory: AsyncSessionFactory,
) -> None:
    """A second presentation stops at the consumption check."""
    token, _ = await _mint(session_factory)
    recorder = InMemoryRejectionRecorder()
    verifier = _verifier(session_factory, recorder)

    first = await verifier.verify_and_consume(token, _gmail_parameters(), _RUN_ID, _GMAIL_TOOL)
    second = await verifier.verify_and_consume(
        token,
        _gmail_parameters("outside@example.net"),
        _RUN_ID,
        _GMAIL_TOOL,
    )

    assert first.accepted is True
    assert second.rejection is RejectionReason.CONSUMPTION
    assert len(recorder.rejections) == 1
    assert recorder.rejections[0].reason is RejectionReason.CONSUMPTION


async def test_two_concurrent_consumption_attempts_have_exactly_one_success(
    session_factory: AsyncSessionFactory,
) -> None:
    """Row locking and a null guard permit exactly one consumer."""
    token, _ = await _mint(session_factory)
    recorder = InMemoryRejectionRecorder()
    verifier = _verifier(session_factory, recorder)

    results = await asyncio.gather(
        verifier.verify_and_consume(token, _gmail_parameters(), _RUN_ID, _GMAIL_TOOL),
        verifier.verify_and_consume(token, _gmail_parameters(), _RUN_ID, _GMAIL_TOOL),
    )

    assert sum(result.accepted for result in results) == 1
    assert [result.rejection for result in results].count(RejectionReason.CONSUMPTION) == 1


async def test_invalid_signature_is_the_first_failure_without_a_capability_id(
    session_factory: AsyncSessionFactory,
) -> None:
    """Authentication precedes every claim and database check."""
    token, _ = await _mint(session_factory)
    recorder = InMemoryRejectionRecorder()
    replacement = "A" if token[-1] != "A" else "B"
    altered = CapabilityToken(f"{token[:-1]}{replacement}")

    result = await _verifier(session_factory, recorder).verify_and_consume(
        altered,
        _gmail_parameters("outside@example.net"),
        _OTHER_RUN_ID,
        _GITHUB_TOOL,
    )

    assert result.rejection is RejectionReason.SIGNATURE
    assert recorder.rejections[0].capability_id is None


class _RecorderError(Exception):
    """Represent unavailable rejection persistence in a test double."""


class _FailingRecorder:
    async def record(self, _rejection: CapabilityRejection) -> None:
        raise _RecorderError


async def test_recorder_failure_does_not_turn_a_rejection_into_success(
    session_factory: AsyncSessionFactory,
) -> None:
    """Unavailable audit recording surfaces as a closed verification failure."""
    token, _ = await _mint(session_factory)
    verifier = CapabilityVerifier(
        session_factory,
        CapabilitySigner(_SIGNING_KEY),
        DEFAULT_FINGERPRINT_SCHEMAS,
        _FailingRecorder(),
        clock=lambda: _VERIFY_AT,
    )

    with pytest.raises(RejectionRecordingError, match="could not be recorded"):
        await verifier.verify_and_consume(
            token,
            _gmail_parameters("outside@example.net"),
            _RUN_ID,
            _GMAIL_TOOL,
        )


async def test_application_role_can_only_update_consumed_at(
    settings: Settings,
    database_engine: AsyncEngine,
    session_factory: AsyncSessionFactory,
) -> None:
    """PostgreSQL denies application mutation of immutable capability fields."""
    token, record = await _mint(session_factory)
    assert token
    async with database_engine.begin() as connection:
        await connection.execute(text("GRANT warden_app TO CURRENT_USER"))
        await connection.execute(text("GRANT USAGE ON SCHEMA public TO warden_app"))
        await connection.execute(text("GRANT SELECT, INSERT ON capabilities TO warden_app"))
        await connection.execute(text("GRANT UPDATE (consumed_at) ON capabilities TO warden_app"))
        await connection.execute(
            text("REVOKE UPDATE (tool), DELETE ON capabilities FROM warden_app")
        )
    restricted_engine = create_database_engine(settings.database_url, "warden_app")
    try:
        async with restricted_engine.connect() as connection:
            with pytest.raises(DBAPIError, match="permission denied"):
                await connection.execute(
                    text("UPDATE capabilities SET tool = 'gmail.other' WHERE id = :id"),
                    {"id": record.id},
                )
        async with restricted_engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE capabilities SET consumed_at = :consumed_at "
                    "WHERE id = :id AND consumed_at IS NULL"
                ),
                {"id": record.id, "consumed_at": _VERIFY_AT},
            )
    finally:
        await restricted_engine.dispose()
