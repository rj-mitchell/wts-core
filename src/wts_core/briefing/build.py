"""The parts a briefing desk is made of, built from a site's settings in one call, with the start-up check.

Before a site could make its ``BriefingDesk`` it made about ten things, in the same order on Where MPs Stand,
Where Countries Stand and Where Councils Stand: the prices, the limits, the spending record, the caps, the
per-minute limiter, the count of briefings in progress, the answer cache, the saved briefings and the notes of
failures, each given the same clock. ``desk_parts`` makes them all, with one clock and one source of chance, and
``DeskParts.desk`` makes the desk from them::

    parts = desk_parts(settings, db, MESSAGES, new_id=lambda chance: token_id(8, random=chance),
                       at_once_per_visitor="briefings_at_once_per_visitor", forget_over=50_000,
                       keep_failures=True, clock=clock, random=random)
    desk = parts.desk(config, log=log, hooks=MyHooks(parts.spending))

It is two steps and not one because what a site makes in between needs the parts: its pipeline takes the spending
record, and its hooks the spending record, the limits, the cache or the saved briefings (Where MPs Stand's and the
example site's do). The parts are also what a site's other routes use: the spending record for its own
sources-only search, the caps for its status page, the saved briefings for their pages.

What the three sites differ in is passed in, and nothing here has a default for a limit:

- the settings they all name alike are read from ``[usage]`` under those names: ``requests_per_minute``,
  ``answer_cache_hours``, ``briefing_estimate_usd``, ``briefings_at_once``, and the limits and prices that
  ``usage.Limits.from_settings`` and ``usage.PriceTable.from_settings`` read;
- how many briefings one visitor may have in progress is ``briefings_at_once_per_reader`` on Where MPs Stand and
  ``briefings_at_once_per_visitor`` on the other two, so the site gives the name (or the number);
- how many idle visitors the limiter holds before it forgets them is a figure in each site's code (50,000, and
  10,000 on Where Councils Stand), so the site gives the number (or the name of a setting);
- how a saved briefing's id is made, and whether notes of failed briefings are kept (Where Councils Stand keeps
  none), are said outright.

**The start-up check** is ``desk_settings``, which ``desk_parts`` calls first: every limit, price and figure the
flow of a briefing needs, and the site's messages. Everything missing or wrong is reported together, in one
``SettingsError`` that names the settings file and each key, so the owner mends the file once.

The pieces stay public and usable on their own: this is a convenience over them, not a path a site must take.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields
from typing import Any

from wts_core.briefing.desk import BriefingDesk, Hooks
from wts_core.ports import SYSTEM_CLOCK, SYSTEM_RANDOM, BriefingConfig, BriefingLog, Clock, Random, UnknownModel
from wts_core.settings import Messages, Settings, SettingsError
from wts_core.state import StateDB
from wts_core.usage import (
    BriefingArchive,
    BriefingsInProgress,
    Caps,
    Failures,
    Limits,
    PriceTable,
    RateLimiter,
    Spending,
    SqliteAnswerCache,
)

__all__ = ["DeskParts", "DeskSettings", "desk_parts", "desk_settings"]

# the settings every site names alike, and what each is
_REQUESTS, _CACHE_HOURS, _ESTIMATE, _AT_ONCE = ("requests_per_minute", "answer_cache_hours", "briefing_estimate_usd",
                                                "briefings_at_once")
# the tables ``usage.migrations()`` makes, which the parts are kept in
_TABLES = ("wts_spending", "wts_answer_cache", "wts_briefings", "wts_failures")


@dataclass(frozen=True)
class DeskSettings:
    """What the flow of a briefing reads from a site's settings, read once and checked together."""

    prices: PriceTable
    limits: Limits
    requests_per_minute: int
    forget_over: int  # how many visitors the per-minute limiter holds before it forgets the idle ones
    at_once_per_visitor: int  # briefings one visitor may have in progress
    at_once: int  # briefings the whole site may have in progress
    estimate_usd: float  # what a briefing in progress is counted as against the caps, until its cost is known
    cache_hours: float  # how long an answer stays in the cache; 0 keeps none


