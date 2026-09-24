"""Exceptions owned by the policy module."""


class PolicyError(Exception):
    """Base class for policy module failures."""


class PolicyBundleError(PolicyError):
    """Base class for policy bundle loading failures."""


class InvalidPolicyDocumentError(PolicyBundleError):
    """Report a policy document that prevents the bundle from loading."""

    def __init__(self, document_name: str, detail: str) -> None:
        """Retain the offending document name for callers and diagnostics."""
        self.document_name = document_name
        self.detail = detail
        super().__init__(f"invalid policy document {document_name}: {detail}")


class EmptyPolicyBundleError(PolicyBundleError):
    """Report a policy directory containing no policy documents."""
