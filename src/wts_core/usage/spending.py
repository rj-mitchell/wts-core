"""The spending record: one row for every model call, and the sums the caps and the owner's reports are made from.

Every model-written briefing costs money and the sites are public, so each call is priced and written down as it
finishes. A row holds when, what kind of call (``parse``, ``answer``; a site may have others), the model, the
visitor's code or the signed-in account, the token counts and the cost. The counts are stored in the sites' own
form (``Usage.as_stored``: input includes the cache writes), so rows copied from a site's old table and rows
written here mean the same.

A row says who it was for, and when to the second, for its own day only. The visitor's code and the account
are there for the daily limits, which count since midnight; once the day is over they are of no use, and left in
place they would let the day's rows (and through their times and token counts, the record of each briefing) be
gathered by person. So when a day is over (``forget_earlier_days``: the first model call of the next day, and
the nightly tidy) each of its rows:

* loses the visitor's code and the account. Both become the same thing: an empty code and no account, so that a
  row that was a signed-in account's cannot be told from one that was a member of the public's;
* keeps the day it was made on and loses the time of day.

What the owner's reports need is kept in their place, and no finer: how many different visitors each day had
(``wts_visitor_days``), and for each signed-in account and each calendar month, how many calls it made, what they
cost to the cent and how many visitors' codes it was seen with (``wts_account_months``). The row itself, with its
day, kind, model, token counts and cost, is kept for good: it is the site's account of what it spent, and names no
one. The sites kept the codes, the accounts and the seconds for good; this is stricter, and nothing a reader sees
changes. docs/adr/0012 says what this does and does not promise.

A period that begins part-way through a day that is over counts the whole of that day, in every figure here:
the time of day is gone. Who the spending was for (``by_account``) is kept by the month, so a period that begins
on a day that is over is counted from the first of its month.

The per-visitor daily limit counts rows of kind ``answer`` since midnight UTC, as Where MPs Stand and Where
Countries Stand count today. Where Councils Stand kept a table of its own for that count (one row a visitor a day,
raised whenever an answer's cost was recorded), which comes to the same number.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wts_core.ports import SYSTEM_CLOCK, Clock, Pricing, SpendingRecord, Usage
from wts_core.state import StateDB, iso, today
from wts_core.usage.interfaces import AccountSpending, DaySpending, SpendingFigures, SpendingTotals

__all__ = ["Forgotten", "Spending", "forget_earlier_days", "forget_visitors"]

ANSWER = "answer"  # the kind of row that counts towards a visitor's or an account's daily limit
# What stands where a visitor's code was, once its day is over: "somebody's", and nothing more. A row that was a
# signed-in account's is given the same, and loses its account.
FORGOTTEN = ""
MIDNIGHT = "T00:00:00+00:00"  # what stands where a row's time of day was, once its day is over


@dataclass(frozen=True)
class Forgotten:
    """What forgetting the days before today changed: the rows that lost a visitor's code, those that lost an
    account, and those whose time was cut to its day."""

    codes: int = 0
    accounts: int = 0
    times: int = 0


def forget_earlier_days(db: StateDB, *, clock: Clock = SYSTEM_CLOCK) -> Forgotten:
    """Forget, on every model call of a day before today, who it was for and what time of day it was made, and
    say how many rows each was taken from. Doing it twice changes nothing.

    Kept in their place: the number of different visitors each day had (``wts_visitor_days``, "*"), the public's
    for each month (the same table, under the month), and each signed-in account's calls, cost to the cent and
    visitors for each calendar month (``wts_account_months``). An account's month is added to a day at a time and
    rounded to the cent each time, so it is right to within half a cent for each day the account was used.

    Afterwards a row of a past day holds its day, kind, model, token counts and cost, an empty code where
    somebody asked, and nothing else: an account's row and a member of the public's are the same."""
    day = today(clock)
    coded = "at < ? AND visitor IS NOT NULL AND visitor != ''"
    again = "ON CONFLICT(day, who) DO UPDATE SET visitors = visitors + excluded.visitors"
    with db.connect() as con:
        # how many different visitors: the whole day's; and by the month, the public's and each account's (a
        # code lasts a day, so a month's is its days' added up)
        con.execute("INSERT INTO wts_visitor_days (day, who, visitors) SELECT substr(at, 1, 10), '*', "
                    f"count(DISTINCT visitor) FROM wts_spending WHERE {coded} GROUP BY 1 {again}", (day,))
        days = (f"SELECT substr(at, 1, 10) AS d, account, count(DISTINCT visitor) AS n FROM wts_spending "
                f"WHERE {coded} GROUP BY 1, 2")
        con.execute("INSERT INTO wts_visitor_days (day, who, visitors) SELECT substr(d, 1, 7), '', sum(n) "
                    f"FROM ({days}) WHERE account IS NULL GROUP BY 1 {again}", (day,))
        con.execute("INSERT INTO wts_account_months (month, account, visitors) SELECT substr(d, 1, 7), account, "
                    f"sum(n) FROM ({days}) WHERE account IS NOT NULL GROUP BY 1, 2 ON CONFLICT(month, account) "
                    "DO UPDATE SET visitors = visitors + excluded.visitors", (day,))
        # what each account's calls came to, by the month and to the cent
        named = "at < ? AND account IS NOT NULL"
        con.execute("INSERT INTO wts_account_months (month, account, cost_usd, calls) SELECT substr(at, 1, 7), "
                    f"account, round(sum(cost_usd), 2), count(*) FROM wts_spending WHERE {named} GROUP BY 1, 2 "
                    "ON CONFLICT(month, account) DO UPDATE SET "
                    "cost_usd = round(cost_usd + excluded.cost_usd, 2), calls = calls + excluded.calls", (day,))
        codes = con.execute(f"UPDATE wts_spending SET visitor = ? WHERE {coded}", (FORGOTTEN, day)).rowcount
        accounts = con.execute(f"UPDATE wts_spending SET account = NULL, visitor = ? WHERE {named}",
                               (FORGOTTEN, day)).rowcount
        # the time of day: with the token counts a row shares with the record of each briefing, it would give
        # every record its second back
        times = con.execute(
            f"UPDATE wts_spending SET at = substr(at, 1, 10) || '{MIDNIGHT}' WHERE at < ? "
            f"AND at != substr(at, 1, 10) || '{MIDNIGHT}' "
            "AND at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]?*'", (day,)).rowcount
    return Forgotten(int(codes), int(accounts), int(times))


def forget_visitors(db: StateDB, *, clock: Clock = SYSTEM_CLOCK) -> int:
    """``forget_earlier_days``, saying only how many rows had a visitor's code forgotten."""
    return forget_earlier_days(db, clock=clock).codes


