"""The statistics commands, for a site to add to its own command line (ADR 0012).

``stats_commands`` gives four, over the record of each briefing (``wts_core.observe``)::

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
  (``cli.replies_tidy``). Where the site's state database declares what becomes of its old tables
  (``state.OldTables``), ``tidy`` applies that too (``StateDB.retire_old``), and ends with status 1 if the day to
  drop them has passed and they could not be dropped. Its order is fixed, and the order is the point:

  1. the package's own deletions: old rows of the record, old weekly reports, the visitor codes on spending rows
     from before today, notes of failed briefings past their 90 days, every day's visitor secret but today's,
     cached answers past the site's cache hours, old copies of the database made before an import;
  2. the site's own steps (``also_tidy``): the right of reply's deletions among them;
  3. the site's old tables, after those steps, so that an address the right of reply deleted tonight is gone
     from the old row tonight as well;
  4. last of all, the file is written out afresh (``StateDB.compact``), so that nothing deleted tonight, or ever
     before, is left in its unused space or in the backups made from now on. If the site is using the file at
     that moment the step says plainly that it was NOT done and is tried again the next night: one such night is
     ordinary and the command still ends with status 0; on the second night running it ends with status 1.

* ``propose-questions --since 7d``: test questions proposed from the period's real questions (those that found no
  records, were rated not useful, or whose briefings the checks flagged most), written for the owner to approve as
  a fragment in the shape of the site's ``eval/questions.toml``. It writes one file under the site's data folder
  and prints its path. It adds nothing to the test set: a person approves each question (``observe.propose``).

Where the site declares an experiment (``experiment``), ``stats`` and the weekly report say whether it is running
and, if it is not, why; and one that is declared and cannot run is said with what tripped, so ``--check`` and the
weekly report's timer fail and the owner is told.

``stats --json`` prints one object with three keys: ``stats`` (the figures, ``Stats.as_dict()``), ``tripped`` (the
sentences for what is over its threshold) and ``counts`` (the daily totals). The figures are inside ``stats``,
not at the top. ``weekly-report`` always groups questions by meaning where the site gives an embedder, so it loads
the site's real embedding model each time it runs: a site's test of the command passes ``embedder`` a stand-in
(``testing.RecordingEmbedder``, or ``adapters.hashing``), or it will load, or try to download, the real one.

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
    proposals_toml,
    proposed_questions,
    proposed_thresholds,
    stats,
    tidy_reports,
    tripped,
    weekly_report,
)
from wts_core.observe.log import months_before
from wts_core.observe.report import _write, week_name
from wts_core.ports import SYSTEM_CLOCK, Clock, Embedder, ExperimentState, Pricing
from wts_core.settings import Site
from wts_core.state import StateDB, today
from wts_core.usage import Failures, SqliteAnswerCache, forget_earlier_days, forget_old_secrets

if TYPE_CHECKING:
    import typer

__all__ = ["StatsNames", "stats_commands", "write_afresh"]

_PERIOD = re.compile(r"(\d+)\s*([hdw])")
_UNITS = {"h": "hours", "d": "days", "w": "weeks"}
_WEEK = re.compile(r"(\d{4})-W(\d{1,2})")


_PROPOSALS = "proposed-questions"  # the folder, beside the weekly reports, that proposed test questions go in
_PROPOSAL = re.compile(r"(\d{4}-\d{2}-\d{2})(?:-from-(\d{4}-\d{2}-\d{2}))?\.toml")


@dataclass(frozen=True)
class StatsNames:
    """What a site calls the four commands. None leaves one out."""

    stats: str | None = "stats"
    weekly_report: str | None = "weekly-report"
    tidy: str | None = "tidy"
    propose: str | None = "propose-questions"


def stats_commands(site: Site, state: Callable[[], StateDB], *, thresholds: Callable[[], Mapping[str, Any]],
                   folder: Callable[[], Path], embedder: Callable[[], Embedder] | None = None,
                   similarity: float | Callable[[], float] | None = None,
                   pricing: Callable[[], Pricing] | None = None,
                   decided_by: Callable[[], str | None] | None = None, compare_weeks: int = 4,
                   retention: Retention = OWNER_ACCEPTED, names: StatsNames | None = None,
                   backup_days: int | None = None, also_tidy: Sequence[Callable[[], Iterable[str]]] = (),
                   cache_hours: float | Callable[[], float] | None = None,
                   clock: Clock | Callable[[], Clock] = SYSTEM_CLOCK,
                   experiment: Callable[[], ExperimentState | None] | None = None,
                   proposals: Callable[[], Path] | None = None,
                   proposals_leave_out: Callable[[str], bool] | None = None) -> typer.Typer:
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
    an import once they are older. What becomes of the site's old tables is not given here: the site declares it
    on its state database (``StateDB(..., old_tables=…)``), and ``tidy`` applies it, after ``also_tidy``.
    ``also_tidy`` is the rest of the site's nightly housekeeping, so that its timer runs one command: each is
    called by ``tidy`` after the package's own deletions and gives the lines to print (``cli.replies_tidy`` is
    the right of reply's). ``cache_hours`` is how long the site keeps a cached answer (its
    ``[usage] answer_cache_hours``; a number, or a function that gives it when the command runs): given it,
    ``tidy`` deletes the cached answers that are older, which otherwise go only when the next answer is stored.
    ``clock`` is a clock, or a function that gives one when a command runs.

    ``experiment`` gives the site's experiment as it stands when a command runs
    (``briefing.experiment_switch(...).state(clock)``; None where the site declares none): the figures then say
    whether it is running and why not, its deciding rate is the one the arms are compared on (``decided_by``
    need not be given as well), and an experiment that is declared and cannot run is among what tripped.
    ``proposals`` is the folder proposed test questions are written to; left out, it is a folder named
    ``proposed-questions`` beside the weekly reports, in the site's data folder. ``tidy`` deletes a file of
    proposals once the oldest question it could hold (the first day of the period it was made for) is older
    than the record itself is kept, so no question outlives its record in one.

    ``proposals_leave_out`` says which saved briefings' questions are never proposed: a function given a
    briefing's id, true for one that is hidden while a concern about it is decided (or that the site shows as
    hidden because of what it cites). The command will not run until the site has given it: this group
    cannot read the right of reply's tables to find out (ADR 0008), and a question someone has raised a concern
    about must not be copied into another file meanwhile. A site with a right of reply gives
    ``lambda briefing: replies().hidden(f"/b/{briefing}") is not None``, with its own address for a briefing;
    a site where nothing can be hidden says so with ``lambda briefing: False``. (A briefing withdrawn,
    corrected or reported is left out in any case, from the record's own marks.)"""
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
                     decided_by=decided_by() if decided_by is not None else None, clock=clock,
                     experiment=experiment() if experiment is not None else None)

    def alerts(found: Stats) -> list[str]:
        try:
            over = tripped(found, thresholds())
        except ValueError as exc:  # a name in [alerts] the package does not know, or a value that is no number
            raise stop(exc) from exc
        state = found.experiment
        if state is not None and state.fault:
            # not a threshold, and the owner must hear of it all the same: readers are on the control alone
            called = f"The experiment {state.name}" if state.name else "The experiment in the site's settings"
            over.append(f"{called} is declared and is not running: {state.why}"
                        + ("" if state.why.endswith(".") else "."))
        return over

    def proposals_folder() -> Path:
        return proposals() if proposals is not None else folder().parent / _PROPOSALS

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
            for sentence in over:  # with no thresholds set, only an experiment that cannot run can be here
                typer.echo(sentence)
            if over:
                raise typer.Exit(1)

    limit_option = typer.Option(10, "--limit", min=1, help="how many questions of each kind to propose")
    to_option = typer.Option(None, "--to", help="the folder to write the file in; the site's own if not given")

    if called.propose:
        @app.command(called.propose, help="Propose test questions from readers' real questions, for the owner to "
                                          "approve. Nothing is added to the test set.")
        def propose(since: str = since_option, until: str | None = until_option, limit: int = limit_option,
                    to: Path | None = to_option) -> None:
            if proposals_leave_out is None:
                raise stop("This site has not said which briefings' questions are never to be proposed (those "
                           "hidden while a concern about them is decided), so none are proposed: give "
                           "stats_commands(proposals_leave_out=…) a function of a briefing's id.")
            try:
                end = _moment(until) if until else clock.now()
                span = _since(since)
                start = end - span if isinstance(span, timedelta) else span
                found = proposed_questions(SqliteBriefingLog(state(), clock=clock), since=start, until=end,
                                           limit=limit, clock=clock, leave_out=proposals_leave_out)
            except ValueError as exc:
                raise stop(exc) from exc
            where = to if to is not None else proposals_folder()
            where.mkdir(parents=True, exist_ok=True)
            # named for the day it was made and for the first day it covers: the tidy deletes it by the second
            path = where / f"{end.astimezone(UTC):%Y-%m-%d}-from-{start.astimezone(UTC):%Y-%m-%d}.toml"
            # for the owner only, like a weekly report: it quotes readers' questions
            _write(path, proposals_toml(found, site, since=start, until=end))
            typer.echo(str(path))
            typer.echo(f"{_counted(len(found), 'question')} proposed. Nothing has been added to the test set: "
                       "read the file, and copy what you approve into eval/questions.toml by hand.")

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
            old_proposals = _tidy_proposals(proposals_folder(), months_before(clock.now(), retention.months))
            if old_proposals:  # said only when there were some: most sites will never have made one
                typer.echo(f"Deleted {_counted(old_proposals, 'file')} of proposed test questions that could hold "
                           f"a question older than {months}.")
            db = state()
            tables = db.tables()
            if "wts_spending" in tables:
                # the first model call of each day does this too; here it is done on a day with none
                forgotten = forget_earlier_days(db, clock=clock)
                typer.echo(f"Forgot the visitor codes on {_counted(forgotten.codes, 'spending row')} from before "
                           "today.")
                if forgotten.accounts:  # only a site with signed-in accounts ever has any
                    typer.echo(f"Forgot the signed-in account on {_counted(forgotten.accounts, 'spending row')} "
                               "from before today.")
            if "wts_failures" in tables:
                # the next failure does this too; here it is done on a site where nothing more has failed
                notes = Failures(db, clock=clock).tidy()
                typer.echo(f"Deleted {_counted(notes, 'note')} of failed briefings older than 90 days.")
            # the day's first visitor does this too; here it is done on a day with none
            secrets = forget_old_secrets(db, clock)
            typer.echo(f"Deleted {_counted(secrets, 'visitor secret')} of earlier days.")
            if cache_hours is not None and "wts_answer_cache" in tables:
                hours = cache_hours() if callable(cache_hours) else cache_hours
                stale = SqliteAnswerCache(db, clock=clock).purge(hours)
                typer.echo(f"Deleted {_counted(stale, 'cached answer')} older than the {hours:g} "
                           f"hour{'' if hours == 1 else 's'} the site keeps one.")
            if backup_days is not None:
                gone = db.forget_old_copies(backup_days)
                typer.echo(f"Deleted {_counted(len(gone), 'copy', 'copies')} of the database made before an import, "
                           f"older than {_counted(backup_days, 'day')}.")
            for step in also_tidy:  # the rest of the site's nightly housekeeping, in its own words
                for line in step():
                    typer.echo(line)
            # after the site's own steps: what the right of reply deleted tonight goes from the old rows tonight
            held_back = _retire(db, typer.echo)
            # last: nothing deleted above, or ever before, is left in the file's unused space
            nights = write_afresh(db, typer.echo)
            # after everything else has been done: the timer fails, and the owner is told
            if held_back or nights >= 2:
                raise typer.Exit(1)

    return app


