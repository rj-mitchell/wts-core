"""The briefing desk: a question's whole journey, from its arrival to the last event sent (ADR 0009).

Where MPs Stand, Where Countries Stand and Where Councils Stand each wrote this flow out by hand in ``api/app.py``
(the ``ask`` route's ``events()`` and ``guarded()``), alike but for a dozen differences. Here it is written once. A
site's route stays the site's: it builds an ``Ask`` and streams what ``BriefingDesk.handle`` gives back. The order
is today's, on every site:

1. the answer cache is looked in (when there is a key, a model, and a briefing was asked for);
2. with nothing cached, the caps are checked: this reader's limit for the day, today's spending, the month's;
3. a place is reserved among the briefings in progress, and the caps are checked again counting the others;
4. the site's pipeline is run, its events passed on as they come. As they pass: the cost of reading the question
   and of writing the briefing is recorded, a failure is noted, the finished briefing is saved at its own address;
5. when the pipeline has finished, what is needed to play the briefing again goes into the answer cache;
6. a cap, a limit or a full house stops the briefing, never the answer: the sources are sent anyway, with the
   site's note saying why, which costs nothing;
7. whatever happens the place is released, and one record of how the briefing went is written (ADR 0012).

What differs between the sites is passed in: every word a reader sees (``Messages``), what is in the cache key,
what a saved briefing holds, and the steps only one site has (``Hooks``). The desk has no branch for any site.

Where the three copies differed by accident, this is the rule here, and whose it was:

- A pipeline's ``error`` event (the model declined) is noted as a failure (Where MPs Stand, Where Countries
  Stand), its token counts are recorded as the answer's (Where Countries Stand, Where Councils Stand) and are not
  sent (all three).
- A briefing that failed, and a question the model could not read, are noted for the owner (Where MPs Stand, Where
  Countries Stand; Where Councils Stand only logged them, and may pass ``failures=None`` to go on so).
- Token counts are never kept in the cache or with a saved briefing: where the final event carries ``usage`` it is
  blanked there (Where MPs Stand, Where Countries Stand; Where Councils Stand takes it out of the event before
  that, with ``Hooks.on_event``, so its copies have no such key, as today).
- With no hours to keep an answer, nothing is put in the cache or looked for (Where MPs Stand, Where Countries
  Stand; Where Councils Stand stored a row that was never read).
"""

from __future__ import annotations

import dataclasses
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from wts_core.briefing.stages import STAGES, Stages, marking
from wts_core.ports import (
    SYSTEM_CLOCK,
    SYSTEM_RANDOM,
    AnswerCache,
    BriefingLog,
    BriefingRecord,
    Clock,
    InProgress,
    Limiter,
    Outcome,
    Random,
    SpendingRecord,
    Usage,
)
from wts_core.settings import Messages
from wts_core.state import iso
from wts_core.usage import Caps, FailureLog, Refusal, SavedBriefings, busy_refusal, cache_key

__all__ = ["Ask", "BriefingDesk", "Event", "Hooks", "TooManyRequests"]

log = logging.getLogger(__name__)
# the structured log (``observe.LOGGER``: a test keeps the names alike) and the fixed message other handlers see
_lines_log = logging.getLogger("wts.briefings")
_LINE = "briefing event"

# One event of a briefing, as a site's pipeline makes it and a reader receives it: today's JSON. The common ones
# are described in ``wts_core.events``; a site may send others of its own (Where MPs Stand's ``progress`` and
# ``interests``), and every key the desk does not know passes through untouched.
type Event = dict[str, Any]

# what a hook may ask to be recorded: the kind of call, the model it is priced as, the token counts
type Spent = tuple[str, str | None, Usage | Mapping[str, Any] | None]

DECLINED = "ModelDeclined"  # the record's error type when the pipeline itself said the model declined: no exception
NO_FINAL = "NoFinalEvent"  # and when a pipeline ended without a final event or an error
START = "start"  # where the reader left, if before the first stage

_PAUSED: dict[str, Outcome] = {
    "visitor_limit": "paused_limit", "account_limit": "paused_limit", "daily_cap": "paused_cap",
    "monthly_cap": "paused_cap", "busy_visitor": "busy", "busy_site": "busy"}


