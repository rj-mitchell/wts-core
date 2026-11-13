"""The answer cache: an identical question is answered from the last briefing written for it, at no cost.

The key is a SHA-256 of the parts a site says an answer depends on (the question with case and spacing evened
out, the reader's choices, the model, a stamp of the site's data, the version of its instructions). Each site's
parts are its own; the key for the same parts is the same, byte for byte, as its own ``cache_key`` gave, so the
week's cache survives the move to this package.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from wts_core.ports import SYSTEM_CLOCK, AnswerCache, Clock
from wts_core.state import StateDB, iso

__all__ = ["SqliteAnswerCache", "cache_key"]


def cache_key(parts: Mapping[str, Any], *, length: int) -> str:
    """The key for an answer: ``length`` hexadecimal characters (64 on Where MPs Stand and Where Countries Stand;
    Where Councils Stand keeps 32). The sites differ, so there is no default: a site that passed the wrong length
    would miss every answer it had cached. Anything JSON cannot write (a date, say) is written as its text."""
    if not 16 <= length <= 64:
        raise ValueError(f"a cache key is 16 to 64 characters long, not {length}")
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:length]


class SqliteAnswerCache:
    """The cache over ``wts_answer_cache`` (``ports.AnswerCache``). What is kept is the list of reader events to
    play again, as the site made it."""

    def __init__(self, db: StateDB, *, clock: Clock = SYSTEM_CLOCK) -> None:
        self._db = db
        self._clock = clock

    def _since(self, max_hours: float) -> str:
        return (self._clock.now() - timedelta(hours=max_hours)).isoformat(timespec="seconds")

    def get(self, key: str, max_hours: float) -> list[dict[str, Any]] | None:
        """The events kept under ``key``, unless they are more than ``max_hours`` old. An answer exactly that old
        is still given (as Where MPs Stand and Where Countries Stand; Where Councils Stand's copy stopped a second
        sooner). No hours means no cache: nothing is ever given."""
        if max_hours <= 0:
            return None
        with self._db.connect() as con:
            row = con.execute("SELECT events FROM wts_answer_cache WHERE key = ? AND created_at >= ?",
                              (key, self._since(max_hours))).fetchone()
        return json.loads(row["events"]) if row else None

    def put(self, key: str, events: list[dict[str, Any]], max_hours: float) -> None:
        """Keep an answer for ``max_hours``. Answers older than that are deleted as each new one is stored: they
        are never read again, and would otherwise fill the database."""
        with self._db.connect() as con:
            con.execute("DELETE FROM wts_answer_cache WHERE created_at < ?", (self._since(max_hours),))
            con.execute("INSERT OR REPLACE INTO wts_answer_cache (key, created_at, events) VALUES (?, ?, ?)",
                        (key, iso(self._clock), json.dumps(events, default=str)))

if TYPE_CHECKING:  # checked by mypy: the class is what its interface asks for

    def _as_answercache(x: SqliteAnswerCache) -> AnswerCache:
        return x
