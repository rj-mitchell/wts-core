"""Backup and restore of the state database: the one thing that cannot be rebuilt from the minutes."""

from __future__ import annotations

import gzip
import stat

import pytest
from fastapi.testclient import TestClient
from wts_core.ops import (
    OffsiteError,
    OffsiteUnavailable,
    RestoreRefused,
    backup_alerts,
    make_backup,
    restore_backup,
    send_offsite,
)
from wts_core.state import StateDB
from wts_core.testing import FixedClock, MemoryOffsiteStore

from conftest import DOGS, HOURS, ask, final_of, rows
from parks.app import Parks
from parks.site import BACKUP_ALERTS, BACKUPS, migrations


def test_a_backup_is_made_under_the_sites_own_name_and_put_back(client: TestClient, parks: Parks,
                                                                clock: FixedClock) -> None:
    settings = parks.settings
    first = final_of(ask(client, DOGS))["briefing_id"]
    archive = make_backup(settings.state_db, settings.backups_dir, BACKUPS, clock=clock)

    assert archive is not None and archive.name == "parks-state-2026-11-13.sqlite.gz"
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600  # it holds reports and contact details: its owner only
    with gzip.open(archive) as packed:
        assert packed.read(16) == b"SQLite format 3\x00"

    # the site goes on, and then the database is lost
    later = final_of(ask(client, HOURS, sources_only=True))
    assert later["answer"] is None
    parks.parts.archive.withdraw(first, "Withdrawn after the backup was made.")
    kept = restore_backup(archive, settings.state_db, BACKUPS)

    # everything is as it was when the backup was made
    saved = parks.parts.archive.get(first)
    assert saved is not None and saved.withdrawn_at is None
    assert len(rows(parks, "SELECT 1 FROM wts_spending")) == 2 and len(rows(parks, "SELECT 1 FROM wts_briefing_log")) == 1
    assert client.get(f"/b/{first}").status_code == 200
    # the database that was replaced is kept beside it, and a second restore will not write over that copy
    assert kept == settings.state_db.with_name("state.db.before-restore") and kept.exists()
    with pytest.raises(RestoreRefused, match="move or delete it first") as refused:
        restore_backup(archive, settings.state_db, BACKUPS)
    assert refused.value.why == "kept-copy"


def test_only_the_newest_backups_are_kept(client: TestClient, parks: Parks, clock: FixedClock) -> None:
    ask(client, DOGS, sources_only=True)
    for _ in range(4):
        make_backup(parks.settings.state_db, parks.settings.backups_dir, BACKUPS, keep=3, clock=clock)
        clock.advance(days=1)
    assert [p.name for p in BACKUPS.archives(parks.settings.backups_dir)] \
        == [f"parks-state-2026-11-{day}.sqlite.gz" for day in (14, 15, 16)]


def test_a_file_that_is_not_this_sites_backup_is_refused(client: TestClient, parks: Parks, tmp_path_factory: pytest.TempPathFactory) -> None:
    ask(client, DOGS, sources_only=True)
    stranger = tmp_path_factory.mktemp("other") / "other-state-2026-11-13.sqlite.gz"
    with gzip.open(stranger, "wb") as out:
        out.write(b"not a database at all")
    with pytest.raises(RestoreRefused) as refused:
        restore_backup(stranger, parks.settings.state_db, BACKUPS)
    assert refused.value.why == "not-a-database"
    assert len(rows(parks, "SELECT 1 FROM wts_briefing_log")) == 1  # nothing was touched


def test_a_sister_sites_backup_is_refused_though_it_has_every_table_this_site_has(
        client: TestClient, parks: Parks, clock: FixedClock, tmp_path_factory: pytest.TempPathFactory) -> None:
    ask(client, DOGS, sources_only=True)
    # a sister site built on the package: the same tables, made the same way, and its own mark
    sister = StateDB(tmp_path_factory.mktemp("rivers") / "state.db", migrations=migrations(), clock=clock,
                     site="rivers")
    theirs = make_backup(sister.path, sister.path.parent / "backups", BACKUPS, clock=clock)
    assert theirs is not None and BACKUPS.site == "parks" and parks.db.get("site") == "parks"
    with pytest.raises(RestoreRefused, match="marked 'rivers', and this site is 'parks'") as refused:
        restore_backup(theirs, parks.settings.state_db, BACKUPS)
    assert refused.value.why == "other-site"
    assert len(rows(parks, "SELECT 1 FROM wts_briefing_log")) == 1  # nothing was touched
    # and this site will not open the sister's data folder by mistake
    with pytest.raises(RuntimeError, match="is the state database of another site"):
        StateDB(sister.path, migrations=migrations(), site="parks")


def test_a_copy_goes_off_site_and_the_owner_is_told_when_backups_stop(parks: Parks, client: TestClient,
                                                                      clock: FixedClock) -> None:
    folder = parks.settings.backups_dir
    folder.mkdir(parents=True)
    said = backup_alerts(folder, BACKUPS, offsite_set_up=False, wording=BACKUP_ALERTS, clock=clock)
    assert [(a.level, a.text) for a in said] == [("warning", "No backups have been made yet."),
                                                 ("warning", BACKUP_ALERTS.server_only)]

    # an off-site store in memory stands in for the real one: any ports.OffsiteStore will do
    ask(client, DOGS, sources_only=True)
    store = MemoryOffsiteStore("parks-backups")
    store.files["councils-state-2026-11-01.sqlite.gz"] = b"another site's backup, in the same bucket"
    for _ in range(3):
        archive = make_backup(parks.settings.state_db, folder, BACKUPS, clock=clock)
        assert archive is not None
        sent = send_offsite(archive, store, BACKUPS, keep=2, clock=clock)
        clock.advance(days=1)
    assert sent == {"ok": True, "when": "2026-11-15T12:00:00+00:00", "file": "parks-state-2026-11-15.sqlite.gz",
                    "bucket": "parks-backups", "stored": 2, "deleted": 1}
    # only this site's old copies are deleted: another site's in the same bucket is left alone
    assert sorted(store.files) == ["councils-state-2026-11-01.sqlite.gz", "parks-state-2026-11-14.sqlite.gz",
                                   "parks-state-2026-11-15.sqlite.gz"]

    store.fail["put"] = OffsiteUnavailable("the store did not answer")
    with pytest.raises(OffsiteError):
        send_offsite(archive, store, BACKUPS, clock=clock)
    said = backup_alerts(folder, BACKUPS, offsite_set_up=True, wording=BACKUP_ALERTS, clock=clock)
    assert (said[-1].level, said[-1].text) \
        == ("error", "The last off-site copy failed (2026-11-16T12:00): the store did not answer")
