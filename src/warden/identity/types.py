"""Domain types for principals, roles, and authority scopes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType, Self
from uuid import UUID

OrgId = NewType("OrgId", UUID)
UserId = NewType("UserId", UUID)
AgentId = NewType("AgentId", UUID)


class Role(StrEnum):
    """Human roles recognized by Warden."""

    OWNER = "owner"
    APPROVER = "approver"
    MEMBER = "member"


class PrincipalKind(StrEnum):
    """Kinds of principals that may hold authority."""

    USER = "user"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class PrincipalId:
    """Identify a user or agent without collapsing their namespaces."""

    kind: PrincipalKind
    value: UUID

    @classmethod
    def for_user(cls, user_id: UserId) -> Self:
        """Create a principal identifier for a user."""
        return cls(kind=PrincipalKind.USER, value=user_id)

    @classmethod
    def for_agent(cls, agent_id: AgentId) -> Self:
        """Create a principal identifier for an agent."""
        return cls(kind=PrincipalKind.AGENT, value=agent_id)

    @classmethod
    def parse(cls, value: str) -> Self:
        """Parse the stable external representation of a principal."""
        kind_value, separator, identifier = value.partition(":")
        if not separator:
            message = "principal identifier must contain a kind prefix"
            raise ValueError(message)
        return cls(kind=PrincipalKind(kind_value), value=UUID(identifier))

    def __str__(self) -> str:
        """Return the stable external representation of the principal."""
        return f"{self.kind.value}:{self.value}"


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated human principal resolved from persistent identity."""

    id: PrincipalId
    org_id: OrgId
    email: str
    role: Role


@dataclass(frozen=True, slots=True)
class Scope:
    """An immutable set of exact or terminal-wildcard permissions."""

    permissions: frozenset[str]

    def __post_init__(self) -> None:
        """Validate the permission grammar at the domain boundary."""
        for permission in self.permissions:
            wildcard_is_invalid = "*" in permission and (
                not permission.endswith(".*") or permission == ".*"
            )
            if not permission or (permission != "*" and wildcard_is_invalid):
                message = f"invalid permission: {permission!r}"
                raise ValueError(message)

    @classmethod
    def of(cls, *permissions: str) -> Self:
        """Build a scope from permission names."""
        return cls(frozenset(permissions))

    def intersect(self, other: Scope) -> Scope:
        """Return the most specific permissions shared by both scopes."""
        shared = {
            intersection
            for left in self.permissions
            for right in other.permissions
            if (intersection := _intersect_permission(left, right)) is not None
        }
        return Scope(frozenset(shared))


def _intersect_permission(left: str, right: str) -> str | None:
    if left == right:
        return left
    if left == "*":
        return right
    if right == "*":
        return left
    if left.endswith(".*") and _is_within(right, left):
        return right
    if right.endswith(".*") and _is_within(left, right):
        return left
    return None


def _is_within(candidate: str, wildcard: str) -> bool:
    prefix = wildcard.removesuffix("*")
    return candidate.startswith(prefix)
