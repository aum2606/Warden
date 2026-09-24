"""Typed policy inputs and loaded bundle values."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NewType

from warden.identity.types import PrincipalKind

from .models import PolicyDocument, PrincipalSelectorId, ToolName

SourceDigest = NewType("SourceDigest", str)

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class PolicyPrincipal:
    """Identify a principal using the logical identifier visible to policy authors."""

    kind: PrincipalKind
    id: PrincipalSelectorId


@dataclass(frozen=True, slots=True)
class DecisionInput:
    """Carry the complete, replayable input surface available to policy decisions."""

    principal: PolicyPrincipal
    authority_chain: tuple[PolicyPrincipal, ...]
    tool: ToolName
    parameters: Mapping[str, JsonValue]
    context_provenance: Mapping[str, JsonValue]
    run_metadata: Mapping[str, JsonValue]
    environment: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class PolicyBundle:
    """Hold one atomically validated set of policy documents and its digest."""

    rules: tuple[PolicyDocument, ...]
    source_digest: SourceDigest
