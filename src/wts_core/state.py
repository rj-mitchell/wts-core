"""The state database: one small SQLite file per site, and the package's own tables in it (ADR 0005).

Every table the package owns has a name starting ``wts_``. Everything else in the file is the site's: the package
never reads or writes a table without the prefix. The package's tables are made and changed by numbered
migrations, which only ever add. A site brings its own rows across once, with ``Import`` statements it declares in
its own repository; its old tables are left exactly as they were.

Connections are short-lived: one per operation, rows by name, a 30-second wait for a lock. The journal mode is
left as the site's file has it.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from wts_core.ports import SYSTEM_CLOCK, Clock

__all__ = ["Import", "Migration", "StateDB", "columns", "core_migrations", "iso", "today"]

PREFIX = "wts_"
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

    A statement is SQL, or a function that is given the connection when the import runs and returns the SQL to
    run then: for an old table whose shape is not the same in every copy of the database. Where Landlords Stand's
    ``reports`` gained its ``kind`` column late, so a backup from before has none, and its import reads
    ``columns(con, "reports")`` to choose what to select. The function runs inside the import's transaction and
    should only read."""

    name: str
    statements: tuple[str | Callable[[sqlite3.Connection], Iterable[str]], ...]
    needs: tuple[str, ...] = ()


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
                 clock: Clock = SYSTEM_CLOCK, site: str | None = None) -> None:
        """``site`` is the site's package name (``Site.package``). Given one, the file is marked as that site's
        (``wts_kv``, key ``site``) the first time it is opened, and a file marked as another site's is refused
        before anything in it is touched: two sites' data folders mixed up on the shared server stop here. The
        mark is what lets a restore refuse a sister site's backup (``ops.BackupSpec.site``)."""
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if site is not None:
            self._refuse_another_sites(site)
        self._migrate((*core_migrations(), *migrations))
        if site is not None:
            self._mark_as(site)
        self._import(imports)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A connection for one operation: committed on success, rolled back on an error, always closed."""
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    # ---- migrations and imports ---------------------------------------------------------------------------------

    @contextmanager
    def _alone(self) -> Iterator[sqlite3.Connection]:
        """A connection holding the database's write lock from the start, with everything done on it (making a
        table included) kept or undone together. Two processes starting at once take turns; a change that fails
        part-way leaves nothing behind."""
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
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

    # ---- whose database this is ---------------------------------------------------------------------------------

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
            if not todo(con):
                return
        self._copy_before_first_import()
        with self._alone() as con:  # all of them, or none; and only once, however many processes start together
            for i in todo(con):
                for statement in i.statements:
                    for sql in ((statement,) if isinstance(statement, str) else tuple(statement(con))):
                        con.execute(sql)
                con.execute("INSERT INTO wts_schema (name, applied_at) VALUES (?, ?)",
                            (f"import:{i.name}", iso(self.clock)))

    def _copy_before_first_import(self) -> Path:
        """A copy of the whole file beside it, made with SQLite's own backup so a write-ahead log is included.
        An import that cannot make its copy does not run."""
        copy = self.path.with_name(f"{self.path.stem}.pre-wts-core.{today(self.clock)}{self.path.suffix}")
        if copy.exists():
            return copy
        # a name of its own, so two processes starting together cannot write over each other's half-made copy
        partial = copy.with_name(f"{copy.name}.{os.getpid()}.{threading.get_ident()}.partial")
        src = sqlite3.connect(self.path, timeout=30)
        dst = sqlite3.connect(partial)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        shutil.move(partial, copy)
        copy.chmod(0o600)
        return copy

    def forget_old_copies(self, days: int) -> list[Path]:
        """Delete the copies made before an import (``<name>.pre-wts-core.<date>``) that are more than ``days``
        days old, and say which. A copy is a whole state database as it was, with whatever the site deletes on a
        schedule frozen in it (the day's visitor secret, addresses awaiting deletion), so it must not outlive the
        site's own backups: a site's nightly update calls this with the days it keeps a backup."""
        gone: list[Path] = []
        for copy in sorted(self.path.parent.glob(f"{self.path.stem}.pre-wts-core.*{self.path.suffix}")):
            stamp = copy.name[len(self.path.stem) + len(".pre-wts-core."):len(copy.name) - len(self.path.suffix)]
            try:
                made = date.fromisoformat(stamp)
            except ValueError:
                continue
            if (self.clock.now().date() - made).days > days:
                copy.unlink()
                gone.append(copy)
        return gone

    # ---- key and value ------------------------------------------------------------------------------------------

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
