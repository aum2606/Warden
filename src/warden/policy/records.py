"""Append-only SQLAlchemy decision records and their repository."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from warden.identity.models import IdentityBase

from .engine import DecisionResult, PolicyEngine
from .errors import DecisionRecordingError
from .models import PolicyEffect
from .types import DecisionId, DecisionInput, PolicyBundleId, PolicyPrincipal, RunId, StepId


def _effect_values(effect_type: type[PolicyEffect]) -> list[str]:
    return [effect.value for effect in effect_type]


class DecisionRecord(IdentityBase):
    """Persist one immutable policy decision with its complete evaluated input."""

    __tablename__ = "decisions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(index=True)
    step_id: Mapped[UUID] = mapped_column(index=True)
    bundle_id: Mapped[UUID] = mapped_column(
        ForeignKey("policy_bundles.id"),
        index=True,
    )
    effect: Mapped[PolicyEffect] = mapped_column(
        Enum(PolicyEffect, name="policy_effect", values_callable=_effect_values),
    )
    rule_id: Mapped[str] = mapped_column(String(200))
    failed_condition_ids: Mapped[list[str]] = mapped_column(JSONB)
    inputs: Mapped[dict[str, object]] = mapped_column(JSONB)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


@dataclass(frozen=True, slots=True)
class DecisionCoordinates:
    """Identify the run, step, and persisted bundle for a decision."""

    run_id: RunId
    step_id: StepId
    bundle_id: PolicyBundleId


class DecisionRepository:
    """Append policy decisions without exposing mutation operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind decision appends to one transaction-owning session."""
        self._session = session

    async def append(
        self,
        *,
        run_id: RunId,
        step_id: StepId,
        bundle_id: PolicyBundleId,
        decision_input: DecisionInput,
        result: DecisionResult,
    ) -> DecisionRecord:
        """Store a decision and its full replay input as one transaction."""
        record = DecisionRecord(
            id=DecisionId(uuid4()),
            run_id=run_id,
            step_id=step_id,
            bundle_id=bundle_id,
            effect=result.effect,
            rule_id=str(result.rule_id),
            failed_condition_ids=[str(value) for value in result.failed_condition_ids],
            inputs=serialize_decision_input(decision_input),
        )
        self._session.add(record)
        try:
            await self._session.commit()
        except SQLAlchemyError as error:
            await self._session.rollback()
            message = "decision could not be appended"
            raise DecisionRecordingError(message) from error
        return record


async def evaluate_and_record(
    engine: PolicyEngine,
    repository: DecisionRepository,
    coordinates: DecisionCoordinates,
    decision_input: DecisionInput,
) -> DecisionRecord:
    """Evaluate and append a decision before returning it to a caller."""
    result = engine.evaluate(decision_input)
    return await repository.append(
        run_id=coordinates.run_id,
        step_id=coordinates.step_id,
        bundle_id=coordinates.bundle_id,
        decision_input=decision_input,
        result=result,
    )


def serialize_decision_input(decision_input: DecisionInput) -> dict[str, object]:
    """Convert all seven typed decision inputs into replayable JSON data."""
    return {
        "principal": _serialize_principal(decision_input.principal),
        "authority_chain": [
            _serialize_principal(principal) for principal in decision_input.authority_chain
        ],
        "tool": str(decision_input.tool),
        "params": dict(decision_input.parameters),
        "context": dict(decision_input.context_provenance),
        "run": dict(decision_input.run_metadata),
        "environment": dict(decision_input.environment),
    }


def _serialize_principal(principal: PolicyPrincipal) -> str:
    return f"{principal.kind.value}:{principal.id!s}"
