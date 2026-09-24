# Warden

Warden is a permission and approval gateway for LLM agents with write access.
Every proposed tool action is evaluated before execution, and only an allow
decision can produce a single-use, parameter-bound capability. This repository
currently includes typed identities, role-based sessions, and authority ceilings.

## Prerequisites

- Python 3.12
- uv
- Docker with Docker Compose

## Run locally

Create the local environment file and start the application with Postgres 16 and
the pgvector extension:

```shell
cp .env.example .env
docker compose up --build -d
```

Replace the placeholder signing secret and seed password in `.env` before
starting the services. Apply the schema and load the local identity fixture with:

```shell
uv run alembic upgrade head
uv run warden-seed
```

The fixture creates `owner@warden.local`, `approver@warden.local`, and
`member@warden.local` with the password supplied through `SEED_PASSWORD`.

The health endpoint is available at `http://localhost:8000/health`. Stop the
services with `docker compose down`.

## Run checks and tests

Install the locked development environment, then run the same checks as CI:

```shell
uv sync --frozen --dev
uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src/
uv run pytest
```
