"""Off-site copies and the backup alerts, against a store kept in memory: the sites' tests of their ``offsite.py``
that are not about Backblaze itself (those are in test_adapters_b2.py), for each site's names and wording, and the
alerts compared word for word with each site's own."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from test_ops_sites import SITES, each_site, own_code, sites_where, state_database
from wts_core.ops import (
    Alert,
    OffsiteError,
    OffsiteUnavailable,
    backup_alerts,
    check_offsite,
    make_backup,
    send_offsite,
)
from wts_core.ports import OffsiteStore, StoredFile
from wts_core.testing import FixedClock

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


class MemoryStore:
    """A ``ports.OffsiteStore`` that keeps what it is given, and can be told to fail."""

    def __init__(self, name: str = "wts-backups", *, can_delete: bool = True, newest_first: bool = False) -> None:
        self.name, self.can_delete, self.newest_first = name, can_delete, newest_first
        self.files: dict[str, bytes] = {}
        self.fail: dict[str, Exception] = {}  # the method's name, and what it raises
        self.closed = 0

    def put(self, path: Path) -> StoredFile:
        if "put" in self.fail:
            raise self.fail["put"]
        self.files[path.name] = path.read_bytes()
        return StoredFile(path.name, f"id-{path.name}", len(self.files[path.name]))

    def list(self, prefix: str) -> list[StoredFile]:
        if "list" in self.fail:
            raise self.fail["list"]
        found = [StoredFile(n, f"id-{n}", len(self.files[n])) for n in sorted(self.files) if n.startswith(prefix)]
        return found[::-1] if self.newest_first else found

    def delete(self, file: StoredFile) -> None:
        if "delete" in self.fail:
            raise self.fail["delete"]
        if not self.can_delete:
            raise OffsiteError("b2_delete_file_version: 401 unauthorized")
        del self.files[file.name]

    def close(self) -> None:
        self.closed += 1


def archive(folder: Path, site, day: str) -> Path:
    p = folder / site.archive_name(datetime.fromisoformat(day).replace(tzinfo=UTC))
    p.write_bytes(f"backup {day}".encode())
    return p


def status(folder: Path) -> dict:
    return json.loads((folder / "offsite.json").read_text())


def test_the_store_in_these_tests_is_an_off_site_store():
    store: OffsiteStore = MemoryStore()
    assert store.list("") == []


# ---- sending and checking ----------------------------------------------------------------------------------------


@each_site
def test_not_set_up_does_nothing(site, tmp_path):
    assert send_offsite(archive(tmp_path, site, "2026-10-12"), None, site.spec) == {"offsite": "not set up"}
    assert not (tmp_path / "offsite.json").exists()
    assert check_offsite(None, site.spec) == {"ok": False, "error": "not set up"}
    assert check_offsite(None, site.spec, how_to_set_up="add the three settings to deploy/.env") == {
        "ok": False, "error": "not set up: add the three settings to deploy/.env"}


@each_site
def test_the_newest_are_kept_and_the_outcome_is_written_down(site, tmp_path):
    store = MemoryStore()
    clock = FixedClock("2026-10-12T03:31:07.250+00:00")
    for day in ("2026-10-10", "2026-10-11", "2026-10-12"):
        out = send_offsite(archive(tmp_path, site, day), store, site.spec, keep=2, clock=clock)
    newest = site.archive_name(datetime(2026, 10, 12, tzinfo=UTC))
    assert out == {"ok": True, "when": "2026-10-12T03:31:07+00:00", "file": newest, "bucket": "wts-backups",
                   "stored": 2, "deleted": 1}
    assert status(tmp_path) == out and list(status(tmp_path)) == ["ok", "when", "file", "bucket", "stored", "deleted"]
    assert sorted(store.files) == [site.archive_name(datetime(2026, 10, 11, tzinfo=UTC)), newest]
    assert check_offsite(store, site.spec) == {"ok": True, "bucket": "wts-backups", "backups": 2, "newest": newest}
    assert store.closed == 4  # after each copy, and after the check


@each_site
def test_sixty_are_kept_unless_another_number_is_given(site, tmp_path):
    store = MemoryStore()
    for n in range(61):
        store.files[site.archive_name(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=n))] = b"x"
    out = send_offsite(archive(tmp_path, site, "2026-10-12"), store, site.spec, clock=FixedClock(NOW))
    assert out["stored"] == 60 and out["deleted"] == 2
    assert min(store.files) == site.archive_name(datetime(2026, 1, 3, tzinfo=UTC))


@each_site
@pytest.mark.parametrize("keep", [0, -1])
def test_keeping_none_or_fewer_deletes_nothing_off_site(site, tmp_path, keep):
    store = MemoryStore()
    for day in ("2026-10-10", "2026-10-11", "2026-10-12"):
        out = send_offsite(archive(tmp_path, site, day), store, site.spec, keep=keep, clock=FixedClock(NOW))
    assert out["stored"] == 3 and out["deleted"] == 0


@each_site
def test_a_key_without_delete_rights_still_stores(site, tmp_path, caplog):
    store = MemoryStore(can_delete=False)
    send_offsite(archive(tmp_path, site, "2026-10-11"), store, site.spec, keep=1, clock=FixedClock(NOW))
    with caplog.at_level(logging.WARNING, logger="wts_core.ops.offsite"):
        out = send_offsite(archive(tmp_path, site, "2026-10-12"), store, site.spec, keep=1, clock=FixedClock(NOW))
    assert out["ok"] and out["stored"] == 2 and out["deleted"] == 0 and status(tmp_path) == out
    assert caplog.messages == ["old off-site backups not deleted: b2_delete_file_version: 401 unauthorized"]


@each_site
def test_failures_are_reported_and_recorded(site, tmp_path):
    store = MemoryStore()
    store.fail["put"] = OffsiteError("Backblaze did not accept the key: check the settings " + "x" * 400)
    with pytest.raises(OffsiteError, match="did not accept the key") as failed:
        send_offsite(archive(tmp_path, site, "2026-10-12"), store, site.spec, clock=FixedClock(NOW))
    assert type(failed.value) is OffsiteError and str(failed.value) == str(store.fail["put"])
    said = status(tmp_path)
    assert said == {"ok": False, "when": "2026-11-06T12:00:00+00:00", "error": str(store.fail["put"])[:300]}
    assert len(said["error"]) == 300 and store.closed == 1


@each_site
@pytest.mark.parametrize("step", ["put", "delete", "list"])
def test_a_store_that_cannot_be_reached_is_a_failed_copy_at_any_step(site, tmp_path, step):
    """Unlike a store that answers and refuses to delete: then the new copy is stored and the old ones stay."""
    store = MemoryStore()
    store.files[site.archive_name(datetime(2026, 10, 1, tzinfo=UTC))] = b"an older copy"
    store.fail[step] = OffsiteUnavailable("[Errno 101] Network is unreachable")
    with pytest.raises(OffsiteError, match="Network is unreachable"):
        send_offsite(archive(tmp_path, site, "2026-10-12"), store, site.spec, keep=1, clock=FixedClock(NOW))
    assert status(tmp_path) == {"ok": False, "when": "2026-11-06T12:00:00+00:00",
                                "error": "[Errno 101] Network is unreachable"}
    assert store.closed == 1
    with pytest.raises(OffsiteError):  # the check catches nothing: the site's command says what went wrong
        store.fail["list"] = store.fail[step]
        check_offsite(store, site.spec)
    assert store.closed == 2


@each_site
def test_sites_sharing_a_bucket_keep_their_own_backups(site, tmp_path):
    """Another of the charity's sites' backups in the same bucket are neither counted nor deleted."""
    store = MemoryStore()
    others = [other.archive_name(datetime(2026, 10, 1, tzinfo=UTC)) for other in SITES if other is not site]
    for name in others:
        store.files[name] = b"another site's"
    for day in ("2026-10-11", "2026-10-12"):
        out = send_offsite(archive(tmp_path, site, day), store, site.spec, keep=1, clock=FixedClock(NOW))
    assert out["stored"] == 1 and out["deleted"] == 1
    assert sorted(store.files) == sorted([*others, site.archive_name(datetime(2026, 10, 12, tzinfo=UTC))])
    assert check_offsite(store, site.spec)["backups"] == 1


def test_the_newest_are_kept_whatever_order_a_store_answers_in(tmp_path):
    site, store = SITES[1], MemoryStore(newest_first=True)
    for day in ("2026-10-10", "2026-10-11", "2026-10-12"):
        send_offsite(archive(tmp_path, site, day), store, site.spec, keep=1, clock=FixedClock(NOW))
    assert list(store.files) == ["wcs-state-2026-10-12.sqlite.gz"]
    assert check_offsite(store, site.spec)["newest"] == "wcs-state-2026-10-12.sqlite.gz"


def test_an_empty_bucket_has_no_newest_backup():
    assert check_offsite(MemoryStore(), SITES[0].spec) == {"ok": True, "bucket": "wts-backups", "backups": 0,
                                                           "newest": None}


def test_an_outcome_that_cannot_be_written_down_is_not_an_error(tmp_path):
    site = SITES[2]
    (tmp_path / "offsite.json").mkdir()  # nothing can be written there
    out = send_offsite(archive(tmp_path, site, "2026-10-12"), MemoryStore(), site.spec, clock=FixedClock(NOW))
    assert out["ok"] and out["stored"] == 1



# ---- alerts ------------------------------------------------------------------------------------------------------


def aged(path: Path, when: datetime) -> Path:
    os.utime(path, (when.timestamp(), when.timestamp()))
    return path


def alerts(folder: Path, site, *, set_up: bool, now: datetime = NOW, **more) -> list[Alert]:
    return backup_alerts(folder, site.spec, offsite_set_up=set_up, wording=site.wording, clock=FixedClock(now), **more)


def record(folder: Path, **said) -> None:
    (folder / "offsite.json").write_text(json.dumps(said))


@each_site
def test_backup_alerts(site, tmp_path):
    """Every condition, in each site's own words (Where Countries Stand's test of its exact texts, for all four)."""
    w, folder = site.wording, tmp_path / "backups"
    assert alerts(tmp_path / "none", site, set_up=False) == []  # no backups folder: nothing to say
    assert alerts(tmp_path / "none", site, set_up=True) == []
    folder.mkdir()
    assert alerts(folder, site, set_up=False) == [Alert("warning", w.no_backups), Alert("warning", w.server_only)]
    assert alerts(folder, site, set_up=True) == [Alert("warning", w.no_backups)]
    out = aged(archive(folder, site, "2026-11-01"), NOW - timedelta(days=3))
    stale = Alert("error", w.backup_stale.format(name=out.name))
    assert alerts(folder, site, set_up=False) == [stale, Alert("warning", w.server_only)]
    assert alerts(folder, site, set_up=True) == [stale, Alert("warning", w.no_offsite_yet)]
    aged(out, NOW - timedelta(hours=3))
    assert alerts(folder, site, set_up=False) == [Alert("warning", w.server_only)]
    assert alerts(folder, site, set_up=True) == [Alert("warning", w.no_offsite_yet)]
    (folder / "offsite.json").write_text("{ cut short")  # unreadable is as good as missing
    assert alerts(folder, site, set_up=True) == [Alert("warning", w.no_offsite_yet)]
    record(folder, ok=False, when="2026-11-06T03:00:00+00:00", error="Backblaze did not accept the key")
    assert alerts(folder, site, set_up=True) == [Alert("error", w.offsite_failed.format(
        when="2026-11-06T03:00", error="Backblaze did not accept the key"))]
    assert alerts(folder, site, set_up=False) == [Alert("warning", w.server_only)]  # nothing further is checked
    record(folder, ok=True, when="2026-11-02T03:00:00+00:00")
    assert alerts(folder, site, set_up=True) == [Alert("error", w.offsite_stale.format(day="2026-11-02"))]
    record(folder, ok=True, when="2026-11-06T03:00:00+00:00")
    assert alerts(folder, site, set_up=True) == []


def test_the_words_are_the_sites_own_and_none_are_the_packages():
    said = {s.repo: backup_stale for s in SITES
            for backup_stale in [s.wording.backup_stale.format(name=s.archive_name(datetime(2026, 11, 1, tzinfo=UTC)))]}
    assert said == {
        "wherempsstand": "The last backup was made over two days ago (where-they-stand-2026-11-01.tar.gz).",
        "wherecountriesstand": "the last backup was made over two days ago (wcs-state-2026-11-01.sqlite.gz): is "
                               "wcs-backup.timer running?",
        "wherecouncilsstand": "The last backup was made over two days ago (councils-state-2026-11-01.sqlite.gz).",
        "wherelandlordsstand": "The last backup was made over two days ago "
                               "(landlords-state-20261101-000000.sqlite.gz)."}
    with pytest.raises(TypeError):  # a site that leaves one out is told so when it starts, not when a backup stops
        type(SITES[0].wording)(no_backups="No backups have been made yet.")  # type: ignore[call-arg]


@each_site
def test_a_failed_copy_with_no_usable_time_is_still_reported(site, tmp_path):
    """A record whose time is null, or a number, is not an exception (from Where Councils Stand's tests)."""
    archive(tmp_path, site, "2026-11-06")
    for when in (None, 1731400000):
        record(tmp_path, ok=False, when=when, error="503")
        [alert] = backup_alerts(tmp_path, site.spec, offsite_set_up=True, wording=site.wording)
        assert alert.level == "error" and alert.text.endswith("): 503")
    record(tmp_path, ok=False)
    [alert] = backup_alerts(tmp_path, site.spec, offsite_set_up=True, wording=site.wording)
    assert alert == Alert("error", site.wording.offsite_failed.format(when="", error=""))


@each_site
def test_only_this_sites_backups_count_and_the_newest_is_by_name(site, tmp_path):
    for other in SITES:
        if other is not site:
            archive(tmp_path, other, "2026-11-06")
    assert alerts(tmp_path, site, set_up=True) == [Alert("warning", site.wording.no_backups)]
    aged(archive(tmp_path, site, "2026-11-05"), NOW - timedelta(days=5))
    aged(archive(tmp_path, site, "2026-11-01"), NOW - timedelta(hours=1))  # an older one, touched since
    assert alerts(tmp_path, site, set_up=False)[0].text == site.wording.backup_stale.format(
        name=site.archive_name(datetime(2026, 11, 5, tzinfo=UTC)))


@each_site
def test_stale_is_over_fifty_hours_unless_the_site_says_otherwise(site, tmp_path):
    out = aged(archive(tmp_path, site, "2026-11-04"), NOW - timedelta(hours=50))
    record(tmp_path, ok=True, when=(NOW - timedelta(hours=50)).isoformat())
    assert alerts(tmp_path, site, set_up=True) == []
    assert [a.level for a in alerts(tmp_path, site, set_up=True, now=NOW + timedelta(seconds=1))] == ["error", "error"]
    assert [a.level for a in alerts(tmp_path, site, set_up=True, stale_hours=26)] == ["error", "error"]
    aged(out, NOW)
    assert [a.text for a in alerts(tmp_path, site, set_up=True, stale_hours=26)] == [
        site.wording.offsite_stale.format(day="2026-11-04")]


@each_site
def test_a_real_backup_and_copy_raise_no_alert_until_they_are_old(site, tmp_path):
    """The three functions together, as a site's nightly command and its daily check use them."""
    db, folder = state_database(tmp_path / "data" / site.state_file, site.spec), tmp_path / "backups"
    store = MemoryStore()
    clock = FixedClock("2026-11-04T04:20:00+00:00")
    out = make_backup(db, folder, site.spec, clock=clock)
    aged(out, clock.now())
    assert send_offsite(out, store, site.spec, clock=clock)["stored"] == 1
    assert backup_alerts(folder, site.spec, offsite_set_up=True, wording=site.wording, clock=clock) == []
    clock.advance(days=3)
    assert [a.level for a in backup_alerts(folder, site.spec, offsite_set_up=True, wording=site.wording,
                                           clock=clock)] == ["error", "error"]
    # a very old backup is an error whatever else is so (Where Countries Stand's update then needs attention)
    aged(out, datetime(1970, 1, 1, tzinfo=UTC))
    assert backup_alerts(folder, site.spec, offsite_set_up=False, wording=site.wording, clock=clock)[0].level == "error"


# ---- the same as each site's own code ----------------------------------------------------------------------------


@sites_where(alerts=True)
def test_the_alerts_are_the_sites_own_word_for_word(site, tmp_path, request):
    """Every condition in the study's table, and each pair of them that can be true together."""
    own = own_code(site, request)
    folder = tmp_path / "backups"

    def same(*expected_levels: str) -> None:
        for set_up in (False, True):
            theirs = own.offsite.backup_alerts(folder, site.env() if set_up else {}, NOW)
            ours = alerts(folder, site, set_up=set_up)
            assert [dataclasses.asdict(a) for a in ours] == theirs, (set_up, theirs)
        assert tuple(a["level"] for a in theirs) == expected_levels, theirs

    same()  # the folder does not exist
    folder.mkdir()
    same("warning")  # no backups yet
    record(folder, ok=False, when="2026-11-06T03:00:00+00:00", error="Backblaze did not accept the key")
    same("warning", "error")  # none yet, and a copy that failed
    (folder / "offsite.json").unlink()
    out = aged(archive(folder, site, "2026-11-01"), NOW - timedelta(days=3))
    same("error", "warning")  # a backup over two days old, and no off-site copy made yet
    aged(out, NOW - timedelta(hours=3))
    same("warning")  # no off-site copy made yet
    (folder / "offsite.json").write_text("not json")
    same("warning")
    record(folder, ok=False, when="2026-11-06T03:00:00+00:00", error="Backblaze did not accept the key")
    same("error")  # the last copy failed
    for when in (None, 1731400000):
        record(folder, ok=False, when=when, error="503")
        same("error")
    record(folder, ok=False)
    same("error")
    record(folder, ok=True, when="2026-11-02T03:00:00+00:00")
    same("error")  # the last copy is over two days old
    aged(out, NOW - timedelta(days=3))
    same("error", "error")  # and so is the last backup
    record(folder, ok=True, when="2026-11-06T03:00:00+00:00")
    aged(out, NOW - timedelta(hours=3))
    same()  # all is well
    for other in SITES:  # another site's archives in the folder change nothing
        if other is not site:
            aged(archive(folder, other, "2026-10-01"), NOW - timedelta(days=30))
    same()


@sites_where(alerts=True)
def test_a_record_the_sites_own_code_cannot_read_stops_the_package_the_same_way(site, tmp_path, request):
    """A copy recorded as made, with no time or a time without a zone, is an exception in each site's code: the daily
    check then fails loudly, which is what should happen to a record nothing here ever writes."""
    own = own_code(site, request)
    archive(tmp_path, site, "2026-11-06")
    for said, error in (({"ok": True}, KeyError), ({"ok": True, "when": "2026-11-06T03:00:00"}, TypeError)):
        record(tmp_path, **said)
        with pytest.raises(error):
            own.offsite.backup_alerts(tmp_path, site.env(), NOW)
        with pytest.raises(error):
            alerts(tmp_path, site, set_up=True)
