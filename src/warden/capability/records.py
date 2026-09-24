"""Capability persistence with append-only records and atomic consumption."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from warden.identity.models import IdentityBase


class CapabilityRecord(IdentityBase):
    """Persist the immutable capability envelope and its one mutable timestamp."""

    __tablename__ = "capabilities"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("decisions.id"),
        index=True,
    )
    run_id: Mapped[UUID] = mapped_column(index=True)
    principal: Mapped[str] = mapped_column(String(500))
    tool: Mapped[str] = mapped_column(String(200))
    param_fingerprint: Mapped[str] = mapped_column(String(71))
    obligations: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
