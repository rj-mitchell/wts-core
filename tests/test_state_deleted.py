"""What is deleted is gone from the file: its bytes are searched, and those of a backup made then.

SQLite does not wipe what it deletes. A deleted row, a value an update replaced and a dropped table's pages stay
in the file's unused space until something is written over them, and a backup copies that space: Where Councils
Stand's review found seven senders' addresses in a backup made 125 days after they were "deleted". So every
connection ``StateDB`` makes overwrites what it deletes, ``retire_old`` writes the file out afresh after it drops
a site's old tables, and ``compact`` does the same for the nightly tidy.

Each test looks for an address that could be nothing else, in the bytes of the database file (and of its
write-ahead log, where it has one) and in the bytes of a backup made at that moment.
"""

from __future__ import annotations

import gzip
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from test_replies_sites import SITES, Open
from wts_core.ops import BackupSpec, make_backup
from wts_core.state import Import, ImportFailed, Migration, OldTables, StateDB
from wts_core.testing import FixedClock

ADDRESS = "a.sender@deleted-address.example"
SPEC = BackupSpec(prefix="test-state-", keep=3, required_tables=("wts_schema",))


def held_in(path: Path, needle: str = ADDRESS) -> list[str]:
    """Where ``needle`` is to be found: in the database file, its write-ahead log, or a backup made now."""
    found = [name for name, file in (("the file", path), ("its write-ahead log", Path(f"{path}-wal")))
             if file.exists() and needle.encode() in file.read_bytes()]
    backup = make_backup(path, path.parent / "backups", SPEC, clock=FixedClock())
    assert backup is not None
    if needle.encode() in gzip.decompress(backup.read_bytes()):
        found.append("a backup")
    return found


