"""The clock a command group is given: a clock, or a function that gives one when a command runs.

A site builds its commands once, when its command line is imported, and a test that wants a backup named by a time
of its choosing must be able to stand another clock in afterwards. So each group takes either, and reads the time
through this: the function, where one was given, is asked afresh each time.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from wts_core.ports import Clock


class _AtRunTime:
    """A ``ports.Clock`` that asks for the site's clock each time it is read."""

    def __init__(self, give: Callable[[], Clock]) -> None:
        self._give = give

    def now(self) -> datetime:
        return self._give().now()

    def monotonic(self) -> float:
        return self._give().monotonic()


def _clock_of(given: Clock | Callable[[], Clock]) -> Clock:
    if callable(given):
        return _AtRunTime(given)
    return given
