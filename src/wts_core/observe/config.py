"""The short name of a configuration: what a briefing ran with, so any figure can be compared before and after a
change (ADR 0012).

A site passes everything that could change a briefing: the model, the model that reads the question, the version
of its instructions, its retrieval settings, the package's and the site's versions, and the experiment's arm if
there is one. The id is the first 12 hex characters of a SHA-256 of that, written as canonical JSON: the same
whatever order the keys come in, and different for any changed value (``1`` and ``1.0`` are different values).

Never pass a key, a password or anything about a reader: the settings behind each id are stored as they are, in
``wts_configs``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import PurePath
from typing import Any

__all__ = ["canonical_json", "config_id"]

LENGTH = 12  # hex characters of the hash that make the id


def _plain(value: Any, where: str) -> Any:
    """``value`` as JSON can hold it, with nothing left to chance: mappings by key, sets in order."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _plain(v, f"{where}.{k}") for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v, where) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(v, where) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, PurePath):
        return str(value)
    raise TypeError(f"{where} is a {type(value).__name__}, which a configuration's id cannot be made from: "
                    "pass text, numbers, lists and tables")


def canonical_json(parts: Mapping[str, Any]) -> str:
    """One way of writing ``parts``, whatever order its keys were given in."""
    return json.dumps(_plain(parts, "the configuration"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def config_id(parts: Mapping[str, Any]) -> str:
    """The id of the configuration ``parts`` describes: 12 hex characters."""
    return hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()[:LENGTH]
