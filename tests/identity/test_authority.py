"""Authority intersection tests."""

import pytest

from warden.identity.authority import effective_authority
from warden.identity.types import Scope


def test_effective_authority_is_intersection_of_all_three_ceilings() -> None:
    """Permissions absent from any ceiling do not survive computation."""
    authority = effective_authority(
        Scope.of("github.issue.create", "gmail.send"),
        Scope.of("github.issue.create", "knowledge.search"),
        Scope.of("github.issue.create", "memory.write"),
    )

    assert authority == Scope.of("github.issue.create")


def test_effective_authority_narrows_agent_wildcard_to_run_ceiling() -> None:
    """A broad agent grant cannot exceed the action named by the run ceiling."""
    authority = effective_authority(
        Scope.of("github.*", "gmail.*"),
        Scope.of("github.*"),
        Scope.of("github.issue.create"),
    )

    assert authority == Scope.of("github.issue.create")


def test_effective_authority_is_empty_when_delegation_does_not_overlap() -> None:
    """A delegation outside the held scope yields no effective authority."""
    authority = effective_authority(
        Scope.of("github.*"),
        Scope.of("gmail.send"),
        Scope.of("*"),
    )

    assert authority == Scope.of()


@pytest.mark.parametrize("permission", [".*", "github.*.write"])
def test_scope_rejects_nonterminal_or_prefixless_wildcard(permission: str) -> None:
    """Wildcard authority is accepted only for a named terminal namespace."""
    with pytest.raises(ValueError, match="invalid permission"):
        Scope.of(permission)
