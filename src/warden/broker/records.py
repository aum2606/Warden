"""Execution persistence for capability-gated connector attempts."""

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from warden.capability.records import CapabilityBase
from warden.capability.service import Clock, server_time
from warden.capability.types import CapabilityId, JsonValue, ToolName

from .errors import ExecutionRecordingError
from .types import ConnectorResult, ExecutionId


class ExecutionStatus(StrEnum):
    """Lifecycle states retained for one connector invocation."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _status_values(status_type: type[ExecutionStatus]) -> list[str]:
    return [status.value for status in status_type]


class ExecutionRecord(CapabilityBase):
    """Record an invocation whose capability foreign key can never be null."""

    __tablename__ = "executions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    capability_id: Mapped[UUID] = mapped_column(
        ForeignKey("capabilities.id"),
        nullable=False,
        index=True,
    )
    tool: Mapped[str] = mapped_column(String(200))
    parameters: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, name="execution_status", values_callable=_status_values),
    )
    result_digest: Mapped[str | None] = mapped_column(String(71))
    error: Mapped[str | None] = mapped_column(String(500))


class ExecutionRepository:
    """Start and finish execution records around one external attempt."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock = server_time,
    ) -> None:
        """Bind execution writes to database sessions and a server clock."""
        self._session_factory = session_factory
        self._clock = clock

    async def start(
        self,
        capability_id: CapabilityId,
        tool: ToolName,
        parameters: Mapping[str, JsonValue],
    ) -> ExecutionRecord:
        """Persist an attempted invocation before calling its connector."""
        record = ExecutionRecord(
            id=ExecutionId(uuid4()),
            capability_id=capability_id,
            tool=tool,
            parameters=_copy_mapping(parameters),
            started_at=self._clock(),
            ended_at=None,
            status=ExecutionStatus.STARTED,
            result_digest=None,
            error=None,
        )
        async with self._session_factory() as session:
            session.add(record)
            try:
                await session.commit()
            except SQLAlchemyError:
                await session.rollback()
                message = "execution attempt could not be recorded"
                raise ExecutionRecordingError(message) from None
        return record

    async def succeed(self, execution_id: ExecutionId, result: ConnectorResult) -> None:
        """Complete an execution with a canonical result digest."""
        await self._finish(
            execution_id,
            ExecutionStatus.SUCCEEDED,
            result_digest=_result_digest(result),
            error=None,
        )

    async def fail(self, execution_id: ExecutionId) -> None:
        """Complete an execution without retaining a connector exception payload."""
        await self._finish(
            execution_id,
            ExecutionStatus.FAILED,
            result_digest=None,
            error="connector invocation failed",
        )

    async def _finish(
        self,
        execution_id: ExecutionId,
        status: ExecutionStatus,
        *,
        result_digest: str | None,
        error: str | None,
    ) -> None:
        async with self._session_factory() as session:
            try:
                updated_id = await session.scalar(
                    update(ExecutionRecord)
                    .where(
                        ExecutionRecord.id == execution_id,
                        ExecutionRecord.status == ExecutionStatus.STARTED,
                    )
                    .values(
                        ended_at=self._clock(),
                        status=status,
                        result_digest=result_digest,
                        error=error,
                    )
                    .returning(ExecutionRecord.id)
                )
                if updated_id is None:
                    message = "execution record is missing or already terminal"
                    raise ExecutionRecordingError(message)
                await session.commit()
            except SQLAlchemyError:
                await session.rollback()
                message = "execution result could not be recorded"
                raise ExecutionRecordingError(message) from None


def _result_digest(result: ConnectorResult) -> str:
    try:
        canonical = json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError):
        message = "connector result is not canonical JSON"
        raise ExecutionRecordingError(message) from None
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _copy_mapping(parameters: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: _copy_value(value) for key, value in parameters.items()}


def _copy_value(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _copy_value(item) for key, item in value.items()}
    return value
