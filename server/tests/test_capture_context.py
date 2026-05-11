from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from soundings.capture.context import CaptureContext


def test_capture_context_round_trips_through_json() -> None:
    original = CaptureContext(
        session_id=uuid4(),
        consent_level="full",
        consent_version="v1.0",
        tool_called="get_indicators",
        tool_inputs={"place_id": "ltla24:E06000004", "indicators": ["population.total"]},
        natural_language_question="What's the population of Stockton?",
        asker_sector="charity",
        asker_purpose="Researching local need for a funding bid.",
    )

    rehydrated = CaptureContext.model_validate_json(original.model_dump_json())

    assert rehydrated == original
    assert isinstance(rehydrated.session_id, UUID)


def test_capture_context_allows_no_session_for_unconsenting_callers() -> None:
    ctx = CaptureContext(
        session_id=None,
        consent_level="none",
        consent_version="v1.0",
        tool_called="find_place",
        tool_inputs={"query": "TS18 1AB"},
        natural_language_question=None,
        asker_sector=None,
        asker_purpose=None,
    )

    assert ctx.session_id is None
    assert ctx.natural_language_question is None


def test_capture_context_rejects_unknown_consent_level() -> None:
    with pytest.raises(ValidationError):
        CaptureContext(
            session_id=None,
            consent_level="partial",  # not in the spec's vocabulary
            consent_version="v1.0",
            tool_called="find_place",
            tool_inputs={},
            natural_language_question=None,
            asker_sector=None,
            asker_purpose=None,
        )


def test_capture_context_rejects_unknown_asker_sector() -> None:
    with pytest.raises(ValidationError):
        CaptureContext(
            session_id=uuid4(),
            consent_level="full",
            consent_version="v1.0",
            tool_called="find_place",
            tool_inputs={},
            natural_language_question=None,
            asker_sector="philanthropist",  # not in spec §8.1's controlled vocabulary
            asker_purpose=None,
        )
