"""Backing up the state database and putting a backup back: every test the four sites have for theirs, run for each
site's own kind of archive, and the comparisons with each site's own code (the same backup from the same database;
each restores the other's)."""

from __future__ import annotations

import dataclasses
import gzip
import shutil
import sqlite3
import stat
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from test_ops_sites import (
    SITES,
    archive_of,
    damaged_database,
    each_site,
    freeze_their_clock,
    marker,
    members,
    names,
    own_code,
    sites_where,
    state_database,
    their_backup,
    their_restore,
    write,
)
from wts_core.ops import RestoreRefused, make_backup, restore_backup
from wts_core.ops import backup as backup_module
from wts_core.testing import FixedClock

DAYS = ("2026-10-01T03:30:00+00:00", "2026-10-02T03:30:00+00:00", "2026-10-03T03:30:00+00:00")


def at(when: str) -> FixedClock:
    return FixedClock(when)


def name_at(site, when: str) -> str:
    return site.archive_name(datetime.fromisoformat(when))


def data_folder(tmp_path: Path, site, value: str = "before") -> Path:
    """A site's data folder with its state database in it, and the files its backups also hold."""
    db = state_database(tmp_path / "data" / site.state_file, site.spec, value)
    for name in site.spec.extra_files:
        (db.parent / name).write_text('[archive]\nstart_date = "2015-01-01"\n')
    return db


# ---- making a backup ---------------------------------------------------------------------------------------------


@each_site
def test_a_backup_is_a_checked_copy_and_the_newest_are_kept(site, tmp_path, monkeypatch):
    db, dest = data_folder(tmp_path, site, "saved"), tmp_path / "backups"
    opened = []
    connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: opened.append(connect(*a, **k)) or opened[-1])
    for day in DAYS:
        out = make_backup(db, dest, site.spec, keep=2, clock=at(day))
    monkeypatch.undo()
    # nothing else is left in the folder: no temporary folder, no uncompressed copy
    assert names(dest) == [name_at(site, DAYS[1]), name_at(site, DAYS[2])]
    assert out == dest / name_at(site, DAYS[2])
    assert stat.S_IMODE(out.stat().st_mode) == 0o600  # it holds readers' reports: its owner only
    held = members(out, site.spec)
    assert sorted(held) == sorted((site.spec.member, *site.spec.extra_files))
    restored = tmp_path / "restored.db"
    restored.write_bytes(held[site.spec.member])
    assert marker(restored) == "saved"
    assert len(opened) == 6  # two for each backup
    for con in opened:  # every connection was closed, not left to be collected
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            con.execute("select 1")


@each_site
def test_a_new_site_has_nothing_to_back_up(site, tmp_path):
    db, dest = tmp_path / "data" / site.state_file, tmp_path / "b"
    assert make_backup(db, dest, site.spec, clock=at(DAYS[0])) is None
    # no empty database is created to be archived as if it were a good backup, and no folder for it
    assert not db.exists() and not dest.exists()
    state_database(db, site.spec)
    assert make_backup(db, dest, site.spec, clock=at(DAYS[0])) == dest / name_at(site, DAYS[0])
    assert len(site.spec.archives(dest)) == 1


@each_site
def test_two_backups_in_a_day_are_two_files_only_where_the_name_carries_the_time(site, tmp_path):
    db, dest = data_folder(tmp_path, site, "morning"), tmp_path / "backups"
    first = make_backup(db, dest, site.spec, clock=at("2026-11-02T04:15:00+00:00"))
    write(db, "evening").close()
    second = make_backup(db, dest, site.spec, clock=at("2026-11-02T18:00:00+00:00"))
    if "%H" in site.spec.stamp:
        assert names(dest) == ["landlords-state-20261102-041500.sqlite.gz", "landlords-state-20261102-180000.sqlite.gz"]
    else:  # the day's file is replaced, whole
        assert first == second and names(dest) == [f"{site.spec.prefix}2026-11-02{site.spec.suffix}"]
    (tmp_path / "newest.db").write_bytes(members(second, site.spec)[site.spec.member])
    assert marker(tmp_path / "newest.db") == "evening"


@each_site
def test_a_copy_that_fails_its_check_is_not_kept(site, tmp_path):
    dest = tmp_path / "backups"
    make_backup(state_database(tmp_path / "good" / site.state_file, site.spec), dest, site.spec, clock=at(DAYS[0]))
    with pytest.raises(RuntimeError, match="the backup copy failed its integrity check: "):
        make_backup(damaged_database(tmp_path / "data" / site.state_file, site.spec), dest, site.spec, keep=1,
                    clock=at(DAYS[1]))
    # no half-made file or temporary folder, and the last good backup is still there
    assert names(dest) == [name_at(site, DAYS[0])]


