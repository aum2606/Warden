"""Port for recording capability verification rejections."""

from typing import Protocol

from .types import CapabilityRejection


class RejectionRecorder(Protocol):
    """Record every failed verification for the audit module to persist later."""

    async def record(self, rejection: CapabilityRejection) -> None:
        """Record one rejection or raise when durability cannot be guaranteed."""
        ...


class InMemoryRejectionRecorder:
    """Collect rejections deterministically for tests and local composition."""

    def __init__(self) -> None:
        """Create an empty rejection collection."""
        self.rejections: list[CapabilityRejection] = []

    async def record(self, rejection: CapabilityRejection) -> None:
        """Append one rejection in call order."""
        self.rejections.append(rejection)
