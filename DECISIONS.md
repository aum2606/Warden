# Decisions

Implementation decisions not settled by `docs/SPEC.md` are recorded here.

## 2026-09-23 - Number build sessions from zero

**Context.** Bootstrap was completed as the prerequisite session, while the
identity handoff names Identity as Session 1. Numbering Bootstrap as Session 1
made the branch name and the next handoff disagree.

**Decision.** Bootstrap is Session 0. Identity is Session 1, and the remaining
phases continue through Session 14, for fifteen sessions in total.

**Consequence.** Session branches and pull requests use the same numbers as the
handoffs. The merged Bootstrap work remains unchanged; only planning documents
and future branch names are affected.

**Spec impact.** Section 19, the public-repository timing in Section 20, and the
local-development range in Section 21.

## 2026-09-24 - Identity identifiers and session security

**Context.** The specification names typed identifiers, Argon2 password hashing,
and signed sessions but does not select identifier storage, token format, or a
session lifetime.

**Decision.** Identity records use UUID primary keys wrapped by domain `NewType`
values. Passwords use Argon2id. Sessions use HS256 JWTs with an environment-only
secret of at least 32 characters and an eight-hour lifetime. Seed passwords are
also supplied only through the environment.

**Consequence.** Tokens are locally verifiable, restart-stable, and contain no
credential material. Rotating the signing secret invalidates existing sessions.

**Spec impact.** None.

## 2026-09-24 - Terminal wildcards narrow to concrete permissions

**Context.** Section 14 grants agents scopes such as `github.*`, while Section 5
requires set intersection and later run ceilings may name concrete actions.

**Decision.** `Scope` accepts exact permissions, the global wildcard `*`, and a
terminal wildcard such as `github.*`. Intersecting a wildcard with a matching
more-specific permission returns the more-specific permission.

**Consequence.** A broad configured maximum grant can be narrowed by delegation
or a run ceiling without accidentally producing an empty scope or widening the
result.

**Spec impact.** Clarifies Section 5 Rule 2; no schema change.

## 2026-09-24 - Canonical policy bundles and logical selectors

**Context.** Section 6 defines the policy document shape and shows agent slugs in
principal selectors, but it does not define digest canonicalization, duplicate
rule handling, wildcard syntax, or how persisted UUIDs map to authored policy.

**Decision.** Version 1 policy documents reject undeclared fields and invalid
scalar types. Policy selectors use logical principal identifiers such as agent
slugs, with `*` as the explicit tool, principal-kind, or principal-id wildcard.
A bundle rejects duplicate rule ids and computes its SHA-256 source digest over
canonical JSON representations of all validated documents sorted by rule id.

**Consequence.** Digests are stable across file enumeration, YAML formatting,
and platform line endings. A later input resolver must map persisted principals
to their stable policy-facing identifiers before matching.

**Spec impact.** Clarifies Sections 5 and 6; no schema change.