_NOT_AFRESH = "tidy:nights_not_written_afresh"  # in ``wts_kv``: how many nights running the last step was missed


def write_afresh(db: StateDB, say: Callable[[str], Any]) -> int:
    """The tidy's last step: write the file out afresh (``StateDB.compact``), and say honestly whether it was
    done. Returns how many nights running it has not been: 0 when it was.

    SQLite says that another connection was in the way in its answer to the checkpoint, not with an error, and
    ``compact`` reads the answer. One such night is ordinary (a reader part-way through a query at that moment):
    it is said, and tried again the next night. Two nights running is not: the count is kept, and the command
    then ends with status 1, so that the timer fails and the owner is told. Nights are counted, not runs:
    a second run on the same day (UTC, by the database's clock) that is also in the way leaves the count as it
    was, so an owner who runs the tidy again by hand does not set off the alert.

    A site with a nightly command of its own, and no stats group, calls this last there, with what prints a line
    (``typer.echo``), and ends with status 1 when it returns 2 or more."""
    if db.compact():
        if db.get(_NOT_AFRESH):
            db.delete(_NOT_AFRESH)
        say("Wrote the database out afresh: nothing deleted is left in the file.")
        return 0
    counted, _, last = (db.get(_NOT_AFRESH) or "0").partition(" ")  # how many nights, and the day of the last
    tonight = today(db.clock)
    nights = int(counted or 0) + (0 if last == tonight else 1)
    db.set(_NOT_AFRESH, f"{nights} {tonight}")
    say("The database was NOT written out afresh tonight: the site was using it at that moment. What was deleted "
        "tonight may still be in the file's unused space or in its write-ahead log. It will be tried again at the "
        "next tidy." + (f" That is {nights} nights running." if nights >= 2 else ""))
    return nights


