"""Create append-only policy decisions and the application role.

Revision ID: 0003_policy_decisions
Revises: 0002_identity_schema
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_policy_decisions"
down_revision: str | Sequence[str] | None = "0002_identity_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_effect_enum = postgresql.ENUM("allow", "deny", "escalate", name="policy_effect")


def upgrade() -> None:
    """Create immutable decision storage and restrict the application role."""
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'warden_app') THEN
                CREATE ROLE warden_app NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute("GRANT warden_app TO CURRENT_USER")
    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bundle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("effect", _effect_enum, nullable=False),
        sa.Column("rule_id", sa.String(length=200), nullable=False),
        sa.Column(
            "failed_condition_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "inputs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["bundle_id"], ["policy_bundles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decisions_run_id", "decisions", ["run_id"])
    op.create_index("ix_decisions_step_id", "decisions", ["step_id"])
    op.create_index("ix_decisions_bundle_id", "decisions", ["bundle_id"])
    op.execute("GRANT USAGE ON SCHEMA public TO warden_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO warden_app")
    op.execute("REVOKE UPDATE, DELETE ON TABLE decisions FROM warden_app")


def downgrade() -> None:
    """Remove decision storage and the application role grants."""
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM warden_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM warden_app")
    op.drop_index("ix_decisions_bundle_id", table_name="decisions")
    op.drop_index("ix_decisions_step_id", table_name="decisions")
    op.drop_index("ix_decisions_run_id", table_name="decisions")
    op.drop_table("decisions")
    _effect_enum.drop(op.get_bind(), checkfirst=True)
    op.execute("REVOKE warden_app FROM CURRENT_USER")
    op.execute("DROP ROLE warden_app")
