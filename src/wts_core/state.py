"""The state database: one small SQLite file per site, and the package's own tables in it (ADR 0005).

Every table the package owns has a name starting ``wts_``. Everything else in the file is the site's: the package
never reads or writes a table without the prefix. The package's tables are made and changed by numbered
migrations, which only ever add. A site brings its own rows across once, with ``Import`` statements it declares in
its own repository; its old tables are left exactly as they were.

Connections are short-lived: one per operation, rows by name, a 30-second wait for a lock. The journal mode is
left as the site's file has it.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from wts_core.ports import SYSTEM_CLOCK, Clock

__all__ = ["Import", "Migration", "StateDB", "core_migrations", "iso", "today"]

PREFIX = "wts_"


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
    after the migrations; skipped (and tried again next start) while any table in ``needs`` is missing."""

    name: str
    statements: tuple[str, ...]
    needs: tuple[str, ...] = ()


def core_migrations() -> tuple[Migration, ...]:
    """The tables every use of the state database needs. Each module that stores something adds its own."""
    return (
        Migration(1, "kv", ("CREATE TABLE IF NOT EXISTS wts_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)",)),
    )


class StateDB:
    """A site's state database. Implements ``ports.KeyValue`` over the ``wts_kv`` table."""

    def __init__(self, path: Path, *, migrations: Sequence[Migration] = (), imports: Sequence[Import] = (),
                 clock: Clock = SYSTEM_CLOCK) -> None:
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate((*core_migrations(), *migrations))
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

    def _migrate(self, migrations: Sequence[Migration]) -> None:
        numbers = [m.number for m in migrations]
        if len(set(numbers)) != len(numbers):
            raise ValueError("two migrations have the same number")
        with self.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS wts_schema (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
            done = {r["name"] for r in con.execute("SELECT name FROM wts_schema")}
            for m in sorted(migrations, key=lambda m: m.number):
                key = f"migration:{m.number}:{m.name}"
                if key in done:
                    continue
                for statement in m.statements:
                    con.execute(statement)
                con.execute("INSERT INTO wts_schema (name, applied_at) VALUES (?, ?)", (key, iso(self.clock)))

    def tables(self) -> set[str]:
        with self.connect() as con:
            return {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def _import(self, imports: Sequence[Import]) -> None:
        if not imports:
            return
        with self.connect() as con:
            done = {r["name"] for r in con.execute("SELECT name FROM wts_schema")}
        todo = [i for i in imports if f"import:{i.name}" not in done and set(i.needs) <= self.tables()]
        if not todo:
            return
        self._copy_before_first_import()
        with self.connect() as con:  # all of them, or none
            for i in todo:
                for statement in i.statements:
                    con.execute(statement)
                con.execute("INSERT INTO wts_schema (name, applied_at) VALUES (?, ?)",
                            (f"import:{i.name}", iso(self.clock)))

    def _copy_before_first_import(self) -> Path:
        """A copy of the whole file beside it, made with SQLite's own backup so a write-ahead log is included.
        An import that cannot make its copy does not run."""
        copy = self.path.with_name(f"{self.path.stem}.pre-wts-core.{today(self.clock)}{self.path.suffix}")
        if copy.exists():
            return copy
        partial = copy.with_name(copy.name + ".partial")
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
