"""The statistics commands, for a site to add to its own command line (ADR 0012).

``stats_commands`` gives three, over the record of each briefing (``wts_core.observe``)::

    app.add_typer(stats_commands(SITE, state, thresholds=lambda: load_settings().section("alerts"),
                                 folder=lambda: load_settings().data_dir / "reports"))

* ``stats --since 7d``: the figures for a period, each beside the weeks before, as a page to read or as JSON;
  then the daily totals the site counts (``observe.counts``). ``--check`` prints only what got worse than the
  owner allows, and ends with status 1 if anything did.
* ``weekly-report``: the same figures for one whole week, saved as ``<year>-W<week>.md`` and ``.json`` in the
  site's reports folder. It prints the two paths, then one sentence for each figure over its threshold, and ends
  with status 1 if there is any, so that the timer that runs it fails and the server's own alerting tells the
  owner. With no thresholds set it prints the thresholds proposed from the week, for the owner to write into
  ``[alerts]``, and ends with status 0: an alert never fires from a number nobody chose.
* ``tidy``: applies the retention the owner accepted (``observe.OWNER_ACCEPTED``) to the record and to the saved
  reports, and says what went. Each site's nightly update runs it. It is the one command a site's timer needs:
  ``also_tidy`` gives it the rest of the site's nightly housekeeping, the right of reply's first of all
  (``cli.replies_tidy``).

These commands are new on every site, so there is no site's wording to keep: what they print is the package's,
in the plain style of the report itself. A site may rename them (Where Countries Stand has a ``stats`` already).

Typer is imported when the commands are built, so ``wts_core.cli`` can be imported without it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wts_core.cli._clock import _clock_of
from wts_core.observe import (
    OWNER_ACCEPTED,
    Retention,
    SqliteBriefingLog,
    Stats,
    counts,
    proposed_thresholds,
    stats,
    tidy_reports,
    tripped,
    weekly_report,
)
from wts_core.observe.report import week_name
from wts_core.ports import SYSTEM_CLOCK, Clock, Embedder, Pricing
from wts_core.settings import Site
from wts_core.state import StateDB
from wts_core.usage import forget_visitors

if TYPE_CHECKING:
    import typer

__all__ = ["StatsNames", "stats_commands"]

_PERIOD = re.compile(r"(\d+)\s*([hdw])")
_UNITS = {"h": "hours", "d": "days", "w": "weeks"}
_WEEK = re.compile(r"(\d{4})-W(\d{1,2})")


@dataclass(frozen=True)
class StatsNames:
    """What a site calls the three commands. None leaves one out."""

    stats: str | None = "stats"
    weekly_report: str | None = "weekly-report"
    tidy: str | None = "tidy"


def stats_commands(site: Site, state: Callable[[], StateDB], *, thresholds: Callable[[], Mapping[str, Any]],
                   folder: Callable[[], Path], embedder: Callable[[], Embedder] | None = None,
                   similarity: float | Callable[[], float] | None = None,
                   pricing: Callable[[], Pricing] | None = None,
                   decided_by: Callable[[], str | None] | None = None, compare_weeks: int = 4,
                   retention: Retention = OWNER_ACCEPTED, names: StatsNames | None = None,
                   backup_days: int | None = None, also_tidy: Sequence[Callable[[], Iterable[str]]] = (),
                   clock: Clock | Callable[[], Clock] = SYSTEM_CLOCK) -> typer.Typer:
    """The site's statistics commands, to add to its own app with ``app.add_typer(...)``.

    Everything the site knows is asked for when a command runs, never when the commands are built: ``state`` (its
    state database, with ``observe.migrations()`` among its migrations), ``thresholds`` (its ``[alerts]`` settings:
    empty until the owner sets them) and ``folder`` (where its weekly reports are kept). ``embedder`` and
    ``similarity`` group readers' questions into themes by meaning: the site's own embedder, so no question
    leaves the server, and the cosine similarity at which two questions are one theme for that model: a number,
    or a function that gives it when a command runs, for a site that keeps it in its settings. ``stats`` uses
    them only when ``--themes`` is given (loading the model takes a while); the weekly report always does.
    ``pricing`` puts whether prompt caching paid back in dollars; ``decided_by`` names the rate that decides the
    site's experiment, if one is running.

    ``backup_days`` is how long the site keeps a backup: ``tidy`` deletes the copies of the database made before
    an import once they are older. ``also_tidy`` is the rest of the site's nightly housekeeping, so that its
    timer runs one command: each is called by ``tidy`` after the package's own work and gives the lines to print
    (``cli.replies_tidy`` is the right of reply's). ``clock`` is a clock, or a function that gives one when a
    command runs."""
    import typer

    clock = _clock_of(clock)

    if embedder is not None and similarity is None:
        raise ValueError("stats_commands: an embedder needs similarity too, the cosine similarity at which two "
                         "questions are one theme for the site's embedding model")
    app = typer.Typer(add_completion=False)
    called = names or StatsNames()

    def stop(why: object) -> typer.Exit:
        typer.echo(str(why), err=True)
        return typer.Exit(1)

    def alike() -> float | None:
        return similarity() if callable(similarity) else similarity

    def figures(since: datetime | timedelta, until: datetime | None, by_meaning: bool) -> Stats:
        log = SqliteBriefingLog(state(), clock=clock)
        return stats(log, since=since, until=until, compare_weeks=compare_weeks,
                     embedder=embedder() if by_meaning and embedder is not None else None,
                     similarity=alike() if by_meaning and embedder is not None else None,
                     pricing=pricing() if pricing is not None else None,
                     decided_by=decided_by() if decided_by is not None else None, clock=clock)

    def alerts(found: Stats) -> list[str]:
        try:
            return tripped(found, thresholds())
        except ValueError as exc:  # a name in [alerts] the package does not know, or a value that is no number
            raise stop(exc) from exc

    def any_set() -> bool:
        return any(value is not None and value != "" for value in thresholds().values())

    since_option = typer.Option("7d", "--since", help="how far back: 24h, 7d, 4w, or a date or time (UTC)")
    until_option = typer.Option(None, "--until", help="up to this date or time (UTC); now if not given")
    json_option = typer.Option(False, "--json", help="print the figures as JSON")
    themes_option = typer.Option(False, "--themes", help="group readers' questions by meaning, with the site's "
                                                         "own embedding model (slower)")
    check_option = typer.Option(False, "--check", help="print only what is over its threshold, and end with "
                                                       "status 1 if anything is")

    if called.stats:
        @app.command(called.stats, help="How briefings went: speed, cost, what the checks found and how each "
                                        "ended, beside the weeks before.")
        def stats_(since: str = since_option, until: str | None = until_option, as_json: bool = json_option,
                   themes: bool = themes_option, check: bool = check_option) -> None:
            if themes and embedder is None:
                raise stop("This site has given no embedding model to group questions with: leave --themes out, "
                           "and questions are grouped by their words.")
            try:
                end = _moment(until) if until else None
                found = figures(_since(since), end, themes)
            except ValueError as exc:
                raise stop(exc) from exc
            over = alerts(found)
            if check:
                for sentence in over:
                    typer.echo(sentence)
                if over:
                    raise typer.Exit(1)
                return
            totals = counts(state(), found.since[:10])
            if as_json:
                typer.echo(json.dumps({"stats": found.as_dict(), "tripped": over, "counts": totals}, indent=2,
                                      ensure_ascii=False))
                return
            typer.echo(found.to_markdown(site, thresholds=thresholds()).rstrip("\n"))
            if totals:
                typer.echo("\n## Daily totals\n")
                for name, days in totals.items():
                    typer.echo(f"- {name}: {sum(days.values()):,} since {found.since[:10]} ("
                               + ", ".join(f"{day} {n:,}" for day, n in days.items()) + ")")

    week_option = typer.Option(None, "--week", help="the week to report: a day in it (2026-11-12) or its name "
                                                    "(2026-W46); the last whole week if not given")
    folder_option = typer.Option(None, "--folder", help="where to save it; the site's reports folder if not given")

    if called.weekly_report:
        @app.command(called.weekly_report, help="Save the week's figures as a page and as JSON, and say what "
                                                "got worse than the thresholds allow.")
        def weekly_report_(week: str | None = week_option, to: Path | None = folder_option) -> None:
            try:
                monday = _monday(week, clock)
                found = figures(monday, monday + timedelta(weeks=1), True)
            except ValueError as exc:
                raise stop(exc) from exc
            over = alerts(found)  # before anything is written: a mistake in [alerts] stops the report
            page, data = weekly_report(found, to if to is not None else folder(), site=site, week=monday.date(),
                                       db=state(), thresholds=thresholds(), clock=clock)
            typer.echo(str(page))
            typer.echo(str(data))
            if not any_set():
                typer.echo(f"No alert thresholds are set yet. These are proposed from {week_name(monday.date())}'s "
                           "figures, for [alerts] in the site's settings:")
                for name, value in proposed_thresholds(found).items():
                    typer.echo(f"{name} = {value:g}")
                return
            for sentence in over:
                typer.echo(sentence)
            if over:
                raise typer.Exit(1)

    if called.tidy:
        @app.command(called.tidy, help="Delete what is older than the record is kept for: old rows, the "
                                       "questions of old failed briefings, and old weekly reports.")
        def tidy() -> None:
            tidied = SqliteBriefingLog(state(), clock=clock).tidy(retention)
            reports = tidy_reports(folder(), retention, clock=clock)
            months = _counted(retention.months, "month")
            typer.echo(f"Deleted {_counted(tidied.deleted, 'record')} of briefings older than {months}.")
            typer.echo(f"Removed the question from {_counted(tidied.blanked, 'record')} of failed briefings older "
                       f"than {_counted(retention.failed_question_days, 'day')}.")
            typer.echo(f"Deleted {_counted(reports, 'weekly report file')} older than {months}.")
            db = state()
            if "wts_spending" in db.tables():
                # the first model call of each day does this too; here it is done on a day with none
                forgotten = forget_visitors(db, clock=clock)
                typer.echo(f"Forgot the visitor codes on {_counted(forgotten, 'spending row')} from before today.")
            if backup_days is not None:
                gone = db.forget_old_copies(backup_days)
                typer.echo(f"Deleted {_counted(len(gone), 'copy', 'copies')} of the database made before an import, "
                           f"older than {_counted(backup_days, 'day')}.")
            for step in also_tidy:  # the rest of the site's nightly housekeeping, in its own words
                for line in step():
                    typer.echo(line)

    return app


def _counted(n: int, one: str, several: str | None = None) -> str:
    """A count with its noun, as it is said: "1 record", "2 records", "0 copies"."""
    return f"{n:,} {one if n == 1 else several or one + 's'}"


def _moment(text: str) -> datetime:
    """A date or a time as the owner types it, in UTC unless it says otherwise."""
    try:
        moment = datetime.fromisoformat(text.strip())
    except ValueError:
        raise ValueError(f"{text!r} is not a date or time: write 2026-11-12 or 2026-11-12T04:30") from None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _since(text: str) -> datetime | timedelta:
    period = _PERIOD.fullmatch(text.strip().lower())
    if period:
        if int(period[1]) < 1:
            raise ValueError("the period must be at least one hour")
        return timedelta(**{_UNITS[period[2]]: int(period[1])})
    try:
        return _moment(text)
    except ValueError:
        raise ValueError(f"{text!r} is not a period: write 24h, 7d or 4w, or a date or time such as "
                         "2026-11-12") from None


def _monday(week: str | None, clock: Clock) -> datetime:
    """Midnight UTC on the Monday of the week asked for; of the last whole week when none is."""
    if week is None:
        day = clock.now().astimezone(UTC).date() - timedelta(weeks=1)
    else:
        named = _WEEK.fullmatch(week.strip().upper())
        try:
            day = date.fromisocalendar(int(named[1]), int(named[2]), 1) if named else _moment(week).date()
        except ValueError:
            raise ValueError(f"{week!r} is not a week: write a day in it (2026-11-12) or its name "
                             "(2026-W46)") from None
    monday = day - timedelta(days=day.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=UTC)
