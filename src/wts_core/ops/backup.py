"""Backup and restore of the one thing that cannot be rebuilt from public sources: the state database.

A backup is a consistent copy made with SQLite's online backup (safe while the site is running), checked, then
packed into the site's own kind of archive under the site's own name, readable by its owner only. The newest
``keep`` of the site's archives are kept. What differs between the sites on purpose is a ``BackupSpec``: the name's
prefix and date stamp, the kind of archive (the database gzipped, or Where MPs Stand's tar that also holds the local
settings), how many to keep, and the tables a restored database must have.

``make_backup`` is the statements Where MPs Stand, Where Countries Stand, Where Councils Stand and Where Landlords
Stand each carry, which differ only in those values. ``restore_backup`` is the safer of the two that exist, step by
step: Where Countries Stand's order (everything is unpacked and checked beside the database before anything is
touched; the database replaced is kept), with what Where MPs Stand's adds (the kept copy carries its write-ahead
log; a lone kept log also stops a second restore; ``./`` in a tar's member names; the local settings come back;
a swap that fails says which files to move back). The one wording the two differ in, the full stop after "move or
delete it first", is Where Countries Stand's: none of the other one-line reasons has one.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import tarfile
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from wts_core.ports import SYSTEM_CLOCK, Clock

__all__ = ["BackupSpec", "RestoreRefused", "make_backup", "restore_backup"]

_SQLITE_HEADER = b"SQLite format 3\x00"


@dataclass(frozen=True, kw_only=True)
class BackupSpec:
    """What a site's backups are called and hold. The site builds one and passes it to everything in ``ops``."""

    prefix: str  # "wcs-state-": what marks an archive, here and off site, as this site's
    stamp: str = "%Y-%m-%d"  # the date in the name, in UTC; Where Landlords Stand's has the time: "%Y%m%d-%H%M%S"
    # "gzip": the database gzipped, <prefix><stamp>.sqlite.gz; "tar": <prefix><stamp>.tar.gz, holding the database
    # as ``member`` and each of ``extra_files`` that exists in the data folder (the folder the database is in)
    format: Literal["gzip", "tar"] = "gzip"
    member: str = "state.db"  # Where MPs Stand: "state.sqlite"
    extra_files: tuple[str, ...] = ()  # Where MPs Stand: ("settings.local.toml",)
    keep: int  # how many archives stay in the backups folder
    keep_offsite: int = 60  # how many of the site's copies stay in the off-site store: 60 on all four sites today
    required_tables: tuple[str, ...]  # a file without these is not a backup of this site's state database
    # whether the database keeps its newest writes in a write-ahead log (Where MPs Stand's does): the copy a restore
    # keeps of the database it replaces then carries the log, without which those writes would be lost
    wal: bool = False
    # The site's package name (``Site.package``), where the site's state database is marked with it
    # (``StateDB(..., site=...)``): a restore then refuses a backup marked as another site's. Two sites built on
    # the package can have exactly the same tables, so ``required_tables`` alone cannot tell them apart. None, or
    # a backup with no mark (every backup made before the mark existed), is judged by its tables only, as before.
    site: str | None = None

    def __post_init__(self) -> None:
        if not [t for t in self.required_tables if t.strip()]:
            # with none named, a restore would put any sound SQLite file, even an empty one, in the database's place
            raise ValueError("required_tables must name at least one table that every backup of this site has")

    @property
    def suffix(self) -> str:
        return ".tar.gz" if self.format == "tar" else ".sqlite.gz"

    def archives(self, folder: Path) -> list[Path]:
        """This site's archives in ``folder``, oldest first by name. Another site's, or anything else, is not listed."""
        return sorted(Path(folder).glob(f"{self.prefix}*{self.suffix}"))


class RestoreRefused(RuntimeError):
    """Why a backup was not put back, in words for the owner. ``why`` is the same in one word, for a command that
    says it in its own: "kept-copy" (an earlier restore's kept copy is in the way), "unreadable", "foreign" (not this
    site's backup: it lacks the site's tables), "other-site" (it is marked as a sister site's), "not-a-database",
    "damaged" (it failed SQLite's check), or "swap-failed". Nothing has been
    changed, except after "swap-failed": the database's journal files are removed just before the swap, and the
    message says which files to move back."""

    def __init__(self, message: str, *, why: str) -> None:
        super().__init__(message)
        self.why = why