class Spending:
    """The spending record over ``wts_spending`` (``ports.SpendingRecord``, and ``SpendingFigures`` for the owner's
    reports)."""

    def __init__(self, db: StateDB, pricing: Pricing, *, clock: Clock = SYSTEM_CLOCK) -> None:
        self._db = db
        self._pricing = pricing
        self._clock = clock
        self._forgot: str | None = None  # the day on which this process last forgot the days before

    def forget_visitors(self) -> int:
        """Forget who every model call of a day before today was for, and its time of day
        (``forget_earlier_days``), and say how many rows had a visitor's code forgotten. Run with the first call
        recorded each day, and by a site's nightly update; doing it twice changes nothing."""
        changed = forget_earlier_days(self._db, clock=self._clock)
        self._forgot = today(self._clock)
        return changed.codes

    def _from(self, since: str) -> str:
        """Where a period that begins at ``since`` is counted from: ``since`` itself if it is today or later, and
        otherwise the start of its day, since a day that is over is kept whole and its times of day are gone. (A
        month, ``YYYY-MM``, is its own start.)"""
        return since if since[:10] >= today(self._clock) else since[:10]

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
        UTC, compared with each row's time as text. A time part-way through a day that is over counts that whole
        day (``_from``)."""
        with self._db.connect() as con:
            row = con.execute("SELECT coalesce(sum(cost_usd), 0) FROM wts_spending WHERE at >= ?",
                              (self._from(since),)).fetchone()
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

    # For the owner's reports: the figures only, the wording is each site's

    def totals(self, since: str) -> SpendingTotals:
        """What was spent from ``since`` on, in how many calls and briefings, for how many different visitors. A
        period that begins part-way through a day that is over counts that whole day."""
        start = self._from(since)
        with self._db.connect() as con:
            row = con.execute(
                "SELECT coalesce(sum(cost_usd), 0), count(*), count(*) FILTER (WHERE kind = ?), "
                "count(DISTINCT visitor) FILTER (WHERE visitor != '') FROM wts_spending WHERE at >= ?",
                (ANSWER, start)).fetchone()
            # days whose codes are forgotten: the number kept for each
            earlier = con.execute("SELECT coalesce(sum(visitors), 0) FROM wts_visitor_days WHERE who = '*' "
                                  "AND day >= ?", (start[:10],)).fetchone()
        return SpendingTotals(float(row[0]), int(row[1]), int(row[2]), int(row[3]) + int(earlier[0]))

    def by_day(self, since: str) -> list[DaySpending]:
        """Each day's spending from ``since`` on, oldest first; days with no model call are left out. A period
        that begins part-way through a day that is over has that whole day."""
        with self._db.connect() as con:
            rows = con.execute(
                "SELECT substr(at, 1, 10), sum(cost_usd), count(*), count(*) FILTER (WHERE kind = ?) "
                "FROM wts_spending WHERE at >= ? GROUP BY 1 ORDER BY 1", (ANSWER, self._from(since))).fetchall()
        return [DaySpending(r[0], float(r[1]), int(r[2]), int(r[3])) for r in rows]

    def by_account(self, since: str) -> list[AccountSpending]:
        """Who the spending from ``since`` on was for, the largest first: each signed-in account, the public, and
        the site's own work.

        Counted by whole months, but for today. Which account a call was for is kept on its row for its own
        day only; for the days before, each account has its calls, its cost to the cent and its visitors for
        each calendar month, and nothing finer. So a period that begins today (or later in today) is read from
        today's rows, exactly; and one that begins on any day that is over is counted from the first of that
        day's month, for every line, since an account's part of a month cannot be divided. Where MPs Stand,
        the one site with accounts, asks by the month.

        For the days that are over, the public's line is what all the rows that were somebody's came to, less
        the accounts' kept totals: so the lines still add up to what was spent, and the public's cost can be a
        cent or two out where the accounts' were rounded. Where the public made no call at all (a site on
        which everyone signs in) there is no public line: what would be left in it is only that rounding, a
        cent or so that nobody spent, and the lines then differ from the total by it."""
        day = today(self._clock)
        past = since[:10] < day
        start = since[:7] if past else since
        with self._db.connect() as con:
            rows = con.execute(
                "SELECT account, visitor IS NOT NULL, sum(cost_usd), count(*), "
                "count(DISTINCT visitor) FILTER (WHERE visitor != '') FROM wts_spending WHERE at >= ? "
                "GROUP BY 1, 2", (start,)).fetchall()
            months = con.execute(
                "SELECT account, sum(cost_usd), sum(calls), sum(visitors) FROM wts_account_months "
                "WHERE month >= ? GROUP BY 1", (start[:7],)).fetchall() if past else []
            public_before = int(con.execute(
                "SELECT coalesce(sum(visitors), 0) FROM wts_visitor_days WHERE who = '' AND day >= ?",
                (start[:7],)).fetchone()[0]) if past else 0
        # each line: [cost, calls, visitors]. A row that names an account is today's (or a day's not yet
        # forgotten); one with a code and no account is the public's today, or somebody's on a day gone by
        found: dict[tuple[int | None, bool], list[float]] = {}
        for account, somebody, cost, calls, counted in rows:
            who = (None if account is None else int(account), account is None and bool(somebody))
            line = found.setdefault(who, [0.0, 0, 0])
            line[0] += float(cost)
            line[1] += int(calls)
            line[2] += int(counted)
        public = found.get((None, True))
        for account, cost, calls, counted in months:
            line = found.setdefault((int(account), False), [0.0, 0, 0])
            line[0] += float(cost)
            line[1] += int(calls)
            line[2] += int(counted)
            if public is not None:  # their rows of days gone by are among "somebody's": taken out again
                public[0] = max(0.0, public[0] - float(cost))
                public[1] = max(0, public[1] - int(calls))
        if public is not None:
            public[2] += public_before
            if not public[1]:
                # every row that was somebody's was an account's: what is left is the rounding of their months
                del found[(None, True)]
            else:
                public[0] = round(public[0], 6)
        lines = [AccountSpending(account, is_public, cost, int(calls), int(counted))
                 for (account, is_public), (cost, calls, counted) in found.items()]
        return sorted(lines, key=lambda a: (-a.spent_usd, a.account is not None, a.account or 0, a.public))


if TYPE_CHECKING:  # checked by mypy: the class is what its interface asks for

    def _as_spendingrecord(x: Spending) -> SpendingRecord:
        return x

    def _as_spendingfigures(x: Spending) -> SpendingFigures:
        return x
