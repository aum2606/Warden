"""Create parameter-bound, single-use capabilities.

Revision ID: 0004_capabilities
Revises: 0003_policy_decisions
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_capabilities"
down_revision: str | Sequence[str] | None = "0003_policy_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create capability storage with only one conditionally writable column."""
    op.create_table(
        "capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal", sa.String(length=500), nullable=False),
        sa.Column("tool", sa.String(length=200), nullable=False),
        sa.Column("param_fingerprint", sa.String(length=71), nullable=False),
        sa.Column("obligations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_capabilities_decision_id", "capabilities", ["decision_id"])
    op.create_index("ix_capabilities_run_id", "capabilities", ["run_id"])
    op.create_index("ix_capabilities_expires_at", "capabilities", ["expires_at"])
    op.execute("GRANT SELECT, INSERT ON TABLE capabilities TO warden_app")
    op.execute("GRANT UPDATE (consumed_at) ON TABLE capabilities TO warden_app")
    op.execute("REVOKE DELETE ON TABLE capabilities FROM warden_app")


def downgrade() -> None:
    """Remove capability storage and its restricted grants."""
    op.execute("REVOKE ALL PRIVILEGES ON TABLE capabilities FROM warden_app")
    op.drop_index("ix_capabilities_expires_at", table_name="capabilities")
    op.drop_index("ix_capabilities_run_id", table_name="capabilities")
    op.drop_index("ix_capabilities_decision_id", table_name="capabilities")
    op.drop_table("capabilities")
