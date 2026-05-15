"""Unit tests for FindThatCharityAdapter — simplified for unit testing."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import UTC, datetime

from soundings.adapters.find_that_charity.client import CharitySearchResult


async def test_fetch_organisations_scotland():
    """For Scottish place_id, calls FTC with country=Scotland."""
    from soundings.adapters.find_that_charity.adapter import FindThatCharityAdapter
    
    mock_engine = MagicMock()
    
    # Create a mock connection that can be used as async context manager
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = ("Scotland", "ltla24")
    mock_conn.execute = AsyncMock(return_value=mock_result)
    
    # Async context manager
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    mock_engine.connect = AsyncMock(return_value=mock_cm)
    
    adapter = FindThatCharityAdapter(mock_engine)
    adapter._now = lambda: datetime.now(tz=UTC)
    
    # Mock the FTC client
    mock_results = [
        CharitySearchResult(id="SC005336", name="Volunteer Scotland", postcode="EH1 1EZ", country="Scotland"),
    ]
    adapter._ftc = MagicMock()
    adapter._ftc.search = AsyncMock(return_value=mock_results)
    adapter._build_source_ref = AsyncMock(return_value=MagicMock(source_id="find_that_charity"))
    
    result = await adapter.fetch_organisations("ltla24:S12000033")
    
    adapter._ftc.search.assert_called_once_with(country="Scotland", limit=50)
    assert len(result) == 1
    assert result[0].id == "SC005336"


async def test_fetch_organisations_england_empty():
    """For English place_id, returns empty list (E&W goes via CC loader)."""
    from soundings.adapters.find_that_charity.adapter import FindThatCharityAdapter
    
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = ("England", "ltla24")
    mock_conn.execute = AsyncMock(return_value=mock_result)
    
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    mock_engine.connect = AsyncMock(return_value=mock_cm)
    
    adapter = FindThatCharityAdapter(mock_engine)
    adapter._ftc = MagicMock()
    adapter._ftc.search = AsyncMock()
    
    result = await adapter.fetch_organisations("ltla24:E06000004")
    
    # FTC should NOT be called for England
    adapter._ftc.search.assert_not_called()
    assert result == []