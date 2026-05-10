from datetime import datetime
from typing import Literal

from pydantic import BaseModel

CacheStatus = Literal["live", "cached", "stale"]


class SourceRef(BaseModel):
    """Provenance attached to every value the server returns.

    Mirrors spec §7. Carried through MCP and HTTP responses unchanged so
    downstream LLM responses can cite the source verbatim.
    """

    source_id: str
    source_label: str
    publisher: str
    publisher_url: str | None = None
    dataset_url: str | None = None
    retrieved_at: datetime
    cache_status: CacheStatus
    licence: str
