"""Where the sites' checkouts are, for the tests that compare an adapter with a site's own copy.

The checkouts sit beside this repository, or in the folder named by ``WTS_SITES_DIR``. A test that needs one that
is not there is skipped, naming it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# the site's repository, its package, and its environment prefix
SITES = {"mps": ("wherempsstand", "hansard", "HANSARD"),
         "countries": ("wherecountriesstand", "wcs", "WCS"),
         "councils": ("wherecouncilsstand", "councils", "COUNCILS")}


def sites_dir() -> Path | None:
    """The folder that holds the sites' checkouts: ``WTS_SITES_DIR``, or the nearest folder above this repository
    that has one of them."""
    named = os.environ.get("WTS_SITES_DIR")
    places = [Path(named)] if named else list(Path(__file__).resolve().parents[1].parents)
    return next((p for p in places if any((p / repo / "src" / package).is_dir()
                                          for repo, package, _ in SITES.values())), None)


def site_file(name: str, relative: str) -> Path:
    """A file of a site's package (``site_file("mps", "embed/base.py")``), or the test is skipped."""
    repo, package, _ = SITES[name]
    home = sites_dir()
    path = (home / repo / "src" / package / relative) if home else None
    if path is None or not path.is_file():
        pytest.skip(f"no checkout of {repo} beside this repository or under WTS_SITES_DIR ({package}/{relative}): "
                    "parity with the site's own copy is not checked here")
    return path
