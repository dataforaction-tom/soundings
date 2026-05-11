"""SanitiserWorker — out-of-band processor for raw_record rows.

Picks up a `corpus.raw_record` by id, runs the sanitisation pipeline over
its raw_payload, then updates the matching `corpus.question_record`
stub (written synchronously by RawRecordWriter at request time) with:

- sanitised free-text fields and structured payload
- the new review_status from the pipeline outcome
- the active `sanitisation.yaml` version

On exception, the row stays at review_status='pending' and the optional
`alert` callable fires (Task 22 wires Resend; tests inject a fake).
Replay (Task 19) picks the row up again next time the pipeline runs.

The worker takes the pipeline, config, and alert as constructor deps
rather than reaching for app.state — keeps it independent of the HTTP
layer for the loader-daemon (`python -m soundings.capture.replay`).
"""

import json
import logging
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.capture.sanitisation.config import SanitisationConfig
from soundings.capture.sanitisation.pipeline import (
    PipelineOutcome,
    SanitisationPipeline,
)

logger = logging.getLogger(__name__)

AlertCallable = Callable[..., None]


def _noop_alert(*args: object, **kwargs: object) -> None:
    del args, kwargs


class SanitiserWorker:
    def __init__(
        self,
        engine: AsyncEngine,
        pipeline: SanitisationPipeline,
        config: SanitisationConfig,
        *,
        alert: AlertCallable | None = None,
    ) -> None:
        self._engine = engine
        self._pipeline = pipeline
        self._config = config
        self._alert = alert or _noop_alert

    async def sanitise(self, record_id: UUID) -> None:
        try:
            await self._sanitise_one(record_id)
        except Exception as exc:
            logger.exception("Sanitiser failed for record %s", record_id)
            self._alert(
                f"Sanitiser failure for {record_id}",
                f"Exception during sanitisation pipeline run.\n\n{exc!r}",
                source="sanitiser",
            )

    async def _sanitise_one(self, record_id: UUID) -> None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT raw_payload FROM corpus.raw_record WHERE id = :id"),
                    {"id": record_id},
                )
            ).first()
        if row is None:
            logger.warning("Sanitiser called for missing record %s", record_id)
            return

        raw_payload = row.raw_payload
        if not isinstance(raw_payload, dict):
            raise TypeError(f"raw_payload for {record_id} is not a dict")

        outcome = self._pipeline.run(raw_payload, self._config)
        await self._write_back(record_id, outcome)

    async def _write_back(self, record_id: UUID, outcome: PipelineOutcome) -> None:
        payload = outcome.sanitised_payload
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE corpus.question_record SET "
                    "natural_language_question = :nlq, "
                    "tool_inputs_redacted = CAST(:tool_inputs AS JSONB), "
                    "geography_referenced = CAST(:geo AS JSONB), "
                    "asker_sector = :sector, "
                    "asker_purpose = :purpose, "
                    "review_status = :status, "
                    "sanitisation_rules_version = :version "
                    "WHERE id = :id"
                ),
                {
                    "id": record_id,
                    "nlq": payload.get("natural_language_question"),
                    "tool_inputs": json.dumps(payload.get("tool_inputs") or {}),
                    "geo": json.dumps(payload.get("geography_referenced") or []),
                    "sector": payload.get("asker_sector"),
                    "purpose": payload.get("asker_purpose"),
                    "status": outcome.review_status,
                    "version": self._config.version,
                },
            )
