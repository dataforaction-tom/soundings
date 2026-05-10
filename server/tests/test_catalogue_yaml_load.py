from pathlib import Path

from soundings.catalogue.models import load_indicators_yaml, load_sources_yaml

REPO = Path(__file__).resolve().parent.parent.parent
SOURCES_YAML = REPO / "catalogue" / "sources.yaml"
INDICATORS_YAML = REPO / "catalogue" / "indicators.yaml"


def test_sources_yaml_loads_and_validates() -> None:
    sources = load_sources_yaml(SOURCES_YAML)
    ids = {s.id for s in sources}
    assert "ons.geography" in ids
    assert "postcodes.io" in ids
    for s in sources:
        assert s.mode in ("loader", "passthrough")
        if s.mode == "passthrough":
            assert s.ttl_hours is not None and s.ttl_hours > 0, (
                f"{s.id} is passthrough but has no ttl_hours"
            )
        if s.mode == "loader":
            assert s.refresh_cadence is not None, f"{s.id} is loader but has no refresh_cadence"


def test_indicators_yaml_loads_and_references_known_sources() -> None:
    indicators = load_indicators_yaml(INDICATORS_YAML)
    sources = load_sources_yaml(SOURCES_YAML)
    source_ids = {s.id for s in sources}
    assert len(indicators) > 0
    for ind in indicators:
        assert ind.source_id in source_ids, (
            f"indicator {ind.key} references unknown source {ind.source_id}"
        )
