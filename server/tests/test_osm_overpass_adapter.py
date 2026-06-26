"""Integration tests for OsmOverpassAdapter.

Tests use a mocked OsmOverpassClient + the real PostGIS test DB for the
bounding-box lookup and SourceCacheStore. The fixed methodology caveat is
asserted verbatim so a refactor removing it fails CI.
"""

import pytest
from sqlalchemy import text

from soundings.adapters.osm_overpass.adapter import (
    INDICATOR_TAGS,
    METHODOLOGY_CAVEAT,
    OsmOverpassAdapter,
)
from soundings.adapters.osm_overpass.client import OsmOverpassClient
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_place(
    *,
    place_id: str = "ltla24:E06000004",
    code: str = "E06000004",
    name: str = "Stockton-on-Tees",
) -> None:
    """Seed one LTLA polygon near (54.57, -1.32)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name, geom) "
                "VALUES (:id, 'ltla24', :code, :name, "
                "ST_Multi(ST_GeomFromText("
                "'POLYGON((-1.34 54.55, -1.30 54.55, -1.30 54.59, -1.34 54.59, -1.34 54.55))',"
                " 4326)))"
            ),
            {"id": place_id, "code": code, "name": name},
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, publisher_url, "
                "dataset_url, licence, mode, rate_limit) VALUES "
                "('osm_overpass', 'OpenStreetMap (Overpass API)', 'OpenStreetMap contributors', "
                "'https://www.openstreetmap.org/', "
                "'https://overpass.atownsend.org.uk/api/interpreter', 'ODbL-1.0', "
                "'passthrough', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )


class _FakeOverpassClient(OsmOverpassClient):
    """Stub client returning canned counts for each tag query."""

    def __init__(self, counts: dict[tuple[str, str], int]) -> None:
        self._counts = counts
        self.calls: list[tuple[str, str, tuple[float, float, float, float]]] = []

    async def count_by_tag(
        self, tag_key: str, tag_value: str, bbox: tuple[float, float, float, float]
    ) -> int:
        self.calls.append((tag_key, tag_value, bbox))
        return self._counts.get((tag_key, tag_value), 0)


async def test_fetch_indicator_single_tag_count() -> None:
    await _seed_place()
    fake = _FakeOverpassClient({("amenity", "school"): 12})
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    iv = await adapter.fetch_indicator(
        "infrastructure.schools_count", "ltla24:E06000004", period=None
    )
    assert iv is not None
    assert iv.value == 12.0
    assert iv.unit == "count"
    assert iv.confidence == "official"
    assert iv.source.source_id == "osm_overpass"


async def test_fetch_indicator_multi_tag_sums_counts() -> None:
    """GP practices: amenity=clinic + healthcare=clinic — counts summed."""
    await _seed_place()
    fake = _FakeOverpassClient({("amenity", "clinic"): 4, ("healthcare", "clinic"): 3})
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    iv = await adapter.fetch_indicator(
        "infrastructure.gp_practices_count", "ltla24:E06000004", period=None
    )
    assert iv is not None
    assert iv.value == 7.0
    # Both tags were queried.
    assert ("amenity", "clinic") in [(c[0], c[1]) for c in fake.calls]
    assert ("healthcare", "clinic") in [(c[0], c[1]) for c in fake.calls]


async def test_fetch_indicator_sports_facilities_sums_three_tags() -> None:
    await _seed_place()
    fake = _FakeOverpassClient(
        {
            ("leisure", "sports_centre"): 2,
            ("leisure", "pitch"): 5,
            ("leisure", "sports_hub"): 1,
        }
    )
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    iv = await adapter.fetch_indicator(
        "infrastructure.sports_facilities_count", "ltla24:E06000004", period=None
    )
    assert iv is not None
    assert iv.value == 8.0
    assert len(fake.calls) == 3


async def test_fetch_indicator_carries_methodology_caveat_verbatim() -> None:
    await _seed_place()
    fake = _FakeOverpassClient({("amenity", "school"): 5})
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    iv = await adapter.fetch_indicator(
        "infrastructure.schools_count", "ltla24:E06000004", period=None
    )
    assert iv is not None
    assert METHODOLOGY_CAVEAT in iv.caveats
    assert "OpenStreetMap" in METHODOLOGY_CAVEAT
    assert "Overpass API" in METHODOLOGY_CAVEAT


async def test_fetch_indicator_unknown_indicator_returns_none() -> None:
    await _seed_place()
    fake = _FakeOverpassClient({})
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    iv = await adapter.fetch_indicator("not.a.real_indicator", "ltla24:E06000004", period=None)
    assert iv is None


async def test_fetch_indicator_returns_none_when_no_bbox() -> None:
    """Place with no geometry should return None."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name, geom) "
                "VALUES ('test:no-geom', 'ltla24', 'X1', 'NoGeom', NULL)"
            ),
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, publisher_url, "
                "dataset_url, licence, mode, rate_limit) VALUES "
                "('osm_overpass', 'OSM', 'OSM', '', '', 'ODbL-1.0', 'passthrough', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
    fake = _FakeOverpassClient({("amenity", "school"): 5})
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    iv = await adapter.fetch_indicator("infrastructure.schools_count", "test:no-geom", period=None)
    assert iv is None


async def test_second_fetch_uses_cache() -> None:
    await _seed_place()
    fake = _FakeOverpassClient({("amenity", "school"): 8})
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    first = await adapter.fetch_indicator(
        "infrastructure.schools_count", "ltla24:E06000004", period=None
    )
    second = await adapter.fetch_indicator(
        "infrastructure.schools_count", "ltla24:E06000004", period=None
    )
    assert first is not None and second is not None
    assert second.value == first.value
    # Upstream called once on miss, zero times on the cached second fetch.
    assert len(fake.calls) == 1


async def test_pre_warm_for_places_caches_every_indicator() -> None:
    """The pre_warmer daemon path: warming a place must populate the cache for
    every OSM indicator so later user reads never hit upstream (and so slow
    multi-tag/county-wide counts can't be cancelled by the orchestrator's
    soft budget mid-flight)."""
    await _seed_place()
    # One canned count for every tag the indicators query.
    counts: dict[tuple[str, str], int] = {}
    for tags in INDICATOR_TAGS.values():
        for tag in tags:
            for k, v in tag.items():
                counts[(k, v)] = 1
    fake = _FakeOverpassClient(counts)
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)

    await adapter.pre_warm_for_places(["ltla24:E06000004"])

    # Every indicator is now a warm cache hit — a subsequent fetch issues no
    # upstream calls.
    fake.calls.clear()
    for indicator_key in INDICATOR_TAGS:
        iv = await adapter.fetch_indicator(indicator_key, "ltla24:E06000004", period=None)
        assert iv is not None, indicator_key
    assert fake.calls == [], "pre-warm should have cached every indicator"


async def test_fetch_indicator_uses_period_when_provided() -> None:
    await _seed_place()
    fake = _FakeOverpassClient({("amenity", "hospital"): 3})
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    iv = await adapter.fetch_indicator(
        "infrastructure.hospitals_count", "ltla24:E06000004", period="2026-06"
    )
    assert iv is not None
    assert iv.period == "2026-06"
