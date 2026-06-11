"""The bulk client must capture the income + date columns that the
civil society profile aggregates depend on. Failing here means the
analytical SQL has nothing to chew on."""

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from soundings.adapters.charity_commission.client import (
    CC_CHARITY_BULK_URL,
    CHARITY_TXT,
    CharityCommissionBulkClient,
)

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).parent / "fixtures" / "charity_commission" / "sample_with_extras.tsv"


def _zip_fixture() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(CHARITY_TXT, FIXTURE.read_bytes())
    return buf.getvalue()


async def test_client_yields_income_and_dates_for_active_rows() -> None:
    zipped = _zip_fixture()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CC_CHARITY_BULK_URL
        return httpx.Response(200, content=zipped)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = CharityCommissionBulkClient(http_client=http)
        rows = [row async for row in client.iter_active_charities()]

    # Removed row dropped, two active rows survive.
    assert len(rows) == 2
    by_reg = {r["registration_number"]: r for r in rows}

    alpha = by_reg["1010101"]
    assert alpha["latest_income"] == 150000.0
    assert alpha["date_of_registration"] == "2010-04-12"
    assert alpha["date_of_removal"] is None

    beta = by_reg["1020202"]
    assert beta["latest_income"] == 7500.0
    assert beta["date_of_registration"] == "1998-11-30"
    assert beta["date_of_removal"] is None