class TooManyRequests(Exception):
    """This reader is over the per-minute limit: the site's route answers 429 with ``message``, its own words."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class Ask:
    """One question, as a site's route describes it to the desk.

    ``write`` runs the site's pipeline and ``sources_only(note, free)`` finds the sources without writing a
    briefing, ending in a final event that carries ``note``. ``free`` is true when the question must cost nothing
    to read: a limit stopped the briefing, or the site's spending caps are reached. Who reads the question then is
    the site's own choice: Where Countries Stand always uses its built-in rules; Where Councils Stand uses them
    when ``free``; Where MPs Stand lets the model read it for as long as the site's own budget lasts, whatever
    stopped this reader.

    ``cache_key`` is the site's key for this question (``usage.cache_key`` of its own parts), or ``None`` for an
    answer that must not be cached or looked for: on Where Countries Stand a follow-up, on Where MPs Stand and
    Where Countries Stand any question while there is no model or no cache. ``limiter_key`` is what this reader
    is counted by among the briefings in progress (the key the site gave ``BriefingDesk.allow``); without one the
    visitor's code is used.

    ``save`` is for a site whose saved briefings have a shape of their own (Where MPs Stand): given the final
    event, the events kept so far and the briefing's whole text, it keeps the briefing and returns what to add to
    the final event (its ``briefing_id`` at least). Without it the desk keeps the plan, the sources, the text and
    the final event, with ``options`` as what the reader chose (Where Countries Stand, Where Councils Stand).
    """

    question: str
    visitor: str | None
    write: Callable[[], Iterator[Event]]
    sources_only: Callable[[str, bool], Iterator[Event]]
    account: int | None = None
    limiter_key: str | None = None
    cache_key: str | None = None
    only_sources: bool = False
    model_available: bool = True
    follow_up: bool = False
    mode: str = "summary"
    filters_set: tuple[str, ...] = ()  # which filters the reader set, never their values: for the record
    kind: Literal["reader", "check", "eval"] = "reader"
    options: Mapping[str, Any] = field(default_factory=dict)
    save: Callable[[Event, list[Event], str], Mapping[str, Any]] | None = None


class Hooks:
    """The steps only some sites have. A site subclasses this and overrides what it needs: each default does
    nothing. The hooks are called while a briefing is being written, in this order for each event of the site's
    pipeline: ``usages``, ``on_event``, then for the final event ``finish``, the saving, and ``for_this_reader``.
    """

    def on_cached(self, ask: Ask, events: list[Event]) -> list[Event]:
        """A cached answer, about to be played again: what to send instead. Where Countries Stand and Where
        Councils Stand judge its flags again by today's rules; Where MPs Stand gives an answer cached before
        briefings had addresses one now, and puts it back in the cache."""
        return events

    def usages(self, ask: Ask, event: Event) -> Iterable[Spent]:
        """More model calls this event reports, to be recorded before the event's own (the reading of the question
        on a ``plan``, the answer on a ``final``): each a kind, the model it is priced as, and the token counts.
        Where MPs Stand's final event carries what matching registered interests cost."""
        return ()

    def on_event(self, ask: Ask, event: Event) -> Event | None:
        """An event of the pipeline, after its cost and any failure have been recorded and before it is kept or
        sent: the event to go on with, or ``None`` to drop it. What is taken out here is in no copy: Where
        Councils Stand takes the token counts out; Where MPs Stand a key that is only for the spending record."""
        return event

    def finish(self, ask: Ask, final: Event, kept: list[Event]) -> Event:
        """The final event, before the briefing is saved or cached: what a site adds to every copy (Where MPs
        Stand's ``briefing_key``). ``kept`` is the events so far, without the text and the citations. It is called
        for every final event the pipeline sends, one with no answer included (no model, or no records): look at
        ``final.get("answer")`` before adding what belongs only to a written briefing."""
        return final

    def for_this_reader(self, ask: Ask, final: Event) -> Event:
        """The final event as this reader alone receives it, after the briefing has been saved: what is added
        here is never saved or cached (Where MPs Stand's reminder of what briefings cost)."""
        return final


