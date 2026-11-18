"""How long each stage of a briefing took, measured from the question's arrival (ADR 0012).

The briefing desk starts a ``Stages`` for every question and marks what it can see for itself: the question read
(the ``plan`` event), the sources sent, the model's first words (text or a citation), the checked briefing. What
happens inside a site's pipeline (the search, the ranking, the model finishing) only the pipeline knows, so it
marks those itself: ``current_stages().mark("searched")``. It is handed nothing: the desk makes its ``Stages`` the
current ones, in a context variable, whenever the pipeline's code runs. Outside a desk (a test of the pipeline
alone, a command) the marks go nowhere.

A stage is marked once: the first mark stands, so a pipeline that marks a stage itself is not overruled by the
desk's own, later, mark.

The same ``Stages`` carries what the model writing the briefing has used so far (``model_call``). A model's
adapter reports it as the stream goes, since the cost of a call is otherwise known only from its ``Completed``,
which never comes when the reader leaves or the model fails part-way. The desk charges what was reported for a
briefing whose cost never reached it in an event. ``adapters.anthropic`` and ``testing.ScriptedModel`` report;
an adapter that does not is charged the site's estimate instead, once the model's first words have been sent.

The configuration a briefing is being written with is made current in the same way (``current_config``): the
site's own, or, while an experiment runs, the arm's the desk chose for this briefing. A pipeline reads the model,
the instructions' version and the variant from it. Read it in the pipeline's own code, at the top: a thread the
pipeline starts for itself does not inherit it, and should be handed what was read.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextvars import ContextVar
from typing import Any, Literal

from wts_core.ports import SYSTEM_CLOCK, BriefingConfig, Clock, Usage

__all__ = ["STAGES", "ModelCall", "Stage", "Stages", "calling", "current_config", "current_stages", "marking"]

type Stage = Literal["parsed", "searched", "ranked", "sources_sent", "first_token", "written", "checked"]

# in the order they happen
STAGES: tuple[Stage, ...] = ("parsed", "searched", "ranked", "sources_sent", "first_token", "written", "checked")


class ModelCall:
    """One call to the model writing a briefing, as its adapter reports it while the call runs: the model, and
    what the call has used so far. ``usage`` is None until the provider has said anything of the call's cost; the
    adapter replaces it as it learns more, and with the exact counts once the call is complete."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.usage: Usage | None = None


class Stages:
    """The stages one briefing has reached, each in milliseconds from when this was made."""

    def __init__(self, clock: Clock = SYSTEM_CLOCK) -> None:
        self._clock = clock
        self._start = clock.monotonic()
        self._at: dict[Stage, int] = {}
        self._calls: list[ModelCall] = []
        self.spent_unseen = Usage()
        self.cost_unseen = 0.0

    def model_call(self, model: str) -> ModelCall:
        """A call to the model that writes the briefing has begun: for its adapter to say so once the provider
        has taken the request (from then on it is paid for), and to keep the ``ModelCall`` it is given up to date
        as the stream goes. Outside a briefing desk the call is noted where nobody reads it."""
        call = ModelCall(model)
        self._calls.append(call)
        return call

    @property
    def model_calls(self) -> tuple[ModelCall, ...]:
        """The calls to the model this briefing has begun, in order."""
        return tuple(self._calls)

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
_CONFIG: ContextVar[BriefingConfig | None] = ContextVar("wts_core_briefing_config", default=None)


def current_stages() -> Stages:
    """The stages of the briefing being written here and now, for a site's pipeline to mark its own. Outside a
    briefing desk this is a ``Stages`` nobody reads: marking it does nothing."""
    return _CURRENT.get() or Stages()


def current_config() -> BriefingConfig | None:
    """The configuration the briefing being written here and now is written with: the site's own, or the arm's
    the desk chose for this briefing while an experiment runs (its ``model``, ``instructions`` and ``variant``
    are then the arm's, and its ``arm`` says which). None outside a briefing desk: a test of the pipeline alone,
    a command, the evaluation harness (which hands the pipeline its configuration itself).

    A site's pipeline that can be in an experiment reads what an arm may change from here, and from its settings
    only when this is None. What it does not read, an arm cannot change."""
    return _CONFIG.get()


def calling[T](stages: Stages, config: BriefingConfig | None, function: Callable[[], T]) -> T:
    """Call ``function`` with ``stages`` and ``config`` the current ones: for the call that makes a pipeline's
    iterator, which may itself do some of the pipeline's work before the first event is asked for."""
    stages_before, config_before = _CURRENT.set(stages), _CONFIG.set(config)
    try:
        return function()
    finally:
        _CONFIG.reset(config_before)
        _CURRENT.reset(stages_before)


def marking[T](stages: Stages, events: Iterator[T], config: BriefingConfig | None = None) -> Iterator[T]:
    """``events``, with ``stages`` the current ones (and ``config`` the current configuration) whenever its code
    runs, and closed when this is.

    They are made current for each step and put back after it, not once for the whole run: whoever is sending the
    events may take each one in another thread or another context, where something set once would be lost. The
    streamer (``sse``) takes them all in one thread; a web framework's own thread pool does not.
    """
    try:
        while True:
            try:
                event = calling(stages, config, lambda: next(events))
            except StopIteration:
                return
            yield event
    finally:
        close = getattr(events, "close", None)
        if close is not None:
            calling(stages, config, close)  # the pipeline's own tidying (closing the model's stream) may mark too
