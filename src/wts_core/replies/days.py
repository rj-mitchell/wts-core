"""Sums over the calendar: three months back, for deleting addresses and for what lapses, and working days, for
what is waiting.

``lapse_cutoff``, ``has_lapsed`` and ``lapses_on`` are the one statement of when something nobody decided lapses.
``Replies`` uses them, and so can anything that must agree with it without a ``Replies`` to ask, such as a site's
page or tests. They need nothing but the standard library and touch no database.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, time, timedelta

__all__ = ["has_lapsed", "lapse_cutoff", "lapses_on", "months_before", "working_days_between"]


def months_before(when: datetime, months: int) -> datetime:
    """The same moment ``months`` calendar months earlier (the month's last day where that day doesn't exist: three
    months before 31 May is 28 February, or 29 in a leap year). Where Countries Stand's, Where Councils Stand's and
    Where Landlords Stand's sum; Where MPs Stand's loop gives the same answers."""
    y, m = divmod(when.year * 12 + when.month - 1 - months, 12)
    return when.replace(year=y, month=m + 1, day=min(when.day, calendar.monthrange(y, m + 1)[1]))


def working_days_between(start: date, end: date) -> int:
    """How many working days (Monday to Friday) have passed from ``start`` to ``end``: the days after ``start``, up
    to and including ``end``. Something received on a Friday is one working day old on the Monday. Bank holidays
    are not taken out, so the count is never too low: it errs towards alerting the owner early."""
    if end <= start:
        return 0
    weeks, rest = divmod((end - start).days, 7)
    return weeks * 5 + sum(1 for n in range(1, rest + 1) if (start + timedelta(days=n)).weekday() < 5)


def lapse_cutoff(now: datetime, months: int = 3) -> str:
    """The moment that decides what has lapsed, as the package stores times (ISO 8601, to the second): whatever
    was sent before it, and is still undecided, lapses. ``months`` is the site's ``ReplyRules.email_kept_months``
    (three on every site: ADR 0008, the second question)."""
    return months_before(now, months).isoformat(timespec="seconds")


def has_lapsed(at: str, now: datetime, months: int = 3) -> bool:
    """Whether something sent at ``at`` (a stored time) and never decided has lapsed by ``now``: a statement
    still waiting is then declined as lapsed and its address deleted, and an open report's contact is deleted.
    Times are compared as the database compares them, as text, so this agrees with ``Replies.lapse_undecided``
    row for row, whatever way an old row's time was written."""
    return at < lapse_cutoff(now, months)


def lapses_on(at: str, months: int = 3) -> date:
    """The first day (UTC) by the end of which something sent at ``at`` has lapsed, if nobody decides it: for
    telling an owner how long is left. Worked out from ``has_lapsed`` itself, so the two cannot disagree: three
    months after 30 November is 1 March, not 28 February, since three months before 28 February is the 28th."""
    sent = datetime.fromisoformat(at)
    day = sent.date() + timedelta(days=27 * months)  # never later than the day it lapses
    for _ in range(8 * months + 8):
        if has_lapsed(at, datetime.combine(day, time(23, 59, 59), sent.tzinfo or UTC), months):
            return day
        day += timedelta(days=1)
    raise ValueError(f"{at!r} is not a time the package stores: no day was found on which it lapses")