class _Run:
    """One question's passage through the desk: what its record will say."""

    def __init__(self, clock: Clock, random: Random) -> None:
        self.id = random.token(8)
        self.at = iso(clock)
        self.stages = Stages(clock)
        self.outcome: Outcome | None = None
        self.usage = Usage()
        self.cost = 0.0
        self.sources = 0
        self.groups: Counter[str] | None = None
        self.final: Event | None = None
        self.error_type: str | None = None
        self.left_at: str | None = None
        self.sources_seen = False
        self.warned = False
        self.recorded = False

    def left(self, *, writing: bool) -> None:
        """The reader went before the end. Only a briefing that was being written is recorded as one the reader
        left: a refusal or a cached answer stays what it was, with where the reader had got to."""
        self.left_at = self.stages.last or START
        if writing or self.outcome is None:
            self.outcome = "left"

    def failed(self, error_type: str) -> None:
        self.outcome = "error"
        self.error_type = error_type


class _Stream:
    """A briefing's events, to be taken one by one and closed if the reader goes. A generator closed before it
    has started runs none of its code, so this notes that ending itself: every question leaves its record."""

    def __init__(self, events: Iterator[Event], never_begun: Callable[[], None]) -> None:
        self._events = events
        self._never_begun = never_begun
        self._begun = False

    def __iter__(self) -> _Stream:
        return self

    def __next__(self) -> Event:
        self._begun = True
        return next(self._events)

    def close(self) -> None:
        if not self._begun:
            self._begun = True
            self._never_begun()
        _close(self._events)


