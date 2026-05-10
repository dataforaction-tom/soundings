"""Smoke tests for the seed CLI argument parsing.

The seed CLI hits live OGP — full integration is exercised by the
nightly `live` job (Task 37). Here we just confirm the argparse contract
holds so `make seed` / `make seed-light` don't break silently.
"""

import pytest

from soundings.seed.run import main


def test_seed_requires_mode_flag() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_seed_full_and_light_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        main(["--full", "--light"])