@each_site
def test_a_database_that_cannot_be_read_leaves_nothing_behind(site, tmp_path):
    db, dest = damaged_database(tmp_path / "data" / site.state_file, site.spec), tmp_path / "backups"
    with open(db, "r+b") as f:  # two pages of the file overwritten
        f.seek(4096)
        f.write(b"\xff" * 8192)
    with pytest.raises((RuntimeError, sqlite3.Error)):
        make_backup(db, dest, site.spec, clock=at(DAYS[0]))
    assert names(dest) == []


@each_site
@pytest.mark.parametrize("keep", [0, -1, -2])
def test_keeping_none_or_fewer_deletes_nothing(site, tmp_path, keep):
    db, dest = data_folder(tmp_path, site), tmp_path / "backups"
    for day in DAYS:
        make_backup(db, dest, site.spec, keep=keep, clock=at(day))
    assert len(names(dest)) == 3
    make_backup(db, dest, dataclasses.replace(site.spec, keep=keep), clock=at("2026-10-04T03:30:00+00:00"))
    assert len(names(dest)) == 4 and all(n.endswith(site.spec.suffix) for n in names(dest))


@each_site
def test_the_specs_own_number_is_kept_unless_another_is_given(site, tmp_path):
    db, dest = data_folder(tmp_path, site), tmp_path / "backups"
    for day in range(1, site.spec.keep + 3):
        make_backup(db, dest, site.spec, clock=at(f"2026-10-{day:02d}T03:30:00+00:00"))
    kept = names(dest)
    assert len(kept) == site.spec.keep and kept[0] == name_at(site, "2026-10-03T03:30:00+00:00")
    make_backup(db, dest, site.spec, keep=2, clock=at("2026-10-20T03:30:00+00:00"))
    assert names(dest) == [kept[-1], name_at(site, "2026-10-20T03:30:00+00:00")]


@each_site
def test_only_this_sites_own_archives_are_deleted(site, tmp_path):
    """The sites' backups can share a folder as they can share a bucket: each deletes only its own."""
    db, dest = data_folder(tmp_path, site), tmp_path / "backups"
    dest.mkdir()
    others = [other.archive_name(datetime(2026, 9, 1, tzinfo=UTC)) for other in SITES if other is not site]
    others += ["offsite.json", f"{site.spec.prefix}2026-09-01.sqlite", "notes.txt"]
    for name in others:
        (dest / name).write_bytes(b"not this site's to delete")
    for day in DAYS:
        make_backup(db, dest, site.spec, keep=1, clock=at(day))
    assert names(dest) == sorted([*others, name_at(site, DAYS[2])])


@sites_where(format="tar")
def test_a_tar_holds_the_extra_files_only_where_they_exist(site, tmp_path):
    db, dest = data_folder(tmp_path, site), tmp_path / "backups"
    with tarfile.open(make_backup(db, dest, site.spec, clock=at(DAYS[0]))) as tar:
        assert sorted(tar.getnames()) == ["settings.local.toml", "state.sqlite"]
    (db.parent / "settings.local.toml").unlink()
    with tarfile.open(make_backup(db, dest, site.spec, clock=at(DAYS[1]))) as tar:
        assert tar.getnames() == ["state.sqlite"]


# ---- putting one back --------------------------------------------------------------------------------------------


@each_site
def test_restore_puts_a_backup_back_and_keeps_the_database_it_replaces(site, tmp_path):
    db = data_folder(tmp_path, site, "before")
    out = make_backup(db, tmp_path / "backups", site.spec, clock=at(DAYS[0]))
    write(db, "after").close()  # the site is stopped first
    for name in site.spec.extra_files:
        (db.parent / name).write_text('[archive]\nstart_date = "2020-01-01"\n')
    (db.parent / f"{db.name}-journal").write_bytes(b"left over")

    kept = restore_backup(out, db, site.spec)
    assert marker(db) == "before"
    assert kept == db.parent / f"{db.name}.before-restore" and marker(kept) == "after"
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    for name in site.spec.extra_files:  # the local settings come back with it
        assert "2015-01-01" in (db.parent / name).read_text()
    assert not (db.parent / f"{db.name}-journal").exists()
    # unpacked beside the database, and nothing of that is left behind
    assert [n for n in names(db.parent) if not n.startswith(f"{db.name}.before-restore")] \
        == sorted([db.name, *site.spec.extra_files])