class BriefingDesk:
    """The flow of a briefing, built once for a site from the shared parts and the site's own wording.

    ``parse_model`` is the model the reading of a question is priced as. ``config`` is what the site says of the
    configuration it is running (``config_id``, ``model``, ``parse_model``, ``instructions``, ``package_version``,
    ``site_version`` and, in an experiment, ``experiment`` and ``arm``): it goes into each briefing's record as it
    is, and in an experiment the arm goes into the cache key, so versions never serve each other's answers.
    ``group_of`` says which group a source card belongs to (a party, a region, a body), for the record's count of
    sources by group. ``log=None`` writes no record: a site that has not turned the record on. ``archive`` is where
    briefings are saved when an ``Ask`` has no ``save`` of its own.

    ``strict`` is for tests: text sent before the sources is a fault in the site's pipeline (a reader must be able
    to see what a briefing is drawn from before reading it), and raises ``AssertionError`` instead of being
    logged.
    """

    def __init__(self, *, messages: Messages, limiter: Limiter, caps: Caps, in_progress: InProgress,
                 spending: SpendingRecord, cache: AnswerCache, cache_hours: float, archive: SavedBriefings | None,
                 failures: FailureLog | None, log: BriefingLog | None, parse_model: str | None,
                 config: Mapping[str, Any], hooks: Hooks | None = None,
                 group_of: Callable[[Mapping[str, Any]], str | None] | None = None, clock: Clock = SYSTEM_CLOCK,
                 random: Random = SYSTEM_RANDOM, strict: bool = False) -> None:
        self._messages = messages
        self._limiter = limiter
        self._caps = caps
        self._in_progress = in_progress
        self._spending = spending
        self._cache = cache
        self._cache_hours = cache_hours
        self._archive = archive
        self._failures = failures
        self._log = log
        self._parse_model = parse_model
        self._config = dict(config)
        self._hooks = hooks or Hooks()
        self._group_of = group_of
        self._clock = clock
        self._random = random
        self._strict = strict

    def allow(self, key: str) -> None:
        """Count a request against the per-minute limit; over it, raise ``TooManyRequests`` with the site's
        words. For the site's route to call first of all, for every route it limits."""
        if not self._limiter.allow(key):
            raise TooManyRequests(self._messages.too_many_requests)

    def handle(self, ask: Ask) -> Iterator[Event]:
        """The events to send for this question, in order. The cache and the caps are looked at here, before
        anything is sent, so a fault in them is the route's to answer as an error; everything after happens as the
        events are taken. Close the iterator if the reader goes (``sse`` does): the site's pipeline is closed with
        it, which stops the model."""
        run = _Run(self._clock, self._random)
        try:
            arm = self._config.get("arm")
            if ask.cache_key is not None and arm is not None:
                ask = dataclasses.replace(ask, cache_key=cache_key(
                    {"key": ask.cache_key, "experiment": self._config.get("experiment"), "arm": arm},
                    length=len(ask.cache_key)))
            key = ask.cache_key if self._cache_hours > 0 else None
            hit = (self._cache.get(key, self._cache_hours)
                   if key is not None and ask.model_available and not ask.only_sources else None)
            refusal = (self._caps.refusal(visitor=ask.visitor, account=ask.account)
                       if ask.model_available and hit is None and not ask.only_sources else None)
        except BaseException as exc:
            run.failed(type(exc).__name__)
            self._record(ask, run)
            raise

        def never_begun() -> None:
            run.left(writing=True)
            self._record(ask, run)

        return _Stream(self._events(ask, run, key, hit, refusal), never_begun)

    # ---- the flow ---------------------------------------------------------------------------------------------

    def _events(self, ask: Ask, run: _Run, key: str | None, hit: list[Event] | None,
                refusal: Refusal | None) -> Iterator[Event]:
        writing = False
        try:
            if hit is not None:
                run.outcome = "cached"
                yield from self._passed(run, iter(self._hooks.on_cached(ask, hit)), replay=True)
            elif ask.only_sources:
                run.outcome = "sources_only"
                # the model may read the question only while the site's own spending allows it
                free = self._caps.site_paused() is not None
                yield from self._site(run, ask.sources_only(self._messages.sources_only, free))
            elif refusal is not None:  # the sources still help, and cost nothing
                yield from self._refused(ask, run, refusal)
            elif not ask.model_available:
                writing = True
                yield from self._passed(run, self._written(ask, run, key))
            else:
                # A briefing about to be written is reserved at its estimated cost while it runs, and the caps
                # are checked again counting the others in progress, so many requests at once cannot all slip
                # past them.
                who = ask.limiter_key or ask.visitor or ask.kind
                busy = self._in_progress.start(who)
                if busy is not None:
                    yield from self._refused(ask, run, busy_refusal(busy, self._messages))
                    return
                try:
                    late = self._caps.refusal(visitor=ask.visitor, account=ask.account,
                                              pending_usd=self._in_progress.pending_usd(besides=1))
                    if late is not None:
                        yield from self._refused(ask, run, late)
                        return
                    writing = True
                    yield from self._passed(run, self._written(ask, run, key))
                finally:
                    self._in_progress.finish(who)
        except GeneratorExit:
            run.left(writing=writing and run.final is None and run.outcome != "error")
            raise
        except BaseException as exc:
            run.failed(type(exc).__name__)
            raise
        finally:
            self._record(ask, run)

    def _refused(self, ask: Ask, run: _Run, refusal: Refusal) -> Iterator[Event]:
        run.outcome = _PAUSED[refusal.kind]
        return self._site(run, ask.sources_only(self._messages.with_sources(refusal.message), True))

    def _site(self, run: _Run, events: Iterator[Event]) -> Iterator[Event]:
        """The site's own sources-only stream, passed on as it is."""
        return self._passed(run, marking(run.stages, events))

    def _passed(self, run: _Run, events: Iterator[Event], *, replay: bool = False) -> Iterator[Event]:
        """Every event on its way to the reader, whichever way the briefing went: the desk sees the question read,
        the sources sent and the model's first words (text or a citation, whichever comes first), and that no text
        goes before the sources."""
        try:
            for event in events:
                kind = event.get("type")
                if kind == "plan" and not replay:
                    run.stages.mark("parsed")
                elif kind == "sources":
                    run.sources_seen = True
                    run.stages.mark("sources_sent")
                    self._count_sources(run, event)
                elif kind == "text":
                    if not run.sources_seen:
                        self._text_before_sources(run)
                    run.stages.mark("first_token")
                elif kind == "citation":
                    # the model's first word may be a citation: it sends one before the text it belongs to
                    run.stages.mark("first_token")
                elif kind == "final" and run.final is None:
                    run.final = event  # a cached answer's: its address and what the checks found, for the record
                yield event
        finally:
            _close(events)  # now, not when it is next tidied away: the site's pipeline stops with it

    def _text_before_sources(self, run: _Run) -> None:
        if self._strict:
            raise AssertionError("the pipeline sent text of a briefing before its sources event: a reader must be "
                                 "shown what a briefing is drawn from first")
        if not run.warned:
            run.warned = True
            log.error("briefing %s: text was sent before the sources event (a fault in the site's pipeline)", run.id)

    def _count_sources(self, run: _Run, event: Event) -> None:
        cards = event.get("sources") or []
        run.sources = len(cards)
        if self._group_of is not None:
            run.groups = Counter(g for g in (self._group_of(card) for card in cards) if g is not None)

    def _written(self, ask: Ask, run: _Run, key: str | None) -> Iterator[Event]:
        """The site's pipeline, its events passed on as they come."""
        kept: list[Event] = []  # every event but the text and the citations
        text: list[str] = []
        last: Event = {}  # the last event that was not text
        pipeline: Iterator[Event] | None = None
        try:
            pipeline = marking(run.stages, ask.write())
            for raw in pipeline:
                event = dict(raw)
                kind = event["type"]
                if kind == "plan" and event.get("parse_error"):
                    # the model could not read the question (a bad API key, say); the built-in rules were used.
                    # Taken off only when it says something, as Where MPs Stand and Where Countries Stand do: an
                    # empty one is passed on as it came (Where Councils Stand's hook takes the key off always)
                    error = event.pop("parse_error")
                    if self._failures is not None:
                        self._failures.note("question reading", ask.question, str(error))
                if kind == "error":  # the model declined to answer: the site's pipeline says so in its own words
                    if self._failures is not None:
                        self._failures.note("briefing", ask.question, str(event.get("message", "")))
                    run.failed(DECLINED)
                for spent in self._spent(ask, event):
                    self._spend(ask, run, *spent)
                if kind == "error":  # the declined call was paid for and is recorded; its counts are not sent
                    event = {k: v for k, v in event.items() if k not in ("usage", "model")}
                passed = self._hooks.on_event(ask, event)
                if passed is None:
                    continue
                event = passed
                if kind == "final":
                    event = self._hooks.finish(ask, event, kept)
                    answer = event.get("answer")
                    if answer and not answer.get("no_records"):
                        # kept at its own address, to share and to check complaints against
                        event = self._saved(ask, event, kept, "".join(text))
                        run.stages.mark("checked")
                    run.final = event
                    run.outcome = "sources_only" if not answer else "no_records" if answer.get("no_records") \
                        else "completed"
                if kind == "text":
                    text.append(event["text"])
                else:
                    last = event
                    if kind != "citation":
                        kept.append(event)
                # what is added for this reader goes to this reader only: never into saved or cached copies
                yield self._hooks.for_this_reader(ask, dict(event)) if kind == "final" else event
        except Exception as exc:  # never leave the reader waiting
            log.exception("ask failed")
            if self._failures is not None:
                self._failures.note("briefing", ask.question, f"{type(exc).__name__}: {exc}")
            run.failed(type(exc).__name__)
            yield {"type": "error", "message": self._messages.briefing_failed}
            return
        finally:
            if pipeline is not None:
                _close(pipeline)
        if run.outcome is None:
            run.failed(NO_FINAL)
        if key is not None and last.get("type") == "final" and last.get("answer"):
            replay = [e for e in kept if e["type"] in ("plan", "sources")]
            replay += [{"type": "text", "text": "".join(text)}, {**_without_counts(last), "cached": True}]
            self._cache.put(key, replay, self._cache_hours)

    def _spent(self, ask: Ask, event: Event) -> Iterator[Spent]:
        """The model calls an event reports: what the site's hook names, then the event's own."""
        yield from self._hooks.usages(ask, event)
        if event["type"] == "plan":
            yield "parse", self._parse_model, event.get("usage")
        elif event["type"] in ("final", "error"):
            yield "answer", event.get("model"), event.get("usage")

    def _spend(self, ask: Ask, run: _Run, kind: str, model: str | None,
               usage: Usage | Mapping[str, Any] | None) -> None:
        if not usage:
            return
        run.cost += self._spending.add(kind, model, usage, visitor=ask.visitor, account=ask.account)
        run.usage += usage if isinstance(usage, Usage) else Usage.from_mapping(usage)

    def _saved(self, ask: Ask, final: Event, kept: list[Event], text: str) -> Event:
        """The final event of a briefing that has just been saved, with its address."""
        if ask.save is not None:
            return {**final, **ask.save(final, kept, text)}
        if self._archive is None:
            return final
        final = {**final, "briefing_id": self._archive.new_id()}
        events = [e for e in kept if e["type"] in ("plan", "sources")]
        events += [{"type": "text", "text": text}, _without_counts(final)]
        # the id it was kept under: another, in the rare case that the first was taken
        final["briefing_id"] = self._archive.save(ask.question, ask.options, events, id=final["briefing_id"]).id
        return final

    # ---- the record -------------------------------------------------------------------------------------------

    def _record(self, ask: Ask, run: _Run) -> None:
        """Write this question's one record, and its lines in the structured log where a site has turned that on.
        A fault here must not reach the reader: it is logged."""
        if run.recorded:
            return
        run.recorded = True
        self._lines(run)
        if self._log is None:
            return
        try:
            self._log.write(self._record_of(ask, run))
        except Exception:
            log.exception("the record of briefing %s could not be written", run.id)

    def _lines(self, run: _Run) -> None:
        """One line for each stage this briefing reached and one for how it ended (ADR 0012): the record's id, a
        stage's name, milliseconds and an error's class name, and nothing else. Only where the site has given the
        structured log a handler of its own (``observe.json_logging``): otherwise nothing is logged at all."""
        if not _lines_log.handlers:
            return
        try:
            for stage in STAGES:
                at = run.stages.at(stage)
                if at is not None:
                    _lines_log.info(_LINE, extra={"event": "briefing.stage", "briefing": run.id, "stage": stage,
                                                  "ms": at, "error_type": None})
            _lines_log.log(logging.ERROR if run.outcome == "error" else logging.INFO, _LINE, extra={
                "event": f"briefing.{run.outcome or 'error'}", "briefing": run.id, "stage": run.left_at,
                "ms": run.stages.elapsed(), "error_type": run.error_type})
        except Exception:
            log.exception("the log lines of briefing %s could not be written", run.id)

    def _record_of(self, ask: Ask, run: _Run) -> BriefingRecord:
        config, stages = self._config, run.stages
        final = run.final or {}
        answer = final.get("answer") or {}
        spent = run.usage + stages.spent_unseen
        counts = spent.as_stored()
        return BriefingRecord(
            id=run.id, at=run.at, outcome=run.outcome or "error", kind=ask.kind, question=ask.question,
            follow_up=ask.follow_up, mode=ask.mode, filters_set=tuple(ask.filters_set),
            config_id=str(config.get("config_id", "")), model=config.get("model"),
            parse_model=config.get("parse_model", self._parse_model),
            instructions=str(config.get("instructions", "")), package_version=str(config.get("package_version", "")),
            site_version=str(config.get("site_version", "")), experiment=config.get("experiment"),
            arm=config.get("arm"), sources=run.sources, spread=None if run.groups is None else dict(run.groups),
            input_tokens=counts["input_tokens"], cache_read_tokens=counts["cache_read_tokens"],
            cache_write_tokens=counts["cache_write_tokens"], cache_write_long_tokens=spent.cache_write_long,
            output_tokens=counts["output_tokens"], cost_usd=round(run.cost + stages.cost_unseen, 6),
            stop_reason=final.get("stop_reason"),
            citations_total=answer.get("citations_total"), citations_invalid=answer.get("citations_invalid"),
            grounded_ratio=answer.get("grounded_ratio"), unsupported=answer.get("unsupported_segments"),
            quotes_unverified=answer.get("quotes_unverified"), loaded_words=answer.get("loaded_words"),
            t_parse=stages.at("parsed"), t_search=stages.at("searched"), t_rank=stages.at("ranked"),
            t_sources_sent=stages.at("sources_sent"), t_first_token=stages.at("first_token"),
            t_written=stages.at("written"), t_checked=stages.at("checked"), t_total=stages.elapsed(),
            left_at=run.left_at, error_type=run.error_type if run.outcome == "error" else None,
            briefing_id=final.get("briefing_id"))


def _close(events: Iterator[Any]) -> None:
    close = getattr(events, "close", None)
    if close is not None:
        close()


def _without_counts(final: Event) -> Event:
    """A final event as it is kept: token counts are for the spending record, not for a saved or cached copy."""
    return {**final, "usage": None} if "usage" in final else final
