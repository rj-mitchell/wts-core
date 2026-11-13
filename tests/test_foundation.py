"""Settings, the state database and the small values in ``ports``."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from wts_core.ports import Usage
from wts_core.settings import EnvSetting, Settings, SettingsError, Site, load_settings, require, save_local_settings
from wts_core.state import Import, Migration, StateDB
from wts_core.testing import FixedClock


@dataclass(frozen=True)
class MySettings(Settings):
    @property
    def start_year(self) -> int:
        return int(self.section("archive").get("start_year", 1997))


def make_site(root: Path, **kw) -> Site:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "settings.toml").write_text(
        '[paths]\ndata_dir = "data"\n[archive]\nstart_year = 2018\n[usage]\ndaily_spend_cap_usd = 3.0\n'
        '[usage.models."claude-haiku-5-5"]\nprice_input_per_mtok = 0.1\n')
    return Site(name="Where Examples Stand", package="examples", env_prefix="EX", root=root, **kw)


def test_settings_layer_the_file_the_local_file_and_overrides(tmp_path):
    site = make_site(tmp_path)
    s = load_settings(MySettings, site, env={})
    assert s.start_year == 2018 and s.data_dir == tmp_path / "data" and s.state_db == tmp_path / "data" / "state.db"
    assert s.config_path == tmp_path / "config" / "settings.toml"

    written = save_local_settings(s.data_dir, {"archive": {"start_year": 2020}, "embedding": {"enabled": False}},
                                  written_by="examples bootstrap")
    assert written.read_text().splitlines()[0] == \
        "# Per-installation settings written by `examples bootstrap`; they override config/settings.toml."
    s = load_settings(MySettings, site, env={})
    assert s.start_year == 2020 and s.section("embedding") == {"enabled": False}
    assert s.usage["daily_spend_cap_usd"] == 3.0  # a section the local file does not mention is untouched

    s = load_settings(MySettings, site, env={}, **{"archive.start_year": 1946})
    assert s.start_year == 1946 and s.overrides == {"archive.start_year": 1946}


def test_the_local_file_is_merged_one_level_deep(tmp_path):
    """As the sites' loaders do today: a table inside a section in the local file replaces the whole table."""
    site = make_site(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "settings.local.toml").write_text('[usage.models."other"]\nprice_input_per_mtok = 9\n')
    s = load_settings(MySettings, site, env={})
    assert list(s.usage["models"]) == ["other"] and s.usage["daily_spend_cap_usd"] == 3.0


def test_the_environment_names_the_config_file_the_data_folder_and_a_sites_own_settings(tmp_path):
    site = make_site(tmp_path, env_settings=(EnvSetting("SITE_URL", "site", "url"),
                                             EnvSetting("LAUNCHED", "site", "launched", "flag")))
    other = tmp_path / "elsewhere.toml"
    other.write_text("[archive]\nstart_year = 1\n")
    s = load_settings(MySettings, site, env={"EX_CONFIG": str(other), "EX_DATA_DIR": str(tmp_path / "d"),
                                             "EX_SITE_URL": " https://example.org ", "EX_LAUNCHED": "Yes"})
    assert s.start_year == 1 and s.data_dir == tmp_path / "d"
    assert s.section("site") == {"url": "https://example.org", "launched": True}
    s = load_settings(MySettings, site, env={"EX_CONFIG": "", "EX_LAUNCHED": "0"})  # empty counts as unset
    assert s.start_year == 2018 and s.section("site") == {"launched": False}


def test_a_missing_setting_stops_the_site_by_name(tmp_path):
    s = load_settings(MySettings, make_site(tmp_path), env={})
    assert require(s, "usage", ["daily_spend_cap_usd"])["daily_spend_cap_usd"] == 3.0
    with pytest.raises(SettingsError, match=r"\[usage\] needs monthly_spend_cap_usd, per_visitor_daily_questions"):
        require(s, "usage", ["daily_spend_cap_usd", "monthly_spend_cap_usd", "per_visitor_daily_questions"])


