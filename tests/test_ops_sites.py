"""The four sites as the backup tests see them: each one's real ``BackupSpec`` (its prefix, date stamp, kind of archive,
how many its timer keeps, and the tables its state database has), its own words for the backup alerts, and how its own
code is loaded from its checkout for the comparisons. The other ``ops`` and Backblaze tests are parametrised over
these (``each_site``), and the tests here keep them true to each site's checkout where one is present."""

from __future__ import annotations

import ast
import gzip
import importlib
import io
import re
import sqlite3
import sys
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from wts_core.ops import AlertWording, BackupSpec
from wts_core.settings import Site

SITES_ROOT = Path("/home/user")

# Where MPs Stand's and Where Councils Stand's alerts are sentences: the first shows them on its admin page, the
# second prints them from `councils backup-check`. Where Landlords Stand has no alerts yet and takes these.
SENTENCES = AlertWording(
    no_backups="No backups have been made yet.",
    backup_stale="The last backup was made over two days ago ({name}).",
    server_only="Backups are kept on this server only: no off-site copy is set up.",
    no_offsite_yet="No off-site copy has been made yet; one is made with the next backup.",
    offsite_failed="The last off-site copy failed ({when}): {error}",
    offsite_stale="The last off-site copy was over two days ago ({day}).")
# Where Countries Stand's follow "warning: backup:" in its update report
AFTER_A_COLON = AlertWording(
    no_backups="no backups have been made yet",
    backup_stale="the last backup was made over two days ago ({name}): is wcs-backup.timer running?",
    server_only="backups are kept on this server only: no off-site copy is set up",
    no_offsite_yet="no off-site copy has been made yet; one is made with the next backup",
    offsite_failed="the last off-site copy failed ({when}): {error}",
    offsite_stale="the last off-site copy was over two days ago ({day})")


@dataclass(frozen=True)
class SiteFacts:
    name: str
    repo: str  # the checkout's folder under SITES_ROOT
    package: str
    env_prefix: str
    state_file: str
    spec: BackupSpec
    wording: AlertWording
    backup_in: str  # the module its make_backup is written in
    schema_in: str  # the file its state database's tables are made in
    unit: str  # the unit file whose command line says how many backups its timer keeps
    restores: bool  # whether it has a restore of its own to compare with
    alerts: bool  # whether it has backup_alerts of its own to compare with

    @property
    def checkout(self) -> Path:
        return SITES_ROOT / self.repo

    @property
    def src(self) -> Path:
        return self.checkout / "src" / self.package

    @property
    def site(self) -> Site:
        return Site(name=self.name, package=self.package, env_prefix=self.env_prefix, root=self.checkout,
                    state_file=self.state_file)

    def env(self, bucket: str = "wts-backups", key_id: str = "kid", application_key: str = "secret") -> dict[str, str]:
        return {f"{self.env_prefix}_B2_BUCKET": bucket, f"{self.env_prefix}_B2_KEY_ID": key_id,
                f"{self.env_prefix}_B2_APPLICATION_KEY": application_key}

    def archive_name(self, when: datetime) -> str:
        return f"{self.spec.prefix}{when.strftime(self.spec.stamp)}{self.spec.suffix}"

    def __str__(self) -> str:
        return self.repo


MPS = SiteFacts(
    name="Where MPs Stand", repo="wherempsstand", package="hansard", env_prefix="HANSARD", state_file="state.sqlite",
    spec=BackupSpec(prefix="where-they-stand-", stamp="%Y-%m-%d", format="tar", member="state.sqlite",
                    extra_files=("settings.local.toml",), keep=14,
                    required_tables=("manifest", "usage", "briefings", "reports"), wal=True),
    wording=SENTENCES, backup_in="backup", schema_in="store/state.py", unit="hansard-backup.service",
    restores=True, alerts=True)
COUNTRIES = SiteFacts(
    name="Where Countries Stand", repo="wherecountriesstand", package="wcs", env_prefix="WCS", state_file="state.db",
    spec=BackupSpec(prefix="wcs-state-", stamp="%Y-%m-%d", format="gzip", member="state.db", keep=14,
                    required_tables=("usage", "briefings")),
    wording=AFTER_A_COLON, backup_in="backup", schema_in="api/usage.py", unit="wcs-backup.service",
    restores=True, alerts=True)
# Neither of the next two has a restore of its own, so neither names the tables a backup must have: these are tables
# each has had since its state database was first made.
COUNCILS = SiteFacts(
    name="Where Councils Stand", repo="wherecouncilsstand", package="councils", env_prefix="COUNCILS",
    state_file="state.db",
    spec=BackupSpec(prefix="councils-state-", stamp="%Y-%m-%d", format="gzip", member="state.db", keep=7,
                    required_tables=("usage", "briefings")),
    wording=SENTENCES, backup_in="backup", schema_in="api/state.py", unit="councils-backup.service",
    restores=False, alerts=True)
