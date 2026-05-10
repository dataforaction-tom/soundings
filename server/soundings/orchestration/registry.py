"""AdapterRegistry — single dispatch table for indicator → adapter.

Tools never instantiate adapters directly. They ask the registry, which
caches a lazily-built adapter per source.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.orchestration.errors import IndicatorNotRegisteredError

AdapterFactory = Callable[[AsyncEngine], Any]


class AdapterRegistry:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._factories: dict[str, AdapterFactory] = {}
        self._instances: dict[str, Any] = {}

    def register(self, source_id: str, factory: AdapterFactory) -> None:
        self._factories[source_id] = factory

    def adapter_for_source(self, source_id: str) -> Any:
        if source_id in self._instances:
            return self._instances[source_id]
        if source_id not in self._factories:
            raise IndicatorNotRegisteredError(source_id)
        adapter = self._factories[source_id](self._engine)
        self._instances[source_id] = adapter
        return adapter

    async def adapter_for_indicator(self, indicator_key: str) -> Any:
        source_id = await self._lookup_source_id(indicator_key)
        if source_id is None:
            raise IndicatorNotRegisteredError(indicator_key)
        return self.adapter_for_source(source_id)

    async def _lookup_source_id(self, indicator_key: str) -> str | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT source_id FROM catalogue.indicator WHERE key = :k"),
                    {"k": indicator_key},
                )
            ).first()
        return row.source_id if row else None