def desk_settings(settings: Settings, messages: Messages, *, at_once_per_visitor: int | str, forget_over: int | str,
                  require_prices_for: Iterable[str | None] = (), section: str = "usage") -> DeskSettings:
    """The start-up check: read everything the flow of a briefing needs from the site's settings, or stop the
    site with one error that names the settings file and every key that is missing or wrong.

    ``at_once_per_visitor`` and ``forget_over`` are each a number, or the name of the setting in ``[usage]`` that
    holds it (the module's docstring says why these two). ``require_prices_for`` names models that must each have
    prices of their own under ``[usage.models]``: a site that wants no model costed at another's prices gives its
    briefing model and its question-reading model; left empty it is today's rule on every site, where a model with
    no entry takes the base prices. ``section`` is where the site keeps all this, if not in ``[usage]``.

    The messages are checked with the settings because the two must agree: a limit for signed-in accounts needs
    its message and the message its limit, no message may be empty, and ``sources_follow`` must have a place for
    the reason (``{reason}``), without which a reader would never be told why no briefing was written."""
    usage = settings.section(section)
    problems: list[str] = []
    limits: Limits | None = None
    prices: PriceTable | None = None
    try:
        limits = Limits.from_settings(usage, section=section)
    except SettingsError as exc:
        problems += exc.problems
    try:
        prices = PriceTable.from_settings(usage, section=section)
    except SettingsError as exc:
        problems += exc.problems

    def figure(given: int | str, number: Callable[[Any], Any] = int) -> Any:
        """A figure given as a number, or read from the setting named."""
        if not isinstance(given, str):
            return given
        if given not in usage:
            problems.append(f"[{section}] needs {given}")
            return None
        try:
            return number(usage[given])
        except (TypeError, ValueError):
            problems.append(f"[{section}] {given} is not a number: {usage[given]!r}")
            return None

    figures = {"requests_per_minute": figure(_REQUESTS), "forget_over": figure(forget_over),
               "at_once_per_visitor": figure(at_once_per_visitor), "at_once": figure(_AT_ONCE),
               "estimate_usd": figure(_ESTIMATE, float), "cache_hours": figure(_CACHE_HOURS, float)}
    if prices is not None:
        try:
            prices.require(require_prices_for, base_counts=False)
        except UnknownModel as exc:
            problems.append(str(exc))
    problems += _wrong_with(messages, limits, section)
    if problems or prices is None or limits is None:
        count = "1 thing" if len(problems) == 1 else f"{len(problems)} things"
        raise SettingsError(f"{settings.config_path}: the briefing desk cannot be built: {count} missing or wrong.\n"
                            + "\n".join(f"  - {problem}" for problem in problems), problems=problems)
    return DeskSettings(prices=prices, limits=limits, **figures)


def _wrong_with(messages: Messages, limits: Limits | None, section: str) -> list[str]:
    """What is wrong with a site's messages, each in a sentence for the owner."""
    problems = [f"Messages.{f.name} is empty: every word a reader is shown is the site's own, and the package has "
                "none to put in its place"
                for f in fields(Messages) if isinstance(getattr(messages, f.name), str)
                and not getattr(messages, f.name).strip()]
    try:
        told = "{reason}" in messages.sources_follow and "why" in messages.with_sources("why")
    except (KeyError, IndexError, ValueError):
        told = False
    if not told:
        problems.append("Messages.sources_follow must have {reason} in it, and no other name in braces: it is where "
                        "a reader is told why no briefing was written")
    if limits is not None:
        if messages.account_daily_limit is not None and limits.per_account_daily is None:
            problems.append(f"[{section}] needs per_user_daily_questions: the site has a message for signed-in "
                            "accounts over their daily limit (Messages.account_daily_limit) and no limit for them")
        if limits.per_account_daily is not None and messages.account_daily_limit is None:
            problems.append(f"Messages.account_daily_limit is missing: [{section}] per_user_daily_questions sets a "
                            "daily limit for signed-in accounts, which needs its message")
    return problems


