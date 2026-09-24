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

## 2026-09-24 - Restricted condition expression language

**Context.** Section 6 shows condition syntax and Section 20 leans toward a
custom mini-language, but neither defines its parser, error semantics, or trust
label ordering.

**Decision.** Conditions use a handwritten allowlisted grammar rather than
Python evaluation or a general expression runtime. It supports field access on
`params`, `context`, `run`, and `environment`; typed comparisons; `endsWith`;
membership; `all`; and `and`, `or`, and `not`. Expression or type errors return a
failed condition. Trust labels compare in the explicit order `untrusted <
internal < trusted`; other strings compare lexically. Time is ordinary data under
`environment` and the evaluator has no clock interface.

**Consequence.** Policy expressions cannot import modules, call arbitrary
functions, access process state, or perform I/O. Evaluation is deterministic for
the same expression and decision input, and malformed conditions fail closed.

**Spec impact.** Settles D2 for the condition language and clarifies Sections 5,
6, and 10.

## 2026-09-24 - Condition-level failure effects

**Context.** The aggregate `when_any_false` effect could not express the
specified Gmail behavior: an external recipient may be approved, while
untrusted provenance must be denied even when both conditions fail together.

**Decision.** Every condition declares `on_fail` as either `deny` or
`escalate`. A rule declares `when_all_true: allow` and
`combine: most_restrictive`. Failed conditions combine in the fixed order
`deny > escalate > allow`; failure count never changes severity. The explicit
default-deny rule uses an always-false condition whose failure effect is deny.

**Consequence.** Each failed condition independently communicates its required
severity, decision records retain the exact failed condition ids, and adding a
second failure cannot weaken an outcome.

**Spec impact.** Replaces the aggregate effect shape in Section 6 and resolves
the Gmail behavior described in Sections 11 and 18.

## 2026-09-24 - Dedicated PostgreSQL application role

**Context.** The local database login owns the schema, and PostgreSQL table
owners retain implicit modification authority even after an explicit revoke.
That cannot prove append-only decisions at the database boundary.

**Decision.** Migrations run as the schema owner and create a `warden_app`
role. Runtime connections assume that role. It receives ordinary application
table permissions except `UPDATE` on `decisions`.

**Consequence.** The application remains able to insert decisions but an
attempted decision update fails at the database level. Local development keeps
migration ownership separate from effective runtime authority.

**Spec impact.** Implements the application-role constraint in Section 7.
