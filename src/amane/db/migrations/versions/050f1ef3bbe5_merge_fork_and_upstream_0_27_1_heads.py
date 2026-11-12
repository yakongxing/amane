"""merge fork and upstream 0.27.1 heads

Revision ID: 050f1ef3bbe5
Revises: 6f7f96674f11, e06def65f72a
Create Date: 2026-11-12 08:31:55.666113
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "050f1ef3bbe5"
down_revision: str | None = ("6f7f96674f11", "e06def65f72a")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