@dataclass(frozen=True)
class DeskParts:
    """Everything a briefing desk is made of, built once by ``desk_parts`` on one clock and one source of chance.
    A site's pipeline, hooks and other routes use the same parts: the spending record its own sources-only search
    records a question's reading in, the caps its status page asks, the saved briefings its pages show."""

    messages: Messages
    prices: PriceTable
    limits: Limits
    spending: Spending
    caps: Caps
    limiter: RateLimiter
    in_progress: BriefingsInProgress
    cache: SqliteAnswerCache
    cache_hours: float
    archive: BriefingArchive
    failures: Failures | None  # None on a site that keeps no notes of failed briefings
    clock: Clock
    random: Random

    def desk(self, config: BriefingConfig, *, log: BriefingLog | None, hooks: Hooks | None = None,
             group_of: Callable[[Mapping[str, Any]], str | None] | None = None,
             strict: bool = False) -> BriefingDesk:
        """The briefing desk over these parts. ``config`` is the configuration the site is running
        (``observe.briefing_config``); ``log`` is its record of briefings, or None, said out loud, on a site that
        has not turned the record on. ``hooks``, ``group_of`` and ``strict`` are ``BriefingDesk``'s own."""
        return BriefingDesk(
            messages=self.messages, limiter=self.limiter, caps=self.caps, in_progress=self.in_progress,
            spending=self.spending, cache=self.cache, cache_hours=self.cache_hours, archive=self.archive,
            failures=self.failures, log=log, config=config, hooks=hooks, group_of=group_of, clock=self.clock,
            random=self.random, strict=strict)


def desk_parts(settings: Settings, db: StateDB, messages: Messages, *, new_id: Callable[[Random], str],
               at_once_per_visitor: int | str, forget_over: int | str, keep_failures: bool,
               require_prices_for: Iterable[str | None] = (), section: str = "usage",
               clock: Clock = SYSTEM_CLOCK, random: Random = SYSTEM_RANDOM) -> DeskParts:
    """The parts of a site's briefing desk, from its settings, its state database and its messages. The start-up
    check is made first (``desk_settings``, which says what ``at_once_per_visitor``, ``forget_over``,
    ``require_prices_for`` and ``section`` are): nothing is built from settings with something missing.

    ``db`` must have the tables of ``usage.migrations()``. ``new_id`` makes a saved briefing's id from the source
    of chance it is given: ``lambda chance: usage.token_id(8, random=chance)`` is Where Countries Stand's and
    Where Councils Stand's eleven characters, ``usage.alphabet_id`` Where MPs Stand's form. ``keep_failures`` says
    whether a failed briefing is noted for the owner in ``wts_failures`` (up to 500 characters of its question,
    for 90 days): Where Councils Stand keeps none today, and its privacy notice must be read before it does.
    ``clock`` and ``random`` are given once, here, and every part uses them."""
    read = desk_settings(settings, messages, at_once_per_visitor=at_once_per_visitor, forget_over=forget_over,
                         require_prices_for=require_prices_for, section=section)
    missing = [table for table in _TABLES if table not in db.tables()]
    if missing:
        raise ValueError(f"{db.path} has no {', '.join(missing)}: give StateDB the tables of usage.migrations() "
                         "with the other modules'")
    spending = Spending(db, read.prices, clock=clock)
    return DeskParts(
        messages=messages, prices=read.prices, limits=read.limits, spending=spending,
        caps=Caps(spending, read.limits, messages, clock),
        limiter=RateLimiter(read.requests_per_minute, forget_over=read.forget_over, clock=clock),
        in_progress=BriefingsInProgress(read.at_once_per_visitor, read.at_once, read.estimate_usd),
        cache=SqliteAnswerCache(db, clock=clock), cache_hours=read.cache_hours,
        archive=BriefingArchive(db, new_id=lambda: new_id(random), clock=clock),
        failures=Failures(db, clock=clock) if keep_failures else None, clock=clock, random=random)
