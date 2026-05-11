from soundings.capture.consent import (
    ASKER_SECTORS,
    CONSENT_BANNER_COPY,
    CONSENT_LEVELS,
    CONSENT_VERSION,
    DEFAULT_CONSENT_LEVEL,
)


def test_consent_banner_copy_exists_for_current_version() -> None:
    assert CONSENT_VERSION in CONSENT_BANNER_COPY
    copy = CONSENT_BANNER_COPY[CONSENT_VERSION]
    assert copy.strip(), "banner copy must be non-empty"


def test_default_consent_level_is_in_vocabulary() -> None:
    assert DEFAULT_CONSENT_LEVEL in CONSENT_LEVELS


def test_consent_levels_match_spec() -> None:
    # Spec §8.2: three levels.
    assert set(CONSENT_LEVELS) == {"full", "minimal", "none"}


def test_asker_sectors_match_spec() -> None:
    # Spec §8.1: controlled vocabulary for the self-declared sector.
    assert set(ASKER_SECTORS) == {
        "charity",
        "funder",
        "researcher",
        "commissioner",
        "public",
        "other",
    }
