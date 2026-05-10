"""Exponential backoff retry helper for loaders.

Per Phase 1 plan task 49: three attempts, 1s/4s/16s backoff on connection
errors and 5xx HTTPStatusError. 4xx never retries.
"""

import asyncio
from collections.abc import Awaitable, Callable

import httpx


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.ConnectError | httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


async def retry_with_backoff[T](
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> T:
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc
            if not _should_retry(exc) or attempt == max_attempts - 1:
                raise
            await asyncio.sleep(base_delay * (4**attempt))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry_with_backoff exited without result or exception")