@each_site
def test_restore_onto_a_new_site_keeps_nothing_because_nothing_was_there(site, tmp_path):
    out = make_backup(data_folder(tmp_path, site, "before"), tmp_path / "backups", site.spec, clock=at(DAYS[0]))
    db = tmp_path / "new" / "data" / site.state_file
    assert restore_backup(out, db, site.spec) is None
    assert marker(db) == "before" and stat.S_IMODE(db.stat().st_mode) == 0o600
    assert names(db.parent) == sorted([db.name, *site.spec.extra_files])


@each_site
def test_archives_and_databases_are_moved_into_place_from_a_folder_beside_them(site, tmp_path, monkeypatch):
    """Not from the system's temporary folder, which is another file system on the server: a rename cannot cross."""
    db, dest = data_folder(tmp_path, site, "before"), tmp_path / "backups"
    moved = []
    rename = Path.replace
    monkeypatch.setattr(Path, "replace",
                        lambda self, target: moved.append((self, Path(target))) or rename(self, target))
    out = make_backup(db, dest, site.spec, clock=at(DAYS[0]))
    restore_backup(out, db, site.spec)
    monkeypatch.undo()
    assert {target for _, target in moved} >= {out, db, db.parent / f"{db.name}.before-restore"}
    assert all(source.parent.parent == target.parent for source, target in moved)


@sites_where(restores=True)
def test_the_backup_is_restored_from_the_newest_kept(site, tmp_path):
    """Where MPs Stand's first test of its backup: three days, the two newest kept, and the newest put back."""
    db, dest = data_folder(tmp_path, site, "before"), tmp_path / "backups"
    for day in DAYS:
        make_backup(db, dest, site.spec, keep=2, clock=at(day))
    write(db, "after").close()
    restore_backup(dest / name_at(site, DAYS[2]), db, site.spec)
    assert marker(db) == "before"


@sites_where(wal=False)
def test_a_wal_is_kept_only_for_a_database_that_has_one(site, tmp_path):
    """Without ``wal`` in its spec, a site's restore is Where Countries Stand's: the copy is the database file."""
    db = data_folder(tmp_path, site, "before")
    out = make_backup(db, tmp_path / "backups", site.spec, clock=at(DAYS[0]))
    kept = restore_backup(out, db, site.spec)
    assert kept is not None and not Path(f"{kept}-wal").exists()


@sites_where(wal=True)
def test_the_kept_database_has_writes_still_in_the_write_ahead_log(site, tmp_path):
    db = data_folder(tmp_path, site, "before")
    out = make_backup(db, tmp_path / "backups", site.spec, clock=at(DAYS[0]))
    left_open = write(db, "after")  # as when the site is killed: this is in the log only
    assert (db.parent / f"{db.name}-wal").stat().st_size > 0
    kept = restore_backup(out, db, site.spec)
    assert kept is not None and marker(kept) == "after" and marker(db) == "before"
    left_open.close()


@sites_where(wal=False)
def test_a_database_with_a_log_beside_it_keeps_the_log_whatever_its_spec_says(site, tmp_path):
    """Found in review: a database switched to a write-ahead log by hand, on a site whose spec does not say so, lost
    its newest writes from the kept copy. A log that is there is always kept with the copy."""
    import sqlite3

    db = data_folder(tmp_path, site, "before")
    out = make_backup(db, tmp_path / "backups", site.spec, clock=at(DAYS[0]))
    con = sqlite3.connect(db)
    assert con.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    con.close()
    left_open = write(db, "after")  # in the log only
    assert (db.parent / f"{db.name}-wal").stat().st_size > 0
    kept = restore_backup(out, db, site.spec)
    assert kept is not None and marker(kept) == "after" and marker(db) == "before"
    left_open.close()


