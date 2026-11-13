"""Notes of briefings that failed (a bad API key, a refusal, an error), for the owner's report and alerts.

A note holds when, what kind of failure, the question and the error, each cut to 500 characters. The newest 500
are kept and none older than 90 days: Where Countries Stand's rule (its privacy notice says these are deleted
after 90 days), which Where MPs Stand gains; Where Councils Stand had no such table and only logged the failure.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from wts_core.ports import SYSTEM_CLOCK, Clock
from wts_core.state import StateDB, iso
from wts_core.usage.interfaces import FailureLog

__all__ = ["Failures"]

CUT = 500  # characters of the question and of the error that are kept
KEEP = 500  # notes: the latest are plenty to diagnose anything
DAYS = 90  # how long a note is kept


class Failures:
    """Notes of failures over ``wts_failures`` (``FailureLog``)."""

    def __init__(self, db: StateDB, *, clock: Clock = SYSTEM_CLOCK) -> None:
        self._db = db
        self._clock = clock

    def note(self, kind: str, question: str | None, error: str) -> None:
        too_old = (self._clock.now() - timedelta(days=DAYS)).isoformat(timespec="seconds")
        with self._db.connect() as con:
            con.execute("INSERT INTO wts_failures (at, kind, question, error) VALUES (?, ?, ?, ?)",
                        (iso(self._clock), kind, (question or "")[:CUT], error[:CUT]))
            con.execute("DELETE FROM wts_failures WHERE at < ? OR id NOT IN "
                        "(SELECT id FROM wts_failures ORDER BY id DESC LIMIT ?)", (too_old, KEEP))

    def recent(self, limit: int | None = 20, *, since: str | None = None) -> list[dict[str, Any]]:
        """The newest notes first, each with ``at``, ``kind``, ``question`` and ``error``: at most ``limit`` of
        them (``None``: all), and only those from ``since`` on if it is given."""
        sql = "SELECT at, kind, question, error FROM wts_failures"
        args: list[str | int] = []
        if since is not None:
            sql += " WHERE at >= ?"
            args.append(since)
        sql += " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        with self._db.connect() as con:
            return [dict(r) for r in con.execute(sql, args)]

if TYPE_CHECKING:  # checked by mypy: the class is what its interface asks for

    def _as_failurelog(x: Failures) -> FailureLog:
        return x
