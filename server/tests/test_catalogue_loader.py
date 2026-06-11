from pathlib import Path

import pytest
from sqlalchemy import func, select

from soundings.catalogue.loader import load_catalogue_into_db
from soundings.catalogue.models import load_indicators_yaml
from soundings.db.engine import get_engine
from soundings.db.models.catalogue import Indicator, Source

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parent.parent.parent
SOURCES_YAML = REPO / "catalogue" / "sources.yaml"
INDICATORS_YAML = REPO / "catalogue" / "indicators.yaml"


async def test_load_catalogue_is_idempotent_and_stamps_version() -> None:
    engine = get_engine()

    # Other tests may have inserted `test.*` rows; ignore them in counts.
    real_indicator_filter = ~Indicator.key.like("test.%")
    real_source_filter = ~Source.id.like("test.%")

    # Run twice; second run must not create duplicate rows.
    await load_catalogue_into_db(engine, sources_path=SOURCES_YAML, indicators_path=INDICATORS_YAML)
    async with engine.connect() as conn:
        n_sources_first = (
            await conn.execute(select(func.count(Source.id)).where(real_source_filter))
        ).scalar_one()
        n_indicators_first = (
            await conn.execute(select(func.count(Indicator.key)).where(real_indicator_filter))
        ).scalar_one()
        version_first = (
            await conn.execute(
                select(Indicator.catalogue_version).where(real_indicator_filter).distinct()
            )
        ).scalar_one()

    await load_catalogue_into_db(engine, sources_path=SOURCES_YAML, indicators_path=INDICATORS_YAML)
    async with engine.connect() as conn:
        n_sources_second = (
            await conn.execute(select(func.count(Source.id)).where(real_source_filter))
        ).scalar_one()
        n_indicators_second = (
            await conn.execute(select(func.count(Indicator.key)).where(real_indicator_filter))
        ).scalar_one()
        version_second = (
            await conn.execute(
                select(Indicator.catalogue_version).where(real_indicator_filter).distinct()
            )
        ).scalar_one()

    assert n_sources_first == n_sources_second
    assert n_indicators_first == n_indicators_second
    assert n_sources_first > 0
    assert n_indicators_first > 0
    assert version_first == version_second
    assert len(version_first) == 64  # sha256 hex


# Every IMD indicator that participates in cross-edition aggregation needs a
# `series_break:` caveat so get_trend can surface the IoD 2019/2025
# methodology break in Trend.breaks_in_series.
IMD_AGGREGATED_KEYS = (
    "deprivation.imd.score",
    "deprivation.imd.decile",
    "deprivation.imd.income_score",
    "deprivation.imd.employment_score",
    "deprivation.imd.health_score",
    "deprivation.imd.education_score",
    "deprivation.idaci",
    "deprivation.idaopi",
)


def test_imd_indicators_carry_series_break_caveat() -> None:
    indicators = {ind.key: ind for ind in load_indicators_yaml(INDICATORS_YAML)}
    for key in IMD_AGGREGATED_KEYS:
        ind = indicators[key]
        assert any(c.startswith("series_break:") for c in ind.caveats), (
            f"{key} is missing a `series_break:` caveat; cross-edition trend "
            "responses won't be flagged in Trend.breaks_in_series."
        )
