"""360Giving Datastore — passthrough adapter.

Re-exports `ThreeSixtyGivingAdapter` under a stable name so app.py's
`build_adapter_registry` can register it without reaching into the
sub-module.
"""

from soundings.adapters.threesixtygiving.adapter import ThreeSixtyGivingAdapter

__all__ = ["ThreeSixtyGivingAdapter"]
