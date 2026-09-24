"""Explicit tool-schema canonicalization and fingerprint property tests."""

from collections import OrderedDict

import pytest
from hypothesis import given
from hypothesis import strategies as st

from warden.capability.canonicalization import (
    DEFAULT_FINGERPRINT_SCHEMAS,
    GITHUB_ISSUE_CREATE_SCHEMA,
    GMAIL_SEND_SCHEMA,
    canonicalize_parameters,
    fingerprint_parameters,
)
from warden.capability.errors import UnregisteredToolError
from warden.policy.models import ToolName


def test_github_issue_fingerprinted_fields_match_declared_schema() -> None:
    """GitHub issue binding covers the repository, title, and hashed body."""
    assert GITHUB_ISSUE_CREATE_SCHEMA.fields == ("repo", "title", "body")
    assert GITHUB_ISSUE_CREATE_SCHEMA.free_text_fields == frozenset({"body"})


def test_gmail_send_fingerprinted_fields_match_declared_schema() -> None:
    """Gmail binding covers recipients, subject, hashed body, and attachments."""
    assert GMAIL_SEND_SCHEMA.fields == ("to", "subject", "body", "attachment_count")
    assert GMAIL_SEND_SCHEMA.recipient_fields == frozenset({"to"})
    assert GMAIL_SEND_SCHEMA.free_text_fields == frozenset({"body"})


def test_unregistered_tool_has_no_fingerprint_fallback() -> None:
    """Unknown tools use neither all fields nor an empty field set."""
    with pytest.raises(UnregisteredToolError, match="no fingerprint schema"):
        fingerprint_parameters(
            ToolName("unknown.write"),
            {"target": "value"},
            DEFAULT_FINGERPRINT_SCHEMAS,
        )


@given(
    repo=st.text(min_size=1).filter(str.strip),
    title=st.text(min_size=1).filter(str.strip),
    body=st.text(),
)
def test_fingerprint_is_stable_under_key_reordering(
    repo: str,
    title: str,
    body: str,
) -> None:
    """Mapping insertion order cannot change a parameter fingerprint."""
    first = OrderedDict((("repo", repo), ("title", title), ("body", body)))
    second = OrderedDict(reversed(tuple(first.items())))

    assert fingerprint_parameters(ToolName("github.issue.create"), first) == (
        fingerprint_parameters(ToolName("github.issue.create"), second)
    )


@given(
    words=st.lists(
        st.text(
            alphabet=st.characters(blacklist_categories=("Z", "C")),
            min_size=1,
        ).filter(str.strip),
        min_size=1,
        max_size=6,
    )
)
def test_fingerprint_is_stable_under_whitespace_variation(words: list[str]) -> None:
    """Equivalent spacing in ordinary and free-text values canonicalizes equally."""
    normalized = " ".join(words)
    varied = " \t\n ".join(words)
    first = {"repo": "aum2606/Warden", "title": normalized, "body": normalized}
    second = {"repo": "aum2606/Warden", "title": varied, "body": varied}

    assert fingerprint_parameters(ToolName("github.issue.create"), first) == (
        fingerprint_parameters(ToolName("github.issue.create"), second)
    )


@given(
    first_count=st.integers(min_value=0, max_value=100),
    delta=st.integers(min_value=1, max_value=100),
)
def test_semantically_different_parameters_do_not_collide(
    first_count: int,
    delta: int,
) -> None:
    """Changing a declared action parameter always changes its fingerprint."""
    base = {
        "to": ["reviewer@acme.example"],
        "subject": "Review",
        "body": "Evidence",
        "attachment_count": first_count,
    }
    changed = {**base, "attachment_count": first_count + delta}

    assert fingerprint_parameters(ToolName("gmail.send"), base) != fingerprint_parameters(
        ToolName("gmail.send"), changed
    )


def test_recipient_order_case_and_undeclared_fields_do_not_change_fingerprint() -> None:
    """Recipient sets normalize while undeclared volatile values stay excluded."""
    first = {
        "to": ["B@Acme.Example", "a@acme.example"],
        "subject": "Review",
        "body": "Evidence",
        "attachment_count": 0,
        "request_id": "first",
    }
    second = {
        "to": ["A@ACME.EXAMPLE", "b@acme.example"],
        "subject": "Review",
        "body": "Evidence",
        "attachment_count": 0,
        "request_id": "second",
    }

    assert fingerprint_parameters(ToolName("gmail.send"), first) == fingerprint_parameters(
        ToolName("gmail.send"), second
    )


def test_free_text_is_hashed_instead_of_embedded_in_canonical_parameters() -> None:
    """A capability canonical form does not carry the sensitive message body."""
    body = "Confidential supporting evidence"

    canonical = canonicalize_parameters(
        ToolName("github.issue.create"),
        {"repo": "aum2606/Warden", "title": "Review", "body": body},
    )

    assert body.encode() not in canonical
    assert b'"body":"sha256:' in canonical
