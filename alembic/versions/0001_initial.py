"""Create the empty initial revision.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-23
"""

from collections.abc import Sequence

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Leave the schema empty for the scaffolding session."""


def downgrade() -> None:
    """Leave the schema empty when reverting the scaffolding revision."""
