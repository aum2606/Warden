"""Identity seed fixture tests."""

from sqlalchemy import func, select

from warden.database import AsyncSessionFactory
from warden.identity.models import Agent, Organization, User
from warden.identity.seed import seed_identity
from warden.identity.types import Role


async def test_seed_command_produces_one_org_three_users_and_two_agents(
    session_factory: AsyncSessionFactory,
) -> None:
    """The deterministic seed remains usable and idempotent."""
    async with session_factory() as session:
        first = await seed_identity(session, "fixture password")
        second = await seed_identity(session, "fixture password")
        organization_count = await session.scalar(select(func.count()).select_from(Organization))
        users = (await session.scalars(select(User).order_by(User.email))).all()
        agents = (await session.scalars(select(Agent).order_by(Agent.slug))).all()

    assert first == second
    assert organization_count == 1
    assert {user.role for user in users} == {Role.OWNER, Role.APPROVER, Role.MEMBER}
    assert {agent.slug for agent in agents} == {"ops-worker", "orchestrator"}
    assert all(agent.enabled for agent in agents)
