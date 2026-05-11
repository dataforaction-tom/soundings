from pathlib import Path

from soundings.capture.sanitisation.config import (
    DEFAULT_CONFIG_PATH,
    SanitisationConfig,
    load_sanitisation_config,
)


def test_default_config_path_resolves_to_repo_catalogue() -> None:
    assert DEFAULT_CONFIG_PATH.exists(), f"sanitisation.yaml missing at {DEFAULT_CONFIG_PATH}"


def test_load_sanitisation_config_yields_v1_with_all_thresholds() -> None:
    config = load_sanitisation_config()

    assert isinstance(config, SanitisationConfig)
    assert config.version == "v1"
    assert config.small_org.income_threshold_gbp == 100_000
    assert config.asker_purpose.max_chars == 280
    assert config.asker_purpose.rate_limit.full_consent_per_session_per_hour == 60
    assert config.geography.redact_finer_than == "msoa21"


def test_load_sanitisation_config_accepts_custom_path(tmp_path: Path) -> None:
    custom = tmp_path / "custom.yaml"
    custom.write_text(
        """
        version: "v2"
        small_org:
          income_threshold_gbp: 50000
        asker_purpose:
          max_chars: 500
          rate_limit:
            full_consent_per_session_per_hour: 100
        geography:
          redact_finer_than: "lsoa21"
        """
    )

    config = load_sanitisation_config(custom)
    assert config.version == "v2"
    assert config.small_org.income_threshold_gbp == 50_000
    assert config.geography.redact_finer_than == "lsoa21"
