"""The state database: one small SQLite file per site, and the package's own tables in it (ADR 0005).

Every table the package owns has a name starting ``wts_``. Everything else in the file is the site's: the package
never reads or writes a table without the prefix. The package's tables are made and changed by numbered
migrations, which only ever add. A site brings its own rows across once, with ``Import`` statements it declares in
its own repository. The import leaves its old tables exactly as they were; what becomes of them afterwards the
site declares too, as ``OldTables``: the statements that keep them within the site's promises each night, and the
day they are dropped (``StateDB.retire_old``). The only statements run on a site's own tables are the site's own.

Connections are short-lived: one per operation, rows by name, a 30-second wait for a lock. The journal mode is
left as the site's file has it.

What is deleted is gone from the file. SQLite does not wipe what it deletes: a deleted row's bytes, a value an
update replaced and a dropped table's pages stay in the file's unused space until something is written over them,
and every backup copies that space. So each connection made here asks SQLite to overwrite what it deletes
(``PRAGMA secure_delete = ON``), and ``StateDB.compact`` writes the whole file out afresh (``VACUUM``), which also
clears what was deleted before a site moved to this package, or by a connection of the site's own that did not
ask. ``retire_old`` compacts after it drops a site's old tables, and the nightly ``tidy`` command ends with it.
One place is not reached by the first of these: a database that keeps a write-ahead log holds earlier copies of
changed pages in the log, until ``compact`` empties it. ADR 0005 has what was measured and what it costs.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

from wts_core.ports import SYSTEM_CLOCK, Clock

__all__ = ["Import", "ImportFailed", "Migration", "OldTables", "Retired", "StateDB", "StateError", "columns",
           "core_migrations", "iso", "today"]

log = logging.getLogger(__name__)  # ``wts_core.state``: table and import names only, never a row

PREFIX = "wts_"
_PARTIAL = ".partial"  # the ending of a copy that is still being made
_BESIDE = ("-journal", "-wal", "-shm")  # SQLite's own files beside a database
SITE_KEY = "site"  # in ``wts_kv``: the package name of the site whose state database this is


def _another_sites(path: Path, theirs: str, ours: str) -> RuntimeError:
    return RuntimeError(f"{path} is the state database of another site: it is marked {theirs!r}, and this site is "
                        f"{ours!r}. Nothing in it has been changed. Check the data folder this site was started "
                        "with")


def iso(clock: Clock = SYSTEM_CLOCK) -> str:
    """The time now as the sites store it: ISO 8601, UTC, to the second."""
    return clock.now().isoformat(timespec="seconds")


def today(clock: Clock = SYSTEM_CLOCK) -> str:
    return clock.now().strftime("%Y-%m-%d")


@dataclass(frozen=True)
class Migration:
    """A numbered, named change to the package's tables. It may only add: tables, columns with defaults, indexes."""

    number: int
    name: str
    statements: tuple[str, ...]


