"""Policy inspection and simulation endpoint tests."""

from http import HTTPStatus

import httpx
from sqlalchemy import func, select

from warden.database import AsyncSessionFactory
from warden.policy.records import DecisionRecord

_SHA256_HEX_LENGTH = 64


async def test_get_policies_returns_current_version_digest_and_rules(
    client: httpx.AsyncClient,
) -> None:
    """Bundle inspection exposes its stable identity and validated documents."""
    response = await client.get("/policies")

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["version"] == 1
    assert len(payload["digest"]) == _SHA256_HEX_LENGTH
    assert {rule["id"] for rule in payload["rules"]} >= {
        "default-deny",
        "gmail-external-send",
    }


async def test_simulate_returns_decision_without_recording(
    client: httpx.AsyncClient,
    session_factory: AsyncSessionFactory,
) -> None:
    """Simulation evaluates current policy without creating durable authority state."""
    response = await client.post(
        "/policies/simulate",
        json={
            "principal": "agent:ops-worker",
            "authority_chain": [
                "user:aum",
                "agent:orchestrator",
                "agent:ops-worker",
            ],
            "tool": "gmail.send",
            "params": {
                "to": ["reviewer@external.example"],
                "subject": "Review",
                "attachment_count": 0,
            },
            "context": {"min_trust": "internal", "sources": ["chunk-1"]},
            "run": {"run_id": "run-simulated", "prior_denials": 0},
            "environment": {"current_time": "2026-09-24T09:00:00Z"},
        },
    )
    async with session_factory() as session:
        decision_count = await session.scalar(select(func.count()).select_from(DecisionRecord))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["effect"] == "escalate"
    assert response.json()["rule_id"] == "gmail-external-send"
    assert response.json()["failed_condition_ids"] == ["recipient-domain"]
    assert decision_count == 0
