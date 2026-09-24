"""Policy bundle loading and validation tests."""

from pathlib import Path

import pytest

from warden.policy.errors import InvalidPolicyDocumentError
from warden.policy.loader import load_policy_bundle

_REPOSITORY_POLICIES = Path(__file__).parents[2] / "policies"
_SHA256_HEX_LENGTH = 64
_MINIMAL_POLICY = """\
version: 1
id: sample-rule
description: Sample rule
priority: 10
match:
  tool: sample.read
  principal:
    kind: agent
    id: [sample-agent]
conditions: []
effect:
  when_all_true: allow
  when_any_false: deny
escalation: null
obligations: []
"""


def test_repository_bundle_loads_with_stable_digest() -> None:
    """Repeated loads of the versioned policy sources produce one stable digest."""
    first = load_policy_bundle(_REPOSITORY_POLICIES)
    second = load_policy_bundle(_REPOSITORY_POLICIES)

    assert first.source_digest == second.source_digest
    assert len(first.source_digest) == _SHA256_HEX_LENGTH
    assert {str(rule.id) for rule in first.rules} == {
        "default-deny",
        "delegate",
        "github-issue-create",
        "gmail-external-send",
        "memory-org-write",
    }


def test_source_digest_is_stable_across_yaml_formatting(tmp_path: Path) -> None:
    """Formatting and mapping order do not change a validated bundle's identity."""
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    first_directory.mkdir()
    second_directory.mkdir()
    (first_directory / "rule.yaml").write_text(_MINIMAL_POLICY, encoding="utf-8")
    (second_directory / "renamed.yaml").write_text(
        """\
id: sample-rule
version: 1
priority: 10
description: Sample rule
conditions: []
match: {tool: sample.read, principal: {id: [sample-agent], kind: agent}}
obligations: []
escalation: null
effect: {when_any_false: deny, when_all_true: allow}
""",
        encoding="utf-8",
    )

    first = load_policy_bundle(first_directory)
    second = load_policy_bundle(second_directory)

    assert first.source_digest == second.source_digest


def test_invalid_document_refuses_entire_bundle_and_names_document(tmp_path: Path) -> None:
    """One invalid document prevents valid neighbors from being returned as a bundle."""
    (tmp_path / "01-valid.yaml").write_text(_MINIMAL_POLICY, encoding="utf-8")
    (tmp_path / "02-invalid.yaml").write_text(
        """\
version: 1
id: invalid-rule
description: Missing required schema fields
priority: 1
""",
        encoding="utf-8",
    )

    with pytest.raises(InvalidPolicyDocumentError, match=r"02-invalid\.yaml") as raised:
        load_policy_bundle(tmp_path)

    assert raised.value.document_name == "02-invalid.yaml"


def test_duplicate_rule_id_refuses_entire_bundle_and_names_second_document(
    tmp_path: Path,
) -> None:
    """Rule identifiers remain unique across an atomically loaded bundle."""
    (tmp_path / "first.yaml").write_text(_MINIMAL_POLICY, encoding="utf-8")
    (tmp_path / "second.yaml").write_text(_MINIMAL_POLICY, encoding="utf-8")

    with pytest.raises(InvalidPolicyDocumentError, match=r"second\.yaml") as raised:
        load_policy_bundle(tmp_path)

    assert raised.value.document_name == "second.yaml"


def test_policy_document_refuses_fields_outside_version_one_schema(tmp_path: Path) -> None:
    """Policy authors cannot introduce silently ignored schema fields."""
    (tmp_path / "unexpected-field.yaml").write_text(
        f"{_MINIMAL_POLICY}unexpected: true\n",
        encoding="utf-8",
    )

    with pytest.raises(
        InvalidPolicyDocumentError,
        match=r"unexpected-field\.yaml",
    ):
        load_policy_bundle(tmp_path)