def test_usage_reads_both_of_todays_forms_and_stores_the_sites_own():
    ours = {"input_tokens": 1200, "output_tokens": 300, "cache_read_tokens": 50, "cache_write_tokens": 200}
    sdk = {"input_tokens": 1000, "output_tokens": 300, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 200}
    assert Usage.from_mapping(ours) == Usage.from_mapping(sdk) == Usage(1000, 200, 50, 300)
    assert Usage.from_mapping(sdk).as_stored() == ours
    assert Usage.from_mapping(None) == Usage() and Usage.from_mapping({"input_tokens": None}) == Usage()
    # the site's own name for cache reads wins when present, even at 0
    assert Usage.from_mapping({"cache_read_tokens": 0, "cache_read_input_tokens": 9}).cache_read == 0
    assert Usage(1, 2, 3, 4) + Usage(10, 20, 30, 40) == Usage(11, 22, 33, 44)


def test_the_state_database_keeps_keys_and_runs_each_migration_once(tmp_path):
    clock = FixedClock()
    extra = Migration(10, "things", ("CREATE TABLE wts_things (id INTEGER PRIMARY KEY, name TEXT)",))
    db = StateDB(tmp_path / "data" / "state.db", migrations=[extra], clock=clock)
    assert {"wts_kv", "wts_schema", "wts_things"} <= db.tables()
    assert db.get("a") is None
    db.set("a", "1")
    db.set("a", "2")
    db.set_if_absent("a", "3")
    db.set_if_absent("salt:2026-11-13", "x")
    db.set_if_absent("salt:2026-11-12", "old")
    db.delete_like("salt:%", keep="salt:2026-11-13")
    assert (db.get("a"), db.get("salt:2026-11-13"), db.get("salt:2026-11-12")) == ("2", "x", None)
    StateDB(db.path, migrations=[extra], clock=clock)  # again: "CREATE TABLE" without IF NOT EXISTS would fail
    with pytest.raises(ValueError):
        StateDB(db.path, migrations=[extra, Migration(10, "clash", ())])


def test_a_state_database_is_marked_as_its_sites_and_another_sites_is_refused_untouched(tmp_path):
    path = tmp_path / "state.db"
    db = StateDB(path, site="councils")
    assert db.get("site") == "councils"
    assert StateDB(path, site="councils").get("site") == "councils"  # opened again by the same site: as it was
    before = path.read_bytes()
    more = (Migration(10, "more", ("CREATE TABLE wts_more (x)",)),)
    with pytest.raises(RuntimeError) as refused:
        StateDB(path, migrations=more, site="wcs")
    said = str(refused.value)
    assert said.startswith(f"{path} is the state database of another site: it is marked 'councils', and this site "
                           "is 'wcs'.")
    assert path.read_bytes() == before and "wts_more" not in db.tables()  # nothing in it was made or changed
    assert db.get("site") == "councils"  # and the mark is never written over


def test_a_database_from_before_the_mark_is_marked_the_first_time_its_site_opens_it(tmp_path):
    path = tmp_path / "state.db"
    unmarked = StateDB(path)  # as every state database was before, and as one is with no site given
    unmarked.set("visitor_salt:2026-11-13", "5a" * 16)
    assert unmarked.get("site") is None
    assert StateDB(path).get("site") is None  # no site given: none written
    assert StateDB(path, site="hansard").get("site") == "hansard"
    assert StateDB(path).get("visitor_salt:2026-11-13") == "5a" * 16
    with pytest.raises(RuntimeError, match="marked 'hansard', and this site is 'councils'"):
        StateDB(path, site="councils")


def test_a_failed_operation_changes_nothing(tmp_path):
    db = StateDB(tmp_path / "state.db")
    with pytest.raises(sqlite3.OperationalError), db.connect() as con:
        con.execute("INSERT INTO wts_kv (key, value) VALUES ('k', 'v')")
        con.execute("INSERT INTO no_such_table VALUES (1)")
    assert db.get("k") is None