LANDLORDS = SiteFacts(
    name="Where Landlords Stand", repo="wherelandlordsstand", package="landlords", env_prefix="LANDLORDS",
    state_file="state.db",
    spec=BackupSpec(prefix="landlords-state-", stamp="%Y%m%d-%H%M%S", format="gzip", member="state.db", keep=14,
                    required_tables=("reports",)),
    wording=SENTENCES, backup_in="cli", schema_in="api.py", unit="landlords-backup.service",
    restores=False, alerts=False)

SITES = (MPS, COUNTRIES, COUNCILS, LANDLORDS)

each_site = pytest.mark.parametrize("site", SITES, ids=str)


def sites_where(**facts: Any) -> pytest.MarkDecorator:
    """Parametrised over the sites of which every given fact, or part of the spec, is so: ``sites_where(wal=True)``."""
    chosen = [s for s in SITES if all(getattr(s, k, getattr(s.spec, k, None)) == v for k, v in facts.items())]
    return pytest.mark.parametrize("site", chosen, ids=str)


# ---- state databases to back up ----------------------------------------------------------------------------------


def state_database(path: Path, spec: BackupSpec, value: str = "saved") -> Path:
    """A state database as the site's: the tables a backup of it must have, its journal mode, and one value to tell
    one copy from another (``marker``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    if spec.wal:
        con.execute("PRAGMA journal_mode=WAL")
    for table in spec.required_tables:
        con.execute(f"CREATE TABLE IF NOT EXISTS {table} (x)")
    con.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT OR REPLACE INTO kv VALUES ('marker', ?)", (value,))
    con.commit()
    con.close()
    return path


def write(path: Path, value: str) -> sqlite3.Connection:
    """Change the value and leave the connection open, as when a site is killed: with a write-ahead log, the change
    is then in the log only."""
    con = sqlite3.connect(path)
    con.execute("INSERT OR REPLACE INTO kv VALUES ('marker', ?)", (value,))
    con.commit()
    return con


def marker(path: Path) -> str | None:
    con = sqlite3.connect(path)
    try:
        row = con.execute("SELECT value FROM kv WHERE key = 'marker'").fetchone()
    finally:
        con.close()
    return row[0] if row else None


def damaged_database(path: Path, spec: BackupSpec) -> Path:
    """One whose pages SQLite's integrity check finds fault with (an index dropped from the list of tables, so its
    pages belong to nothing), though it still opens and copies. From Where Landlords Stand's tests."""
    state_database(path, spec)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE notes (message TEXT)")
    con.executemany("INSERT INTO notes VALUES (?)", [("a mistake " * 20,)] * 50)
    con.execute("CREATE INDEX by_message ON notes (message)")
    con.commit()
    con.execute("PRAGMA writable_schema = ON")
    con.execute("DELETE FROM sqlite_master WHERE name = 'by_message'")
    con.commit()
    con.close()
    return path


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def members(archive: Path, spec: BackupSpec) -> dict[str, bytes]:
    """What an archive holds, by name: a tar's files, or the one database of a gzipped copy (under the spec's name)."""
    if spec.format == "tar":
        with tarfile.open(archive) as tar:
            return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}  # type: ignore[union-attr]
    return {spec.member: gzip.decompress(archive.read_bytes())}


def archive_of(path: Path, spec: BackupSpec, **files: bytes) -> Path:
    """An archive of the site's kind holding the given files (``state`` for its database), for the cases
    ``make_backup`` would never write."""
    if spec.format == "tar":
        with tarfile.open(path, "w:gz") as tar:
            for name, data in files.items():
                info = tarfile.TarInfo(spec.member if name == "state" else name.replace("__", "."))
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    else:
        path.write_bytes(gzip.compress(files["state"]))
    return path


# ---- each site's own code, from its checkout ---------------------------------------------------------------------


def checkout_of(facts: SiteFacts) -> Path:
    """The site's checkout, or the test is skipped: the comparisons with a site's own code need its repository."""
    if not (facts.src / "offsite.py").exists():
        pytest.skip(f"{facts.name}'s checkout is not at {facts.checkout}: nothing to compare with")
    return facts.checkout


def own_code(facts: SiteFacts, request: pytest.FixtureRequest) -> SimpleNamespace:
    """The site's own ``backup`` and ``offsite`` modules, loaded from its checkout by file path for this one test.

    The site is not installed: a stand-in for its package, holding nothing but the folder its modules are in, lets
    each module's imports of its neighbours work without the package's own ``__init__`` or anything else of the
    site's being run. It is taken away again when the test ends."""
    checkout_of(facts)
    mine = [k for k in sys.modules if k == facts.package or k.startswith(facts.package + ".")]
    before = {k: sys.modules.pop(k) for k in mine}

    def forget() -> None:
        for k in [k for k in sys.modules if k == facts.package or k.startswith(facts.package + ".")]:
            del sys.modules[k]
        sys.modules.update(before)

    request.addfinalizer(forget)
    package = ModuleType(facts.package)
    package.__path__ = [str(facts.src)]
    sys.modules[facts.package] = package
    try:
        backup = importlib.import_module(f"{facts.package}.{facts.backup_in}")
        offsite = importlib.import_module(f"{facts.package}.offsite")
    except ImportError as exc:  # a module of the site's that needs a library this package's tests don't install
        pytest.skip(f"{facts.name}'s own code could not be loaded from {facts.checkout}: {exc}")
    return SimpleNamespace(backup=backup, offsite=offsite)