def old_statements(path: Path, rows: int = 40) -> None:
    """A site's old table of statements, written as the site's own code wrote it before the package: by a
    connection that does not overwrite what it deletes."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE statements (id INTEGER PRIMARY KEY, email TEXT, text TEXT)")
    con.executemany("INSERT INTO statements (email, text) VALUES (?, ?)",
                    [(f"sender{n}@old-table.example" if n else ADDRESS, "The words of a statement. " * 8)
                     for n in range(rows)])
    con.commit()
    con.close()


# A deletion


def test_addresses_the_right_of_reply_deletes_are_in_the_file_and_its_backup_nowhere(tmp_path):
    """The real path: statements are declined, three months pass, and their confirming addresses are deleted,
    with the address the owner wrote into one reason."""
    site = Open(SITES["countries"], tmp_path)
    for n in range(30):
        sid = site.send(email=f"sender{n}.{ADDRESS}")
        site.replies.decline(sid, f"Told sender{n}.{ADDRESS} it is about another delegation." if n == 7
                             else "It is about another delegation.")
    assert held_in(site.db.path) == ["the file", "a backup"]  # kept while they may be needed
    site.clock.advance(days=93)
    assert site.replies.forget_old_emails() == 30
    assert held_in(site.db.path) == []
    assert site.replies.statement(8)["reason"] == "Told [address deleted] it is about another delegation."


def test_a_deleted_row_and_a_replaced_value_leave_nothing_behind(tmp_path):
    db = StateDB(tmp_path / "state.db")
    for n in range(30):
        db.set(f"key{n}", f"{n}-{ADDRESS}" if n % 3 else f"other-{n}@kept.example")
    db.delete_like("key1%")  # rows deleted
    with db.connect() as con:  # values replaced, by a longer and by a shorter one
        con.execute("UPDATE wts_kv SET value = 'x' WHERE key IN ('key2', 'key4', 'key5')")
        con.execute("UPDATE wts_kv SET value = value || value || 'kept' WHERE value LIKE 'other-%'")
        con.execute("DELETE FROM wts_kv WHERE value LIKE ?", (f"%{ADDRESS}",))
    assert held_in(db.path) == []
    assert db.get("key0") == "other-0@kept.exampleother-0@kept.examplekept"  # what is kept is whole


def test_every_connection_overwrites_what_it_deletes(tmp_path):
    """SQLite keeps the setting for a connection, not for the file, so each one asks."""
    db = StateDB(tmp_path / "state.db")
    with db.connect() as con:
        assert con.execute("PRAGMA secure_delete").fetchone()[0] == 1
    with db._alone() as con:
        assert con.execute("PRAGMA secure_delete").fetchone()[0] == 1


# A site's old tables: a retire, and a drop


def test_an_address_blanked_in_an_old_table_by_the_nightly_statements_is_gone_once_the_night_is_done(tmp_path):
    """The nightly statement blanks the address, and that row's bytes are overwritten at once. But the table grew
    under the site's old code, which overwrote nothing: when SQLite split its first page it left a copy of the
    early rows behind in the page it turned into an index, and no statement can reach that copy. Writing the
    file out afresh does, which is why the nightly tidy ends with it."""
    path = tmp_path / "state.db"
    old_statements(path)
    copies = path.read_bytes().count(ADDRESS.encode())
    assert copies == 2 and held_in(path) == ["the file", "a backup"]  # the row, and the stray copy of it
    old = OldTables(tables=("statements",), drop_on=date(2027, 1, 1),
                    nightly=("UPDATE statements SET email = NULL WHERE email = '" + ADDRESS + "'",))
    db = StateDB(path, old_tables=old, clock=FixedClock())
    retired = db.retire_old()
    assert retired.changed == 1 and retired.left == ("statements",) and retired.compacted is None
    assert path.read_bytes().count(ADDRESS.encode()) == 1  # the row's own bytes went with the statement
    assert db.compact() is True  # the tidy command's last step
    assert held_in(path) == []
    assert b"sender7@old-table.example" in path.read_bytes()  # the other rows are as they were


def test_a_table_that_grows_under_the_package_leaves_no_stray_copy_to_begin_with(tmp_path):
    """The same growth, written by the package's own connections: a split page is wiped as it is reused, so a
    deletion needs no compacting to be complete."""
    db = StateDB(tmp_path / "state.db",
                 migrations=[Migration(90, "senders", ("CREATE TABLE wts_senders (id INTEGER PRIMARY KEY, "
                                                       "email TEXT, text TEXT)",))])
    for n in range(40):  # one connection a row, as a site writes
        with db.connect() as con:
            con.execute("INSERT INTO wts_senders (email, text) VALUES (?, ?)",
                        (f"sender{n}@kept.example" if n else ADDRESS, "The words of a statement. " * 8))
    assert db.path.read_bytes().count(ADDRESS.encode()) == 1
    with db.connect() as con:
        con.execute("UPDATE wts_senders SET email = NULL WHERE email = ?", (ADDRESS,))
    assert held_in(db.path) == []


def test_a_dropped_table_leaves_none_of_its_rows_in_the_file(tmp_path):
    path = tmp_path / "state.db"
    old_statements(path)
    old = OldTables(tables=("statements",), drop_on=date(2026, 11, 20))
    clock = FixedClock("2026-11-20T03:00:00+00:00")
    retired = StateDB(path, old_tables=old, clock=clock).retire_old()
    assert retired.dropped == ("statements",) and retired.compacted is True
    assert held_in(path) == [] and held_in(path, "@old-table.example") == []


def test_what_the_old_code_deleted_without_wiping_goes_when_the_old_tables_are_dropped(tmp_path):
    """The address was "deleted" months ago by the site's own code, which did not overwrite it: it is in no row,
    and in the file all the same. Overwriting from now on cannot reach it; writing the file out afresh does."""
    path = tmp_path / "state.db"
    old_statements(path)
    con = sqlite3.connect(path)
    con.execute("DELETE FROM statements WHERE email = ?", (ADDRESS,))
    con.commit()
    assert con.execute("SELECT count(*) FROM statements WHERE email = ?", (ADDRESS,)).fetchone()[0] == 0
    con.close()
    assert held_in(path) == ["the file", "a backup"]  # no row holds it; the file and its backup do
    db = StateDB(path, old_tables=OldTables(tables=("statements",), drop_on=date(2026, 11, 20)),
                 clock=FixedClock("2026-11-19T03:00:00+00:00"))
    assert db.retire_old().dropped == () and held_in(path) == ["the file", "a backup"]  # not its day yet
    assert db.compact() is True  # the nightly tidy's last step
    assert held_in(path) == []
    with db.connect() as con:
        assert con.execute("SELECT count(*) FROM statements").fetchone()[0] == 39  # the rows kept are all there


def test_compacting_keeps_every_row_and_the_sites_mark(tmp_path):
    db = StateDB(tmp_path / "state.db", site="councils",
                 migrations=[Migration(90, "things", ("CREATE TABLE wts_things (id INTEGER PRIMARY KEY, x TEXT)",))])
    with db.connect() as con:
        con.executemany("INSERT INTO wts_things (x) VALUES (?)", [(f"thing {n}",) for n in range(500)])
        con.execute("DELETE FROM wts_things WHERE id % 2 = 0")
    before = db.path.stat().st_size
    assert db.compact() is True and db.path.stat().st_size <= before
    with db.connect() as con:
        assert con.execute("SELECT count(*), min(id), max(id) FROM wts_things").fetchone()[:] == (250, 1, 499)
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert StateDB(db.path, site="councils").get("site") == "councils"


# A database with a write-ahead log


def test_with_a_write_ahead_log_the_log_holds_the_deleted_address_until_the_file_is_compacted(tmp_path):
    """Where MPs Stand's state database keeps a write-ahead log. Overwriting on delete cleans the page, but the
    log still holds the page as it was before, for as long as the log is there: SQLite removes it when the last
    connection closes, and on a site that is serving there is nearly always another open. A backup (made by
    SQLite's own copy) never has the address; the log beside the live file does, until the nightly ``compact``."""
    path = tmp_path / "state.sqlite"
    sqlite3.connect(path).execute("PRAGMA journal_mode = WAL").close()
    db = StateDB(path)
    another = sqlite3.connect(path)  # the site, with a connection open as it serves
    try:
        another.execute("SELECT count(*) FROM wts_kv").fetchone()
        db.set("address", ADDRESS)
        assert "a backup" in held_in(path)
        db.delete("address")
        assert held_in(path) == ["its write-ahead log"]  # in no row, no page of the file and no backup
        assert db.compact() is True
        assert held_in(path) == [] and Path(f"{path}-wal").stat().st_size == 0
    finally:
        another.close()
    with db.connect() as con:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"  # left as the site's file has it
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_with_a_write_ahead_log_and_nothing_else_open_the_log_goes_with_each_connection(tmp_path):
    path = tmp_path / "state.sqlite"
    sqlite3.connect(path).execute("PRAGMA journal_mode = WAL").close()
    db = StateDB(path)
    db.set("address", ADDRESS)
    db.delete("address")
    assert held_in(path) == [] and not Path(f"{path}-wal").exists()


# An import that fails says which, and where


def test_a_failed_import_names_the_import_and_the_statement_that_failed(tmp_path):
    """SQLite's own message ("no such column: kind") names neither. The owner reads this at a start that failed."""
    path = tmp_path / "state.db"
    sqlite3.connect(path).executescript("CREATE TABLE reports (id INTEGER PRIMARY KEY, message TEXT);"
                                        "INSERT INTO reports VALUES (1, 'A report nobody should see quoted');")
    reports = Import("reports", ("INSERT INTO wts_kv (key, value) VALUES ('first', 'done')",
                                 "INSERT INTO wts_kv (key, value)\n    SELECT 'r' || id, kind FROM reports"),
                     needs=("reports",))
    with pytest.raises(ImportFailed) as caught:
        StateDB(path, imports=[reports])
    said = str(caught.value)
    assert "the import 'reports' failed at statement 2" in said
    assert "INSERT INTO wts_kv (key, value) SELECT 'r' || id, kind FROM reports" in said  # on one line
    assert "no such column: kind" in said and "OperationalError" in said
    assert isinstance(caught.value.__cause__, sqlite3.OperationalError)  # SQLite's own, for whoever needs it
    assert (caught.value.name, caught.value.number) == ("reports", 2)
    assert "nobody should see" not in said  # the statement is the site's code: never a row
    assert StateDB(path).get("first") is None  # nothing of the import was kept


def test_a_failed_statement_built_when_the_import_runs_is_named_too(tmp_path):
    path = tmp_path / "state.db"
    sqlite3.connect(path).executescript("CREATE TABLE reports (id INTEGER PRIMARY KEY);")

    def by_shape(con: sqlite3.Connection) -> list[str]:
        return ["INSERT INTO wts_kv (key, value) VALUES ('a', 'b')", "INSERT INTO no_such_table VALUES (1)"]

    with pytest.raises(ImportFailed, match=r"the import 'old reports' failed at statement 1 \(INSERT INTO "
                                           r"no_such_table VALUES \(1\)\): OperationalError: no such table"):
        StateDB(path, imports=[Import("old reports", (by_shape,), needs=("reports",))])
    assert StateDB(path).get("a") is None


def test_a_failed_import_is_still_the_kind_of_error_sqlite_raised(tmp_path):
    """A site's own tests, and anything else that caught the bare error, catch this one: Where Councils Stand
    expects ``sqlite3.IntegrityError`` of an old statement's log entry with no time, and
    ``sqlite3.OperationalError`` of a log that is not JSON."""
    path = tmp_path / "state.db"
    sqlite3.connect(path).executescript("CREATE TABLE old (id INTEGER PRIMARY KEY, log TEXT);"
                                        "INSERT INTO old VALUES (1, 'not json');")
    no_value = Import("no value", ("INSERT INTO wts_schema (name, applied_at) SELECT 'x', NULL FROM old",),
                      needs=("old",))
    with pytest.raises(sqlite3.IntegrityError, match="NOT NULL constraint failed") as caught:
        StateDB(path, imports=[no_value])
    assert isinstance(caught.value, ImportFailed) and not isinstance(caught.value, sqlite3.OperationalError)
    assert (caught.value.name, caught.value.number, type(caught.value).__name__) == ("no value", 1, "ImportFailed")
    not_json = Import("not json", ("INSERT INTO wts_kv (key, value) SELECT 'k', json_extract(log, '$.at') FROM old",),
                      needs=("old",))
    with pytest.raises(sqlite3.OperationalError, match="malformed JSON") as caught:
        StateDB(path, imports=[not_json])
    assert isinstance(caught.value, ImportFailed) and not isinstance(caught.value, sqlite3.IntegrityError)


# The copy made before an import, when the start that was making it is killed


def _old_site(tmp_path: Path) -> Path:
    path = tmp_path / "state.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE reports (id INTEGER PRIMARY KEY, contact TEXT, message TEXT)")
    con.executemany("INSERT INTO reports (contact, message) VALUES (?, ?)",
                    [(ADDRESS, "A report with a reader's contact address. " * 40)] * 400)
    con.commit()
    con.close()
    return path


