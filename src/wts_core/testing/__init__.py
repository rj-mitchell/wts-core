"""Fakes, recorded fixtures and the contract tests each adapter and each site must pass.

Shipped with the package so a site's own tests can use them: a clock that stands still, chance that is fixed, an
off-site store in memory, the two checks of what is kept about readers and where statements may go, and the
comparison with a stored file; and, in the modules beside this one, a scripted model (``models``), a recording
embedder and an index in memory (``index``), and the contract tests (``contracts``, which needs pytest and so is
not imported here).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from wts_core.testing.golden import golden
from wts_core.testing.offsite import MemoryOffsiteStore

if TYPE_CHECKING:
    from wts_core.testing.privacy import assert_no_reader_data, assert_statements_stay_out

__all__ = ["FixedClock", "FixedRandom", "MemoryOffsiteStore", "assert_no_reader_data", "assert_statements_stay_out",
           "golden"]


_LATER = ("assert_no_reader_data", "assert_statements_stay_out")


def __getattr__(name: str) -> Any:
    """The two privacy checks are imported when first asked for, not with this package: they read
    ``wts_core.replies``, and ``wts_core.eval`` reads the recording format beside this module. Imported here at the
    top, the evaluation harness would load the right of reply's code, which nothing near the model may do
    (ADR 0008; tests/test_walls.py)."""
    if name in _LATER:
        from wts_core.testing import privacy

        return getattr(privacy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
