"""Errors raised by the orchestrator and surfaced through the HTTP error envelope."""


class OrchestrationError(Exception):
    """Base for orchestrator-emitted errors."""

    code: str = "INTERNAL"


class IndicatorNotRegisteredError(OrchestrationError):
    code = "INDICATOR_NOT_REGISTERED"

    def __init__(self, indicator_key: str) -> None:
        super().__init__(f"No adapter registered for indicator {indicator_key!r}")
        self.indicator_key = indicator_key


class IndicatorNotAvailableAtLevelError(OrchestrationError):
    code = "INDICATOR_NOT_AVAILABLE_AT_LEVEL"

    def __init__(self, indicator_key: str, place_id: str, available_at: list[str]) -> None:
        super().__init__(
            f"Indicator {indicator_key!r} is not published at the level of {place_id!r}; "
            f"available at: {available_at}"
        )
        self.indicator_key = indicator_key
        self.place_id = place_id
        self.available_at = available_at


class GeographyNotFoundError(OrchestrationError):
    code = "GEOGRAPHY_NOT_FOUND"

    def __init__(self, place_id: str) -> None:
        super().__init__(f"No place row for {place_id!r}")
        self.place_id = place_id
