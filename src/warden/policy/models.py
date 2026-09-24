"""Strict Pydantic models for versioned policy documents."""

from enum import StrEnum
from typing import Annotated, Literal, NewType

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from warden.identity.types import PrincipalKind

PolicyRuleId = NewType("PolicyRuleId", str)
ConditionId = NewType("ConditionId", str)
ToolName = NewType("ToolName", str)
PrincipalSelectorId = NewType("PrincipalSelectorId", str)
Expression = NewType("Expression", str)
FieldPath = NewType("FieldPath", str)
ApproverSelector = NewType("ApproverSelector", str)


class PolicyEffect(StrEnum):
    """Effects expressible by a policy rule."""

    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"


class StrictPolicyModel(BaseModel):
    """Reject undeclared fields throughout the policy schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PrincipalMatch(StrictPolicyModel):
    """Select a principal kind and one or more configured logical identifiers."""

    kind: PrincipalKind | Literal["*"]
    id: tuple[PrincipalSelectorId, ...]


class PolicyMatch(StrictPolicyModel):
    """Select actions by tool and principal."""

    tool: ToolName
    principal: PrincipalMatch


class PolicyCondition(StrictPolicyModel):
    """Name an expression so a later decision can identify its result."""

    id: ConditionId
    expr: Expression
    on_fail: Literal[PolicyEffect.DENY, PolicyEffect.ESCALATE]


class PolicyEffectMap(StrictPolicyModel):
    """Declare the successful effect and condition conflict strategy."""

    when_all_true: Literal[PolicyEffect.ALLOW]
    combine: Literal["most_restrictive"]


class PolicyEscalation(StrictPolicyModel):
    """Describe who can approve an escalation and what evidence they see."""

    approvers: tuple[ApproverSelector, ...]
    ttl_seconds: Annotated[int, Field(gt=0, strict=True)]
    show: tuple[FieldPath, ...]


class PolicyObligation(StrictPolicyModel):
    """Describe the redaction obligation defined by the version 1 schema."""

    redact: FieldPath
    unless: Literal["approved"]


class PolicyDocument(StrictPolicyModel):
    """Represent one complete version 1 policy rule."""

    version: Literal[1]
    id: PolicyRuleId
    description: str
    priority: StrictInt
    match: PolicyMatch
    conditions: tuple[PolicyCondition, ...]
    effect: PolicyEffectMap
    escalation: PolicyEscalation | None
    obligations: tuple[PolicyObligation, ...]
