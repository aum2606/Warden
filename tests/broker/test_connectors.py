"""Connector protocol and GitHub fake and live-client unit tests."""

import inspect

import httpx
import pytest
from pydantic import SecretStr

from warden.broker.connectors import Connector, FakeGitHubConnector, GitHubConnector
from warden.broker.errors import ConnectorInvocationError
from warden.broker.registry import fingerprint_registry
from warden.capability.canonicalization import fingerprint_parameters
from warden.capability.types import ToolName

_SECRET = "github-secret-that-must-not-escape"


def test_connector_protocol_exposes_exactly_describe_and_invoke() -> None:
    """Connector implementations cannot receive governance or runtime objects."""
    methods = {
        name
        for name, member in inspect.getmembers(Connector, predicate=inspect.isfunction)
        if not name.startswith("_")
    }

    assert methods == {"describe", "invoke"}


def test_github_connector_declares_three_complete_fingerprint_schemas() -> None:
    """Every action-changing GitHub parameter is connector-declared and bound."""
    descriptions = {item.name: item for item in FakeGitHubConnector().describe()}

    assert set(descriptions) == {
        ToolName("github.repo.read"),
        ToolName("github.issue.create"),
        ToolName("github.issue.comment"),
    }
    assert descriptions[ToolName("github.repo.read")].fingerprint_schema.fields == ("repo",)
    assert descriptions[ToolName("github.issue.create")].fingerprint_schema.fields == (
        "repo",
        "title",
        "body",
    )
    assert descriptions[ToolName("github.issue.comment")].fingerprint_schema.fields == (
        "repo",
        "issue_number",
        "body",
    )
    assert descriptions[ToolName("github.issue.create")].fingerprint_schema.free_text_fields == (
        frozenset({"body"})
    )
    assert descriptions[ToolName("github.repo.read")].parameter_schema["required"] == ["repo"]
    assert descriptions[ToolName("github.issue.create")].parameter_schema["required"] == [
        "repo",
        "title",
        "body",
    ]
    assert descriptions[ToolName("github.issue.comment")].parameter_schema["required"] == [
        "repo",
        "issue_number",
        "body",
    ]


def test_connector_descriptions_populate_the_operational_fingerprint_registry() -> None:
    """Capability binding derives from connector declarations rather than caller fields."""
    registry = fingerprint_registry((FakeGitHubConnector(),))
    params = {"repo": "aum2606/Warden", "title": "Finding", "body": "Evidence"}

    fingerprint = fingerprint_parameters(ToolName("github.issue.create"), params, registry)

    assert str(fingerprint).startswith("sha256:")


async def test_fake_connector_records_tool_and_real_parameters_but_not_credential() -> None:
    """The fake retains observable calls without retaining broker secret material."""
    connector = FakeGitHubConnector()
    params = {"repo": "aum2606/Warden", "title": "Finding", "body": "Full body"}

    result = await connector.invoke(
        ToolName("github.issue.create"),
        params,
        SecretStr(_SECRET),
    )

    assert connector.invocations[0].parameters == params
    assert _SECRET not in repr(connector.invocations[0])
    assert result["title"] == "Finding"


@pytest.mark.parametrize(
    ("tool", "parameters", "method", "path"),
    [
        pytest.param(
            ToolName("github.repo.read"),
            {"repo": "aum2606/Warden"},
            "GET",
            "/repos/aum2606/Warden",
            id="repository-read",
        ),
        pytest.param(
            ToolName("github.issue.create"),
            {"repo": "aum2606/Warden", "title": "Finding", "body": "Evidence"},
            "POST",
            "/repos/aum2606/Warden/issues",
            id="issue-create",
        ),
        pytest.param(
            ToolName("github.issue.comment"),
            {"repo": "aum2606/Warden", "issue_number": 7, "body": "Evidence"},
            "POST",
            "/repos/aum2606/Warden/issues/7/comments",
            id="issue-comment",
        ),
    ],
)
async def test_live_connector_uses_the_declared_github_endpoint(
    tool: ToolName,
    parameters: dict[str, object],
    method: str,
    path: str,
) -> None:
    """The live client maps each governed tool to its official REST endpoint."""
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        if tool == ToolName("github.repo.read"):
            payload = {
                "id": 1,
                "full_name": "aum2606/Warden",
                "html_url": "https://github.com/aum2606/Warden",
                "default_branch": "main",
                "private": False,
            }
        elif tool == ToolName("github.issue.create"):
            payload = {
                "id": 2,
                "number": 7,
                "title": "Finding",
                "body": "Evidence",
                "html_url": "https://github.com/aum2606/Warden/issues/7",
                "state": "open",
            }
        else:
            payload = {
                "id": 3,
                "body": "Evidence",
                "html_url": "https://github.com/aum2606/Warden/issues/7#issuecomment-3",
            }
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        await GitHubConnector(client).invoke(tool, parameters, SecretStr(_SECRET))

    assert seen_request is not None
    assert seen_request.method == method
    assert seen_request.url.path == path
    assert seen_request.headers["Authorization"] == f"Bearer {_SECRET}"


async def test_live_connector_error_exposes_neither_credential_nor_response_payload() -> None:
    """Connector failures cross the broker boundary as sanitized module errors."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": _SECRET})

    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(ConnectorInvocationError) as captured:
            await GitHubConnector(client).invoke(
                ToolName("github.repo.read"),
                {"repo": "aum2606/Warden"},
                SecretStr(_SECRET),
            )

    assert _SECRET not in str(captured.value)
    assert captured.value.__cause__ is None
