"""Connector protocol plus fake and live GitHub implementations."""

from collections.abc import Mapping
from typing import Final, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from warden.capability.canonicalization import FingerprintSchema
from warden.capability.types import JsonValue, ToolName

from .errors import ConnectorInvocationError
from .types import ConnectorInvocation, ConnectorResult, ToolDescription

_GITHUB_API_VERSION: Final = "2026-03-10"
_REPO_PATTERN: Final = r"^[^/\s]+/[^/\s]+$"


class Connector(Protocol):
    """Expose only schema discovery and credential-scoped invocation."""

    def describe(self) -> tuple[ToolDescription, ...]:
        """Return every supported tool and its fingerprint declaration."""
        ...

    async def invoke(
        self,
        tool: ToolName,
        params: Mapping[str, JsonValue],
        credential: SecretStr,
    ) -> ConnectorResult:
        """Invoke one described tool with broker-supplied credential material."""
        ...


class _StrictParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _RepositoryParameters(_StrictParameters):
    repo: str = Field(pattern=_REPO_PATTERN)


class _IssueCreateParameters(_RepositoryParameters):
    title: str = Field(min_length=1)
    body: str


class _IssueCommentParameters(_RepositoryParameters):
    issue_number: int = Field(gt=0)
    body: str


class _RepositoryResponse(BaseModel):
    id: int
    full_name: str
    html_url: str
    default_branch: str
    private: bool


class _IssueResponse(BaseModel):
    id: int
    number: int
    title: str
    body: str | None
    html_url: str
    state: str


class _CommentResponse(BaseModel):
    id: int
    body: str | None
    html_url: str


_REPO_READ = ToolName("github.repo.read")
_ISSUE_CREATE = ToolName("github.issue.create")
_ISSUE_COMMENT = ToolName("github.issue.comment")

_GITHUB_TOOLS: Final = (
    ToolDescription(
        name=_REPO_READ,
        description="Read repository metadata",
        parameter_schema={
            "type": "object",
            "properties": {"repo": {"type": "string"}},
            "required": ["repo"],
            "additionalProperties": False,
        },
        fingerprint_schema=FingerprintSchema(fields=("repo",)),
    ),
    ToolDescription(
        name=_ISSUE_CREATE,
        description="Create an issue in a repository",
        parameter_schema={
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["repo", "title", "body"],
            "additionalProperties": False,
        },
        fingerprint_schema=FingerprintSchema(
            fields=("repo", "title", "body"),
            free_text_fields=frozenset({"body"}),
        ),
    ),
    ToolDescription(
        name=_ISSUE_COMMENT,
        description="Comment on an issue in a repository",
        parameter_schema={
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "issue_number": {"type": "integer", "minimum": 1},
                "body": {"type": "string"},
            },
            "required": ["repo", "issue_number", "body"],
            "additionalProperties": False,
        },
        fingerprint_schema=FingerprintSchema(
            fields=("repo", "issue_number", "body"),
            free_text_fields=frozenset({"body"}),
        ),
    ),
)


class FakeGitHubConnector:
    """Return deterministic GitHub-shaped results and retain credential-free calls."""

    def __init__(self) -> None:
        """Create a fake with an empty invocation history."""
        self.invocations: list[ConnectorInvocation] = []

    def describe(self) -> tuple[ToolDescription, ...]:
        """Return the same declarations used by the live connector."""
        return _GITHUB_TOOLS

    async def invoke(
        self,
        tool: ToolName,
        params: Mapping[str, JsonValue],
        credential: SecretStr,
    ) -> ConnectorResult:
        """Validate and record a call without retaining the supplied credential."""
        validated = _validate_parameters(tool, params)
        if not credential.get_secret_value():
            message = "GitHub credential is empty"
            raise ConnectorInvocationError(message)
        copied = _copy_mapping(params)
        self.invocations.append(ConnectorInvocation(tool=tool, parameters=copied))
        if isinstance(validated, _RepositoryParameters) and not isinstance(
            validated,
            (_IssueCreateParameters, _IssueCommentParameters),
        ):
            return {
                "id": 1,
                "full_name": validated.repo,
                "html_url": f"https://github.com/{validated.repo}",
                "default_branch": "main",
                "private": False,
            }
        if isinstance(validated, _IssueCreateParameters):
            return {
                "id": len(self.invocations),
                "number": len(self.invocations),
                "title": validated.title,
                "body": validated.body,
                "html_url": f"https://github.com/{validated.repo}/issues/{len(self.invocations)}",
                "state": "open",
            }
        return {
            "id": len(self.invocations),
            "body": validated.body,
            "html_url": (
                f"https://github.com/{validated.repo}/issues/"
                f"{validated.issue_number}#issuecomment-{len(self.invocations)}"
            ),
        }


