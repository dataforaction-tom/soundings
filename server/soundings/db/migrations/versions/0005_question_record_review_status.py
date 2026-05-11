"""question_record review_status + sanitisation_rules_version

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-11

Phase 2 Task 15. Adds the two columns the sanitiser worker (Task 16)
writes when it processes a raw_record. `review_status` defaults to
'pending' for back-fill — every existing row is treated as un-sanitised
until the replay job (Task 19) catches up.

Values for review_status:
    pending  — not yet sanitised; raw_record is still present.
    cleared  — sanitised, total_fires < 2, safe to publish.
    flagged  — sanitised, total_fires >= 2, needs human review.
    released — explicitly approved for publication after flag review.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "question_record",
        sa.Column(
            "review_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        schema="corpus",
    )
    op.add_column(
        "question_record",
        sa.Column(
            "sanitisation_rules_version",
            sa.String(length=32),
            nullable=True,
        ),
        schema="corpus",
    )


def downgrade() -> None:
    op.drop_column("question_record", "sanitisation_rules_version", schema="corpus")
    op.drop_column("question_record", "review_status", schema="corpus")
