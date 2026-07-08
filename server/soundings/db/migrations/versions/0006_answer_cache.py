"""answer_cache table for caching composed ask responses

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-07

Stores the full SSE event list for a normalised question + place_id so
identical questions can be replayed without calling Claude. Keyed by
SHA-256 hash of (normalised_question, place_id).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "answer_cache",
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("place_id", sa.Text(), nullable=True),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("question_hash"),
        schema="cache",
    )
    op.create_index(
        "ix_answer_cache_expires_at",
        "answer_cache",
        ["expires_at"],
        schema="cache",
    )


def downgrade() -> None:
    op.drop_index("ix_answer_cache_expires_at", schema="cache", table_name="answer_cache")
    op.drop_table("answer_cache", schema="cache")
