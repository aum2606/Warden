"""Atomic loading and canonical digesting of policy YAML documents."""

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from .errors import EmptyPolicyBundleError, InvalidPolicyDocumentError
from .models import PolicyDocument, PolicyRuleId
from .types import PolicyBundle, SourceDigest


def load_policy_bundle(directory: Path) -> PolicyBundle:
    """Load every YAML policy or reject the bundle without returning a partial result."""
    document_paths = sorted(directory.glob("*.yaml"), key=lambda path: path.name)
    if not document_paths:
        message = f"no policy documents found in {directory}"
        raise EmptyPolicyBundleError(message)

    documents: list[PolicyDocument] = []
    document_names: dict[PolicyRuleId, str] = {}
    for path in document_paths:
        document = _load_document(path)
        previous_name = document_names.get(document.id)
        if previous_name is not None:
            detail = f"duplicate rule id {document.id!s}; first declared in {previous_name}"
            raise InvalidPolicyDocumentError(path.name, detail)
        document_names[document.id] = path.name
        documents.append(document)

    rules = tuple(sorted(documents, key=lambda document: str(document.id)))
    return PolicyBundle(rules=rules, source_digest=_source_digest(rules))


def _load_document(path: Path) -> PolicyDocument:
    try:
        source = path.read_text(encoding="utf-8")
        raw_document: object = yaml.safe_load(source)
        return PolicyDocument.model_validate(raw_document)
    except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as error:
        raise InvalidPolicyDocumentError(path.name, str(error)) from error


def _source_digest(rules: tuple[PolicyDocument, ...]) -> SourceDigest:
    canonical_documents = [rule.model_dump(mode="json") for rule in rules]
    canonical_source = json.dumps(
        canonical_documents,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return SourceDigest(hashlib.sha256(canonical_source).hexdigest())
