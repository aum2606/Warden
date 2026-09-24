"""Deterministic identity fixtures for local development and tests."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Agent, Organization, User
from .security import hash_password
from .types import AgentId, OrgId, Role, UserId

_ORG_ID = OrgId(UUID("00000000-0000-4000-8000-000000000001"))
_OWNER_ID = UserId(UUID("00000000-0000-4000-8000-000000000101"))
_APPROVER_ID = UserId(UUID("00000000-0000-4000-8000-000000000102"))
_MEMBER_ID = UserId(UUID("00000000-0000-4000-8000-000000000103"))
_ORCHESTRATOR_ID = AgentId(UUID("00000000-0000-4000-8000-000000000201"))
_OPS_WORKER_ID = AgentId(UUID("00000000-0000-4000-8000-000000000202"))


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Identifiers produced by the identity seed operation."""

    org_id: OrgId
    user_ids: tuple[UserId, ...]
    agent_ids: tuple[AgentId, ...]


async def seed_identity(session: AsyncSession, password: str) -> SeedResult:
    """Create or refresh the single-organization demo identity fixture."""
    password_hash = hash_password(password)
    organization = await session.get(Organization, _ORG_ID)
    if organization is None:
        organization = Organization(id=_ORG_ID, name="Warden Demo", settings={})
        session.add(organization)
    else:
        organization.name = "Warden Demo"
        organization.settings = {}

    users = (
        (_OWNER_ID, "owner@warden.local", Role.OWNER),
        (_APPROVER_ID, "approver@warden.local", Role.APPROVER),
        (_MEMBER_ID, "member@warden.local", Role.MEMBER),
    )
    for user_id, email, role in users:
        user = await session.get(User, user_id)
        if user is None:
            user = User(
                id=user_id,
                org_id=_ORG_ID,
                email=email,
                password_hash=password_hash,
                role=role,
            )
            session.add(user)
        else:
            user.org_id = _ORG_ID
            user.email = email
            user.password_hash = password_hash
            user.role = role

    agents: tuple[tuple[AgentId, str, str, dict[str, object]], ...] = (
        (
            _ORCHESTRATOR_ID,
            "orchestrator",
            "Orchestrator",
            {
                "permissions": ["knowledge.search", "memory.write", "delegate"],
                "constraints": {"memory.write": {"scopes": ["run"]}},
            },
        ),
        (
            _OPS_WORKER_ID,
            "ops-worker",
            "Operations Worker",
            {
                "permissions": ["github.*", "gmail.*", "knowledge.search", "memory.write"],
                "constraints": {"memory.write": {"scopes": ["run"]}},
            },
        ),
    )
    for agent_id, slug, display_name, max_grant in agents:
        agent = await session.get(Agent, agent_id)
        if agent is None:
            agent = Agent(
                id=agent_id,
                org_id=_ORG_ID,
                slug=slug,
                display_name=display_name,
                model="stubbed",
                system_prompt_ref=f"prompts/{slug}.md",
                max_grant=max_grant,
                enabled=True,
            )
            session.add(agent)
        else:
            agent.org_id = _ORG_ID
            agent.slug = slug
            agent.display_name = display_name
            agent.model = "stubbed"
            agent.system_prompt_ref = f"prompts/{slug}.md"
            agent.max_grant = max_grant
            agent.enabled = True

    await session.commit()
    return SeedResult(
        org_id=_ORG_ID,
        user_ids=(_OWNER_ID, _APPROVER_ID, _MEMBER_ID),
        agent_ids=(_ORCHESTRATOR_ID, _OPS_WORKER_ID),
    )