@dataclass(frozen=True)
class Import:
    """A site's own one-off copy of rows from its old tables into the package's. Run once, in one transaction,
    after the migrations; skipped (and tried again next start) while any table in ``needs`` is missing.

    ``needs`` should name only tables that are in every backup the site's restore accepts. An import that
    needs a table an older backup lacks is skipped on a database restored from that backup, at every start, for
    ever: nothing it brings across arrives, and the site shows no spending and no saved briefings. When some of
    an import's needed tables are there and others are not, that is almost certainly what has happened, and a
    warning says so in the log (``wts_core.state``), naming the import and the missing tables. With none of them
    there the database simply never had the old tables (a new site, or a new install), and nothing is said.

    A statement is SQL, or a function that is given the connection when the import runs and returns the SQL to
    run then: for an old table whose shape is not the same in every copy of the database. Where Landlords Stand's
    ``reports`` gained its ``kind`` column late, so a backup from before has none, and its import reads
    ``columns(con, "reports")`` to choose what to select. The same serves for a table that may be missing: leave
    it out of ``needs`` and make its statement a function that returns nothing when ``columns(con, table)`` is
    empty. The function runs inside the import's transaction and should only read.

    ``written_at`` is how a site that went back and came forward again is noticed. An import runs once. If
    the site is then put back on its old code for a while (the earlier commit is checked out, without the site's
    script for undoing the move being run), the old code writes to the old tables again; when the new code is
    deployed once more the import is marked as done and is skipped, and everything written meanwhile is silently
    missing from the package's tables: spending that no longer counts towards the caps, briefings whose addresses
    answer nothing. So the site says, for each old table the old code adds rows to, which column holds the time a
    row was written (``{"usage": "at", "briefings": "created_at"}``); or gives a function of the connection and
    the time the import ran that returns how many rows are newer, for a table whose times are kept some way that
    cannot be read as a time. Each time the database is opened, while the old tables are still there, a row
    written after the second the import ran stops the site with ``StateError``, which names the tables and the
    mend. The nightly tidy of the old tables never trips this: it changes and deletes rows, and adds none.

    What is declared is checked, so that a slip in it cannot hide a loss. A table named here must be one the
    import ``needs`` or the site's ``OldTables`` names: any other is a mistyped name, and the database is not
    opened. A table that is there without the column named is refused too, naming the columns it does have (a
    site whose old ``briefings`` keeps its time in ``at`` and declares ``created_at`` would otherwise be told
    nothing, ever). A table that is not there at all is passed over: it was dropped on its day, or this copy of
    the database never had it.

    Times are compared as times, to the second, whatever way the old code wrote them: with ``+00:00`` or
    ``Z``, with or without microseconds, with another offset, or as SQLite's own ``datetime('now')`` writes one
    (a space, and no zone: taken as UTC). A value that cannot be read as a time never stops the site: it is
    passed over, and a warning in the log (``wts_core.state``) says how many there were and in which column.

    What this cannot see, and a site's operations page should say:

    * a row the old code wrote in the very second the import ran (it cannot be told from one the import copied);
    * a row with no time at all;
    * what the old code changed in a row that was already there (a report closed, a statement decided): only
      rows added are seen. A site for which that matters gives a function that also looks at its other times;
    * and it can be wrong the other way: if the server's clock was put back between the old code's last write
      and the move, that row is "newer" than the import and the site is stopped, though nothing was lost. The
      mend is the same and loses nothing: run the undo script, start again, and the import brings everything
      across once more."""

    name: str
    statements: tuple[str | Callable[[sqlite3.Connection], Iterable[str]], ...]
    needs: tuple[str, ...] = ()
    written_at: Mapping[str, str | Callable[[sqlite3.Connection, str], int]] = field(default_factory=dict)


class StateError(RuntimeError):
    """The state database is in a state the site must not start on, and only the owner can mend: the message
    says what was found and what to do. Nothing has been changed."""


class ImportFailed(sqlite3.Error):
    """One of a site's imports could not be made: which import, which of its statements, and what SQLite said of
    it (``__cause__`` is SQLite's own error). Nothing of any import was kept: they are made together or not at
    all, and tried again at the next start. ``name`` is the import's, ``statement`` the SQL that failed (its
    number, from 1, is ``number``); a statement given as a function that itself failed has no SQL, and
    ``statement`` is then empty. The SQL is the site's own code and holds no row.

    It is still the kind of error SQLite raised. What is raised is made by ``ImportFailed.of``, and is both an
    ``ImportFailed`` and whatever the bare error was: an ``sqlite3.OperationalError`` for no such column, no such
    table or malformed JSON, an ``sqlite3.IntegrityError`` for a row with no value where one is required. SQLite's
    words are in its message. So whatever caught or matched the old error catches this one."""

    def __init__(self, name: str, number: int, statement: str, cause: BaseException) -> None:
        said = " ".join(statement.split())
        shown = said if len(said) <= 400 else said[:399] + "…"
        what = (f"statement {number} ({shown})" if shown
                else f"statement {number}, a function that could not say what to run")
        super().__init__(f"the import {name!r} failed at {what}: {type(cause).__name__}: {cause}. Nothing was "
                         "imported; the database is as it was, and the import will be tried again at the next start")
        self.name, self.number, self.statement = name, number, statement

    @classmethod
    def of(cls, name: str, number: int, statement: str, cause: sqlite3.Error) -> ImportFailed:
        """The error for a statement that failed with ``cause``: an ``ImportFailed`` that is also of the cause's
        own kind."""
        kind = type(cause)
        made = _FAILED_AS.get(kind)
        if made is None:
            made = _FAILED_AS[kind] = cast("type[ImportFailed]", type(
                cls.__name__, (cls, kind), {"__module__": cls.__module__, "__doc__": cls.__doc__}))
        return made(name, number, statement, cause)


