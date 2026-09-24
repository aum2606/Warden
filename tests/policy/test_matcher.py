"""Policy rule matcher tests."""

from warden.identity.types import PrincipalKind
from warden.policy.matcher import match_rules
from warden.policy.models import (
    PolicyDocument,
    PolicyEffect,
    PolicyEffectMap,
    PolicyMatch,
    PolicyRuleId,
    PrincipalMatch,
    PrincipalSelectorId,
    ToolName,
)
from warden.policy.types import PolicyBundle, PolicyPrincipal, SourceDigest


def _rule(
    rule_id: str,
    priority: int,
    *,
    principal_kind: PrincipalKind | str = PrincipalKind.AGENT,
    principal_id: str = "ops-worker",
    tool: str = "github.issue.create",
) -> PolicyDocument:
    return PolicyDocument(
        version=1,
        id=PolicyRuleId(rule_id),
        description=f"Rule {rule_id}",
        priority=priority,
        match=PolicyMatch(
            tool=ToolName(tool),
            principal=PrincipalMatch(
                kind=principal_kind,
                id=(PrincipalSelectorId(principal_id),),
            ),
        ),
        conditions=(),
        effect=PolicyEffectMap(
            when_all_true=PolicyEffect.ALLOW,
            when_any_false=PolicyEffect.DENY,
        ),
        escalation=None,
        obligations=(),
    )


def _bundle(*rules: PolicyDocument) -> PolicyBundle:
    return PolicyBundle(rules=rules, source_digest=SourceDigest("test-digest"))


def test_matcher_orders_by_descending_priority_then_rule_id() -> None:
    """Candidate order is stable regardless of bundle document order."""
    bundle = _bundle(
        _rule("lower", 10),
        _rule("same-priority-z", 20),
        _rule("same-priority-a", 20),
    )

    matched = match_rules(
        bundle,
        ToolName("github.issue.create"),
        PolicyPrincipal(PrincipalKind.AGENT, PrincipalSelectorId("ops-worker")),
    )

    assert [str(rule.id) for rule in matched] == [
        "same-priority-a",
        "same-priority-z",
        "lower",
    ]


def test_matcher_selects_by_principal_kind_and_id() -> None:
    """A shared identifier does not collapse user and agent principal namespaces."""
    bundle = _bundle(
        _rule("matching-agent", 30),
        _rule("other-agent", 30, principal_id="orchestrator"),
        _rule("same-id-user", 30, principal_kind=PrincipalKind.USER),
        _rule("default-deny", -1, principal_kind="*", principal_id="*", tool="*"),
    )

    matched = match_rules(
        bundle,
        ToolName("github.issue.create"),
        PolicyPrincipal(PrincipalKind.AGENT, PrincipalSelectorId("ops-worker")),
    )

    assert [str(rule.id) for rule in matched] == ["matching-agent"]


def test_matcher_selects_explicit_default_deny_only_when_no_specific_rule_matches() -> None:
    """The fallback rule names an otherwise unmatched denial without competing."""
    bundle = _bundle(
        _rule("github-only", 10),
        _rule("default-deny", -1, principal_kind="*", principal_id="*", tool="*"),
    )

    matched = match_rules(
        bundle,
        ToolName("gmail.send"),
        PolicyPrincipal(PrincipalKind.AGENT, PrincipalSelectorId("ops-worker")),
    )

    assert [str(rule.id) for rule in matched] == ["default-deny"]


def test_matcher_does_not_select_rule_for_different_tool() -> None:
    """Principal matches cannot make a rule apply to an unrelated tool."""
    bundle = _bundle(_rule("github-only", 10))

    matched = match_rules(
        bundle,
        ToolName("gmail.send"),
        PolicyPrincipal(PrincipalKind.AGENT, PrincipalSelectorId("ops-worker")),
    )

    assert matched == ()
