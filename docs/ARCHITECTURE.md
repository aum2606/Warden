# Architecture

Warden is a modular monolith whose FastAPI service contains seven modules under
`src/warden/`. The policy decision point precedes every external side effect, and
the broker is the only component that holds credentials or invokes connectors.
The full system and data model are specified in `docs/SPEC.md`.

## Modules

| Module | Responsibility | May import |
| --- | --- | --- |
| `identity` | Users, agents, sessions, and authority computation | None |
| `policy` | Bundle loading, evaluation, simulation, and fixtures | `identity` |
| `capability` | Minting, signing, verification, and consumption | `identity`, `policy` |
| `broker` | Connectors, credential handling, execution, and obligations | `capability` |
| `runtime` | Orchestration, agents, the tool loop, and delegation | `identity`, `policy`, `capability`, `knowledge`, `memory` |
| `knowledge` | Ingestion, chunking, embedding, retrieval, and provenance | None |
| `audit` | Event append, run reconstruction, and trace assembly | None; every module may write audit events |

Each module owns an `errors.py` file with its exception base class. Exceptions do
not cross module boundaries as control flow.

## Import rules

The directed import edges in the table are exhaustive. In particular, `runtime`
must not import `broker`: the agent loop may mint a capability and hand it off,
but it must hold no symbol capable of external execution.

The future Streamlit application under `ui/` must not import from `src/warden/`.
It communicates with FastAPI over HTTP, opens no database connection, and
evaluates no policy in process.

These boundaries are enforced by architecture tests. If a feature appears to
require another edge, the design must be reconsidered rather than bypassed.

## Decision path

Every external action follows this order:

1. The runtime emits an intent containing the tool, parameters, and provenance.
2. The policy engine evaluates and records an allow, deny, or escalate decision.
3. An allow decision mints a parameter-bound, single-use capability.
4. The broker verifies and consumes the capability before invoking a connector.
5. The execution result is recorded.

The policy condition evaluator performs no I/O, reads no clock except one supplied
in its input, and uses no randomness. Any error in the decision path fails closed.
