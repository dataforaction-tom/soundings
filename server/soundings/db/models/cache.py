from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from soundings.db.models import Base


class SourceCache(Base):
    __tablename__ = "source_cache"
    __table_args__ = ({"schema": "cache"},)

    source_id: Mapped[str] = mapped_column(
        ForeignKey("catalogue.source.id"), primary_key=True
    )
    cache_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
