import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from soundings.db.models import Base


class QuestionRecord(Base):
    __tablename__ = "question_record"
    __table_args__ = ({"schema": "corpus"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    consent_version: Mapped[str] = mapped_column(String(32))
    capture_level: Mapped[str] = mapped_column(String(16))

    natural_language_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_called: Mapped[str] = mapped_column(String(64))
    tool_inputs_redacted: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    geography_referenced: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    indicators_returned: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    sources_used: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    result_status: Mapped[str] = mapped_column(String(16))
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)

    asker_sector: Mapped[str | None] = mapped_column(String(32), nullable=True)
    asker_purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    marked_useful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # v1.5 fields, nullable until then
    composed_artefact: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    gap_signals: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    derived_from_question_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("corpus.question_record.id"), nullable=True
    )


class RawRecord(Base):
    __tablename__ = "raw_record"
    __table_args__ = ({"schema": "corpus"},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("corpus.question_record.id"),
        primary_key=True,
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
