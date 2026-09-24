"""Deterministic rule matching by tool and principal."""

from .models import PolicyDocument, PrincipalMatch, ToolName
from .types import PolicyBundle, PolicyPrincipal

_DEFAULT_DENY_RULE_ID = "default-deny"


def match_rules(
    bundle: PolicyBundle,
    tool: ToolName,
    principal: PolicyPrincipal,
) -> tuple[PolicyDocument, ...]:
    """Return matching rules ordered by descending priority and then rule id."""
    matching_rules = tuple(
        rule
        for rule in bundle.rules
        if _matches_tool(rule, tool) and _matches_principal(rule.match.principal, principal)
    )
    specific_rules = tuple(rule for rule in matching_rules if rule.id != _DEFAULT_DENY_RULE_ID)
    candidates = specific_rules or matching_rules
    return tuple(sorted(candidates, key=lambda rule: (-rule.priority, str(rule.id))))


def _matches_tool(rule: PolicyDocument, tool: ToolName) -> bool:
    return rule.match.tool in ("*", tool)


def _matches_principal(selector: PrincipalMatch, principal: PolicyPrincipal) -> bool:
    kind_matches = selector.kind == "*" or selector.kind is principal.kind
    id_matches = "*" in selector.id or principal.id in selector.id
    return kind_matches and id_matches