_FAILED_AS: dict[type[sqlite3.Error], type[ImportFailed]] = {}  # each kind of SQLite's error, as an ImportFailed


@dataclass(frozen=True)
class OldTables:
    """What becomes of a site's old tables once its imports have copied from them: declared by the site, beside
    its imports, and applied by ``StateDB.retire_old``, which the site's nightly tidy calls.

    After adoption the old tables stay in the live file so that the deploy can be undone. They would then hold
    what the package has since deleted from its own tables: the addresses of senders whose statements ended three
    months ago, the contacts of closed reports, the questions of failed briefings past their 90 days, and the
    adoption day's visitor secret beside that day's visitor codes. The site's promise is that nothing is kept
    longer than before, so the site says here how its old tables keep to it:

    * ``nightly``: statements run every night while the old tables are there. For each promise the package keeps
      on its own tables, the same on the old one: blank an old statement's address and an old report's contact
      wherever the package's row has none; delete old notes of failures older than the site keeps them; delete
      every old visitor secret but today's. A statement is SQL, which may use the named values ``:now`` (the
      time, as the package stores times) and ``:today`` (the date, ``YYYY-MM-DD``), both UTC; or a function given
      the connection that returns the SQL to run, as for an ``Import``. A statement that names a table no longer
      there is passed over, so the list need not change when a table goes.
    * ``tables``, and when they are dropped: the old tables, and either ``drop_on``, the day from which they are
      dropped, or ``drop_after_days``, so many days after the site's imports ran (the day the last of them ran
      is in ``wts_schema``; ``StateDB.old_tables_due`` gives the day that makes). Exactly one of the two.
      A table is not dropped while an import the site declares has still to run.

    Which to give. The old tables are for going back, and going back also needs the copy of the file made
    before the import, which is deleted so many days after it was made (``StateDB.forget_old_copies``, with the
    days the site keeps a backup). The old tables should go no later than that copy does: after it, the site's
    script for undoing the adoption has nothing to go back to. A fixed date can only keep to that if the deploy
    day is known when the code is written, which it is not: the owner deploys when the owner deploys. So a site
    adopting from now on gives ``drop_after_days`` (the days it keeps a backup, or fewer), and the two keep
    step whatever day the deploy falls on. A fixed ``drop_on`` still works, and is right where the day was
    promised in public: the four sites state 1 February 2027 (docs/UPGRADING.md).

    The package's own tables (``wts_…``) can never be named: they are not a site's to retire."""

    tables: tuple[str, ...]
    drop_on: date | None = None
    nightly: tuple[str | Callable[[sqlite3.Connection], Iterable[str]], ...] = ()
    drop_after_days: int | None = None

    def __post_init__(self) -> None:
        if (self.drop_on is None) == (self.drop_after_days is None):
            raise ValueError("OldTables needs the day the old tables are dropped: drop_on (a date) or "
                             "drop_after_days (so many days after the site's imports ran), and not both")
        if self.drop_after_days is not None and (isinstance(self.drop_after_days, bool)
                                                 or not isinstance(self.drop_after_days, int)
                                                 or self.drop_after_days < 0):
            raise ValueError("OldTables.drop_after_days is a whole number of days, nought or more")
        if isinstance(self.tables, str) or not all(isinstance(t, str) and t for t in self.tables):
            raise ValueError("OldTables.tables is a tuple of the names of the site's old tables")
        own = sorted(t for t in self.tables if t.lower().startswith(PREFIX) or t.lower().startswith("sqlite_"))
        if own:
            raise ValueError(f"OldTables names {', '.join(own)}: only a site's own old tables can be retired, never "
                             "the package's or SQLite's")
        bad = sorted(t for t in self.tables if not t.replace("_", "a").isalnum())
        if bad:
            raise ValueError(f"OldTables names {', '.join(map(repr, bad))}: a table's name is letters, digits and "
                             "underscores")