def make_backup(state_db: Path, dest: Path, spec: BackupSpec, *, keep: int | None = None,
                clock: Clock = SYSTEM_CLOCK) -> Path | None:
    """The backup written into ``dest``, or None when there is no state database yet (a new site): opening it to copy
    it would create an empty one, and an empty database is not a backup. ``keep`` overrides the spec's; zero or less
    deletes nothing. Raises RuntimeError if the copy fails SQLite's integrity check: nothing is then left behind,
    and no older archive is deleted."""
    state_db, dest = Path(state_db), Path(dest)
    if not state_db.exists():
        return None
    keep = spec.keep if keep is None else keep
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{spec.prefix}{clock.now().strftime(spec.stamp)}{spec.suffix}"
    with tempfile.TemporaryDirectory(dir=dest) as tmp:  # its owner only, as the copy inside it must be
        copy = Path(tmp) / spec.member
        src, dst = sqlite3.connect(state_db), sqlite3.connect(copy)
        try:
            src.backup(dst)  # a consistent copy, even while the site is writing
            ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst.close()
            src.close()
        if ok != "ok":
            raise RuntimeError(f"the backup copy failed its integrity check: {ok}")
        partial = Path(tmp) / out.name
        if spec.format == "tar":
            with tarfile.open(partial, "w:gz") as tar:
                tar.add(copy, arcname=spec.member)
                for name in spec.extra_files:
                    extra = state_db.parent / name
                    if extra.exists():
                        tar.add(extra, arcname=name)
        else:
            with open(copy, "rb") as f, gzip.open(partial, "wb") as g:
                shutil.copyfileobj(f, g)
        partial.chmod(0o600)  # it holds readers' reports and contact details: its owner only
        partial.replace(out)  # there whole, or not at all
    for old in spec.archives(dest)[:-keep] if keep > 0 else []:
        old.unlink()
    return out


def restore_backup(archive: Path, state_db: Path, spec: BackupSpec) -> Path | None:
    """Put a backup's state database (and the spec's extra files) back. Stop the site first. The backup is unpacked
    beside the database and checked before anything is replaced; the database it replaces is kept beside it as
    ``<name>.before-restore``, which is returned (None when there was none). A kept copy from an earlier restore is
    never written over: the restore is refused until it has been moved or deleted.

    Where the spec names the ``site``, a backup marked as another site's is refused; one with no mark at all (made
    before the mark existed, or by a site that does not mark its database) is taken as before, on its tables.

    ``archive`` is one of the site's own, or an uncompressed database file (a kept copy can itself be put back: a
    gzip site takes any file not named ``.gz`` as one, a tar site any file that begins as SQLite's do; where the
    spec says ``wal``, a log beside such a file is read with it).

    Raises ``RestoreRefused`` with the reason. An error while the kept copy is being written (a full disk) is raised
    as it is: nothing has been replaced then, and no half-written kept copy is left."""
    archive, state_db = Path(archive), Path(state_db)
    kept = state_db.with_name(state_db.name + ".before-restore") if state_db.exists() else None
    # a database that has a write-ahead log beside it is treated as one that keeps its newest writes there,
    # whatever the spec says: the kept copy must carry the log, or those writes are lost
    wal = spec.wal or _beside(state_db, "-wal").exists()
    if kept:
        for earlier in (kept, _beside(kept, "-wal")) if wal else (kept,):
            if earlier.exists():  # the only copy of what an earlier restore replaced: never written over
                raise RestoreRefused(f"{earlier} is still there from an earlier restore: move or delete it first",
                                     why="kept-copy")
    state_db.parent.mkdir(parents=True, exist_ok=True)
    # beside the database, not in the system's temporary folder: the swap is then a rename on one file system
    with tempfile.TemporaryDirectory(dir=state_db.parent) as tmp:
        db = Path(tmp) / spec.member
        _unpack(archive, Path(tmp), spec)
        _check(db, archive.name, spec)
        if kept:
            # Copied under a temporary name and renamed into place, so a failure part-way never leaves a damaged
            # kept copy. A database with a write-ahead log keeps its newest writes there until they are folded in,
            # so the log is kept with the copy: SQLite reads the two together. The log is put in place first: the
            # copy is never there without it.
            copy = Path(tmp) / kept.name
            shutil.copy2(state_db, copy)
            if wal:
                _beside(kept, "-shm").unlink(missing_ok=True)  # an index of a log no longer there; SQLite remakes it
                if _beside(state_db, "-wal").exists():
                    shutil.copy2(_beside(state_db, "-wal"), _beside(copy, "-wal"))
                    _beside(copy, "-wal").replace(_beside(kept, "-wal"))
            copy.replace(kept)
        try:
            for suffix in ("-wal", "-shm", "-journal"):  # left from the database being replaced, they would corrupt it
                _beside(state_db, suffix).unlink(missing_ok=True)
            db.chmod(0o600)  # as the backup: it holds readers' reports and contact details
            db.replace(state_db)
        except OSError as exc:
            if not kept:
                raise
            # Nothing is rolled back automatically: the owner is told exactly which files hold what was there.
            back = f"move {kept} to {state_db}"
            if _beside(kept, "-wal").exists():
                back += f" and {kept}-wal to {state_db}-wal"
            raise RestoreRefused(
                f"the backup could not be put in place ({exc}). {state_db} may no longer be complete: its "
                f"{'write-ahead log' if spec.wal else 'journal'} is removed just before. To go back to what was "
                f"there, {back}.", why="swap-failed") from exc
        for name in spec.extra_files:
            extra = Path(tmp) / name
            if extra.exists():
                extra.replace(state_db.parent / name)
    return kept


