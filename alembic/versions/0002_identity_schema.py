"""Create identity and configuration tables.

Revision ID: 0002_identity_schema
Revises: 0001_initial
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_identity_schema"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_role_enum = postgresql.ENUM("owner", "approver", "member", name="user_role")


def upgrade() -> None:
    """Create the five tables owned by the identity module."""
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", _role_enum, nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "email", name="uq_users_org_email"),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("system_prompt_ref", sa.String(length=500), nullable=False),
        sa.Column(
            "max_grant",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "slug", name="uq_agents_org_slug"),
    )
    op.create_index("ix_agents_org_id", "agents", ["org_id"])
    op.create_table(
        "connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("account_label", sa.String(length=200), nullable=False),
        sa.Column("credential_ref", sa.String(length=500), nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "provider",
            "account_label",
            name="uq_connections_org_provider_label",
        ),
    )
    op.create_index("ix_connections_org_id", "connections", ["org_id"])
    op.create_table(
        "policy_bundles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("git_sha", sa.String(length=40), nullable=False),
        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "version", name="uq_policy_bundles_org_version"),
    )
    op.create_index("ix_policy_bundles_org_id", "policy_bundles", ["org_id"])


def downgrade() -> None:
    """Remove the identity and configuration schema."""
    op.drop_table("policy_bundles")
    op.drop_table("connections")
    op.drop_table("agents")
    op.drop_table("users")
    op.drop_table("organizations")
    _role_enum.drop(op.get_bind(), checkfirst=True)