@each_site
def test_a_second_restore_never_writes_over_the_kept_copy(site, tmp_path):
    """Restoring the wrong day and then the right one once replaced the kept copy, and the database the site had been
    running on was gone for good. The second restore is refused before anything is touched."""
    db, dest = data_folder(tmp_path, site, "monday"), tmp_path / "backups"
    wrong = make_backup(db, dest, site.spec, clock=at(DAYS[0]))
    write(db, "tuesday").close()
    right = make_backup(db, dest, site.spec, clock=at(DAYS[1]))
    write(db, "live").close()
    kept = restore_backup(wrong, db, site.spec)
    assert kept == db.parent / f"{db.name}.before-restore"
    before = {p: p.read_bytes() for p in (db, kept, wrong, right)}
    (db.parent / f"{db.name}-journal").write_bytes(b"left over")
    folder = names(db.parent)
    with pytest.raises(RestoreRefused, match=f"{db.name}.before-restore is still there from an earlier restore: move "
                                             "or delete it first") as refused:
        restore_backup(right, db, site.spec)
    # nothing was touched: the live database, the kept one and the backups are all still there, and nothing unpacked
    assert refused.value.why == "kept-copy" and str(refused.value).startswith(str(kept))
    assert {p: p.read_bytes() for p in before} == before and names(db.parent) == folder
    (db.parent / f"{db.name}-journal").unlink()
    if site.spec.wal:  # a write-ahead log left on its own by an earlier restore stops it too: it is not this database's
        kept.rename(tmp_path / "set-aside.db")
        Path(f"{kept}-wal").write_bytes(b"left behind")
        with pytest.raises(RestoreRefused, match="before-restore-wal is still there"):
            restore_backup(right, db, site.spec)
        Path(f"{kept}-wal").unlink()
    else:
        kept.rename(tmp_path / "set-aside.db")
    # once the kept copy has been moved away, the right day goes back, and what it replaces is kept in turn
    assert restore_backup(right, db, site.spec) == kept
    assert marker(db) == "tuesday" and marker(kept) == "monday" and marker(tmp_path / "set-aside.db") == "live"


@each_site
def test_a_kept_copy_that_fails_part_way_is_never_left_damaged(site, tmp_path, monkeypatch):
    db = data_folder(tmp_path, site, "live")
    out = make_backup(db, tmp_path / "backups", site.spec, clock=at(DAYS[0]))
    folder, live_now = names(db.parent), db.read_bytes()

    def fails(src, dst, **kw):
        with open(dst, "wb") as f:
            f.write(b"half a file")
        raise OSError("No space left on device")

    monkeypatch.setattr(backup_module.shutil, "copy2", fails)
    with pytest.raises(OSError, match="No space left"):
        restore_backup(out, db, site.spec)
    monkeypatch.undo()
    # no kept copy at all, never a damaged one, and the live database as it was
    assert names(db.parent) == folder and db.read_bytes() == live_now


@each_site
def test_a_swap_that_fails_says_which_files_to_move_back(site, tmp_path, monkeypatch):
    db = data_folder(tmp_path, site, "before")
    out = make_backup(db, tmp_path / "backups", site.spec, clock=at(DAYS[0]))
    left_open = write(db, "after")  # with a write-ahead log, in the log only, which is removed just before the swap
    kept = db.parent / f"{db.name}.before-restore"
    rename = Path.replace

    def fails_for_the_database(self, target):
        if Path(target) == db:
            raise OSError(18, "Invalid cross-device link")
        return rename(self, target)

    monkeypatch.setattr(Path, "replace", fails_for_the_database)
    with pytest.raises(RestoreRefused) as failed:
        restore_backup(out, db, site.spec)
    said = str(failed.value)
    assert failed.value.why == "swap-failed"
    assert "the backup could not be put in place (" in said and "Invalid cross-device link" in said
    back = f"move {kept} to {db}" + (f" and {kept}-wal to {db}-wal" if site.spec.wal else "")
    assert said.endswith(f"To go back to what was there, {back}.")
    assert ("its write-ahead log is removed just before" in said) == site.spec.wal
    with pytest.raises(RestoreRefused, match="is still there from an earlier restore"):
        restore_backup(out, db, site.spec)  # and until that is done, nothing more is touched
    monkeypatch.setattr(Path, "replace", rename)
    left_open.close()
    # doing what it says brings back everything, the newest writes included
    assert not Path(f"{db}-wal").exists() and kept.exists() and Path(f"{kept}-wal").exists() == site.spec.wal
    kept.replace(db)
    if site.spec.wal:
        Path(f"{kept}-wal").replace(f"{db}-wal")
    assert marker(db) == "after"


def test_a_swap_that_fails_on_a_new_site_is_the_systems_own_error(tmp_path, monkeypatch):
    """Nothing was there to go back to, so there is nothing to say about moving files back."""
    site = SITES[1]
    out = make_backup(data_folder(tmp_path, site), tmp_path / "backups", site.spec, clock=at(DAYS[0]))
    db = tmp_path / "new" / site.state_file
    rename = Path.replace
    monkeypatch.setattr(Path, "replace", lambda self, target: (_ for _ in ()).throw(OSError(18, "Invalid link"))
                        if Path(target) == db else rename(self, target))
    with pytest.raises(OSError, match="Invalid link"):
        restore_backup(out, db, site.spec)
    monkeypatch.undo()
    assert names(db.parent) == []


