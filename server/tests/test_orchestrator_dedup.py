from datetime import UTC, datetime

from soundings.contracts.source_ref import SourceRef
from soundings.orchestration.orchestrator import IndicatorOrchestrator


def _ref(source_id: str, retrieved_at: datetime) -> SourceRef:
    return SourceRef(
        source_id=source_id,
        source_label=source_id,
        publisher="t",
        retrieved_at=retrieved_at,
        cache_status="cached",
        licence="CC0",
    )


def test_dedup_collapses_same_source_within_one_minute() -> None:
    base = datetime(2026, 5, 10, 12, 30, 15, tzinfo=UTC)
    same_minute_later = datetime(2026, 5, 10, 12, 30, 45, tzinfo=UTC)
    refs = [
        _ref("ons.census2021", base),
        _ref("ons.census2021", same_minute_later),
    ]
    deduped = IndicatorOrchestrator._dedup_sources(refs)
    assert len(deduped) == 1


def test_dedup_keeps_distinct_minutes_separate() -> None:
    refs = [
        _ref("ons.census2021", datetime(2026, 5, 10, 12, 30, tzinfo=UTC)),
        _ref("ons.census2021", datetime(2026, 5, 10, 12, 31, tzinfo=UTC)),
    ]
    deduped = IndicatorOrchestrator._dedup_sources(refs)
    assert len(deduped) == 2


def test_dedup_keeps_different_sources_separate() -> None:
    now = datetime(2026, 5, 10, 12, 30, tzinfo=UTC)
    refs = [
        _ref("ons.census2021", now),
        _ref("mhclg.imd2025", now),
    ]
    deduped = IndicatorOrchestrator._dedup_sources(refs)
    assert len(deduped) == 2
