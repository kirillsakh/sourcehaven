"""Drop document_versions.detected_language: the product supports English only.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("document_versions", "detected_language")


def downgrade() -> None:
    op.add_column("document_versions", sa.Column("detected_language", sa.Text(), nullable=True))
