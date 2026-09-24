"""Policy decision input type tests."""

from dataclasses import fields

from warden.identity.types import PrincipalKind
from warden.policy.models import PrincipalSelectorId, ToolName
from warden.policy.types import DecisionInput, PolicyPrincipal


def test_decision_input_carries_exactly_the_seven_specified_inputs() -> None:
    """The decision boundary exposes no implicit process or external state."""
    assert tuple(field.name for field in fields(DecisionInput)) == (
        "principal",
        "authority_chain",
        "tool",
        "parameters",
        "context_provenance",
        "run_metadata",
        "environment",
    )


def test_decision_input_accepts_typed_principal_chain_and_replayable_context() -> None:
    """A complete decision input can be constructed without accessing infrastructure."""
    principal = PolicyPrincipal(PrincipalKind.AGENT, PrincipalSelectorId("ops-worker"))
    decision_input = DecisionInput(
        principal=principal,
        authority_chain=(
            PolicyPrincipal(PrincipalKind.USER, PrincipalSelectorId("aum")),
            principal,
        ),
        tool=ToolName("gmail.send"),
        parameters={"to": ["reviewer@acme.example"], "attachment_count": 0},
        context_provenance={"min_trust": "internal", "sources": ["chunk-1"]},
        run_metadata={"run_id": "run-1", "prior_denials": 0},
        environment={"current_time": "2026-09-24T00:00:00Z", "org_settings": {}},
    )

    assert decision_input.principal == principal
    assert decision_input.authority_chain[-1] == principal
