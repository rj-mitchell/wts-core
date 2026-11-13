"""How long each stage of a briefing took, measured from the question's arrival (ADR 0012).

The briefing desk starts a ``Stages`` for every question and marks what it can see for itself: the question read
(the ``plan`` event), the sources sent, the model's first words (text or a citation), the checked briefing. What
happens inside a site's pipeline (the search, the ranking, the model finishing) only the pipeline knows, so it
marks those itself: ``current_stages().mark("searched")``. It is handed nothing: the desk makes its ``Stages`` the
current ones, in a context variable, whenever the pipeline's code runs. Outside a desk (a test of the pipeline
alone, a command) the marks go nowhere.

A stage is marked once: the first mark stands, so a pipeline that marks a stage itself is not overruled by the
desk's own, later, mark.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from typing import Any, Literal

from wts_core.ports import SYSTEM_CLOCK, Clock, Usage

__all__ = ["STAGES", "Stage", "Stages", "current_stages", "marking"]

type Stage = Literal["parsed", "searched", "ranked", "sources_sent", "first_token", "written", "checked"]

# in the order they happen
STAGES: tuple[Stage, ...] = ("parsed", "searched", "ranked", "sources_sent", "first_token", "written", "checked")


class Stages:
    """The stages one briefing has reached, each in milliseconds from when this was made."""

    def __init__(self, clock: Clock = SYSTEM_CLOCK) -> None:
        self._clock = clock
        self._start = clock.monotonic()
        self._at: dict[Stage, int] = {}
        self.spent_unseen = Usage()
        self.cost_unseen = 0.0

    def spent(self, usage: Usage | Mapping[str, Any] | None, cost: float) -> None:
        """A model call the desk cannot see in the events, already recorded as spending by the site, for this
        briefing's record: the reading of the question on a sources-only request, whose events carry no token
        counts. ``cost`` is what ``SpendingRecord.add`` returned for it."""
        if usage:
            self.spent_unseen += usage if isinstance(usage, Usage) else Usage.from_mapping(usage)
        self.cost_unseen += cost

    def elapsed(self) -> int:
        """Milliseconds since the question arrived."""
        return round((self._clock.monotonic() - self._start) * 1000)

    def mark(self, stage: Stage) -> None:
        """This stage has just been reached. Marking it again changes nothing."""
        if stage not in STAGES:
            raise ValueError(f"{stage!r} is not a stage of a briefing: use one of {', '.join(STAGES)}")
        self._at.setdefault(stage, self.elapsed())

    def at(self, stage: Stage) -> int | None:
        """When the stage was reached, or ``None`` if it was not."""
        return self._at.get(stage)

    @property
    def last(self) -> Stage | None:
        """The furthest stage reached, or ``None`` before the first."""
        reached = [s for s in STAGES if s in self._at]
        return reached[-1] if reached else None


_CURRENT: ContextVar[Stages | None] = ContextVar("wts_core_briefing_stages", default=None)


def current_stages() -> Stages:
    """The stages of the briefing being written here and now, for a site's pipeline to mark its own. Outside a
    briefing desk this is a ``Stages`` nobody reads: marking it does nothing."""
    return _CURRENT.get() or Stages()


def marking[T](stages: Stages, events: Iterator[T]) -> Iterator[T]:
    """``events``, with ``stages`` the current ones whenever its code runs, and closed when this is.

    The stages are made current for each step and put back after it, not once for the whole run: whoever is
    sending the events may take each one in another thread or another context, where something set once would be
    lost. The streamer (``sse``) takes them all in one thread; a web framework's own thread pool does not.
    """
    try:
        while True:
            token = _CURRENT.set(stages)
            try:
                event = next(events)
            except StopIteration:
                return
            finally:
                _CURRENT.reset(token)
            yield event
    finally:
        close = getattr(events, "close", None)
        if close is not None:
            token = _CURRENT.set(stages)
            try:
                close()  # the pipeline's own tidying (closing the model's stream) may mark a stage too
            finally:
                _CURRENT.reset(token)
