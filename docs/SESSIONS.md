# Build sessions

Fifteen sessions are defined by `docs/SPEC.md` Section 19. Each session is a
self-contained unit of work and ends when its stated exit condition passes.

| # | Session | Objective | Exit condition |
| --- | --- | --- | --- |
| 0 | Bootstrap | Repository, FastAPI app, Postgres with pgvector through Compose, migrations, CI, module packages, and an import-boundary test | `docker compose up` serves the health check and CI is green |
| 1 | Identity | Organizations, users, agents, sessions, roles, and pure authority computation | Authority intersection is unit-tested, including delegation narrowing, and seeded users can log in as all three roles |
| 2 | Policy bundle loading and matching | Bundle loading, schema validation, stable digests, and deterministic matching | A valid bundle has a stable digest, an invalid bundle is refused, and matching is tested |
| 3 | Condition evaluator | Pure condition evaluation, per-condition results, and fixture execution | At least 15 fixtures pass with identical results for repeated identical inputs |
| 4 | Effects, default deny, and decision recording | Effect combining, default deny, immutable decisions, and policy simulation | The full fixture set passes, simulation records nothing, and decision updates fail at the database |
| 5 | Capabilities | Minting, signing, canonicalization, verification, and single-use consumption | Replay, expiry, fingerprint mismatch, wrong-run, and concurrent double-consume tests pass |
| 6 | Broker and GitHub connector | Broker verification, connector interface, credential isolation, and GitHub fake and live modes | A capability-gated GitHub issue is created through the fake connector and can run live when configured |
| 7 | First governed vertical slice | Runs, steps, state machine, scripted model, tool loop, guards, and run endpoints | A scripted run creates an issue through the full path and the runtime-to-broker boundary test passes |
| 8 | Audit trail and trace reconstruction | Append-only events, trace reconstruction, audit endpoints, and decision recompute | A run is reconstructed from events alone and recompute verifies a stored decision |
| 9 | Knowledge and retrieval | Ingestion, chunking, local embeddings, provenance-aware retrieval, trust levels, and context digest | Retrieval returns trust-tagged chunks, citations resolve, and context digest reflects minimum trust |
| 10 | Approvals | Escalation lifecycle, expiry, approve-with-edit, and run suspension and resume | A scenario escalates, approves an edited recipient, and executes only the edited parameters |
| 11 | Delegation | Authority chains, monotonic narrowing, widening refusal, and the orchestrator agent | A widening attempt is refused and recorded, and a two-agent run completes |
| 12 | Gmail connector and injection scenario | Gmail connector, external-send policy, poisoned document, and memory taint | Allowed, approval, and blocked-injection scenarios all pass with both failed conditions named |
| 13 | Streamlit interface | Five Streamlit pages using only the live HTTP API | All three demo paths are driveable end to end and the UI import-boundary test passes |
| 14 | Deployment | Single image, external Postgres, secrets, boot migrations, seed command, documentation, and metrics | Success criteria S1 through S7 are demonstrable on the deployed instance |

The order is intentional: policy and capabilities precede the runtime, Session 7
establishes the first complete governed path, and the UI follows the behavior it
needs to expose.
