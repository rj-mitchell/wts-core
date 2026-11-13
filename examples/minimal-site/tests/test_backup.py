"""Backup and restore of the state database: the one thing that cannot be rebuilt from the minutes."""

from __future__ import annotations

import gzip
import stat

import pytest
from fastapi.testclient import TestClient
from wts_core.ops import RestoreRefused, backup_alerts, make_backup, restore_backup
from wts_core.testing import FixedClock

from conftest import DOGS, HOURS, ask, final_of, rows
from parks.app import Parks
from parks.site import BACKUP_ALERTS, BACKUPS


def test_a_backup_is_made_under_the_sites_own_name_and_put_back(client: TestClient, parks: Parks,
                                                                clock: FixedClock) -> None:
    settings = parks.settings
    first = final_of(ask(client, DOGS))["briefing_id"]
    archive = make_backup(settings.state_db, settings.backups_dir, BACKUPS,
                          keep=int(settings.section("backup")["keep"]), clock=clock)

    assert archive is not None and archive.name == "parks-state-2026-11-13.sqlite.gz"
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600  # it holds reports and contact details: its owner only
    with gzip.open(archive) as packed:
        assert packed.read(16) == b"SQLite format 3\x00"

    # the site goes on, and then the database is lost
    later = final_of(ask(client, HOURS, sources_only=True))
    assert later["answer"] is None
    parks.archive.withdraw(first, "Withdrawn after the backup was made.")
    kept = restore_backup(archive, settings.state_db, BACKUPS)

    # everything is as it was when the backup was made
    saved = parks.archive.get(first)
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


def test_the_owner_is_told_in_the_sites_words_when_backups_have_stopped(parks: Parks, client: TestClient,
                                                                       clock: FixedClock) -> None:
    folder = parks.settings.backups_dir
    folder.mkdir(parents=True)
    said = backup_alerts(folder, BACKUPS, offsite_set_up=False, wording=BACKUP_ALERTS, clock=clock)
    assert [(a.level, a.text) for a in said] == [("warning", "No backups have been made yet."),
                                                 ("warning", BACKUP_ALERTS.server_only)]
    # TODO(wts_core.cli): send a backup off site with wts_core.testing.MemoryOffsiteStore once it is on the
    # package branch, and read the alerts again.
