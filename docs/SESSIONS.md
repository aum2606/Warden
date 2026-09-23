# Build sessions

Fourteen sessions are defined by `docs/SPEC.md` Section 19. Each session is a
self-contained unit of work and ends when its stated exit condition passes.

| # | Session | Objective | Exit condition |
| --- | --- | --- | --- |
| 1 | Skeleton | Repository, FastAPI app, Postgres with pgvector through Compose, migrations, CI, module packages, and an import-boundary test | `docker compose up` serves the health check and CI is green |
| 2 | Identity | Organizations, users, agents, sessions, roles, and pure authority computation | Authority intersection is unit-tested, including delegation narrowing |
| 3 | Policy engine I | Bundle loading, schema validation, matching, and the pure condition evaluator | At least 15 fixtures pass and an invalid bundle refuses to load |
| 4 | Policy engine II | Effect combining, default deny, decision recording, and policy simulation | The full fixture set passes and simulation returns a decision without recording |
| 5 | Capability | Minting, signing, canonicalization, verification, and single-use consumption | Replay, expiry, fingerprint mismatch, and concurrent double-consume tests pass |
| 6 | Broker and first connector | Broker verification, connector interface, and GitHub connector in fake and live modes | A capability-gated GitHub issue is created against a test repository |
| 7 | First vertical slice | Minimal runtime, stubbed model, one tool, and the full governed action path | A scripted run creates an issue and produces a complete event stream |
| 8 | Audit and trace | Event schema, append-only constraints, trace reconstruction, and decision recompute | A run is reconstructed without live calls and recompute verifies its decision |
| 9 | Knowledge | Ingestion, chunking, local embeddings, provenance-aware retrieval, trust levels, and context digest | Retrieval returns trust-tagged chunks and citations resolve to source offsets |
| 10 | Approvals | Escalation lifecycle, expiry, approve-with-edit, and run suspension and resume | A scenario escalates, approves an edited recipient, and executes only the edited parameters |
| 11 | Delegation | Orchestrator, narrowing, refusal on widening, and authority chains | A widening attempt is refused and recorded, and a two-agent run completes |
| 12 | Gmail connector and injection scenario | Gmail connector, external-send policy, poisoned document, and memory taint | The injection attempt is denied with both failed conditions named |
| 13 | UI | Five Streamlit pages using only the live HTTP API | All three demo paths are driveable end to end in the browser |
| 14 | Deploy and harden | Single image, external Postgres, secrets, boot migrations, seed command, documentation, and metrics | Success criteria S1 through S7 are demonstrable on the deployed instance |

The order is intentional: policy and capabilities precede the runtime, Session 7
establishes the first complete governed path, and the UI follows the behavior it
needs to expose.