def frozen(when: datetime) -> type[datetime]:
    """A ``datetime`` whose ``now()`` is always ``when``, for a site's own code, which reads the clock itself."""

    class Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            return when.astimezone(tz) if tz else when.replace(tzinfo=None)

    return Frozen


def freeze_their_clock(monkeypatch: pytest.MonkeyPatch, own: SimpleNamespace, when: datetime) -> None:
    for module in (own.backup, own.offsite):
        if hasattr(module, "datetime"):
            monkeypatch.setattr(module, "datetime", frozen(when))
        else:  # Where Landlords Stand's make_backup imports datetime when it is called
            import datetime as real

            stand_in = ModuleType("datetime")
            stand_in.__dict__.update(real.__dict__)
            stand_in.datetime = frozen(when)  # type: ignore[attr-defined]
            monkeypatch.setitem(sys.modules, "datetime", stand_in)


def their_backup(facts: SiteFacts, own: SimpleNamespace, state_db: Path, dest: Path, keep: int) -> Path | None:
    """The site's own make_backup. Where MPs Stand's takes its settings; the others the two paths."""
    if facts is MPS:
        return own.backup.make_backup(SimpleNamespace(state_db=state_db, data_dir=state_db.parent), dest, keep=keep)
    return own.backup.make_backup(state_db, dest, keep=keep)


def their_restore(facts: SiteFacts, own: SimpleNamespace, archive: Path, state_db: Path) -> Path | None:
    if facts is MPS:
        return own.backup.restore_backup(SimpleNamespace(state_db=state_db, data_dir=state_db.parent), archive)
    return own.backup.restore_backup(archive, state_db)


# ---- the facts above are the sites' own --------------------------------------------------------------------------


def written(path: Path) -> set[str]:
    """Every piece of text written in a file's code, the fixed parts of its f-strings among them."""
    return {n.value for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Constant)
            and isinstance(n.value, str)}


@each_site
def test_each_spec_is_the_sites_own(site, request):
    own = own_code(site, request)
    spec, source = site.spec, (site.src / f"{site.backup_in}.py").read_text()
    assert spec.prefix == own.offsite.PREFIX
    assert f"strftime('{spec.stamp}')" in source or f'strftime("{spec.stamp}")' in source
    assert f'{spec.suffix}"' in source and f'/ "{spec.member}"' in source
    assert ("tarfile.open" in source) == (spec.format == "tar")
    for name in spec.extra_files:
        assert f'arcname="{name}"' in source
    unit = (site.checkout / "deploy" / site.unit).read_text()
    assert re.search(rf"{site.package} backup --to /backups --keep (\d+)", unit).group(1) == str(spec.keep)
    assert f'"{site.state_file}"' in source or f'"{site.state_file}"' in (site.src / "config.py").read_text()


@each_site
def test_the_tables_a_backup_must_have_are_the_sites_own(site, request):
    own = own_code(site, request)
    schema = (site.src / site.schema_in).read_text()
    for table in site.spec.required_tables:
        assert re.search(rf"create table if not exists {table}\b", schema, re.I), table
    if site is MPS:
        assert set(site.spec.required_tables) == own.backup.REQUIRED_TABLES
    if site is COUNTRIES:
        assert 'if not {"usage", "briefings"} <= tables' in (site.src / "backup.py").read_text()
    # only a database that keeps a write-ahead log has one to keep with the copy a restore sets aside
    assert ("journal_mode=WAL" in schema) == site.spec.wal


@sites_where(alerts=True)
def test_the_alerts_wording_is_written_in_the_sites_own_code(site):
    checkout_of(site)
    theirs = written(site.src / "offsite.py")
    w = site.wording
    for text in (w.no_backups, w.backup_stale, w.server_only, w.no_offsite_yet, w.offsite_failed, w.offsite_stale):
        pieces = [p for p in re.split(r"\{\w+\}", text) if p]
        assert [p for p in pieces if p not in theirs] == [], text


def test_a_site_without_alerts_of_its_own_takes_where_councils_stands():
    assert not LANDLORDS.alerts and LANDLORDS.wording == COUNCILS.wording


def test_the_clock_used_in_these_tests_is_in_utc():
    assert frozen(datetime(2026, 11, 2, 4, 15, tzinfo=UTC)).now(UTC).strftime(LANDLORDS.spec.stamp) == "20261102-041500"
