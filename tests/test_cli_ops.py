"""The backup commands, beside each site's own.

For each of the four sites, the site's own command (its Typer app, loaded from its checkout and run in a temporary
data folder) and the package's (``ops_commands`` with that site's names and words, added to an app as a site adds
it) are run on the same state of things, each in its own folder, and what they print and how they end are compared
line for line: standard output, standard error, the exit status, and any error left uncaught. Every site's
commands can be driven here, so nothing is compared with a recording.

One reason for refusing a restore is not driven through the commands: a swap that fails part-way needs the
operating system to fail at one exact step, which ``test_ops_backup.py`` arranges for the functions themselves.
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from cli_sites import OPS, Said, logging_left_as_it_was, mounted, options, run, their_modules  # noqa: F401
from test_adapters_b2 import FakeB2
from test_ops_offsite import MemoryStore
from test_ops_sites import (
    COUNCILS,
    LANDLORDS,
    MPS,
    SiteFacts,
    archive_of,
    damaged_database,
    each_site,
    freeze_their_clock,
    marker,
    names,
    sites_where,
    state_database,
)
from wts_core.cli import ops_commands
from wts_core.ops import OffsiteError
from wts_core.settings import Settings
from wts_core.testing import FixedClock

pytestmark = pytest.mark.usefixtures("logging_left_as_it_was")

WHEN = datetime(2026, 11, 13, 4, 20, 7, tzinfo=UTC)
Args = Callable[[Path], list[Any]]


class Pair:
    """A site's own commands and the package's, each with a folder of its own (``theirs`` and ``ours``, and in each
    ``data`` and ``backups``), the same clock, and the same Backblaze (a pretend one each)."""

    def __init__(self, site: SiteFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                 request: pytest.FixtureRequest) -> None:
        self.site, self.monkeypatch = site, monkeypatch
        self.cli, backup, offsite = their_modules(site, request, "cli", site.backup_in, "offsite")
        self.own = SimpleNamespace(backup=backup, offsite=offsite)
        self.roots = {"theirs": tmp_path / "theirs", "ours": tmp_path / "ours"}
        self.side = "theirs"
        self.b2: dict[str, FakeB2] = {}
        self.env: dict[str, str] = {}
        self.clock = FixedClock(WHEN)
        monkeypatch.setenv(f"{site.env_prefix}_DATA_DIR", str(self.roots["theirs"] / "data"))
        for name in site.env():
            monkeypatch.delenv(name, raising=False)
        self.at(WHEN)
        settings = Settings(raw={}, data_dir=self.roots["ours"] / "data", config_path=Path("settings.toml"),
                            site=site.site)
        self.called: list[str] = []
        self.app = mounted(ops_commands(site.site, lambda: settings, site.spec, OPS[site.repo], env=self.env,
                                        clock=self.clock, before=lambda: self.called.append("before")))

    def at(self, when: datetime) -> None:
        freeze_their_clock(self.monkeypatch, self.own, when)
        self.clock.set(when)

    def db(self, side: str) -> Path:
        return self.roots[side] / "data" / self.site.state_file

    def state(self, value: str = "live") -> None:
        for side in self.roots:
            state_database(self.db(side), self.site.spec, value)

    def bucket(self, **how: Any) -> None:
        """Off-site copies set up on both sides, each with a pretend Backblaze of its own."""
        self.b2 = {"theirs": FakeB2(**how), "ours": FakeB2(**how)}
        for name, value in self.site.env().items():
            self.monkeypatch.setenv(name, value)
        self.env.update(self.site.env())
        real = httpx.Client
        self.monkeypatch.setattr(httpx, "Client",
                                 lambda **_: real(transport=httpx.MockTransport(self.b2[self.side])))

    def both(self, args: Args, *, answer: str | None = None) -> tuple[Said, Said]:
        said = []
        for side, app in (("theirs", self.cli.app), ("ours", self.app)):
            self.side = side
            said.append(run(app, args(self.roots[side]), self.roots[side], answer=answer))
        return said[0], said[1]

    def same(self, args: Args, *, answer: str | None = None) -> Said:
        """Run both, and they must have said the same and ended the same."""
        theirs, ours = self.both(args, answer=answer)
        assert ours == theirs, f"\ntheirs: {theirs}\nours: {ours}"
        return ours

    def backups(self, side: str) -> list[str]:
        folder = self.roots[side] / "backups"
        return names(folder) if folder.exists() else []


@pytest.fixture
def pair(site: SiteFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Pair:
    return Pair(site, tmp_path, monkeypatch, request)


def backup(root: Path) -> list[Any]:
    return ["backup", "--to", root / "backups"]


# ---- backup --------------------------------------------------------------------------------------------------------


@each_site
def test_a_new_site_has_nothing_to_back_up(site, pair):
    said = pair.same(backup)
    assert said == Said(0, OPS[site.repo].backup.nothing_to_back_up + "\n", "", None)
    assert pair.backups("theirs") == pair.backups("ours") == []
    assert not pair.db("ours").exists()  # and asking did not make a database


@each_site
def test_a_first_backup_and_a_second_on_the_same_day(site, pair):
    pair.state()
    first = pair.same(backup)
    name = site.archive_name(WHEN)
    assert first.exit_code == 0 and f"<root>/backups/{name}" in first.stdout
    assert first.stdout.endswith("Off-site copy: not set up\n") and first.stderr == ""
    assert pair.backups("theirs") == pair.backups("ours") == [name]
    pair.at(WHEN + timedelta(hours=3))
    second = pair.same(backup)
    later = site.archive_name(WHEN + timedelta(hours=3))
    # only Where Landlords Stand's names carry the time: its second backup is a second file, and it says so
    assert pair.backups("theirs") == pair.backups("ours") == sorted({name, later})
    assert ("(2 kept)" in second.stdout) == (site is LANDLORDS) == (later != name)
    assert pair.called == ["before", "before"]


@each_site
def test_only_as_many_as_asked_are_kept(site, pair):
    pair.state()
    for day in range(3):
        pair.at(WHEN + timedelta(days=day))
        said = pair.same(lambda root: [*backup(root), "--keep", "2"])
    assert said.exit_code == 0
    assert pair.backups("theirs") == pair.backups("ours") == [site.archive_name(WHEN + timedelta(days=d))
                                                             for d in (1, 2)]


@sites_where(repo=MPS.repo)
def test_where_mps_stand_backs_up_into_its_data_folder_when_no_folder_is_named(site, pair):
    pair.state()
    said = pair.same(lambda root: ["backup"])
    assert said.stdout.startswith(f"Backed up to <root>/data/backups/{site.archive_name(WHEN)}\n")
    assert (pair.roots["ours"] / "data" / "backups" / site.archive_name(WHEN)).exists()


@sites_where(restores=False)
def test_elsewhere_the_folder_must_be_named(site, pair):
    theirs, ours = pair.both(lambda root: ["backup"])
    assert theirs.exit_code == ours.exit_code == 2
    assert "--to" in theirs.stderr and "--to" in ours.stderr


@each_site
def test_a_backup_goes_off_site_when_a_bucket_is_set_up(site, pair):
    pair.state()
    pair.bucket()
    first = pair.same(backup)
    assert first.exit_code == 0 and "Off-site copy: stored in wts-backups" in first.stdout
    assert ("(1 kept there)" in first.stdout) == (site is not LANDLORDS)
    pair.at(WHEN + timedelta(days=1))
    pair.same(backup)
    assert sorted(pair.b2["theirs"].files) == sorted(pair.b2["ours"].files) == [
        site.archive_name(WHEN), site.archive_name(WHEN + timedelta(days=1))]
    their_status, our_status = (json.loads((pair.roots[side] / "backups" / "offsite.json").read_text())
                                for side in pair.roots)
    assert our_status == their_status and our_status["stored"] == 2


@each_site
def test_an_off_site_copy_that_fails_is_said_and_the_backup_is_still_made(site, pair):
    pair.state()
    pair.bucket(authorize=403)
    said = pair.same(backup)
    refused = (f"Backblaze did not accept the key: check {site.env_prefix}_B2_KEY_ID and "
               f"{site.env_prefix}_B2_APPLICATION_KEY\n")
    assert said.exit_code == 1 and pair.backups("ours") == pair.backups("theirs")
    assert site.archive_name(WHEN) in pair.backups("ours") and "offsite.json" in pair.backups("ours")
    if site is LANDLORDS:  # it says a failure on standard output, in its own words
        assert said.stdout.endswith("Off-site copy failed: " + refused) and said.stderr == ""
    else:
        assert said.stderr == "The off-site copy failed: " + refused


@each_site
def test_a_copy_that_fails_its_check_is_never_kept(site, pair):
    for side in pair.roots:
        damaged_database(pair.db(side), site.spec)
    said = pair.same(backup)
    assert said.exit_code == 1 and pair.backups("theirs") == pair.backups("ours") == []
    if site is LANDLORDS:  # the only site that says it in a line: the others leave the error as it is
        assert said.stdout.startswith("Backup failed: the backup copy failed its integrity check: ")
        assert said.error is None
    else:
        assert said.error.startswith("RuntimeError: the backup copy failed its integrity check: ")
        assert said.stdout == ""


# ---- offsite -------------------------------------------------------------------------------------------------------


@each_site
def test_offsite_says_what_to_set_when_nothing_is_set_up(site, pair):
    said = pair.same(lambda root: ["offsite"])
    p = site.env_prefix
    assert said.exit_code == 0 and json.loads(said.stdout) == {
        "ok": False, "error": f"not set up: add {p}_B2_BUCKET, {p}_B2_KEY_ID and {p}_B2_APPLICATION_KEY to "
                              "deploy/.env"}


@each_site
def test_offsite_says_what_is_in_the_bucket(site, pair):
    pair.bucket()
    assert json.loads(pair.same(lambda root: ["offsite"]).stdout) == {
        "ok": True, "bucket": "wts-backups", "backups": 0, "newest": None}
    pair.state()
    pair.same(backup)
    said = pair.same(lambda root: ["offsite"])
    assert json.loads(said.stdout) == {"ok": True, "bucket": "wts-backups", "backups": 1,
                                       "newest": site.archive_name(WHEN)}
    assert said.stdout.startswith('{\n  "ok": true,\n')  # two spaces in, as each site prints it


@each_site
def test_offsite_with_a_key_that_is_refused_ends_in_the_stores_own_error(site, pair):
    pair.bucket(authorize=401)
    said = pair.same(lambda root: ["offsite"])
    assert said.exit_code == 1 and said.stdout == ""
    assert said.error.startswith("OffsiteError: Backblaze did not accept the key: check ")


# ---- restore -------------------------------------------------------------------------------------------------------


def made(pair: Pair, value: str = "saved") -> None:
    """A backup of each side's database as it is now, then the database changed: restoring brings ``value`` back."""
    pair.state(value)
    pair.same(backup)
    pair.state("changed since")


