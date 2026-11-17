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
    play again, as the site made it.

    ``purge``, ``delete`` and ``delete_briefing`` are this class's own and not part of ``ports.AnswerCache``:
    that interface is what the briefing desk asks of a cache, and the desk only looks and stores (a replay its
    hook refuses is written afresh and stored over the old one). ``delete`` and ``delete_briefing`` are for a
    site, which has this class from ``briefing.DeskParts.cache``, to drop the replay of a briefing it has
    withdrawn or hidden, so that the next reader with the same question is not played what was taken down;
    ``purge`` is for the nightly tidy."""

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

    def purge(self, max_hours: float) -> int:
        """Delete every answer more than ``max_hours`` old, and say how many went. ``put`` does this as each new
        answer is stored; on a site where nothing new is written for a while the old answers (each holds a
        reader's question) would otherwise stay past the hours the site keeps them, so a site's nightly tidy
        calls this with its cache hours (the statistics group's ``tidy`` does, given them). No hours means no
        cache: everything goes."""
        with self._db.connect() as con:
            if max_hours <= 0:
                return int(con.execute("DELETE FROM wts_answer_cache").rowcount)
            return int(con.execute("DELETE FROM wts_answer_cache WHERE created_at < ?",
                                   (self._since(max_hours),)).rowcount)

    def delete(self, key: str) -> bool:
        """Drop the answer kept under ``key``, whatever its age, and say whether there was one. For a site that
        has the key in hand: in ``Hooks.on_cached``, say, where ``ask.cache_key`` is the key of the replay it has
        just been given and has decided not to play."""
        with self._db.connect() as con:
            return con.execute("DELETE FROM wts_answer_cache WHERE key = ?", (key,)).rowcount > 0

    def delete_briefing(self, briefing_id: str) -> int:
        """Drop every cached answer that is the replay of this saved briefing (its final event carries the
        briefing's id), and say how many went: one for each wording, choice of options or arm of an experiment the
        briefing was cached under. For a site's command that withdraws or hides a briefing, which knows the
        briefing's id and not the key its question was cached under."""
        with self._db.connect() as con:
            # the id as JSON writes it narrows the rows read; the events themselves decide
            keys = [row["key"] for row in con.execute("SELECT key, events FROM wts_answer_cache WHERE "
                                                      "instr(events, ?) > 0", (json.dumps(briefing_id),)).fetchall()
                    if any(isinstance(event, dict) and event.get("briefing_id") == briefing_id
                           for event in json.loads(row["events"]))]
            con.executemany("DELETE FROM wts_answer_cache WHERE key = ?", [(key,) for key in keys])
        return len(keys)


if TYPE_CHECKING:  # checked by mypy: the class is what its interface asks for

    def _as_answercache(x: SqliteAnswerCache) -> AnswerCache:
        return x
