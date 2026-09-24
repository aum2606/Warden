"""Pure authority computation for governed actions."""

from .types import Scope


def effective_authority(
    agent_grant: Scope,
    delegation_scope: Scope,
    run_ceiling: Scope,
) -> Scope:
    """Intersect every authority ceiling without widening any input scope."""
    return agent_grant.intersect(delegation_scope).intersect(run_ceiling)