def test_a_sites_rows_are_imported_once_and_its_old_tables_left_alone(tmp_path):
    path = tmp_path / "state.db"
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT); INSERT INTO kv VALUES ('visitor_salt:x', 's');")
    old.close()
    before = sqlite3.connect(path).execute("SELECT * FROM kv").fetchall()
    bring = Import("kv", ("INSERT OR IGNORE INTO wts_kv (key, value) SELECT key, value FROM kv",), needs=("kv",))
    later = Import("reports", ("INSERT INTO wts_kv (key, value) SELECT 'n', count(*) FROM reports",), needs=("reports",))
    clock = FixedClock("2026-12-01T03:00:00+00:00")
    db = StateDB(path, imports=[bring, later], clock=clock)
    assert db.get("visitor_salt:x") == "s" and db.get("n") is None  # "reports" isn't there: that import waits
    copy = tmp_path / "state.pre-wts-core.2026-12-01.db"
    assert copy.exists() and sqlite3.connect(copy).execute("SELECT * FROM kv").fetchall() == before

    sqlite3.connect(path).executescript("DELETE FROM wts_kv; ")
    db = StateDB(path, imports=[bring, later], clock=clock)
    assert db.get("visitor_salt:x") is None  # not run a second time
    assert sqlite3.connect(path).execute("SELECT * FROM kv").fetchall() == before


def test_a_copy_made_before_an_import_does_not_outlive_the_sites_backups(tmp_path):
    """The copy is the whole database as it was, the day's visitor secret included, which the site deletes the
    next day. So it is kept only as long as a backup is."""
    from wts_core.state import Import, StateDB
    from wts_core.testing import FixedClock

    clock = FixedClock("2026-11-13T12:00:00+00:00")
    path = tmp_path / "state.db"
    StateDB(path, clock=clock).set("old", "row")
    db = StateDB(path, imports=[Import("first", ("INSERT INTO wts_kv (key, value) VALUES ('new', 'row')",))],
                 clock=clock)
    copy = tmp_path / "state.pre-wts-core.2026-11-13.db"
    assert copy.exists()
    (tmp_path / "state.pre-wts-core.notes.db").write_text("not one of ours")
    clock.advance(days=14)
    assert db.forget_old_copies(14) == [] and copy.exists()  # fourteen days old: kept
    clock.advance(days=1)
    assert db.forget_old_copies(14) == [copy] and not copy.exists()
    assert (tmp_path / "state.pre-wts-core.notes.db").exists() and path.exists()  # nothing else is touched


def test_a_migration_or_import_that_fails_part_way_leaves_nothing_behind(tmp_path):
    """Found in review: Python's sqlite3 opens a transaction only before the first INSERT, so a statement that
    makes or alters a table was kept even when the next statement failed, and every later start then failed on
    "duplicate column name"."""
    import sqlite3

    import pytest

    from wts_core.state import Import, Migration, StateDB

    path = tmp_path / "state.db"
    StateDB(path, migrations=[Migration(90, "things", ("CREATE TABLE wts_things (id INTEGER)",))])
    broken = Migration(91, "more", ("ALTER TABLE wts_things ADD COLUMN name TEXT", "INSERT INTO no_such VALUES (1)"))
    first = Migration(90, "things", ("CREATE TABLE wts_things (id INTEGER)",))
    for _ in range(2):  # the second start fails for the same reason as the first, not for a new one
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            StateDB(path, migrations=[first, broken])
    mended = Migration(91, "more", ("ALTER TABLE wts_things ADD COLUMN name TEXT",))
    db = StateDB(path, migrations=[first, mended])
    with db.connect() as con:
        assert [r[1] for r in con.execute("PRAGMA table_info(wts_things)")] == ["id", "name"]
    bad = Import("bring", ("CREATE TABLE wts_brought (id INTEGER)", "INSERT INTO no_such VALUES (1)"))
    with pytest.raises(sqlite3.OperationalError):
        StateDB(path, migrations=[first, mended], imports=[bad])
    assert "wts_brought" not in db.tables()


def test_processes_that_start_together_take_turns(tmp_path):
    """Found in review: several processes opening a new file at once each tried to record the same migration, and
    all but one died. A web server with several workers, or the site and its nightly update, start like that."""
    import threading

    from wts_core.state import Import, Migration, StateDB

    path = tmp_path / "state.db"
    StateDB(path).set("old", "1")
    migrations = [Migration(90, "things", ("CREATE TABLE wts_things (id INTEGER)",))]
    imports = [Import("bring", ("INSERT INTO wts_things (id) VALUES (1)",))]
    errors: list[BaseException] = []
    go = threading.Barrier(8)

    def start() -> None:
        try:
            go.wait()
            StateDB(path, migrations=migrations, imports=imports)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with StateDB(path, migrations=migrations, imports=imports).connect() as con:
        assert con.execute("SELECT count(*) FROM wts_things").fetchone()[0] == 1  # the import ran once
