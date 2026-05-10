"""Structural type for every Soundings source adapter.

Both LoaderAdapter and PassthroughAdapter implement this protocol; the
orchestrator depends only on the protocol, not the concrete classes.
"""

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.source_ref import CacheStatus, SourceRef

AdapterMode = Literal["loader", "passthrough"]


@runtime_checkable
class SourceAdapter(Protocol):
    source_id: str
    mode: AdapterMode

    async def fetch_indicator(
        self,
        indicator_key: str,
        place_id: str,
        period: str | None,
    ) -> IndicatorValue | None: ...

    async def list_available_indicators(self) -> list[str]: ...

    def get_source_ref(
        self,
        *,
        retrieved_at: datetime,
        cache_status: CacheStatus,
    ) -> SourceRef: ...
