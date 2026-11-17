"""Comparing what the code gives now with what it gave when someone last looked: the parity tests' helper.

``golden(path, value)`` compares ``value`` with the file at ``path`` and fails, showing the lines that differ, when
they are not the same. Text is kept as it is; anything else as JSON, indented and with its keys in order, so that
the file reads well in a pull request and two runs always write the same bytes. The file is written (not compared)
when ``update`` is true or the environment has ``WTS_UPDATE_GOLDEN=1``: run the tests once that way after a change
that is meant, and read the difference before committing it.
"""

from __future__ import annotations

import difflib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = ["golden"]

UPDATE = "WTS_UPDATE_GOLDEN"


def golden(path: Path, value: Any, *, update: bool = False, env: Mapping[str, str] | None = None) -> None:
    """Compare ``value`` with the stored file, or store it. Raises ``AssertionError`` with the differing lines
    (the stored file's marked ``-``, what the code gives now ``+``), or saying how to write a file that is not
    there yet: a comparison that has nothing to compare with never passes."""
    path = Path(path)
    now = value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                                                          default=str) + "\n"
    if update or (os.environ if env is None else env).get(UPDATE) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(now, encoding="utf-8")
        return
    if not path.exists():
        raise AssertionError(f"{path} is not there yet. Run the tests once with {UPDATE}=1 to write it, read what "
                             "was written, and commit it.")
    stored = path.read_text(encoding="utf-8")
    if stored != now:
        lines = difflib.unified_diff(stored.splitlines(), now.splitlines(), f"{path} (stored)",
                                     "what the code gives now", lineterm="")
        raise AssertionError("\n".join(lines) + f"\n\nIf the change is meant, run the tests once with {UPDATE}=1 and "
                             "commit the file.")
