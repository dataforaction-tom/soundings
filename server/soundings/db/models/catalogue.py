from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from soundings.db.models import Base


class Source(Base):
    __tablename__ = "source"
    __table_args__ = (
        CheckConstraint("mode IN ('loader', 'passthrough')", name="ck_source_mode"),
        {"schema": "catalogue"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    publisher_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    licence: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))
    refresh_cadence: Mapped[str | None] = mapped_column(Text, nullable=True)
    rate_limit: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Indicator(Base):
    __tablename__ = "indicator"
    __table_args__ = ({"schema": "catalogue"},)

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str] = mapped_column(String(64))
    higher_is: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalogue.source.id"))
    available_at: Mapped[list[str]] = mapped_column(ARRAY(String))
    refresh_cadence: Mapped[str | None] = mapped_column(Text, nullable=True)
    caveats: Mapped[list[str]] = mapped_column(JSONB, default=list)
    related_keys: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    catalogue_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