def restore(root: Path, *more: Any, archive: str | None = None) -> list[Any]:
    return ["restore", root / "backups" / archive if archive else root / "the-archive", *more]


@sites_where(restores=True)
def test_restore_puts_a_backup_back_and_says_where_the_replaced_database_is(site, pair):
    made(pair)
    name = site.archive_name(WHEN)
    said = pair.same(lambda root: restore(root, "--yes", archive=name))
    assert said.exit_code == 0 and f"<root>/data/{site.state_file}.before-restore" in said.stdout
    for side in pair.roots:
        assert marker(pair.db(side)) == "saved"
        assert marker(pair.db(side).with_name(site.state_file + ".before-restore")) == "changed since"


@sites_where(restores=True)
def test_restore_onto_a_new_site_has_nothing_to_keep(site, pair):
    made(pair)
    for side in pair.roots:
        pair.db(side).unlink()
        for beside in ("-wal", "-shm"):
            pair.db(side).with_name(site.state_file + beside).unlink(missing_ok=True)
    said = pair.same(lambda root: restore(root, "--yes", archive=site.archive_name(WHEN)))
    assert said.exit_code == 0 and "before-restore" not in said.stdout
    assert said.stdout == {MPS.repo: "Restored. Start the site again.\n"}.get(
        site.repo, f"restored <root>/data/state.db from <root>/backups/{site.archive_name(WHEN)}\n")


