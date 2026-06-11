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


def test_refresh_trends_is_in_the_mode_mutex() -> None:
    # Combining --refresh-trends with any other mode must fail the argparser
    # before any loader runs (otherwise a typo could trigger a full re-seed).
    with pytest.raises(SystemExit):
        main(["--refresh-trends", "--full"])
    with pytest.raises(SystemExit):
        main(["--refresh-trends", "--light"])
