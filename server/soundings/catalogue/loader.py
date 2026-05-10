import hashlib
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.catalogue.models import (
    IndicatorModel,
    SourceModel,
    load_indicators_yaml,
    load_sources_yaml,
)
from soundings.db.models.catalogue import Indicator, Source


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def load_catalogue_into_db(
    engine: AsyncEngine,
    *,
    sources_path: Path,
    indicators_path: Path,
) -> str:
    """Upsert sources and indicators from YAML into the catalogue schema.

    Returns the catalogue_version (sha256 of indicators.yaml) that was stamped
    on every indicator row in this load.
    """
    sources: list[SourceModel] = load_sources_yaml(sources_path)
    indicators: list[IndicatorModel] = load_indicators_yaml(indicators_path)
    catalogue_version = _sha256(indicators_path)

    async with engine.begin() as conn:
        for s in sources:
            stmt = insert(Source).values(
                id=s.id,
                label=s.label,
                publisher=s.publisher,
                publisher_url=s.publisher_url,
                dataset_url=s.dataset_url,
                licence=s.licence,
                mode=s.mode,
                refresh_cadence=s.refresh_cadence,
                rate_limit=s.rate_limit,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[Source.id],
                set_={
                    "label": stmt.excluded.label,
                    "publisher": stmt.excluded.publisher,
                    "publisher_url": stmt.excluded.publisher_url,
                    "dataset_url": stmt.excluded.dataset_url,
                    "licence": stmt.excluded.licence,
                    "mode": stmt.excluded.mode,
                    "refresh_cadence": stmt.excluded.refresh_cadence,
                    "rate_limit": stmt.excluded.rate_limit,
                },
            )
            await conn.execute(stmt)

        for ind in indicators:
            stmt = insert(Indicator).values(
                key=ind.key,
                label=ind.label,
                description=ind.description,
                unit=ind.unit,
                higher_is=ind.higher_is,
                source_id=ind.source_id,
                available_at=ind.available_at,
                refresh_cadence=ind.refresh_cadence,
                caveats=ind.caveats,
                related_keys=ind.related_keys,
                catalogue_version=catalogue_version,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[Indicator.key],
                set_={
                    "label": stmt.excluded.label,
                    "description": stmt.excluded.description,
                    "unit": stmt.excluded.unit,
                    "higher_is": stmt.excluded.higher_is,
                    "source_id": stmt.excluded.source_id,
                    "available_at": stmt.excluded.available_at,
                    "refresh_cadence": stmt.excluded.refresh_cadence,
                    "caveats": stmt.excluded.caveats,
                    "related_keys": stmt.excluded.related_keys,
                    "catalogue_version": stmt.excluded.catalogue_version,
                },
            )
            await conn.execute(stmt)

    return catalogue_version