def _beside(path: Path, suffix: str) -> Path:
    """SQLite's own files beside a database: ``state.db-wal``, ``state.db-shm``, ``state.db-journal``."""
    return path.with_name(path.name + suffix)


def _is_database(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER


def _unpack(archive: Path, tmp: Path, spec: BackupSpec) -> None:
    """The archive's database as ``tmp/<member>``, and its extra files beside it. Only the archive is read."""
    db = tmp / spec.member
    try:
        if spec.format == "tar" and not _is_database(archive):
            with tarfile.open(archive) as tar:
                # "./state.sqlite" as well as "state.sqlite": a backup repacked by hand is named that way
                members = {m.name.removeprefix("./"): m for m in tar.getmembers() if m.isfile()}
                if spec.member not in members:
                    raise RestoreRefused(f"{archive.name} is not a backup of this site: it has no {spec.member}",
                                         why="foreign")
                tar.extractall(tmp, members=[members[n] for n in (spec.member, *spec.extra_files) if n in members],
                               filter="data")
            return
        compressed = spec.format == "gzip" and archive.suffix == ".gz"
        with (gzip.open(archive, "rb") if compressed else open(archive, "rb")) as f, open(db, "wb") as out:
            shutil.copyfileobj(f, out)
        if spec.wal and not compressed and _beside(archive, "-wal").exists():
            shutil.copyfile(_beside(archive, "-wal"), _beside(db, "-wal"))  # its newest writes: read with it
    except (tarfile.TarError, OSError, EOFError, zlib.error) as exc:  # not there, cut short, damaged (gzip's own
        # errors are OSErrors), or not a tar
        raise RestoreRefused(f"{archive.name} could not be read: {exc}", why="unreadable") from exc


def _check(db: Path, name: str, spec: BackupSpec) -> None:
    """Refuse a file that is not a sound copy of this site's state database."""
    con = sqlite3.connect(db)
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        marked = (con.execute("SELECT value FROM wts_kv WHERE key = 'site'").fetchone()
                  if spec.site is not None and "wts_kv" in tables else None)
        # a log unpacked beside an uncompressed database is folded in here, so that the file alone is complete (it
        # does nothing to a database without one)
        folded = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    except sqlite3.DatabaseError as exc:
        raise RestoreRefused(f"{name} is not a database: {exc}", why="not-a-database") from exc
    finally:
        con.close()
    if ok != "ok":
        raise RestoreRefused(f"the backup's database failed its integrity check: {ok}", why="damaged")
    if set(spec.required_tables) - tables:
        raise RestoreRefused(f"{name} is not a backup of this site's state database", why="foreign")
    if marked is not None and marked[0] != spec.site:
        # a sister site's backup has the same package tables; only the mark tells the two apart
        raise RestoreRefused(f"{name} is a backup of another site's state database: it is marked {marked[0]!r}, "
                             f"and this site is {spec.site!r}", why="other-site")
    if not folded:
        raise RestoreRefused(f"{name}'s write-ahead log could not be read in full", why="unreadable")
