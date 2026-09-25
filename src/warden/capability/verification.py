"""Ordered fail-closed verification and atomic capability consumption."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from warden.policy.models import ToolName
from warden.policy.types import JsonValue, RunId

from .canonicalization import FingerprintSchemaRegistry, fingerprint_parameters
from .errors import CanonicalizationError, InvalidCapabilityTokenError, RejectionRecordingError
from .records import CapabilityRecord
from .rejections import RejectionRecorder
from .service import Clock, server_time
from .signing import CapabilitySigner
from .types import (
    CapabilityClaims,
    CapabilityId,
    CapabilityRejection,
    CapabilityToken,
    RejectionReason,
    VerificationResult,
)


@dataclass(frozen=True, slots=True)
class _VerificationRequest:
    parameters: Mapping[str, JsonValue]
    expected_run_id: RunId
    expected_tool: ToolName
    occurred_at: datetime


class CapabilityVerifier:
    """Apply the six broker checks in their required first-failure order."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        signer: CapabilitySigner,
        schemas: FingerprintSchemaRegistry,
        rejection_recorder: RejectionRecorder,
        clock: Clock = server_time,
    ) -> None:
        """Bind server-controlled verification and recording dependencies."""
        self._session_factory = session_factory
        self._signer = signer
        self._schemas = schemas
        self._rejection_recorder = rejection_recorder
        self._clock = clock

    async def verify_and_consume(
        self,
        token: CapabilityToken,
        parameters: Mapping[str, JsonValue],
        expected_run_id: RunId,
        expected_tool: ToolName,
    ) -> VerificationResult:
        """Return the first failed check or atomically consume a valid capability."""
        occurred_at = self._clock()
        authenticated = await self._authenticate(token, occurred_at)
        if isinstance(authenticated, VerificationResult):
            return authenticated
        claims = authenticated
        expiry_rejection = await self._reject_if_expired(claims, occurred_at)
        if expiry_rejection is not None:
            return expiry_rejection
        request = _VerificationRequest(
            parameters,
            expected_run_id,
            expected_tool,
            occurred_at,
        )
        failure: RejectionReason | None = None
        async with self._session_factory() as session:
            try:
                failure = await self._locked_failure_reason(
                    session,
                    claims,
                    request,
                )
                if failure is None:
                    await session.commit()
                else:
                    await session.rollback()
            except SQLAlchemyError:
                await session.rollback()
                failure = RejectionReason.CONSUMPTION
            except CanonicalizationError:
                await session.rollback()
                failure = RejectionReason.FINGERPRINT
        if failure is not None:
            return await self._reject(claims.cap_id, failure, occurred_at)
        return VerificationResult(
            accepted=True,
            capability_id=claims.cap_id,
            rejection=None,
            claims=claims,
        )

    async def _authenticate(
        self,
        token: CapabilityToken,
        occurred_at: datetime,
    ) -> CapabilityClaims | VerificationResult:
        try:
            return self._signer.verify(token)
        except InvalidCapabilityTokenError:
            return await self._reject(None, RejectionReason.SIGNATURE, occurred_at)

    async def _reject_if_expired(
        self,
        claims: CapabilityClaims,
        occurred_at: datetime,
    ) -> VerificationResult | None:
        if occurred_at < claims.expires_at:
            return None
        return await self._reject(claims.cap_id, RejectionReason.EXPIRY, occurred_at)

    async def _locked_failure_reason(
        self,
        session: AsyncSession,
        claims: CapabilityClaims,
        request: _VerificationRequest,
    ) -> RejectionReason | None:
        record = await session.scalar(
            select(CapabilityRecord).where(CapabilityRecord.id == claims.cap_id).with_for_update()
        )
        if record is None or record.consumed_at is not None:
            return RejectionReason.CONSUMPTION
        if fingerprint_parameters(claims.tool, request.parameters, self._schemas) != (
            claims.param_fingerprint
        ):
            return RejectionReason.FINGERPRINT
        if claims.run_id != request.expected_run_id:
            return RejectionReason.RUN_BINDING
        if claims.tool != request.expected_tool:
            return RejectionReason.TOOL_BINDING
        consumed_id = await session.scalar(
            update(CapabilityRecord)
            .where(
                CapabilityRecord.id == claims.cap_id,
                CapabilityRecord.consumed_at.is_(None),
            )
            .values(consumed_at=request.occurred_at)
            .returning(CapabilityRecord.id)
        )
        if consumed_id is None:
            return RejectionReason.CONSUMPTION
        return None

    async def _reject(
        self,
        capability_id: CapabilityId | None,
        reason: RejectionReason,
        occurred_at: datetime,
    ) -> VerificationResult:
        rejection = CapabilityRejection(capability_id, reason, occurred_at)
        try:
            await self._rejection_recorder.record(rejection)
        except Exception as error:
            message = "capability rejection could not be recorded"
            raise RejectionRecordingError(message) from error
        return VerificationResult(
            accepted=False,
            capability_id=capability_id,
            rejection=reason,
            claims=None,
        )
