"""Fakes, recorded fixtures and the contract tests each adapter and each site must pass.

Shipped with the package so a site's own tests can use them: a clock that stands still, chance that is fixed, and
(in the modules beside this one) a scripted model, a recording embedder, an index in memory.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

__all__ = ["FixedClock", "FixedRandom"]


class FixedClock:
    """A clock that says what it is told (``ports.Clock``). ``advance`` moves both the time and the monotonic count."""

    def __init__(self, start: datetime | str = "2026-11-13T12:00:00+00:00") -> None:
        self._now = datetime.fromisoformat(start) if isinstance(start, str) else start
        if self._now.tzinfo is None:
            self._now = self._now.replace(tzinfo=UTC)
        self._monotonic = 1000.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float = 0.0, **delta: float) -> None:
        step = timedelta(seconds=seconds, **delta)
        self._now += step
        self._monotonic += step.total_seconds()

    def set(self, when: datetime | str) -> None:
        new = datetime.fromisoformat(when) if isinstance(when, str) else when
        self._now = new if new.tzinfo else new.replace(tzinfo=UTC)


class FixedRandom:
    """Chance that is decided beforehand (``ports.Random``): tokens are handed out in order, then numbered; choices
    are the indexes given, in order, then always the first item."""

    def __init__(self, tokens: Sequence[str] = (), choices: Sequence[int] = ()) -> None:
        self._tokens = list(tokens)
        self._choices = list(choices)
        self._made = 0

    def token(self, nbytes: int) -> str:
        if self._tokens:
            return self._tokens.pop(0)
        self._made += 1
        return f"token{self._made:04d}"

    def token_hex(self, nbytes: int) -> str:
        if self._tokens:
            return self._tokens.pop(0)
        self._made += 1
        return f"{self._made:0{nbytes * 2}x}"

    def choice[T](self, items: Sequence[T], weights: Sequence[float]) -> T:
        return items[self._choices.pop(0) if self._choices else 0]