@sites_where(restores=True)
def test_restore_asks_first_and_no_changes_nothing(site, pair):
    made(pair)
    name = site.archive_name(WHEN)
    no = pair.same(lambda root: restore(root, archive=name), answer="n\n")
    assert no.exit_code == 1 and ("Aborted." in no.stdout + no.stderr) == (site is MPS)
    assert [marker(pair.db(side)) for side in pair.roots] == ["changed since"] * 2
    yes = pair.same(lambda root: restore(root, archive=name), answer="y\n")
    assert yes.exit_code == 0 and [marker(pair.db(side)) for side in pair.roots] == ["saved"] * 2


@sites_where(restores=True)
def test_restore_refused_for_each_reason_in_the_sites_own_words(site, pair, tmp_path):
    spec = site.spec
    made(pair)
    good = pair.roots["ours"] / "backups" / site.archive_name(WHEN)
    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("CREATE TABLE something (x)").connection.close()
    unsound = damaged_database(tmp_path / "unsound.db", spec)
    short = gzip.compress(b"x" * 1000)[:20]
    archives: dict[str, bytes] = {
        "not-a-database": archive_of(tmp_path / f"bad{spec.suffix}", spec,
                                     state=b"not a database at all" * 100).read_bytes(),
        "unreadable": good.read_bytes()[: good.stat().st_size // 2],  # cut short
        "unreadable, cut to nothing": short,
        "foreign": archive_of(tmp_path / f"foreign{spec.suffix}", spec, state=other.read_bytes()).read_bytes(),
        "damaged": archive_of(tmp_path / f"unsound{spec.suffix}", spec, state=unsound.read_bytes()).read_bytes(),
    }
    if spec.format == "tar":
        archives["foreign, no database in it"] = archive_of(tmp_path / "empty.tar.gz", spec,
                                                           settings__local__toml=b"#\n").read_bytes()
    for why, content in archives.items():
        for root in pair.roots.values():
            (root / f"the-archive{spec.suffix}").write_bytes(content)
        said = pair.same(lambda root: ["restore", root / f"the-archive{spec.suffix}", "--yes"])
        assert said.exit_code == 1 and said.stderr.startswith("Not restored: ") and said.stdout == "", why
        assert [marker(pair.db(side)) for side in pair.roots] == ["changed since"] * 2, why
    # a kept copy from an earlier restore is in the way: the one reason the two sites word differently (Where MPs
    # Stand ends it with a full stop, and no other reason), and the package's is Where Countries Stand's
    for side in pair.roots:
        pair.db(side).with_name(site.state_file + ".before-restore").write_bytes(b"from an earlier restore")
    theirs, ours = pair.both(lambda root: restore(root, "--yes", archive=site.archive_name(WHEN)))
    assert ours.exit_code == theirs.exit_code == 1 and ours.stdout == theirs.stdout == ""
    assert ours.stderr == (f"Not restored: <root>/data/{site.state_file}.before-restore is still there from an "
                           "earlier restore: move or delete it first\n")
    assert theirs.stderr == (ours.stderr.rstrip("\n") + ".\n" if site is MPS else ours.stderr)


@sites_where(restores=True)
def test_restore_of_a_file_that_is_not_there(site, pair):
    pair.state()
    theirs, ours = pair.both(lambda root: restore(root, "--yes", archive="missing" + site.spec.suffix))
    if site is MPS:  # Typer refuses the path before the command runs: its own message, and exit status 2
        def unboxed(said: Said) -> str:  # the message without the box drawn round it, which breaks lines by width
            return "".join(said.stderr.split("Error")[1].replace("│", "").split())

        assert ours.exit_code == theirs.exit_code == 2 and "doesnotexist" in unboxed(ours)
        assert unboxed(ours) == unboxed(theirs)
    else:
        assert ours == theirs and ours.exit_code == 1
        assert ours.stderr.startswith(f"Not restored: missing{site.spec.suffix} could not be read: ")


@sites_where(restores=False)
def test_a_site_without_a_restore_command_gains_none(site, pair):
    theirs, ours = pair.both(lambda root: ["restore", "x"])
    assert theirs.exit_code == ours.exit_code == 2 and "No such command" in ours.stderr


# ---- backup-check (Where Councils Stand's) -------------------------------------------------------------------------


def check(root: Path) -> list[Any]:
    return ["backup-check", "--in", root / "backups"]


@sites_where(repo=COUNCILS.repo)
def test_backup_check_with_no_folder(site, pair):
    said = pair.same(check)
    assert said == Said(1, "", "error: there is no backup folder at <root>/backups\n", None)


@sites_where(repo=COUNCILS.repo)
def test_backup_check_says_each_problem_and_fails_on_an_error(site, pair):
    pair.state()
    for root in pair.roots.values():
        (root / "backups").mkdir(parents=True)
    none_yet = pair.same(check)
    assert none_yet == Said(0, "warning: No backups have been made yet.\nwarning: Backups are kept on this server "
                               "only: no off-site copy is set up.\n", "", None)
    pair.bucket()
    pair.same(backup)
    assert pair.same(check) == Said(0, "Backups are up to date.\n", "", None)
    for root in pair.roots.values():  # the timer stopped three days ago
        old = (WHEN - timedelta(days=3)).timestamp()
        os.utime(root / "backups" / site.archive_name(WHEN), (old, old))
        (root / "backups" / "offsite.json").write_text(json.dumps({"ok": False, "when": "2026-11-10T04:30:07+00:00",
                                                                   "error": "upload failed: 503"}))
    stale = pair.same(check)
    assert stale.exit_code == 1 and stale.stdout == ""
    assert stale.stderr == (f"error: The last backup was made over two days ago ({site.archive_name(WHEN)}).\n"
                            "error: The last off-site copy failed (2026-11-10T04:30): upload failed: 503\n")


@sites_where(repo=MPS.repo)
def test_a_site_without_a_backup_check_gains_none(site, pair):
    theirs, ours = pair.both(check)
    assert theirs.exit_code == ours.exit_code == 2


# ---- names and options ---------------------------------------------------------------------------------------------


@each_site
def test_each_command_takes_the_options_the_sites_own_takes(site, pair):
    wording = OPS[site.repo]
    commands = ["backup", "offsite", *(["restore"] if wording.restore else []),
                *(["backup-check"] if wording.backup_check else [])]
    for name in commands:
        assert options(pair.app, name) == options(pair.cli.app, name), name


# ---- the package's own -------------------------------------------------------------------------------------------


def our_app(site: SiteFacts, folder: Path, **more: Any) -> Any:
    settings = Settings(raw={}, data_dir=folder / "data", config_path=Path("settings.toml"), site=site.site)
    return mounted(ops_commands(site.site, lambda: settings, site.spec, OPS[site.repo], clock=FixedClock(WHEN),
                                **more))


@each_site
def test_the_backup_command_keeps_off_site_as_many_as_the_sites_spec_says(site, tmp_path):
    import dataclasses

    store = MemoryStore("wts-backups")
    for day in range(1, 8):
        store.files[site.archive_name(WHEN - timedelta(days=day))] = b"x"
    two = dataclasses.replace(site.spec, keep_offsite=2)
    settings = Settings(raw={}, data_dir=tmp_path / "data", config_path=Path("settings.toml"), site=site.site)
    app = mounted(ops_commands(site.site, lambda: settings, two, OPS[site.repo], store=lambda: store,
                               clock=FixedClock(WHEN)))
    state_database(tmp_path / "data" / site.state_file, site.spec)
    assert run(app, backup(tmp_path), tmp_path).exit_code == 0
    assert sorted(store.files) == [site.archive_name(WHEN - timedelta(days=1)), site.archive_name(WHEN)]


@each_site
def test_the_clock_may_be_given_when_a_command_runs_so_a_test_can_fix_a_backups_name(site, tmp_path):
    """A site builds its commands once, when its command line is imported. Given a function, they ask for the
    clock each time, so a test that stands another clock in afterwards names the backup."""
    stood_in = [FixedClock(WHEN)]
    settings = Settings(raw={}, data_dir=tmp_path / "data", config_path=Path("settings.toml"), site=site.site)
    app = mounted(ops_commands(site.site, lambda: settings, site.spec, OPS[site.repo], store=lambda: None,
                               clock=lambda: stood_in[0]))
    state_database(tmp_path / "data" / site.state_file, site.spec)
    assert run(app, backup(tmp_path), tmp_path).exit_code == 0
    later = WHEN + timedelta(days=3, hours=2)
    stood_in[0] = FixedClock(later)  # after the commands were built
    assert run(app, backup(tmp_path), tmp_path).exit_code == 0
    assert names(tmp_path / "backups") == [site.archive_name(WHEN), site.archive_name(later)]


@each_site
def test_a_site_may_keep_its_copies_in_another_store(site, tmp_path):
    store = MemoryStore("somewhere-else")
    app = our_app(site, tmp_path, store=lambda: store, how_to_set_up="set OTHER_STORE in deploy/.env")
    state_database(tmp_path / "data" / site.state_file, site.spec)
    said = run(app, backup(tmp_path), tmp_path)
    assert said.exit_code == 0 and "stored in somewhere-else" in said.stdout
    assert list(store.files) == [site.archive_name(WHEN)]
    assert json.loads(run(app, ["offsite"], tmp_path).stdout)["backups"] == 1
    nowhere = our_app(site, tmp_path, store=lambda: None, how_to_set_up="set OTHER_STORE in deploy/.env")
    assert json.loads(run(nowhere, ["offsite"], tmp_path).stdout) == {
        "ok": False, "error": "not set up: set OTHER_STORE in deploy/.env"}


@each_site
def test_a_store_that_cannot_be_reached_is_a_failed_copy(site, tmp_path):
    store = MemoryStore()
    store.fail["put"] = OffsiteError("upload failed: 503 service unavailable")
    app = our_app(site, tmp_path, store=lambda: store)
    state_database(tmp_path / "data" / site.state_file, site.spec)
    said = run(app, backup(tmp_path), tmp_path)
    assert said.exit_code == 1 and "upload failed: 503 service unavailable" in said.stdout + said.stderr
    assert json.loads((tmp_path / "backups" / "offsite.json").read_text())["ok"] is False


@each_site
def test_off_site_copies_set_up_without_their_library_say_what_to_install(site, tmp_path, monkeypatch):
    """httpx is the ``offsite`` extra: a site that sets a bucket without installing it is told so in a line."""
    monkeypatch.setitem(sys.modules, "httpx", None)  # as if it were not installed
    app = our_app(site, tmp_path, env=site.env())
    state_database(tmp_path / "data" / site.state_file, site.spec)
    for args in (backup(tmp_path), ["offsite"]):
        said = run(app, args, tmp_path)
        assert said.exit_code == 1 and said.error is None
        assert "(httpx) is not installed" in said.stderr and "wts-core[offsite]" in said.stderr
    assert site.archive_name(WHEN) in names(tmp_path / "backups")  # the backup itself was made
    # and with nothing set up, the library is never asked for
    plain = our_app(site, tmp_path, env={})
    assert run(plain, backup(tmp_path), tmp_path).exit_code == 0
    assert run(plain, ["offsite"], tmp_path).exit_code == 0


def test_the_commands_module_needs_neither_typer_nor_httpx_until_a_command_is_built():
    code = ("import sys; sys.modules['typer'] = None; sys.modules['httpx'] = None; sys.modules['fastapi'] = None\n"
            "import wts_core.cli\n"
            "from wts_core.cli import check_route, eval_commands, ops_commands, replies_commands, stats_commands\n"
            "print(sorted(m for m in ('typer', 'httpx', 'fastapi') if sys.modules.get(m)))")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert (done.returncode, done.stdout.strip()) == (0, "[]"), done.stderr