BRING = "Import('reports', ('INSERT INTO wts_kv (key, value) SELECT \\'reports\\', count(*) FROM reports',), " \
        "needs=('reports',))"


def test_the_copy_is_its_owners_alone_from_its_first_byte_and_is_removed_if_it_cannot_be_finished(tmp_path, monkeypatch):
    """Found by the review of Where MPs Stand's adoption: the half-made copy was readable by anyone on the server
    until it was finished (the mode was set after the move), and a failed copy was left behind."""
    import stat

    from wts_core import state as state_module

    path = _old_site(tmp_path)
    seen: list[int] = []
    real = sqlite3.connect

    class Failing:
        def __init__(self, con: sqlite3.Connection) -> None:
            self._con = con

        def backup(self, target: sqlite3.Connection) -> None:
            self._con.backup(target, pages=3, progress=self._stop)  # a few pages in, the disk fills

        def _stop(self, status: int, remaining: int, total: int) -> None:
            seen.extend(stat.S_IMODE(p.stat().st_mode) for p in tmp_path.glob("*.partial*"))
            raise OSError("no space left on device")

        def close(self) -> None:
            self._con.close()

    def connect(database, *args, **kwargs):
        con = real(database, *args, **kwargs)
        return Failing(con) if Path(database) == path and not args and kwargs == {"timeout": 30} and seen == [] \
            and any(tmp_path.glob("*.partial")) else con

    monkeypatch.setattr(state_module.sqlite3, "connect", connect)
    bring = Import("reports", ("INSERT INTO wts_kv (key, value) SELECT 'reports', count(*) FROM reports",),
                   needs=("reports",))
    with pytest.raises((OSError, sqlite3.Error)):
        StateDB(path, imports=[bring], clock=FixedClock())
    assert seen and set(seen) == {0o600}  # the half-made copy, and SQLite's journal beside it, while it was being made
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.db"]  # nothing of it is left
    monkeypatch.undo()
    assert StateDB(path).get("reports") is None  # an import that cannot make its copy does not run
    StateDB(path, imports=[bring], clock=FixedClock())  # and the next start makes both
    copy = tmp_path / "state.pre-wts-core.2026-11-13.db"
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600 and StateDB(path).get("reports") == "400"


