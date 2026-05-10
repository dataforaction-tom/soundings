"""IndicatorOrchestrator — concurrent fan-out across adapters.

Per design §4: `asyncio.gather(return_exceptions=True)`, soft 10s budget,
collects values into one list and converts adapter exceptions into caveats
without sinking the whole call. SourceRef dedup happens here so callers
don't see redundant citations.
"""

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.source_ref import SourceRef
from soundings.orchestration.errors import (
    IndicatorNotAvailableAtLevelError,
    IndicatorNotRegisteredError,
    OrchestrationError,
)
from soundings.orchestration.registry import AdapterRegistry

DEFAULT_TIMEOUT = 10.0


@dataclass
class OrchestrationResult:
    values: list[IndicatorValue]
    sources: list[SourceRef] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    partial: bool = False


class IndicatorOrchestrator:
    def __init__(self, engine: AsyncEngine, registry: AdapterRegistry) -> None:
        self._engine = engine
        self._registry = registry

    async def fetch(
        self,
        indicator_keys: list[str],
        place_id: str,
        period: str | None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> OrchestrationResult:
        tasks = [self._fetch_one(key, place_id, period) for key in indicator_keys]
        try:
            outcomes = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            outcomes = [TimeoutError("orchestrator soft budget exceeded")] * len(indicator_keys)

        values: list[IndicatorValue] = []
        caveats: list[str] = []
        partial = False

        for indicator_key, outcome in zip(indicator_keys, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                partial = True
                caveats.append(self._caveat_for_failure(indicator_key, outcome))
                continue
            if outcome is None:
                partial = True
                caveats.append(f"No value for indicator {indicator_key} at {place_id}")
                continue
            values.append(outcome)

        return OrchestrationResult(
            values=values,
            sources=self._dedup_sources([v.source for v in values]),
            caveats=caveats,
            partial=partial,
        )

    async def _fetch_one(
        self, indicator_key: str, place_id: str, period: str | None
    ) -> IndicatorValue | None:
        await self._enforce_level(indicator_key, place_id)
        adapter = await self._registry.adapter_for_indicator(indicator_key)
        result: IndicatorValue | None = await adapter.fetch_indicator(
            indicator_key, place_id, period
        )
        return result

    async def _enforce_level(self, indicator_key: str, place_id: str) -> None:
        place_type, _, _ = place_id.partition(":")
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT available_at FROM catalogue.indicator WHERE key = :k"),
                    {"k": indicator_key},
                )
            ).first()
        available_at = list(row.available_at) if row else []
        if available_at and place_type not in available_at:
            raise IndicatorNotAvailableAtLevelError(indicator_key, place_id, available_at)

    @staticmethod
    def _caveat_for_failure(indicator_key: str, exc: BaseException) -> str:
        if isinstance(exc, IndicatorNotAvailableAtLevelError):
            return f"INDICATOR_NOT_AVAILABLE_AT_LEVEL: {exc}"
        if isinstance(exc, OrchestrationError):
            return f"{indicator_key}: {exc}"
        if isinstance(exc, IndicatorNotRegisteredError):
            return f"{indicator_key}: no adapter registered"
        return f"{indicator_key}: {exc.__class__.__name__}"

    @staticmethod
    def _dedup_sources(refs: list[SourceRef]) -> list[SourceRef]:
        """Dedup by (source_id, retrieved_at minute).

        Lets the UI cite a single source once per source even when many
        indicators share that source within the same orchestration call.
        """
        seen: set[tuple[str, str]] = set()
        out: list[SourceRef] = []
        for r in refs:
            minute = r.retrieved_at.replace(second=0, microsecond=0).isoformat()
            key = (r.source_id, minute)
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out
