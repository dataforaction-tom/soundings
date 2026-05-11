"""Consent vocabulary and banner copy.

The banner copy is keyed by CONSENT_VERSION so that any change to the
text bumps the version, and every captured record records which version
of the banner the user saw. Past records keep the version they
consented under — we never retroactively reinterpret consent.
"""

from soundings.capture.context import AskerSector, ConsentLevel

CONSENT_VERSION = "v1.0"

CONSENT_LEVELS: tuple[ConsentLevel, ...] = ("full", "minimal", "none")
DEFAULT_CONSENT_LEVEL: ConsentLevel = "minimal"

ASKER_SECTORS: tuple[AskerSector, ...] = (
    "charity",
    "funder",
    "researcher",
    "commissioner",
    "public",
    "other",
)

CONSENT_BANNER_COPY: dict[str, str] = {
    "v1.0": (
        "Soundings logs every question to a public corpus. Choose what to share:\n"
        "  full — your question text and self-declared context are captured and "
        "published after sanitisation.\n"
        "  minimal — only the structured fields (tool, place, indicators) are "
        "captured and published.\n"
        "  none — nothing is captured. You can still use the server.\n"
        "Postcodes, personal names, and small-org names are stripped before "
        "publication. See /about for details."
    ),
}
