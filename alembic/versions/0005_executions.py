"""Create capability-bound execution records.

Revision ID: 0005_executions
Revises: 0004_capabilities
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_executions"
down_revision: str | Sequence[str] | None = "0004_capabilities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_status_enum = postgresql.ENUM(
    "started",
    "succeeded",
    "failed",
    name="execution_status",
)


def upgrade() -> None:
    """Create execution storage whose capability reference is mandatory."""
    op.create_table(
        "executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool", sa.String(length=200), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", _status_enum, nullable=False),
        sa.Column("result_digest", sa.String(length=71), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["capability_id"], ["capabilities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_executions_capability_id", "executions", ["capability_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON TABLE executions TO warden_app")
    op.execute("REVOKE DELETE ON TABLE executions FROM warden_app")


def downgrade() -> None:
    """Remove execution storage and its application grants."""
    op.execute("REVOKE ALL PRIVILEGES ON TABLE executions FROM warden_app")
    op.drop_index("ix_executions_capability_id", table_name="executions")
    op.drop_table("executions")
    _status_enum.drop(op.get_bind(), checkfirst=True)
