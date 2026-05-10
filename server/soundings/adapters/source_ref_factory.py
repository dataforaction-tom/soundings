"""Single source of truth for SourceRef construction.

Both LoaderAdapter and PassthroughAdapter delegate here so SourceRef shape
stays consistent and there's one place to evolve the contract.
"""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.contracts.source_ref import CacheStatus, SourceRef


class SourceRefFactory:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def build(
        self,
        source_id: str,
        *,
        retrieved_at: datetime,
        cache_status: CacheStatus,
    ) -> SourceRef | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, label, publisher, publisher_url, dataset_url, licence "
                        "FROM catalogue.source WHERE id = :sid"
                    ),
                    {"sid": source_id},
                )
            ).first()
        if row is None:
            return None
        return SourceRef(
            source_id=row.id,
            source_label=row.label,
            publisher=row.publisher,
            publisher_url=row.publisher_url,
            dataset_url=row.dataset_url,
            retrieved_at=retrieved_at,
            cache_status=cache_status,
            licence=row.licence,
        )
