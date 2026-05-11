"""CaptureContext — the per-request payload built by the capture middleware.

One CaptureContext is constructed per `/v1/tools/*` invocation. It travels
from the session/consent middleware (which fills the session + consent
fields), through the tool body extractor (which strips `nl_question` off
the request body and stashes it here), to the raw-record writer (which
persists this plus the tool's response).

Vocabularies for `consent_level` and `asker_sector` match spec §8.1.
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

ConsentLevel = Literal["full", "minimal", "none"]
AskerSector = Literal[
    "charity",
    "funder",
    "researcher",
    "commissioner",
    "public",
    "other",
]
ResultStatus = Literal["ok", "no_data", "partial", "error"]


class CaptureContext(BaseModel):
    # session_id is None when the caller has no consent cookie yet — in that
    # case capture_level should also be "none" and no rows are written.
    session_id: UUID | None
    consent_level: ConsentLevel
    consent_version: str

    # --- Input side (carries everything sanitisation runs against) ---

    tool_called: str
    tool_inputs: dict[str, Any]

    # Only populated when consent_level == "full"; stripped earlier otherwise.
    natural_language_question: str | None

    asker_sector: AskerSector | None
    asker_purpose: str | None

    # --- Output side (filled by the middleware after the tool responds) ---

    result_status: ResultStatus = "ok"
    error_class: str | None = None
    indicators_returned: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    geography_referenced: list[dict[str, str]] = Field(default_factory=list)
