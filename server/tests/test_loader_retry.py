import httpx
import pytest

from soundings.loader.retry import retry_with_backoff


async def test_retry_succeeds_after_transient_failure() -> None:
    calls: list[int] = []

    async def flakey() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("boom")
        return "ok"

    result = await retry_with_backoff(flakey, max_attempts=3, base_delay=0.001)
    assert result == "ok"
    assert len(calls) == 3


async def test_retry_gives_up_after_max_attempts() -> None:
    async def always_fails() -> None:
        raise httpx.ConnectError("always")

    with pytest.raises(httpx.ConnectError):
        await retry_with_backoff(always_fails, max_attempts=3, base_delay=0.001)


async def test_retry_does_not_retry_on_4xx() -> None:
    calls: list[int] = []

    async def fails_with_400() -> None:
        calls.append(1)
        response = httpx.Response(400, request=httpx.Request("GET", "http://x/"))
        raise httpx.HTTPStatusError("Bad Request", request=response.request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        await retry_with_backoff(fails_with_400, max_attempts=3, base_delay=0.001)
    # 4xx is not retried.
    assert len(calls) == 1
