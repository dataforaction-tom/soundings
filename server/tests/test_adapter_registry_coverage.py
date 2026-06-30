"""Guards that every indicator can actually be served at runtime.

The catalogue test checks that each indicator's source exists in sources.yaml,
but the orchestrator also needs a *registered adapter* for that source — a
loader source with no registered read adapter fetches as "no adapter
registered" (the bug that hid the Companies House + FoE green-space
indicators from the ask/profile path).
"""

from pathlib import Path

import yaml

from soundings.app import CATALOGUE_DIR, build_adapter_registry

# Sources catalogued with indicators but not yet implemented (no loader/adapter
# or live data). Their indicators are placeholders. Listed explicitly so the
# test still catches *accidental* gaps while tolerating known-unimplemented ones.
_KNOWN_UNIMPLEMENTED = {"mhclg.live_tables"}


def test_every_indicator_source_has_a_registered_adapter() -> None:
    indicators = yaml.safe_load((Path(CATALOGUE_DIR) / "indicators.yaml").read_text())["indicators"]
    referenced = {ind["source_id"] for ind in indicators}

    registry = build_adapter_registry(None)
    missing = sorted(
        s for s in referenced if s not in registry._factories and s not in _KNOWN_UNIMPLEMENTED
    )

    assert not missing, (
        "indicator sources with no registered adapter (orchestrator can't "
        f"serve their indicators): {missing}"
    )