class GitHubConnector:
    """Invoke the three governed GitHub tools through the REST API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Use a caller-owned HTTP client so connection lifetime stays explicit."""
        self._client = client

    def describe(self) -> tuple[ToolDescription, ...]:
        """Declare every supported GitHub tool and fingerprinted field."""
        return _GITHUB_TOOLS

    async def invoke(
        self,
        tool: ToolName,
        params: Mapping[str, JsonValue],
        credential: SecretStr,
    ) -> ConnectorResult:
        """Validate parameters and invoke exactly the named GitHub endpoint."""
        validated = _validate_parameters(tool, params)
        owner, repository = validated.repo.split("/", maxsplit=1)
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {credential.get_secret_value()}",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }
        try:
            if isinstance(validated, _IssueCreateParameters):
                response = await self._client.post(
                    f"/repos/{owner}/{repository}/issues",
                    headers=headers,
                    json={"title": validated.title, "body": validated.body},
                )
                return _issue_result(response)
            if isinstance(validated, _IssueCommentParameters):
                response = await self._client.post(
                    f"/repos/{owner}/{repository}/issues/{validated.issue_number}/comments",
                    headers=headers,
                    json={"body": validated.body},
                )
                return _comment_result(response)
            response = await self._client.get(
                f"/repos/{owner}/{repository}",
                headers=headers,
            )
            return _repository_result(response)
        except (httpx.HTTPError, ValidationError):
            message = "GitHub connector invocation failed"
            raise ConnectorInvocationError(message) from None


def _validate_parameters(
    tool: ToolName,
    params: Mapping[str, JsonValue],
) -> _RepositoryParameters | _IssueCreateParameters | _IssueCommentParameters:
    try:
        if tool == _REPO_READ:
            return _RepositoryParameters.model_validate(params)
        if tool == _ISSUE_CREATE:
            return _IssueCreateParameters.model_validate(params)
        if tool == _ISSUE_COMMENT:
            return _IssueCommentParameters.model_validate(params)
    except ValidationError as error:
        message = f"parameters for {tool!s} are invalid"
        raise ConnectorInvocationError(message) from error
    message = f"GitHub connector does not support tool {tool!s}"
    raise ConnectorInvocationError(message)


def _repository_result(response: httpx.Response) -> ConnectorResult:
    _require_success(response)
    model = _RepositoryResponse.model_validate_json(response.content)
    return {
        "id": model.id,
        "full_name": model.full_name,
        "html_url": model.html_url,
        "default_branch": model.default_branch,
        "private": model.private,
    }


def _issue_result(response: httpx.Response) -> ConnectorResult:
    _require_success(response)
    model = _IssueResponse.model_validate_json(response.content)
    return {
        "id": model.id,
        "number": model.number,
        "title": model.title,
        "body": model.body,
        "html_url": model.html_url,
        "state": model.state,
    }


def _comment_result(response: httpx.Response) -> ConnectorResult:
    _require_success(response)
    model = _CommentResponse.model_validate_json(response.content)
    return {"id": model.id, "body": model.body, "html_url": model.html_url}


def _require_success(response: httpx.Response) -> None:
    if response.is_success:
        return
    message = f"GitHub API returned status {response.status_code}"
    raise ConnectorInvocationError(message)


def _copy_mapping(params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: _copy_value(value) for key, value in params.items()}


def _copy_value(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _copy_value(item) for key, item in value.items()}
    return value