def _tidy_proposals(folder: Path, too_old: datetime) -> int:
    """Delete the files of proposed test questions whose oldest question could be from before ``too_old``, so
    that no question quoted in one is kept longer than the record it came from. A file is named for the day it
    was made and the first day of the period it covers (``2026-11-16-from-2026-10-17.toml``), and goes by the
    second: one made for a year back is deleted when its first day is as old as the record is kept, not a year
    later. (A file named for its day alone goes by that day.) Only files named as the command names them are
    touched."""
    deleted = 0
    for path in sorted(folder.glob("*.toml")) if folder.is_dir() else []:
        named = _PROPOSAL.fullmatch(path.name)
        try:
            oldest = datetime.fromisoformat(named[2] or named[1]).replace(tzinfo=UTC) if named else None
        except ValueError:
            oldest = None
        if oldest is not None and oldest < too_old:
            path.unlink()
            deleted += 1
    return deleted


def _retire(db: StateDB, say: Callable[[str], Any]) -> bool:
    """Keep the site's old tables within its promises, and drop them once their day has come
    (``StateDB.retire_old``): nothing is done or said on a site that declared none. True when a drop that was due
    was held back, which the owner must hear of."""
    old = db.old_tables
    if old is None:
        return False
    retired = db.retire_old()
    if retired.dropped:
        say(f"Dropped the site's old tables, kept since it moved to the shared package: {', '.join(retired.dropped)}.")
    elif retired.left and not retired.waiting_for:
        when = (f"They are dropped on {retired.due.isoformat()}." if retired.due is not None
                else f"They are dropped {_counted(old.drop_after_days or 0, 'day')} after the site's import has "
                     "run, which it has not yet.")
        say(f"Kept the site's old tables within what it promises: {_counted(retired.changed, 'row')} changed or "
            f"deleted. {when}")
    if retired.waiting_for:
        due = retired.due.isoformat() if retired.due is not None else "a day now past"
        say(f"Kept the site's old tables within what it promises: {_counted(retired.changed, 'row')} changed or "
            "deleted.")
        say(f"The site's old tables ({', '.join(retired.left)}) were due to be dropped on {due} "
            f"and were not, because {_counted(len(retired.waiting_for), 'import has', 'imports have')} not run: "
            f"{', '.join(retired.waiting_for)}. The log from the site's start says which table each is waiting "
            "for. Until that is settled the old tables are kept past the day the site stated.")
    return bool(retired.waiting_for)


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
