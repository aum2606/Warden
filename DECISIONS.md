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
