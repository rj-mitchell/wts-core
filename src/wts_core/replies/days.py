"""Two sums over the calendar: three months back, for deleting addresses, and working days, for what is waiting."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

__all__ = ["months_before", "working_days_between"]


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
