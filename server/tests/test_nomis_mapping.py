from pathlib import Path

from soundings.adapters.nomis.mapping import load_nomis_mapping
from soundings.catalogue.models import load_indicators_yaml

REPO = Path(__file__).resolve().parent.parent.parent
NOMIS_YAML = REPO / "catalogue" / "nomis-mapping.yaml"
INDICATORS_YAML = REPO / "catalogue" / "indicators.yaml"


def test_nomis_mapping_loads_and_references_known_indicators() -> None:
    mappings = load_nomis_mapping(NOMIS_YAML)
    indicator_keys = {ind.key for ind in load_indicators_yaml(INDICATORS_YAML)}
    assert len(mappings) > 0
    for m in mappings:
        assert m.indicator_key in indicator_keys, (
            f"nomis mapping references unknown indicator {m.indicator_key}"
        )
        assert m.dataset_id.startswith("NM_")


def test_nomis_mapping_covers_population_total() -> None:
    mappings = {m.indicator_key: m for m in load_nomis_mapping(NOMIS_YAML)}
    assert "population.total" in mappings
    assert mappings["population.total"].source_id == "ons.mid_year_estimates"