@dataclass(frozen=True)
class Retired:
    """What one call of ``StateDB.retire_old`` did. ``changed`` is how many rows the nightly statements changed
    or deleted; ``dropped`` the old tables dropped by this call; ``left`` those still there. ``waiting_for``
    names the imports that have not run and so held back a drop that was due: the owner must be told, since the
    old tables are then being kept past the day the site stated. ``compacted`` says whether the file was written
    out afresh after a drop (``StateDB.compact``): None when nothing was dropped and so nothing was tried, False
    when another connection held the file, in which case the next call of ``compact`` (the nightly tidy ends
    with one) does it. ``due`` is the day from which the old tables are dropped, as far as it is known: the
    site's ``drop_on``, or its imports' day and ``drop_after_days`` (None while no import has run, and where the
    site declared no old tables)."""

    changed: int = 0
    dropped: tuple[str, ...] = ()
    left: tuple[str, ...] = ()
    waiting_for: tuple[str, ...] = ()
    # left out of comparisons, so that a site's test comparing the whole value is not affected by them
    compacted: bool | None = field(default=None, compare=False)
    due: date | None = field(default=None, compare=False)


def _due(con: sqlite3.Connection, old: OldTables) -> date | None:
    """The day from which ``old``'s tables are dropped: the day stated, or so many days after the last import ran
    (None while none has)."""
    if old.drop_on is not None:
        return old.drop_on
    ran = con.execute("SELECT max(applied_at) FROM wts_schema WHERE name LIKE 'import:%'").fetchone()[0]
    if not ran or old.drop_after_days is None:
        return None
    return date.fromisoformat(str(ran)[:10]) + timedelta(days=old.drop_after_days)


def _moment(value: object) -> datetime | None:
    """A stored time, to the second and in UTC, however it was written: ISO 8601 with ``+00:00``, ``Z`` or any
    other offset, with or without microseconds, or as SQLite's ``datetime('now')`` writes one (a space, and no
    zone, which is UTC). None for anything that is not a time."""
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    when = when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
    return when.replace(microsecond=0)


def columns(con: sqlite3.Connection, table: str) -> set[str]:
    """The names of a table's columns (none if there is no such table): for an ``Import`` whose statement depends
    on what an old table has."""
    return {row[0] for row in con.execute("SELECT name FROM pragma_table_info(?)", (table,))}


def core_migrations() -> tuple[Migration, ...]:
    """The tables every use of the state database needs. Each module that stores something adds its own."""
    return (
        Migration(1, "kv", ("CREATE TABLE IF NOT EXISTS wts_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)",)),
    )