@sites_where(format="tar")
def test_restore_accepts_a_backup_repacked_by_hand(site, tmp_path):
    """`tar -czf new.tar.gz -C folder .` names its members ./state.sqlite and ./settings.local.toml."""
    db = data_folder(tmp_path, site, "before")
    out = make_backup(db, tmp_path / "backups", site.spec, clock=at(DAYS[0]))
    unpacked = tmp_path / "unpacked"
    with tarfile.open(out) as tar:
        tar.extractall(unpacked, filter="data")
    repacked = tmp_path / "repacked.tar.gz"
    with tarfile.open(repacked, "w:gz") as tar:
        tar.add(unpacked, arcname=".")
    with tarfile.open(repacked) as tar:
        assert {"./state.sqlite", "./settings.local.toml"} <= set(tar.getnames())
    write(db, "after").close()
    (db.parent / "settings.local.toml").write_text('[archive]\nstart_date = "2020-01-01"\n')
    restore_backup(repacked, db, site.spec)
    assert marker(db) == "before" and "2015-01-01" in (db.parent / "settings.local.toml").read_text()


@each_site
def test_restore_refuses_a_damaged_or_foreign_file_and_changes_nothing(site, tmp_path):
    db, spec = data_folder(tmp_path, site, "live"), site.spec
    for name in spec.extra_files:
        (db.parent / name).write_text("# live\n")
    good = make_backup(db, tmp_path / "b", spec, clock=at(DAYS[1]))
    beside = db.parent / f"{db.name}{'-wal' if spec.wal else '-journal'}"
    beside.write_bytes(b"")  # must still be there after every refusal
    folder = names(db.parent)

    def refused(archive: Path, saying: str) -> str:
        with pytest.raises(RestoreRefused, match=saying) as exc:
            restore_backup(archive, db, spec)
        assert names(db.parent) == folder
        return exc.value.why

    bad = archive_of(tmp_path / name_at(site, DAYS[0]), spec, state=b"not a database at all" * 100,
                     settings__local__toml=b"# from the archive\n")
    assert refused(bad, f"{bad.name} is not a database: ") == "not-a-database"
    cut = tmp_path / f"cut{spec.suffix}"
    cut.write_bytes(good.read_bytes()[: good.stat().st_size // 2])
    assert refused(cut, f"{cut.name} could not be read: ") == "unreadable"
    short = tmp_path / f"short{spec.suffix}"
    short.write_bytes(gzip.compress(b"x" * 1000)[:20])
    assert refused(short, "could not be read") == "unreadable"
    assert refused(tmp_path / f"missing{spec.suffix}", f"missing{spec.suffix} could not be read: ") == "unreadable"
    other = tmp_path / "other.db"
    con = sqlite3.connect(other)
    for table in spec.required_tables[1:] or ("something",):  # another site's has some of these tables, never all
        con.execute(f"CREATE TABLE {table} (x)")
    con.commit()
    con.close()
    foreign = archive_of(tmp_path / f"foreign{spec.suffix}", spec, state=other.read_bytes())
    assert refused(foreign, f"{foreign.name} is not a backup of this site's state database") == "foreign"
    assert refused(other, "other.db is not a backup of this site's state database") == "foreign"  # uncompressed
    unsound = damaged_database(tmp_path / "unsound.db", spec)
    assert refused(archive_of(tmp_path / f"unsound{spec.suffix}", spec, state=unsound.read_bytes()),
                   "the backup's database failed its integrity check: ") == "damaged"
    if spec.format == "tar":
        not_a_tar = tmp_path / "notes.tar.gz"
        not_a_tar.write_bytes(b"x" * 1000)
        assert refused(not_a_tar, "notes.tar.gz could not be read: ") == "unreadable"
        empty = archive_of(tmp_path / "empty.tar.gz", spec, settings__local__toml=b"# from the archive\n")
        # was: an empty database replaced the live one
        assert refused(empty, f"empty.tar.gz is not a backup of this site: it has no {spec.member}") == "foreign"
    else:
        notes = tmp_path / "notes.txt"  # not named .gz, so taken as an uncompressed database: it is not one
        notes.write_bytes(b"x" * 1000)
        assert refused(notes, "notes.txt is not a database: ") == "not-a-database"

    assert marker(db) == "live"
    for name in spec.extra_files:
        assert (db.parent / name).read_text() == "# live\n"


# ---- a sister site's backup ---------------------------------------------------------------------------------------


def marked_database(path: Path, spec, package: str | None, value: str) -> Path:
    """A state database as a site on the package has it: the spec's tables, and in ``wts_kv`` the mark of whose it
    is (none: a database from before the mark, or of a site that gives none)."""
    db = state_database(path, spec, value)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS wts_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if package is not None:
        con.execute("INSERT OR REPLACE INTO wts_kv VALUES ('site', ?)", (package,))
    con.commit()
    con.close()
    return db


@each_site
def test_restore_refuses_a_sister_sites_backup_that_has_the_same_tables(site, tmp_path):
    """Two sites built on the package can have exactly the same tables, so the tables cannot tell them apart."""
    ours = dataclasses.replace(site.spec, site="councils")
    db = marked_database(tmp_path / "data" / site.state_file, ours, "councils", "live")
    theirs = marked_database(tmp_path / "sister" / site.state_file, ours, "wcs", "the sister site's")
    sisters = make_backup(theirs, tmp_path / "b", ours, clock=at(DAYS[0]))
    folder = names(db.parent)
    for archive in (sisters, theirs):  # its archive, and its database uncompressed
        with pytest.raises(RestoreRefused) as refused:
            restore_backup(archive, db, ours)
        assert refused.value.why == "other-site"
        assert str(refused.value) == (f"{archive.name} is a backup of another site's state database: it is marked "
                                      "'wcs', and this site is 'councils'")
        assert names(db.parent) == folder and marker(db) == "live"  # nothing was changed
    # the site's own is put back as ever
    own = make_backup(db, tmp_path / "own", ours, clock=at(DAYS[1]))
    write(db, "changed since").close()
    assert restore_backup(own, db, ours) is not None and marker(db) == "live"


@each_site
def test_a_backup_with_no_mark_is_accepted_as_before(site, tmp_path):
    """Every backup made before the mark existed has none: it is judged by its tables, as it always was."""
    ours = dataclasses.replace(site.spec, site="councils")
    db = marked_database(tmp_path / "data" / site.state_file, ours, "councils", "live")
    with_table = marked_database(tmp_path / "older" / site.state_file, ours, None, "from before the mark")
    old = make_backup(with_table, tmp_path / "b", ours, clock=at(DAYS[0]))
    assert restore_backup(old, db, ours) is not None and marker(db) == "from before the mark"
    (db.parent / f"{db.name}.before-restore").unlink()
    for beside in db.parent.glob(f"{db.name}.before-restore-*"):
        beside.unlink()
    # and one with no wts_kv table at all: a site's backup from before it took the package
    oldest = make_backup(state_database(tmp_path / "oldest" / site.state_file, ours, "from before the package"),
                         tmp_path / "c", ours, clock=at(DAYS[0]))
    assert restore_backup(oldest, db, ours) is not None and marker(db) == "from before the package"


@each_site
def test_a_spec_that_names_no_site_takes_any_backup_with_the_sites_tables(site, tmp_path):
    """Today's rule, and each site's own restore's: none of the four sites' specs names a site until it adopts
    the mark, so nothing changes for them."""
    assert site.spec.site is None
    db = marked_database(tmp_path / "data" / site.state_file, site.spec, "councils", "live")
    theirs = marked_database(tmp_path / "sister" / site.state_file, site.spec, "wcs", "the sister site's")
    sisters = make_backup(theirs, tmp_path / "b", site.spec, clock=at(DAYS[0]))
    assert restore_backup(sisters, db, site.spec) is not None and marker(db) == "the sister site's"


def test_a_database_opened_by_its_site_makes_backups_only_that_site_restores(tmp_path):
    """End to end with the real state database: the mark ``StateDB`` writes is the one a restore reads."""
    from wts_core.ops import BackupSpec
    from wts_core.state import StateDB

    def spec(package: str) -> BackupSpec:
        return BackupSpec(prefix="state-", keep=3, required_tables=("wts_schema", "wts_kv"), site=package)

    parks = StateDB(tmp_path / "parks" / "state.db", site="parks")
    rivers = StateDB(tmp_path / "rivers" / "state.db", site="rivers")
    parks.set("marker", "the parks site's")
    archive = make_backup(parks.path, tmp_path / "b", spec("parks"), clock=at(DAYS[0]))
    with pytest.raises(RestoreRefused, match="marked 'parks', and this site is 'rivers'") as refused:
        restore_backup(archive, rivers.path, spec("rivers"))
    assert refused.value.why == "other-site" and rivers.get("marker") is None
    parks.set("marker", "changed since")
    restore_backup(archive, parks.path, spec("parks"))
    assert parks.get("marker") == "the parks site's" and parks.get("site") == "parks"


@each_site
def test_the_database_a_restore_kept_can_itself_be_put_back(site, tmp_path):
    """An uncompressed database file is accepted, so ``<name>.before-restore`` is a backup like any other once it has
    been moved out of the way. Where the database has a write-ahead log, the log moved with it is read with it."""
    db = data_folder(tmp_path, site, "before")
    out = make_backup(db, tmp_path / "backups", site.spec, clock=at(DAYS[0]))
    left_open = write(db, "after")
    kept = restore_backup(out, db, site.spec)
    left_open.close()
    assert kept is not None and marker(db) == "before"
    aside = tmp_path / "aside" / "what-was-there.db"
    aside.parent.mkdir()
    for suffix in ("", "-wal"):
        if Path(f"{kept}{suffix}").exists():
            shutil.move(f"{kept}{suffix}", f"{aside}{suffix}")
    assert Path(f"{aside}-wal").exists() == site.spec.wal
    set_aside = {p.name: p.read_bytes() for p in aside.parent.iterdir()}
    assert marker(restore_backup(aside, db, site.spec)) == "before" and marker(db) == "after"
    assert {p.name: p.read_bytes() for p in aside.parent.iterdir()} == set_aside  # only read, never changed
    assert [n for n in names(db.parent) if not n.startswith(f"{db.name}.before-restore")] \
        == sorted([db.name, *site.spec.extra_files])


# ---- the same as each site's own code ----------------------------------------------------------------------------

WHEN = datetime(2026, 11, 2, 4, 15, tzinfo=UTC)


@each_site
def test_the_package_makes_the_backup_the_sites_own_code_makes(site, tmp_path, request, monkeypatch):
    own = own_code(site, request)
    db, spec = data_folder(tmp_path, site, "saved"), site.spec
    freeze_their_clock(monkeypatch, own, WHEN)
    theirs = their_backup(site, own, db, tmp_path / "theirs", spec.keep)
    ours = make_backup(db, tmp_path / "ours", spec, clock=FixedClock(WHEN))
    assert theirs is not None and ours is not None
    assert ours.name == theirs.name == site.archive_name(WHEN)
    assert members(ours, spec) == members(theirs, spec)  # the same names, and every byte of the database
    assert stat.S_IMODE(ours.stat().st_mode) == stat.S_IMODE(theirs.stat().st_mode) == 0o600
    assert names(tmp_path / "ours") == names(tmp_path / "theirs") == [ours.name]
    if spec.format == "tar":
        with tarfile.open(ours) as a, tarfile.open(theirs) as b:
            assert [(m.name, m.size, m.mode, m.type) for m in a] == [(m.name, m.size, m.mode, m.type) for m in b]


@each_site
def test_the_package_deletes_the_backups_the_sites_own_code_deletes(site, tmp_path, request, monkeypatch):
    own = own_code(site, request)
    db, spec = data_folder(tmp_path, site), site.spec
    for folder in ("theirs", "ours"):
        (tmp_path / folder).mkdir()
        for name in ("offsite.json", "wcs-state-2026-01-01.sqlite.gz", "where-they-stand-2026-01-01.tar.gz",
                     "councils-state-2026-01-01.sqlite.gz", "landlords-state-20260101-045200.sqlite.gz"):
            (tmp_path / folder / name).write_bytes(b"x")
    for keep in (spec.keep, 2, 1, 0, -1):
        for day in range(1, 5):
            when = datetime(2026, 11, day, 4, 15, tzinfo=UTC)
            freeze_their_clock(monkeypatch, own, when)
            their_backup(site, own, db, tmp_path / "theirs", keep)
            make_backup(db, tmp_path / "ours", spec, keep=keep, clock=FixedClock(when))
            assert names(tmp_path / "ours") == names(tmp_path / "theirs"), (keep, day)


@each_site
def test_neither_makes_anything_of_a_site_with_no_state_database(site, tmp_path, request):
    own = own_code(site, request)
    db = tmp_path / "data" / site.state_file
    if site.backup_in == "cli":  # Where Landlords Stand's command looks before it calls its make_backup
        assert "if not src.exists():" in (site.src / "cli.py").read_text()
    else:
        assert their_backup(site, own, db, tmp_path / "theirs", site.spec.keep) is None
    assert make_backup(db, tmp_path / "ours", site.spec) is None
    assert names(tmp_path) == []


@each_site
def test_both_refuse_a_copy_that_fails_its_check_in_the_same_words(site, tmp_path, request):
    own = own_code(site, request)
    db = damaged_database(tmp_path / "data" / site.state_file, site.spec)
    said = []
    for make in (lambda: their_backup(site, own, db, tmp_path / "theirs", 14),
                 lambda: make_backup(db, tmp_path / "ours", site.spec)):
        with pytest.raises(RuntimeError) as exc:
            make()
        said.append(str(exc.value))
    assert said[0] == said[1] and said[0].startswith("the backup copy failed its integrity check: ")
    assert names(tmp_path / "theirs") == names(tmp_path / "ours") == []


@each_site
def test_the_package_restores_a_backup_the_sites_own_code_made(site, tmp_path, request, monkeypatch):
    own = own_code(site, request)
    db = data_folder(tmp_path, site, "before")
    freeze_their_clock(monkeypatch, own, WHEN)
    theirs = their_backup(site, own, db, tmp_path / "theirs", site.spec.keep)
    write(db, "after").close()
    kept = restore_backup(theirs, db, site.spec)
    assert marker(db) == "before" and kept is not None and marker(kept) == "after"


@sites_where(restores=True)
def test_the_sites_own_code_restores_a_backup_the_package_made(site, tmp_path, request):
    own = own_code(site, request)
    db = data_folder(tmp_path, site, "before")
    ours = make_backup(db, tmp_path / "ours", site.spec, clock=FixedClock(WHEN))
    write(db, "after").close()
    kept = their_restore(site, own, ours, db)
    assert marker(db) == "before" and marker(kept) == "after"


@sites_where(restores=True)
def test_a_restore_leaves_what_the_sites_own_restore_leaves(site, tmp_path, request):
    """The same archive put back over the same data folder by each: the same files, with the same contents."""
    own = own_code(site, request)
    left = []
    for who in ("theirs", "ours"):
        db = data_folder(tmp_path / who, site, "before")
        archive = make_backup(db, tmp_path / who / "backups", site.spec, clock=FixedClock(WHEN))
        left_open = write(db, "after")  # killed, not stopped: with a write-ahead log, the newest write is in the log
        for name in site.spec.extra_files:
            (db.parent / name).write_text("# changed since\n")
        (db.parent / f"{db.name}-journal").write_bytes(b"left over")
        kept = their_restore(site, own, archive, db) if who == "theirs" else restore_backup(archive, db, site.spec)
        left_open.close()
        assert kept == db.parent / f"{db.name}.before-restore"
        files = {p.name: (stat.S_IMODE(p.stat().st_mode), b"" if p.name.startswith(db.name) else p.read_bytes())
                 for p in db.parent.iterdir()}  # the databases are compared by what they hold, read last
        left.append((files, marker(db), marker(kept)))
    assert left[0] == left[1] and left[1][1:] == ("before", "after") and left[1][0][site.state_file][0] == 0o600
    assert sorted(left[1][0]) == sorted([db.name, kept.name, *site.spec.extra_files,
                                         *([f"{kept.name}-wal"] if site.spec.wal else [])])


@sites_where(restores=True)
def test_refusals_are_in_the_sites_own_words(site, tmp_path, request):
    own = own_code(site, request)
    spec = site.spec
    good = make_backup(data_folder(tmp_path / "made", site), tmp_path / "b", spec, clock=FixedClock(WHEN))
    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("CREATE TABLE something (x)").connection.close()
    cut = tmp_path / f"cut{spec.suffix}"
    cut.write_bytes(good.read_bytes()[: good.stat().st_size // 2])
    unsound = damaged_database(tmp_path / "unsound.db", spec)
    refusals = {
        "not a database": archive_of(tmp_path / f"bad{spec.suffix}", spec, state=b"not a database at all" * 100),
        "cut short": cut,
        "missing": tmp_path / f"missing{spec.suffix}",
        "another site's": archive_of(tmp_path / f"foreign{spec.suffix}", spec, state=other.read_bytes()),
        "unsound": archive_of(tmp_path / f"unsound{spec.suffix}", spec, state=unsound.read_bytes()),
        "kept copy in the way": good,
    }
    if spec.format == "tar":
        refusals["no database in it"] = archive_of(tmp_path / "empty.tar.gz", spec, settings__local__toml=b"#\n")
    for what, archive in refusals.items():
        said = []
        for who in ("theirs", "ours"):
            db = data_folder(tmp_path / what.replace(" ", "-") / who, site, "live")
            if what == "kept copy in the way":
                (db.parent / f"{db.name}.before-restore").write_bytes(b"from an earlier restore")
            folder = names(db.parent)
            with pytest.raises(RuntimeError) as exc:
                their_restore(site, own, archive, db) if who == "theirs" else restore_backup(archive, db, spec)
            assert names(db.parent) == folder and marker(db) == "live", (what, who)
            said.append(str(exc.value).replace(str(db.parent), "<data>"))
        # the one difference: Where MPs Stand ends this one reason with a full stop, and no other
        assert said[1] == (said[0].removesuffix(".") if what == "kept copy in the way" else said[0]), what
