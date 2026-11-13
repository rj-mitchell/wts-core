"""Saved briefings: every completed briefing is kept at an unguessable address (``/b/<id>``).

A kept briefing is the record to consult if someone later questions what the site published, so rows are never
deleted. A briefing can be withdrawn (after a complaint, for example); its address then says so instead of showing
it, and the corrections page lists what was withdrawn, when and why.

What is kept is each site's own: Where MPs Stand keeps the plan, the sources and the final event; the others keep
the events to play again. The events are stored exactly as given.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from wts_core.ports import SYSTEM_CLOCK, SYSTEM_RANDOM, Clock, Random
from wts_core.state import StateDB, iso
from wts_core.usage.interfaces import BriefingListing, SavedBriefing, SavedBriefings

__all__ = ["BriefingArchive", "alphabet_id", "token_id"]

TRIES = 5  # ids tried before giving up: a clash is astronomically unlikely, five in a row is a fault


def token_id(nbytes: int, *, random: Random = SYSTEM_RANDOM) -> str:
    """An id as Where Countries Stand and Where Councils Stand make them: a URL-safe string from ``nbytes`` random
    bytes (8 on both: 64 bits, 11 characters)."""
    return random.token(nbytes)


def alphabet_id(alphabet: str, length: int, *, random: Random = SYSTEM_RANDOM) -> str:
    """An id as Where MPs Stand makes them: ``length`` characters chosen from ``alphabet`` (its own leaves out 0,
    o, 1 and l, so an address read aloud or retyped is not misread; 10 characters of its 32 is about 50 bits)."""
    weights = [1.0] * len(alphabet)
    return "".join(random.choice(alphabet, weights) for _ in range(length))


class BriefingArchive:
    """Saved briefings over ``wts_briefings`` (``SavedBriefings``). ``new_id`` is how the site makes an id: the
    sites' formats differ, so there is no default (``token_id`` and ``alphabet_id`` are the two in use)."""

    def __init__(self, db: StateDB, *, new_id: Callable[[], str], clock: Clock = SYSTEM_CLOCK) -> None:
        self._db = db
        self._new_id = new_id
        self._clock = clock

    def new_id(self) -> str:
        return self._new_id()

    def save(self, question: str, options: Mapping[str, Any], events: Sequence[Mapping[str, Any]], *,
             id: str | None = None, extra: Mapping[str, Any] | None = None) -> SavedBriefing:
        """Keep a briefing and return it as kept.

        It is kept under ``id`` (a new one if none is given). If that id is taken another is tried, up to five in
        all, rather than lose a briefing that has been written and paid for; any event that carried the taken id
        as its ``briefing_id`` carries the new one, in what is kept and in what is returned.
        """
        created = iso(self._clock)
        bid = id or self.new_id()
        kept = [dict(e) for e in events]
        with self._db.connect() as con:
            for _ in range(TRIES):
                try:
                    con.execute(
                        "INSERT INTO wts_briefings (id, created_at, question, options, events, extra) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (bid, created, question, json.dumps(options, default=str), json.dumps(kept, default=str),
                         json.dumps(extra or {}, default=str)))
                    return SavedBriefing(bid, created, question, dict(options), kept, dict(extra or {}))
                except sqlite3.IntegrityError as exc:  # an id collision is astronomically unlikely; try another
                    if "UNIQUE" not in str(exc):
                        raise
                    taken, bid = bid, self.new_id()
                    kept = [{**e, "briefing_id": bid} if e.get("briefing_id") == taken else e for e in kept]
        raise RuntimeError("could not allocate a briefing id")

    def get(self, id: str) -> SavedBriefing | None:
        with self._db.connect() as con:
            row = con.execute("SELECT id, created_at, question, options, events, extra, withdrawn_at, "
                              "withdrawn_reason FROM wts_briefings WHERE id = ?", (id,)).fetchone()
        if row is None:
            return None
        return SavedBriefing(row["id"], row["created_at"], row["question"], json.loads(row["options"]),
                             json.loads(row["events"]), json.loads(row["extra"]), row["withdrawn_at"],
                             row["withdrawn_reason"])

    def withdraw(self, id: str, reason: str) -> bool:
        """Mark a briefing withdrawn, with the reason shown at its address. False if there is no such briefing."""
        with self._db.connect() as con:
            cur = con.execute("UPDATE wts_briefings SET withdrawn_at = ?, withdrawn_reason = ? WHERE id = ?",
                              (iso(self._clock), reason, id))
            return cur.rowcount > 0

    def _listing(self, where: str, order: str, limit: int | None) -> list[BriefingListing]:
        sql = ("SELECT id, created_at, question, withdrawn_at, withdrawn_reason FROM wts_briefings "
               f"{where} ORDER BY {order}")
        with self._db.connect() as con:
            rows = con.execute(sql + (" LIMIT ?" if limit is not None else ""),
                               () if limit is None else (limit,)).fetchall()
        return [BriefingListing(r["id"], r["created_at"], r["question"], r["withdrawn_at"], r["withdrawn_reason"])
                for r in rows]

    def withdrawn(self) -> list[BriefingListing]:
        """For the corrections page: what was withdrawn, when and why (the question, not the briefing), the most
        recently withdrawn first."""
        return self._listing("WHERE withdrawn_at IS NOT NULL", "withdrawn_at DESC, id", None)

    def recent(self, limit: int = 50) -> list[BriefingListing]:
        """The newest briefings, for the owner's list."""
        return self._listing("", "created_at DESC, id", limit)

if TYPE_CHECKING:  # checked by mypy: the class is what its interface asks for

    def _as_savedbriefings(x: BriefingArchive) -> SavedBriefings:
        return x
