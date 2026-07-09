"""add lat/lon to geography.postcode

Revision ID: 0007_postcode_latlon
Revises: 0006_answer_cache
Create Date: 2026-07-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_postcode_latlon"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "postcode",
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        schema="geography",
    )
    op.add_column(
        "postcode",
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        schema="geography",
    )


def downgrade() -> None:
    op.drop_column("postcode", "longitude", schema="geography")
    op.drop_column("postcode", "latitude", schema="geography")
