"""The spending record: one row for every model call, and the sums the caps and the owner's reports are made from.

Every model-written briefing costs money and the sites are public, so each call is priced and written down as it
finishes. A row holds when, what kind of call (``parse``, ``answer``; a site may have others), the model, the
visitor's code or the signed-in account, the token counts and the cost. The counts are stored in the sites' own
form (``Usage.as_stored``: input includes the cache writes), so rows copied from a site's old table and rows
written here mean the same.

A visitor's code is kept on a row only for its own day. The code is there for the daily limit, and changes at
midnight with the day's secret; once the day is over it is of no use, and left in place it would let the day's
rows (and through their times and token counts, the record of each briefing) be gathered by visitor. So the codes
of days gone by are forgotten: replaced by an empty text, with the number of different visitors that day kept in
``wts_visitor_days`` so the owner's reports say what they said before. The sites kept the codes for good; this is
stricter, and nothing a reader sees changes.

The per-visitor daily limit counts rows of kind ``answer`` since midnight UTC, as Where MPs Stand and Where
Countries Stand count today. Where Councils Stand kept a table of its own for that count (one row a visitor a day,
raised whenever an answer's cost was recorded), which comes to the same number.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from wts_core.ports import SYSTEM_CLOCK, Clock, Pricing, SpendingRecord, Usage
from wts_core.state import StateDB, iso, today
from wts_core.usage.interfaces import AccountSpending, DaySpending, SpendingFigures, SpendingTotals

__all__ = ["Spending", "forget_visitors"]

ANSWER = "answer"  # the kind of row that counts towards a visitor's or an account's daily limit
FORGOTTEN = ""  # what stands where a visitor's code was, once its day is over: still "a member of the public"


def forget_visitors(db: StateDB, *, clock: Clock = SYSTEM_CLOCK) -> int:
    """Forget the visitor codes of every day before today in the spending record, keeping how many different ones
    each day had, and say how many rows were changed. Doing it twice changes nothing."""
    day = today(clock)
    with db.connect() as con:
        old = "at < ? AND visitor IS NOT NULL AND visitor != ''"
        for who in ("'*'", "CASE WHEN account IS NULL THEN '' ELSE CAST(account AS TEXT) END"):
            con.execute(
                "INSERT INTO wts_visitor_days (day, who, visitors) "
                f"SELECT substr(at, 1, 10), {who}, count(DISTINCT visitor) FROM wts_spending WHERE {old} "
                "GROUP BY 1, 2 ON CONFLICT(day, who) DO UPDATE SET visitors = visitors + excluded.visitors",
                (day,))
        return con.execute(f"UPDATE wts_spending SET visitor = ? WHERE {old}", (FORGOTTEN, day)).rowcount


class Spending:
    """The spending record over ``wts_spending`` (``ports.SpendingRecord``, and ``SpendingFigures`` for the owner's
    reports)."""

    def __init__(self, db: StateDB, pricing: Pricing, *, clock: Clock = SYSTEM_CLOCK) -> None:
        self._db = db
        self._pricing = pricing
        self._clock = clock
        self._forgot: str | None = None  # the day on which this process last forgot the days before

    def forget_visitors(self) -> int:
        """Forget the visitor codes of every day before today, keeping how many different ones each day had, and
        say how many rows were changed. Run with the first call recorded each day, and by a site's nightly update;
        doing it twice changes nothing."""
        changed = forget_visitors(self._db, clock=self._clock)
        self._forgot = today(self._clock)
        return changed

    def add(self, kind: str, model: str | None, usage: Usage | Mapping[str, Any] | None, *,
            visitor: str | None = None, account: int | None = None) -> float:
        """Record one model call and return its cost. ``usage`` may be a ``Usage`` or the token counts as either
        of today's dictionaries. Nothing is written when there is no usage (``None`` or an empty dictionary), as
        Where Councils Stand's copy: the others wrote a row of noughts, and their callers took care not to ask."""
        if usage is None or (not isinstance(usage, Usage) and not usage):
            return 0.0
        counts = usage if isinstance(usage, Usage) else Usage.from_mapping(usage)
        cost = self._pricing.cost(counts, model)
        stored = counts.as_stored()
        if self._forgot != today(self._clock):
            self.forget_visitors()
        with self._db.connect() as con:
            con.execute(
                "INSERT INTO wts_spending (at, kind, model, visitor, account, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (iso(self._clock), kind, model, visitor, account, stored["input_tokens"], stored["output_tokens"],
                 stored["cache_read_tokens"], stored["cache_write_tokens"], cost))
        return cost

    def spent_since(self, since: str) -> float:
        """Everything spent from ``since`` on: a day (``YYYY-MM-DD``), a month (``YYYY-MM``) or a full time, in
        UTC, compared with each row's time as text."""
        with self._db.connect() as con:
            row = con.execute("SELECT coalesce(sum(cost_usd), 0) FROM wts_spending WHERE at >= ?", (since,)).fetchone()
        return float(row[0])

    def briefings_today(self, *, visitor: str | None = None, account: int | None = None) -> int:
        """How many new briefings this account, or else this visitor, has had written since midnight UTC."""
        who: tuple[str, str | int]
        if account is not None:
            who = ("account", account)
        elif visitor is not None:
            who = ("visitor", visitor)
        else:
            raise ValueError("briefings_today needs a visitor's code or an account")
        with self._db.connect() as con:
            row = con.execute(f"SELECT count(*) FROM wts_spending WHERE {who[0]} = ? AND kind = ? AND at >= ?",
                              (who[1], ANSWER, today(self._clock))).fetchone()
        return int(row[0])

    # ---- for the owner's reports: the figures only, the wording is each site's ----------------------------------

    def totals(self, since: str) -> SpendingTotals:
        with self._db.connect() as con:
            row = con.execute(
                "SELECT coalesce(sum(cost_usd), 0), count(*), count(*) FILTER (WHERE kind = ?), "
                "count(DISTINCT visitor) FILTER (WHERE visitor != '') FROM wts_spending WHERE at >= ?",
                (ANSWER, since)).fetchone()
            # days whose codes are forgotten: the number kept for each (a period that begins part-way through
            # such a day counts the whole day's visitors)
            earlier = con.execute("SELECT coalesce(sum(visitors), 0) FROM wts_visitor_days WHERE who = '*' "
                                  "AND day >= ?", (since[:10],)).fetchone()
        return SpendingTotals(float(row[0]), int(row[1]), int(row[2]), int(row[3]) + int(earlier[0]))

    def by_day(self, since: str) -> list[DaySpending]:
        """Each day's spending from ``since`` on, oldest first; days with no model call are left out."""
        with self._db.connect() as con:
            rows = con.execute(
                "SELECT substr(at, 1, 10), sum(cost_usd), count(*), count(*) FILTER (WHERE kind = ?) "
                "FROM wts_spending WHERE at >= ? GROUP BY 1 ORDER BY 1", (ANSWER, since)).fetchall()
        return [DaySpending(r[0], float(r[1]), int(r[2]), int(r[3])) for r in rows]

    def by_account(self, since: str) -> list[AccountSpending]:
        """Who the spending from ``since`` on was for, the largest first."""
        with self._db.connect() as con:
            rows = con.execute(
                "SELECT account, account IS NULL AND visitor IS NOT NULL, sum(cost_usd), count(*), "
                "count(DISTINCT visitor) FILTER (WHERE visitor != '') FROM wts_spending WHERE at >= ? "
                "GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2", (since,)).fetchall()
            earlier = {r[0]: int(r[1]) for r in con.execute(
                "SELECT who, sum(visitors) FROM wts_visitor_days WHERE who != '*' AND day >= ? GROUP BY 1",
                (since[:10],))}

        def visitors(account: int | None, public: bool, counted: int) -> int:
            who = str(account) if account is not None else "" if public else None
            return counted + (earlier.get(who, 0) if who is not None else 0)

        return [AccountSpending(r[0], bool(r[1]), float(r[2]), int(r[3]), visitors(r[0], bool(r[1]), int(r[4])))
                for r in rows]

if TYPE_CHECKING:  # checked by mypy: the class is what its interface asks for

    def _as_spendingrecord(x: Spending) -> SpendingRecord:
        return x

    def _as_spendingfigures(x: Spending) -> SpendingFigures:
        return x