class StateDB:
    """A site's state database. Implements ``ports.KeyValue`` over the ``wts_kv`` table."""

    def __init__(self, path: Path, *, migrations: Sequence[Migration] = (), imports: Sequence[Import] = (),
                 clock: Clock = SYSTEM_CLOCK, site: str | None = None, old_tables: OldTables | None = None) -> None:
        """``site`` is the site's package name (``Site.package``). Given one, the file is marked as that site's
        (``wts_kv``, key ``site``) the first time it is opened, and a file marked as another site's is refused
        before anything in it is touched: two sites' data folders mixed up on the shared server stop here. The
        mark is what lets a restore refuse a sister site's backup (``ops.BackupSpec.site``).

        ``old_tables`` is what becomes of the tables the imports copied from (``OldTables``). Nothing is done
        with it here: ``retire_old`` applies it, when the site's nightly tidy calls it."""
        self.path = Path(path)
        self.clock = clock
        self.old_tables = old_tables
        self._imports = tuple(imports)
        self._refuse_unknown_written_at()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if site is not None:
            self._refuse_another_sites(site)
        self._migrate((*core_migrations(), *migrations))
        if site is not None:
            self._mark_as(site)
        self._import(imports)

    def _open(self, *, alone: bool = False) -> sqlite3.Connection:
        """A connection that overwrites what it deletes. SQLite keeps that setting for the connection only, so it
        is asked for each time: a row deleted, a value replaced and a table dropped here leave nothing readable
        in the file's unused space, nor in a backup made of it."""
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None) if alone \
            else sqlite3.connect(self.path, timeout=30)
        con.execute("PRAGMA secure_delete = ON")
        con.row_factory = sqlite3.Row
        return con

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A connection for one operation: committed on success, rolled back on an error, always closed. What it
        deletes is overwritten in the file (``PRAGMA secure_delete``)."""
        con = self._open()
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    # Migrations and imports

    @contextmanager
    def _alone(self) -> Iterator[sqlite3.Connection]:
        """A connection holding the database's write lock from the start, with everything done on it (making a
        table included) kept or undone together. Two processes starting at once take turns; a change that fails
        part-way leaves nothing behind."""
        con = self._open(alone=True)
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except BaseException:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def _migrate(self, migrations: Sequence[Migration]) -> None:
        numbers = [m.number for m in migrations]
        if len(set(numbers)) != len(numbers):
            raise ValueError("two migrations have the same number")
        with self._alone() as con:
            con.execute("CREATE TABLE IF NOT EXISTS wts_schema (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
            done = {r["name"] for r in con.execute("SELECT name FROM wts_schema")}  # read under the lock
            for m in sorted(migrations, key=lambda m: m.number):
                key = f"migration:{m.number}:{m.name}"
                if key in done:
                    continue
                for statement in m.statements:
                    con.execute(statement)
                con.execute("INSERT INTO wts_schema (name, applied_at) VALUES (?, ?)", (key, iso(self.clock)))

    # Whose database this is

    def _refuse_another_sites(self, site: str) -> None:
        """Before anything is made or changed: a file already marked as another site's is left exactly as it is."""
        if not self.path.exists():
            return
        con = sqlite3.connect(self.path, timeout=30)
        try:
            marked = con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'wts_kv'").fetchone()
            row = con.execute(f"SELECT value FROM wts_kv WHERE key = '{SITE_KEY}'").fetchone() if marked else None
        finally:
            con.close()
        if row is not None and row[0] != site:
            raise _another_sites(self.path, row[0], site)

    def _mark_as(self, site: str) -> None:
        with self._alone() as con:  # read and written under the one lock: the first mark stands
            con.execute("INSERT OR IGNORE INTO wts_kv (key, value) VALUES (?, ?)", (SITE_KEY, site))
            marked = con.execute("SELECT value FROM wts_kv WHERE key = ?", (SITE_KEY,)).fetchone()["value"]
        if marked != site:
            raise _another_sites(self.path, marked, site)

    def tables(self) -> set[str]:
        with self.connect() as con:
            return {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def _import(self, imports: Sequence[Import]) -> None:
        if not imports:
            return

        def todo(con: sqlite3.Connection) -> list[Import]:
            done = {r["name"] for r in con.execute("SELECT name FROM wts_schema")}
            there = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            return [i for i in imports if f"import:{i.name}" not in done and set(i.needs) <= there]

        with self.connect() as con:
            ready = todo(con)
            self._warn_of_skipped(con, imports)
            self._refuse_rows_newer_than_the_import(con, imports)
            if not ready:
                return
        self._copy_before_first_import()
        with self._alone() as con:  # all of them, or none; and only once, however many processes start together
            waiting = todo(con)
            if waiting:
                self._forget_summaries_of_no_rows(con)
            for i in waiting:
                for number, statement in enumerate(i.statements, start=1):
                    sql = ""  # what is being run, for the error: the site's own SQL, never a row
                    try:
                        for sql in ((statement,) if isinstance(statement, str) else tuple(statement(con))):
                            con.execute(sql)
                    except sqlite3.Error as exc:
                        # SQLite's own message ("no such column: kind") names neither the import nor the
                        # statement, and an owner reading it at a failed start could not tell which to mend
                        raise ImportFailed.of(i.name, number, sql, exc) from exc
                con.execute("INSERT INTO wts_schema (name, applied_at) VALUES (?, ?)",
                            (f"import:{i.name}", iso(self.clock)))

    @staticmethod
    def _forget_summaries_of_no_rows(con: sqlite3.Connection) -> None:
        """Before an import runs: if the spending record is empty, whatever is kept in summary of it is of rows
        that are no longer there, and goes too. That is the state a site's undo script leaves (it clears the
        package's rows and the import's mark, so that the import runs again over the old tables): each account's
        month totals, and the public's count of visitors by the month, would otherwise survive the undo, and
        the second import would bring the same spending back beside them, counted twice in the report of who
        the spending was for. A first import finds both tables empty, and nothing is done. (The day's count of
        all visitors is kept: the rows that come back have no codes to count again.)"""
        tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "wts_spending" not in tables or con.execute("SELECT 1 FROM wts_spending LIMIT 1").fetchone():
            return
        if "wts_account_months" in tables:
            con.execute("DELETE FROM wts_account_months")
        if "wts_visitor_days" in tables:
            con.execute("DELETE FROM wts_visitor_days WHERE who != '*'")

    def _refuse_unknown_written_at(self) -> None:
        """A table named in an import's ``written_at`` that neither the import's ``needs`` nor the site's
        ``OldTables`` names is a mistyped name: left alone, the check it was written for would never be made,
        and nothing would say so."""
        old = set(self.old_tables.tables) if self.old_tables is not None else set()
        for i in self._imports:
            unknown = sorted(set(i.written_at) - set(i.needs) - old)
            if unknown:
                raise StateError(
                    f"{self.path}: the import {i.name!r} says when rows are written to {', '.join(unknown)}, which "
                    "is not a table the import needs or one of the site's old tables ("
                    + (", ".join(sorted(set(i.needs) | old)) or "it names none") + "). A name in written_at that "
                    "matches no old table would never be looked at: correct it. Nothing has been changed")

    def _refuse_rows_newer_than_the_import(self, con: sqlite3.Connection, imports: Sequence[Import]) -> None:
        """An import that has run, whose old tables hold rows written since: the site was run on its old code
        after the move, and what that code wrote is in none of the package's tables. Refused, before anything
        else is done with the database (``Import.written_at`` says why, what a site declares, and what this
        cannot see)."""
        ran = {r["name"]: r["applied_at"] for r in con.execute("SELECT name, applied_at FROM wts_schema "
                                                               "WHERE name LIKE 'import:%'")}
        newer: list[str] = []
        for i in imports:
            mark = ran.get(f"import:{i.name}")
            if mark is None:
                continue
            for table, written in i.written_at.items():
                there = columns(con, table)
                if not there:
                    continue  # the table has gone (dropped on its day), or this database never had it
                if callable(written):
                    count = int(written(con, mark) or 0)
                elif written not in there:
                    raise StateError(
                        f"{self.path}: the import {i.name!r} says rows of {table} are timed by its column "
                        f"{written!r}, and {table} has no such column (it has {', '.join(sorted(there))}). With "
                        "the wrong column named, rows the site's old code wrote after the move would never be "
                        "noticed: correct written_at. Nothing has been changed")
                else:
                    count = self._written_after(con, table, written, str(mark))
                if count:
                    newer.append(f"{table} has {count:,} row{'' if count == 1 else 's'} written after the import "
                                 f"{i.name!r} ran ({mark})")
        if newer:
            raise StateError(
                f"{self.path}: the site's old tables hold rows that are newer than the import that copied them: "
                + "; ".join(newer) + ". The site was run on its old code after it had moved to the shared package, "
                "and what that code wrote is in none of the package's tables: spending that would not count, "
                "saved briefings that would not be found. Nothing has been changed. To mend it: stop the site, "
                "run the site's script for undoing the move (it clears the import's mark and the package's rows; "
                "the old tables are then the whole truth again), and start the site again: the import then brings "
                "everything across, what was written meanwhile included. (If nothing was written on the old code, "
                "and the server's clock was put back about the time of the move, this is a false alarm: the mend "
                "is the same, and loses nothing.)")

    def _written_after(self, con: sqlite3.Connection, table: str, column: str, mark: str) -> int:
        """How many rows of an old table were written after the second the import ran, their times read as
        times. Only rows from the day before the mark on are read (whatever zone a time is written in, its date
        is within a day of the mark's), so a large old table is not gone through at every start."""
        ran = _moment(mark)
        if ran is None:
            return 0  # the mark itself cannot be read: nothing can be said to be after it
        earliest = (ran - timedelta(days=1)).strftime("%Y-%m-%d")
        after = unread = 0
        for (value,) in con.execute(f'SELECT "{column}" FROM "{table}" WHERE typeof("{column}") = \'text\' '
                                    f'AND "{column}" >= ?', (earliest,)):
            when = _moment(value)
            if when is None:
                unread += 1
            elif when > ran:
                after += 1
        # What the reading above never reaches, and must still be said: a time kept as a number (seconds since
        # 1970), which sorts before any text, and one written day first ("16/11/2026 13:00"), which sorts before
        # the year. They are counted, not read: none begins as a date does.
        unread += int(con.execute(
            f'SELECT count(*) FROM "{table}" WHERE "{column}" IS NOT NULL AND (typeof("{column}") != \'text\' '
            f'OR ("{column}" < ? AND "{column}" NOT GLOB \'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*\'))',
            (earliest,)).fetchone()[0])
        if unread:
            log.warning("%s: %d value%s of %s.%s could not be read as a time and %s passed over: a row the site's "
                        "old code wrote there after the move would not be noticed", self.path.name, unread,
                        "" if unread == 1 else "s", table, column, "was" if unread == 1 else "were")
        return after

    def _warn_of_skipped(self, con: sqlite3.Connection, imports: Sequence[Import]) -> None:
        """An import skipped because some of its needed tables are missing, while others are there, will be
        skipped at every start: say so, each time, where the owner looks. (With none of them there, the database
        never had the old tables, and there is nothing to bring across.)"""
        done = {r["name"] for r in con.execute("SELECT name FROM wts_schema")}
        there = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for i in imports:
            missing = sorted(set(i.needs) - there)
            if f"import:{i.name}" in done or not missing or len(missing) == len(set(i.needs)):
                continue
            log.warning(
                "%s: the import %r was skipped, and will be at every start: it needs the table%s %s, which this "
                "database does not have (it has %s). Nothing that import brings across has arrived. If this "
                "database was restored from an older backup, the import's `needs` should name only tables that "
                "are in every backup the site's restore accepts: a statement for a table that may be missing "
                "should be a function that returns nothing when the table is not there",
                self.path.name, i.name, "" if len(missing) == 1 else "s", ", ".join(missing),
                ", ".join(sorted(set(i.needs) & there)))

    # The site's old tables, after its imports

    def retire_old(self) -> Retired:
        """Apply what the site declared for its old tables (``OldTables``), in one transaction: run each nightly
        statement, passing over one that names a table no longer there; then, from the day the site stated, drop
        the old tables. For the site's nightly tidy (the statistics group's ``tidy`` calls it); safe to run every
        night, and to run again: once the tables are gone it does nothing. With no ``OldTables`` it does nothing.

        A drop that is due is held back while any import the site declares has not run, since its rows may be
        nowhere else: ``Retired.waiting_for`` names them, and the caller should tell the owner. Any other fault
        (a column that is not there, say) is raised, with nothing of this call kept.

        After a drop the file is written out afresh (``compact``), so that nothing the old tables held is left
        in its unused space: not what this call dropped, and not what was deleted from them before the site
        moved to this package. ``Retired.compacted`` says whether that could be done."""
        old = self.old_tables
        if old is None:
            return Retired()
        values = {"now": iso(self.clock), "today": today(self.clock)}
        changed = 0
        dropped: list[str] = []
        waiting_for: tuple[str, ...] = ()
        with self._alone() as con:
            for statement in old.nightly:
                for sql in ((statement,) if isinstance(statement, str) else tuple(statement(con))):
                    try:
                        changed += max(con.execute(sql, values).rowcount, 0)
                    except sqlite3.OperationalError as exc:
                        if not str(exc).startswith("no such table"):
                            raise
            there = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            still = [t for t in old.tables if t in there]
            due = _due(con, old)
            if still and due is not None and self.clock.now().date() >= due:
                done = {r["name"] for r in con.execute("SELECT name FROM wts_schema")}
                waiting_for = tuple(i.name for i in self._imports if f"import:{i.name}" not in done)
                if not waiting_for:
                    for table in still:
                        con.execute(f'DROP TABLE "{table}"')
                    dropped, still = still, []
        compacted = self.compact() if dropped else None  # after the transaction: SQLite compacts outside one
        return Retired(changed=changed, dropped=tuple(dropped), left=tuple(still), waiting_for=waiting_for,
                       compacted=compacted, due=due)

    def old_tables_due(self) -> date | None:
        """The day from which the site's old tables are dropped: its ``OldTables.drop_on``, or the day its last
        import ran and ``drop_after_days`` more. None where the site declared no old tables, and while the day
        cannot be known because no import has run yet. For a site's update report and its deploy notes."""
        if self.old_tables is None:
            return None
        with self.connect() as con:
            return _due(con, self.old_tables)

    def compact(self) -> bool:
        """Write the whole file out afresh (SQLite's ``VACUUM``), and empty its write-ahead log where it keeps
        one: afterwards the file holds only what is kept. Each connection made here already overwrites what it
        deletes; this clears what they cannot reach: what was deleted before the site moved to this package (or
        by a connection of the site's own), and the earlier copies of pages a write-ahead log holds. For the end
        of a site's nightly tidy (the statistics group's ``tidy`` calls it); safe every night.

        True when it was done. False when another connection held the file for the whole of the 30-second wait
        (the site was in the middle of a write), or was part-way through a query when the log was to be emptied:
        nothing is lost then, and the next night's call does it.

        The free space it needs. The file is rewritten beside itself first: as much again as the file takes
        up. In a database with a write-ahead log the rewrite also goes through the log, which grows to about the
        size of the file while it is made: so about twice the file's size free, for the length of the call
        (a 540 MB file was measured with a 544 MB log beside its temporary copy). Without the space SQLite
        raises "database or disk is full", nothing is changed, and the file is as it was."""
        con = self._open(alone=True)
        try:
            con.execute("VACUUM")
            # In a database with a write-ahead log the rewrite itself went through the log: fold it in and cut the
            # log to nothing, so that no earlier copy of a page is left there. (It does nothing without a log.)
            held = bool(con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0])
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) and "busy" not in str(exc):
                raise
            held = True
        finally:
            con.close()
        if held:
            log.warning("%s was not compacted: another connection held it. The next tidy tries again",
                        self.path.name)
        return not held

    def _copy_before_first_import(self) -> Path:
        """A copy of the whole file beside it, made with SQLite's own backup so a write-ahead log is included.
        An import that cannot make its copy does not run.

        The copy holds everything the database does, so it is its owner's alone from its first byte: the file it
        is written to is made with mode 0600 before SQLite opens it (SQLite gives a journal the mode of its
        database), and is removed again if the copy fails. A start that is killed outright part-way can remove
        nothing: what it leaves is cleared by ``forget_old_copies``."""
        copy = self.path.with_name(f"{self.path.stem}.pre-wts-core.{today(self.clock)}{self.path.suffix}")
        if copy.exists():
            return copy
        # a name of its own, so two processes starting together cannot write over each other's half-made copy
        partial = copy.with_name(f"{copy.name}.{os.getpid()}.{threading.get_ident()}{_PARTIAL}")
        os.close(os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        try:
            src = sqlite3.connect(self.path, timeout=30)
            try:
                dst = sqlite3.connect(partial)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
            partial.chmod(0o600)
            shutil.move(partial, copy)
        except BaseException:
            for left in (partial, *(partial.with_name(partial.name + ending) for ending in _BESIDE)):
                left.unlink(missing_ok=True)
            raise
        return copy

    def forget_old_copies(self, days: int) -> list[Path]:
        """Delete the copies made before an import (``<name>.pre-wts-core.<date>``) that are more than ``days``
        days old, and say which. A copy is a whole state database as it was, with whatever the site deletes on a
        schedule frozen in it (the day's visitor secret, addresses awaiting deletion), so it must not outlive the
        site's own backups: a site's nightly update calls this with the days it keeps a backup.

        What a start that was killed while making its copy left behind goes too, whatever ``days`` is: a
        half-made copy (``….partial``) and SQLite's own files beside it, once they are more than a day old. (A
        day, so that the half-made copy of a start that is still running is never taken from under it.) Those
        are among the files returned."""
        gone: list[Path] = []
        made_before = f"{self.path.stem}.pre-wts-core."
        for copy in sorted(self.path.parent.glob(f"{made_before}*{self.path.suffix}")):
            stamp = copy.name[len(made_before):len(copy.name) - len(self.path.suffix)]
            try:
                made = date.fromisoformat(stamp)
            except ValueError:
                continue
            if (self.clock.now().date() - made).days > days:
                copy.unlink()
                gone.append(copy)
        a_day_ago = self.clock.now().timestamp() - 86400
        for left in sorted(self.path.parent.glob(f"{made_before}*{_PARTIAL}*")):
            try:
                if left.is_file() and left.stat().st_mtime < a_day_ago:
                    left.unlink()
                    gone.append(left)
            except OSError:  # gone in the meantime: a start that finished, or another tidy
                continue
        return gone

    # Key and value

    def get(self, key: str) -> str | None:
        with self.connect() as con:
            row = con.execute("SELECT value FROM wts_kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        with self.connect() as con:
            con.execute("INSERT INTO wts_kv (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def set_if_absent(self, key: str, value: str) -> None:
        with self.connect() as con:
            con.execute("INSERT OR IGNORE INTO wts_kv (key, value) VALUES (?, ?)", (key, value))

    def delete(self, key: str) -> None:
        with self.connect() as con:
            con.execute("DELETE FROM wts_kv WHERE key = ?", (key,))

    def delete_like(self, pattern: str, *, keep: str | None = None) -> None:
        with self.connect() as con:
            if keep is None:
                con.execute("DELETE FROM wts_kv WHERE key LIKE ?", (pattern,))
            else:
                con.execute("DELETE FROM wts_kv WHERE key LIKE ? AND key != ?", (pattern, keep))
