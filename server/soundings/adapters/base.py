from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class LoaderResult:
    rows_written: int
    notes: str | None = None


class LoaderAdapter(ABC):
    """Base class for loader-mode adapters.

    Loader adapters fetch a whole dataset from upstream and upsert it into
    Postgres. They run as part of `make seed` and on a refresh cadence.
    Each invocation is wrapped in a `data.loader_run` row.
    """

    source_id: str
    mode = "loader"

    @abstractmethod
    async def load(self, run_id: str | None = None) -> LoaderResult:
        """Fetch from upstream and upsert into Postgres."""
        ...

    @staticmethod
    def now_utc() -> datetime:
        from datetime import timezone

        return datetime.now(tz=timezone.utc)
