"""SQLAlchemy persistence models owned by the identity module."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .types import Role


def _role_values(role_type: type[Role]) -> list[str]:
    return [role.value for role in role_type]


class IdentityBase(DeclarativeBase):
    """Declarative metadata root for the Session 1 identity schema."""


class Organization(IdentityBase):
    """The organization boundary that owns identity and configuration."""

    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    settings: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class User(IdentityBase):
    """A human principal with credentials and an organization role."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_users_org_email"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", values_callable=_role_values),
    )


class Agent(IdentityBase):
    """A configured agent principal and the maximum authority it may hold."""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_agents_org_slug"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(200))
    model: Mapped[str] = mapped_column(String(200))
    system_prompt_ref: Mapped[str] = mapped_column(String(500))
    max_grant: Mapped[dict[str, object]] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Connection(IdentityBase):
    """A reference to broker-held credentials for one external account."""

    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "provider",
            "account_label",
            name="uq_connections_org_provider_label",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(100))
    account_label: Mapped[str] = mapped_column(String(200))
    credential_ref: Mapped[str] = mapped_column(String(500))
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(50))


class PolicyBundle(IdentityBase):
    """Metadata for one immutable loaded version of the policy bundle."""

    __tablename__ = "policy_bundles"
    __table_args__ = (UniqueConstraint("org_id", "version", name="uq_policy_bundles_org_version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    version: Mapped[str] = mapped_column(String(100))
    git_sha: Mapped[str] = mapped_column(String(40))
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    source_digest: Mapped[str] = mapped_column(String(64))
