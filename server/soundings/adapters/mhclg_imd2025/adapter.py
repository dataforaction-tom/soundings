"""mhclg.imd2025 + mhclg.imd2019 adapters."""

from soundings.adapters.mhclg_imd2025.loader import MhclgImd2019Loader, MhclgImd2025Loader

MhclgImd2025Adapter = MhclgImd2025Loader
MhclgImd2019Adapter = MhclgImd2019Loader

__all__ = ["MhclgImd2019Adapter", "MhclgImd2025Adapter"]
