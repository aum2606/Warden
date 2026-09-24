# AGENTS.md

Engineering contract for Warden. This file is binding. Read it in full at the
start of every session, before writing any code.

## Project

Warden is a permission and approval gateway for LLM agents with write access.
An agent cannot call a tool directly: every tool call is an intent that passes a
policy decision point first, and only an allow decision mints a single-use,
parameter-bound capability that the broker will execute.

The full specification is `docs/SPEC.md`. It is authoritative. Where the code and
the spec disagree, the spec wins. If you believe the spec is wrong, stop and say
so; do not resolve the conflict by writing different code.

## Documents to read before working

| File | What it holds |
| --- | --- |
| `docs/SPEC.md` | The full specification: domain model, authorization model, data model, architecture |
| `docs/ARCHITECTURE.md` | Module boundaries and the import rules |
| `docs/SESSIONS.md` | The fifteen build sessions with objectives and exit conditions |
| `DECISIONS.md` | Every implementation decision the spec did not cover |

## Working rules

- Work only within the current session's stated scope. Do not implement future
  sessions, even when the next step seems obvious.
- Finish at the exit condition. Not before, not after.
- If a decision is required that the documents do not cover, stop and ask.
  Once it is decided, append it to `DECISIONS.md` in the same pull request as
  the code that embodies it.
- Never modify a file outside the session's scope without saying why.
- Never weaken a test to make it pass.

## Language and tooling

| Concern | Choice |
| --- | --- |
| Language | Python 3.12 |
| Packaging | `uv`, lockfile committed |
| Format and lint | `ruff format`, `ruff check` — zero warnings on main |
| Types | `mypy --strict` on `src/` — zero errors on main |
| Tests | `pytest`, `pytest-asyncio`, `hypothesis` |
| Migrations | Alembic, one per schema change, never edited after merge |
| Settings | `pydantic-settings`, environment-driven |
| Logging | `structlog`, JSON output |

## Code standards

**Types.** Full annotations on every signature. No bare `Any`, no implicit
`Optional`. Use domain types rather than primitives: `RunId`, `PrincipalId`,
`Fingerprint`, `Scope`. A system about authority that passes bare strings around
has lost its own distinctions.

**Errors.** Each module defines its own exception hierarchy in `errors.py`. No
bare `except`. No exception used for control flow across a module boundary. No
swallowed exceptions.

**Fail closed.** Any error in the decision path results in a deny. There is no
code path where a failure lets an action proceed. Each failure mode has a test
proving it denies.

**Purity.** The policy condition evaluator performs no I/O, opens no connection,
reads no clock except one injected through its input, and uses no randomness.
This is a requirement, not a preference: offline fixtures and decision recompute
both depend on it.

**Logging.** One structured event per line, stable event name, typed fields. No
f-string log messages. No `print`. No banners, separators or decorative output.

**No emoji.** Not in code, comments, docstrings, log output, commit messages,
test names, documentation, or console output. Anywhere.

**Comments and docstrings.** Docstrings on public modules, classes and
functions. A docstring that restates the signature is noise. A comment that
explains why a non-obvious choice was made is valuable. No `TODO` comments:
unfinished work is an issue or it does not exist.

**Tests.** Names state the assertion:
`test_capability_is_rejected_when_recipient_differs_from_fingerprint`. The suite
is a document about the system's guarantees and reads as one. Nothing in the
suite may require a live model or a live external API.

## Architecture constraints

These are enforced by tests. Do not work around them.

- `runtime` must not import `broker`. The agent loop can mint a capability and
  hand it off; it holds no symbol capable of executing anything.
- `ui/` must not import anything from `src/warden/`. The Streamlit application
  communicates with the API over HTTP only, opens no database connection, and
  evaluates no policy in process.
- `executions.capability_id` is `NOT NULL` with a foreign key. An execution
  without a capability must be impossible at the schema level.
- `decisions`, `capabilities` and `audit_events` are append-only. The
  application role has no `UPDATE` grant on them, except `capabilities.consumed_at`
  via a conditional update guarded on `consumed_at IS NULL`.

## Git workflow

- One branch per session: `session/NN-short-slug`.
- Small commits, each leaving the suite green.
- Conventional Commits, no emoji:
  `feat(policy): add condition evaluator with injected clock`
- Scopes are the module names: identity, policy, capability, broker, runtime,
  knowledge, audit, ui, ci, docs, decisions.
- The body explains why when the subject cannot.
- No generated-by trailers. No co-author attribution to a tool.
- Never force-push a pushed branch.
- Never commit secrets, `.env` files or credentials.
- Push the branch and open a pull request before the session ends. Do not merge
  it yourself.

## Definition of done

A session is complete when all of these hold. State each explicitly in your
closing message:

1. The stated exit condition passes, demonstrated with command output.
2. `ruff format --check .`, `ruff check .`, `mypy --strict src/` and `pytest`
   are all clean.
3. New behaviour has tests, and the full suite passes.
4. No file outside the session's stated scope is modified.
5. `DECISIONS.md` records any decision the documents did not cover.
6. The branch is pushed and a pull request is open, describing what changed,
   which exit condition it satisfies, how to verify it, and any decision logged.
