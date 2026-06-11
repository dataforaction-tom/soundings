"""Integration test for build_default_pipeline."""

import pytest
from sqlalchemy import text

from soundings.capture.sanitisation.build import build_default_pipeline
from soundings.capture.sanitisation.config import load_sanitisation_config
from soundings.capture.sanitisation.direct_identifiers import StripDirectIdentifiers
from soundings.capture.sanitisation.fine_geography import StripFineGeographyInFreeText
from soundings.capture.sanitisation.normalise import (
    NormaliseAskerPurpose,
    ValidateConsentLevel,
)
from soundings.capture.sanitisation.small_orgs import StripSmallOrgNames
from soundings.db.engine import get_engine

# spaCy is optional locally; skip the build tests when the model isn't there.
spacy = pytest.importorskip("spacy")
try:
    spacy.load("en_core_web_sm")
    _MODEL_AVAILABLE = True
except OSError:
    _MODEL_AVAILABLE = False

from soundings.capture.sanitisation.personal_names import (  # noqa: E402
    StripPersonalNamesViaNER,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _MODEL_AVAILABLE, reason="en_core_web_sm model not installed locally"),
]


async def _seed_lsoa(name: str) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES (:id, 'lsoa21', :code, :name)"
            ),
            {"id": "lsoa21:E01012018", "code": "E01012018", "name": name},
        )


async def test_build_default_pipeline_composes_all_six_rules() -> None:
    await _seed_lsoa("Stockton 010A")
    engine = get_engine()
    config = load_sanitisation_config()

    pipeline = await build_default_pipeline(engine, config)

    types = [type(rule).__name__ for rule in pipeline._rules]
    assert types == [
        StripDirectIdentifiers.__name__,
        StripFineGeographyInFreeText.__name__,
        StripPersonalNamesViaNER.__name__,
        StripSmallOrgNames.__name__,
        NormaliseAskerPurpose.__name__,
        ValidateConsentLevel.__name__,
    ]


async def test_fine_geography_rule_loads_lsoa_names_from_db() -> None:
    await _seed_lsoa("Stockton 010A")
    engine = get_engine()
    config = load_sanitisation_config()

    pipeline = await build_default_pipeline(engine, config)
    out = pipeline.run({"natural_language_question": "Stockton 010A is poor"}, config)
    assert "[redacted area]" in out.sanitised_payload["natural_language_question"]


async def test_build_default_pipeline_handles_empty_organisation_table() -> None:
    # data.organisation is empty by default in test envs — the small-org
    # rule should still build, just be a no-op.
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.organisation_operates_in"))
        await conn.execute(text("DELETE FROM data.organisation"))
    config = load_sanitisation_config()

    pipeline = await build_default_pipeline(engine, config)
    # Pipeline runs without raising.
    out = pipeline.run(
        {
            "capture_level": "full",
            "natural_language_question": "Anything about Stockton-on-Tees",
        },
        config,
    )
    assert out.review_status in ("cleared", "flagged")