def test_what_a_start_killed_during_the_copy_leaves_behind_is_private_and_is_cleared_a_day_later(tmp_path):
    """A process killed outright removes nothing. What it leaves is a half-made copy of the whole database, so it
    is mode 0600 like the copy itself, and the nightly tidy's ``forget_old_copies`` removes it once it is a day
    old (a day: the half-made copy of a start still running must not be taken from under it)."""
    import stat
    import subprocess
    import sys
    import textwrap

    path = _old_site(tmp_path)
    killed = subprocess.run([sys.executable, "-c", textwrap.dedent(f"""
        import os, sqlite3
        from pathlib import Path
        from wts_core import state
        from wts_core.state import Import, StateDB
        real = sqlite3.connect

        class Killed:
            def __init__(self, con): self._con = con
            def backup(self, target): self._con.backup(target, pages=3, progress=lambda *a: os._exit(137))
            def close(self): self._con.close()

        def connect(database, *args, **kwargs):
            con = real(database, *args, **kwargs)
            copying = any(Path({str(tmp_path)!r}).glob("*.partial"))
            return Killed(con) if copying and str(database) == {str(path)!r} else con

        state.sqlite3.connect = connect
        StateDB(Path({str(path)!r}), imports=[{BRING}])
        """)], capture_output=True, text=True, check=False)
    assert killed.returncode == 137, killed.stderr
    left = sorted(p for p in tmp_path.iterdir() if ".partial" in p.name)
    assert left and all(".pre-wts-core." in p.name for p in left)
    # whatever of the database had reached the disk when it was killed, nobody else on the server can read it
    assert {stat.S_IMODE(p.stat().st_mode) for p in left} == {0o600}

    clock = FixedClock()
    clock.set(datetime.fromtimestamp(max(p.stat().st_mtime for p in left), UTC))
    db = StateDB(path, clock=clock)
    clock.advance(hours=23)
    assert db.forget_old_copies(60) == [] and all(p.exists() for p in left)  # it may be a start still running
    clock.advance(hours=2)
    assert db.forget_old_copies(60) == left and not any(p.exists() for p in left)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.db"]
    # nothing was imported by the start that was killed, and the next start does the whole of it
    assert db.get("reports") is None
    bring = Import("reports", ("INSERT INTO wts_kv (key, value) SELECT 'reports', count(*) FROM reports",),
                   needs=("reports",))
    assert StateDB(path, imports=[bring], clock=clock).get("reports") == "400"
