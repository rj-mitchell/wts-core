"""Shared by every test: plain output from the command line's help.

Typer draws its help with colours and boxes when it thinks a terminal is watching, and it thinks so on GitHub
Actions (it looks for ``GITHUB_ACTIONS``). The colour codes split an option's name in two, so a test that looks for
``--max-cost`` in the help passed on a developer's machine and failed in CI. Typer reads these when it is first
imported, so they are set here, before any test imports it.
"""

from __future__ import annotations

import os

os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"
os.environ["NO_COLOR"] = "1"
