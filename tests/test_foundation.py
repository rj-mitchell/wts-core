"""Settings, the state database and the small values in ``ports``."""

from __future__ import annotations

import dataclasses
import sqlite3
from dataclasses import dataclass
from datetime import date
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


def test_the_local_file_is_merged_two_levels_deep(tmp_path):
    """A table inside a section in the local file is merged into the site's, key by key. The sites' own loaders
    merged one level deep, so this table replaced the whole of the site's (the tests further down say what that
    cost, and that nothing else is read differently)."""
    site = make_site(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "settings.local.toml").write_text('[usage.models."other"]\nprice_input_per_mtok = 9\n')
    s = load_settings(MySettings, site, env={})
    assert list(s.usage["models"]) == ["claude-haiku-5-5", "other"] and s.usage["daily_spend_cap_usd"] == 3.0


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


def test_a_section_an_environment_setting_may_fill_is_there_even_when_nothing_fills_it(tmp_path):
    """Each site's own loader always made the section (Where Landlords Stand's ``[site]``), so an accessor that
    reads ``raw["site"]`` found a table. The settings file here has no ``[site]`` at all."""
    site = make_site(tmp_path, env_settings=(EnvSetting("SITE_URL", "site", "url"),
                                             EnvSetting("LAUNCHED", "site", "launched", "flag")))
    s = load_settings(MySettings, site, env={})
    assert s.raw["site"] == {} and s.section("site") == {} and "site" in s.raw
    assert s.raw["usage"] == load_settings(MySettings, make_site(tmp_path), env={}).raw["usage"]  # nothing else moved
    assert "site" not in load_settings(MySettings, make_site(tmp_path), env={}).raw  # no setting, no section


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


def test_fixed_chance_gives_ids_of_the_real_shape_in_a_fixed_order():
    import re
    import secrets

    from wts_core.testing import FixedRandom

    chance = FixedRandom()
    assert [chance.token(8), chance.token(8), chance.token(8)] == ["token000001", "token000002", "token000003"]
    for nbytes in (1, 2, 3, 4, 6, 8, 9, 16, 32):  # as long as a real one for the bytes asked, and URL-safe
        made = FixedRandom().token(nbytes)
        assert len(made) == len(secrets.token_urlsafe(nbytes)), nbytes
        assert re.fullmatch(r"[A-Za-z0-9_-]+", made) and made.endswith("1")
    mixed = FixedRandom()  # one sequence, whatever is asked for in between
    assert [mixed.token(8), mixed.token(16), mixed.token(3), mixed.token_hex(4)] == [
        "token000001", "token00000000000000002", "0003", "00000004"]
    given = FixedRandom(tokens=["first"])  # tokens a test gives are handed out first, exactly as given
    assert [given.token(8), given.token(8)] == ["first", "token000001"]


def test_events_are_one_plain_type_wherever_they_are_passed():
    """A site's pipeline makes them, the desk passes them on, the harness reads them: with one type for all of
    it, a site needs no cast (its own mypy run is the proof: the example site's has none)."""
    from collections.abc import Iterator
    from typing import Any, get_type_hints

    from wts_core import briefing, events
    from wts_core.checks import curl_event
    from wts_core.eval import EvalSite

    assert briefing.Event is events.Event and events.Event.__value__ == dict[str, Any]
    assert get_type_hints(events.to_reader)["return"] is events.Event
    assert get_type_hints(EvalSite.ask)["return"] == Iterator[events.Event]
    assert get_type_hints(curl_event)["return"] is events.Event
    assert events.to_reader(events.TextDelta("word")) == {"type": "text", "text": "word"}


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


@pytest.mark.parametrize("has_kind", [True, False])
def test_an_imports_statement_may_be_built_when_it_runs_from_what_the_old_table_has(tmp_path, has_kind):
    """Where Landlords Stand's ``reports`` gained its ``kind`` column late: a backup from before has none, and one
    fixed statement that names the column fails on it."""
    from wts_core.state import columns

    path = tmp_path / "state.db"
    old = sqlite3.connect(path)
    old.execute(f"CREATE TABLE reports (id INTEGER PRIMARY KEY, message TEXT{', kind TEXT' if has_kind else ''})")
    old.execute("INSERT INTO reports (message) VALUES ('The grade is out of date.')")
    if has_kind:
        old.execute("UPDATE reports SET kind = 'wrong'")
    old.commit()
    old.close()
    seen: list[set[str]] = []

    def bring(con: sqlite3.Connection) -> list[str]:
        have = columns(con, "reports")
        seen.append(have)
        kind = "kind" if "kind" in have else "NULL"
        return [f"INSERT INTO wts_kv (key, value) SELECT 'report:' || id, coalesce({kind}, 'no kind') FROM reports"]

    made = (Migration(10, "more", ("CREATE TABLE wts_more (x)",)),)
    reports = Import("reports", ("INSERT INTO wts_more VALUES (1)", bring), needs=("reports",))
    db = StateDB(path, migrations=made, imports=[reports])
    assert db.get("report:1") == ("wrong" if has_kind else "no kind")
    assert seen == [{"id", "message", "kind"} if has_kind else {"id", "message"}]
    assert columns(sqlite3.connect(path), "no_such_table") == set()
    StateDB(path, migrations=made, imports=[reports])  # run once: the function is not asked again
    assert len(seen) == 1
    with db.connect() as con:
        assert con.execute("SELECT count(*) FROM wts_more").fetchone()[0] == 1


def test_a_statement_built_at_run_time_that_fails_undoes_the_whole_import(tmp_path):
    path = tmp_path / "state.db"
    sqlite3.connect(path).executescript("CREATE TABLE reports (id INTEGER PRIMARY KEY);")

    def broken(con: sqlite3.Connection) -> list[str]:
        raise RuntimeError("the old table is not as expected")

    half = Import("reports", ("INSERT INTO wts_kv (key, value) VALUES ('half', 'done')", broken), needs=("reports",))
    with pytest.raises(RuntimeError, match="not as expected"):
        StateDB(path, imports=[half])
    assert StateDB(path).get("half") is None  # nothing of it was kept, and it will be tried again


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
    with pytest.raises(sqlite3.OperationalError, match="the import 'bring' failed at statement 2"):
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


# An import that is skipped says so (0.2.1)

def _old_database(path: Path, *tables: str) -> None:
    con = sqlite3.connect(path)
    for table in tables:
        con.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, at TEXT, value TEXT)")
    con.commit()
    con.close()


def test_an_import_skipped_for_a_table_an_older_backup_lacks_says_so_at_every_start(tmp_path, caplog):
    """Found in review: an import whose ``needs`` named a table missing from an older backup was skipped silently
    and for ever, so a restored site showed no spending and no saved briefings."""
    path = tmp_path / "state.db"
    _old_database(path, "usage", "briefings")  # a backup from before the site had a table of failures
    bring = Import("site-state", ("INSERT INTO wts_kv (key, value) SELECT 'usage', count(*) FROM usage",),
                   needs=("usage", "briefings", "failures", "answer_cache"))
    for _ in range(2):  # the second start says it again: it is not a thing to be told once
        caplog.clear()
        with caplog.at_level("WARNING", logger="wts_core.state"):
            db = StateDB(path, imports=[bring])
        assert db.get("usage") is None  # skipped, as before
        [warning] = [r for r in caplog.records if r.name == "wts_core.state"]
        said = warning.getMessage()
        assert warning.levelname == "WARNING" and "'site-state' was skipped" in said
        assert "needs the tables answer_cache, failures" in said and "(it has briefings, usage)" in said
    assert not list(tmp_path.glob("*.pre-wts-core.*"))  # nothing ran, so no copy was made


def test_an_import_that_waits_for_tables_a_new_database_never_had_says_nothing(tmp_path, caplog):
    """A new site, or a new install of an adopted one, has none of the old tables: there is nothing to bring
    across, and nothing to warn of. Nor is anything said once an import has run."""
    waits = Import("old-state", ("INSERT INTO wts_kv (key, value) SELECT 'n', count(*) FROM usage",),
                   needs=("usage", "briefings"))
    with caplog.at_level("WARNING", logger="wts_core.state"):
        StateDB(tmp_path / "new.db", imports=[waits])
        path = tmp_path / "state.db"
        _old_database(path, "usage", "briefings")
        assert StateDB(path, imports=[waits]).get("n") == "0"
        sqlite3.connect(path).executescript("DROP TABLE briefings;")
        StateDB(path, imports=[waits])  # run already: the missing table is of no account now
    assert [r for r in caplog.records if r.name == "wts_core.state"] == []


def test_a_statement_for_a_table_that_may_be_missing_is_a_function_that_returns_nothing(tmp_path, caplog):
    """The remedy the warning names: ``needs`` holds only what every backup has, and the rest look first."""
    from wts_core.state import columns

    def failures(con: sqlite3.Connection) -> list[str]:
        if not columns(con, "failures"):
            return []
        return ["INSERT INTO wts_kv (key, value) SELECT 'failures', count(*) FROM failures"]

    bring = Import("site-state", ("INSERT INTO wts_kv (key, value) SELECT 'usage', count(*) FROM usage", failures),
                   needs=("usage",))
    older, newer = tmp_path / "older.db", tmp_path / "newer.db"
    _old_database(older, "usage")
    _old_database(newer, "usage", "failures")
    with caplog.at_level("WARNING", logger="wts_core.state"):
        assert (StateDB(older, imports=[bring]).get("usage"), StateDB(older).get("failures")) == ("0", None)
        assert StateDB(newer, imports=[bring]).get("failures") == "0"
    assert caplog.records == []


# A site's old tables, after its imports (0.2.1)

def _adopted(tmp_path: Path, clock: FixedClock, **more):
    """A site the day after it adopted the package: its old tables hold what they held, and the package's own
    have moved on (an address deleted, a contact deleted, the secret of a new day)."""
    from datetime import date

    from wts_core.state import OldTables

    path = tmp_path / "state.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE statements (id INTEGER PRIMARY KEY, email TEXT, status TEXT);
        INSERT INTO statements VALUES (1, 'ended@example.org', 'declined'), (2, 'waiting@example.org', 'pending');
        CREATE TABLE reports (id INTEGER PRIMARY KEY, contact TEXT);
        INSERT INTO reports VALUES (1, 'closed@example.org'), (2, 'open@example.org');
        CREATE TABLE failures (id INTEGER PRIMARY KEY, at TEXT, question TEXT);
        INSERT INTO failures VALUES (1, '2026-08-01T09:00:00+00:00', 'An old question that failed?'),
                                    (2, '2026-11-10T09:00:00+00:00', 'A recent question that failed?');
        CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO kv VALUES ('visitor_salt:2026-11-13', 'the adoption day''s secret'),
                              ('visitor_salt:2026-11-14', 'today''s'), ('other', 'kept');
    """)
    con.close()
    made = (Migration(90, "replies", (
        "CREATE TABLE wts_statements (id INTEGER PRIMARY KEY, email TEXT)",
        "CREATE TABLE wts_reports (id INTEGER PRIMARY KEY, contact TEXT)")),)
    bring = Import("site-state", (
        "INSERT INTO wts_statements (id, email) SELECT id, email FROM statements",
        "INSERT INTO wts_reports (id, contact) SELECT id, contact FROM reports"), needs=("statements", "reports"))
    old = OldTables(
        tables=("statements", "reports", "failures", "kv", "gone_long_ago"), drop_on=date(2026, 11, 27),
        nightly=(
            "UPDATE statements SET email = NULL WHERE email IS NOT NULL AND id IN "
            "(SELECT id FROM wts_statements WHERE email IS NULL)",
            "UPDATE reports SET contact = NULL WHERE contact IS NOT NULL AND id IN "
            "(SELECT id FROM wts_reports WHERE contact IS NULL)",
            "DELETE FROM failures WHERE substr(at, 1, 10) < date(:today, '-90 days')",
            "DELETE FROM kv WHERE key LIKE 'visitor_salt:%' AND key != 'visitor_salt:' || :today",
            "DELETE FROM answer_cache_of_old WHERE at < :now",  # a table this database never had: passed over
        ))
    db = StateDB(path, migrations=made, imports=more.pop("imports", [bring]), clock=clock, old_tables=old, **more)
    with db.connect() as con:  # what the package has since deleted from its own tables
        con.execute("UPDATE wts_statements SET email = NULL WHERE id = 1")
        con.execute("UPDATE wts_reports SET contact = NULL WHERE id = 1")
    return db


def _all(db: StateDB, sql: str) -> list[tuple]:
    with db.connect() as con:
        return [tuple(r) for r in con.execute(sql)]


def test_a_sites_old_tables_are_kept_within_its_promises_each_night_until_they_are_dropped(tmp_path):
    """Found in review: after the import a site's old tables stayed in the live file, still holding senders'
    addresses the package had since deleted from its own tables, reports' contacts, failed questions past their
    90 days, and the adoption day's visitor secret. "Nothing is kept longer than before" did not hold."""
    from wts_core.state import Retired

    clock = FixedClock("2026-11-14T03:00:00+00:00")
    db = _adopted(tmp_path, clock)
    held = ("statements", "reports", "failures", "kv")
    assert db.retire_old() == Retired(changed=4, dropped=(), left=held, waiting_for=())
    assert _all(db, "SELECT id, email FROM statements") == [(1, None), (2, "waiting@example.org")]
    assert _all(db, "SELECT id, contact FROM reports") == [(1, None), (2, "open@example.org")]
    assert _all(db, "SELECT id FROM failures") == [(2,)]
    assert _all(db, "SELECT key FROM kv ORDER BY key") == [("other",), ("visitor_salt:2026-11-14",)]
    assert _all(db, "SELECT id, email FROM wts_statements") == [(1, None), (2, "waiting@example.org")]  # untouched
    assert db.retire_old() == Retired(changed=0, left=held)  # every night: nothing more to do

    clock.set("2026-11-26T03:00:00+00:00")  # the day before the stated day: still there
    assert db.retire_old() == Retired(changed=1, left=held)  # the 14th's secret, now a day that is not today
    assert {"statements", "kv"} <= db.tables()
    clock.set("2026-11-27T03:00:00+00:00")
    dropped = db.retire_old()
    assert dropped == Retired(changed=0, dropped=held, left=())
    assert dropped.compacted is True and dropped.due == date(2026, 11, 27)  # and the file written out afresh
    assert db.tables() & set(held) == set() and {"wts_statements", "wts_reports", "wts_kv"} <= db.tables()
    assert db.retire_old() == Retired()  # and every night after: nothing to do, and nothing goes wrong


def test_old_tables_are_not_dropped_while_an_import_has_still_to_run(tmp_path):
    """Their rows may be nowhere else. The owner is told instead, by whoever calls."""
    clock = FixedClock("2026-12-01T03:00:00+00:00")
    never = Import("spending", ("INSERT INTO wts_kv (key, value) SELECT 'n', count(*) FROM usage",),
                   needs=("usage", "statements"))
    db = _adopted(tmp_path, clock, imports=[never])
    retired = db.retire_old()
    assert retired.dropped == () and retired.waiting_for == ("spending",)
    assert retired.left == ("statements", "reports", "failures", "kv") and "statements" in db.tables()


def test_a_fault_in_what_a_site_declared_for_its_old_tables_changes_nothing(tmp_path):
    from datetime import date

    from wts_core.state import OldTables, Retired

    clock = FixedClock("2026-12-01T03:00:00+00:00")
    db = _adopted(tmp_path, clock)
    broken = StateDB(db.path, clock=clock, old_tables=OldTables(
        tables=("statements",), drop_on=date(2026, 11, 27),
        nightly=("UPDATE statements SET email = NULL", "UPDATE statements SET no_such_column = 1")))
    with pytest.raises(sqlite3.OperationalError, match="no such column"):
        broken.retire_old()
    assert _all(db, "SELECT email FROM statements WHERE id = 2") == [("waiting@example.org",)]  # all or nothing
    assert StateDB(db.path, clock=clock).retire_old() == Retired()  # a site that declared nothing: nothing done
    assert "statements" in db.tables()


def test_only_a_sites_own_old_tables_can_be_retired(tmp_path):
    from datetime import date

    from wts_core.state import OldTables

    for wrong in (("wts_statements",), ("usage", "WTS_kv"), ("sqlite_master",), ("usage; DROP TABLE wts_kv",),
                  ("",), "usage"):
        with pytest.raises(ValueError, match="OldTables"):
            OldTables(tables=wrong, drop_on=date(2026, 12, 1))  # type: ignore[arg-type]

    def by_function(con: sqlite3.Connection) -> list[str]:
        return ["DELETE FROM failures WHERE id = 1"]

    clock = FixedClock("2026-11-14T03:00:00+00:00")
    db = _adopted(tmp_path, clock)
    db.old_tables = OldTables(tables=("failures",), drop_on=date(2027, 1, 1), nightly=(by_function,))
    assert db.retire_old().changed == 1 and _all(db, "SELECT id FROM failures") == [(2,)]


# The installation's own settings, laid over the site's (0.2.1)

PRICED = ('[paths]\ndata_dir = "data"\n[answer]\nmodel = "model-a"\nquery_parse_model = "model-b"\n'
          "[usage]\nprice_input_per_mtok = 3.0\nprice_output_per_mtok = 15.0\nprice_cache_read_per_mtok = 0.3\n"
          'cache_write_multiplier = 1.25\n[usage.models."model-a"]\nprice_output_per_mtok = 15.0\n'
          '[usage.models."model-b"]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 5.0\n')


def priced_site(root: Path, local: str | None = None) -> Site:
    (root / "config").mkdir(parents=True)
    (root / "config" / "settings.toml").write_text(PRICED)
    if local is not None:
        (root / "data").mkdir()
        (root / "data" / "settings.local.toml").write_text(local)
    return Site(name="Where Examples Stand", package="examples", env_prefix="EX", root=root)


def test_a_server_prices_one_model_in_its_own_settings_without_repeating_the_rest(tmp_path):
    """Found in review, and reproduced: a server's ``[usage.models."claude-opus-5-5"]`` replaced the site's whole
    table of models' prices (the local file was laid over one level deep), and a site that asks for strict prices
    then refused to start, naming every other model. A table inside a section is now merged key by key."""
    from wts_core.usage import PriceTable

    site = priced_site(tmp_path, '[answer]\nmodel = "model-dear"\n[usage]\ndaily_spend_cap_usd = 9.0\n'
                                 '[usage.models."model-dear"]\nprice_output_per_mtok = 75.0\n'
                                 '[usage.models."model-b"]\nprice_output_per_mtok = 6.0\n')
    local = load_settings(MySettings, site)
    assert local.answer == {"model": "model-dear", "query_parse_model": "model-b"}
    assert local.usage["daily_spend_cap_usd"] == 9.0 and local.usage["price_input_per_mtok"] == 3.0
    assert local.usage["models"] == {"model-a": {"price_output_per_mtok": 15.0},  # the site's, still there
                                     "model-dear": {"price_output_per_mtok": 75.0},  # the server's, added
                                     "model-b": {"price_output_per_mtok": 6.0}}  # one model's table: given whole
    prices = PriceTable.from_settings(local.usage, file=local.files)
    prices.require((local.answer["model"], local.answer["query_parse_model"]), base_counts=False)  # it starts
    assert (prices.price_for("model-dear").output, prices.price_for("model-b").input) == (75.0, 3.0)
    assert local.local_path == tmp_path / "data" / "settings.local.toml"


def test_anything_but_a_table_inside_a_section_replaces_what_was_there_as_before(tmp_path):
    site = priced_site(tmp_path, '[usage]\nmodels = "none"\n[answer]\nmodel = { name = "x" }\n'
                                 '[alerts]\nerror_rate = 0.05\n[alerts.more]\na = 1\n')
    local = load_settings(MySettings, site)
    assert local.usage["models"] == "none"  # a plain value over a table
    assert local.answer["model"] == {"name": "x"}  # a table over a plain value
    assert local.section("alerts") == {"error_rate": 0.05, "more": {"a": 1}}  # a section the site's file has not


def test_an_error_about_the_settings_names_the_installations_file_too_when_one_was_read(tmp_path):
    """The fault may be in either file. Before 0.2.1 only ``config/settings.toml`` was named, for a table that was
    wrong in the server's own."""
    from wts_core.briefing import desk_settings
    from wts_core.settings import Messages
    from wts_core.usage import Limits, PriceTable

    alone = load_settings(MySettings, priced_site(tmp_path / "a"))
    assert alone.local_path is None and alone.files == str(tmp_path / "a" / "config" / "settings.toml")
    site = priced_site(tmp_path / "b", '[usage.models."model-dear"]\nprice_output_per_mtok = "lots"\n')
    local = load_settings(MySettings, site)
    both = (f"{tmp_path / 'b' / 'config' / 'settings.toml'} (with {tmp_path / 'b' / 'data' / 'settings.local.toml'} "
            "laid over it)")
    assert local.files == both
    with pytest.raises(SettingsError) as stopped:
        require(local, "usage", ["no_such_key"])
    assert str(stopped.value) == f"{both}: [usage] needs no_such_key"
    with pytest.raises(SettingsError) as stopped:
        PriceTable.from_settings(local.usage, file=local.files)
    assert str(stopped.value).startswith(f"{both}: [usage.models.\"model-dear\"] price_output_per_mtok must be")
    with pytest.raises(SettingsError) as stopped:
        Limits.from_settings(local.usage, file=local.files)
    assert str(stopped.value).startswith(f"{both}: [usage] needs per_visitor_daily_questions")
    # given the settings themselves (0.3.0), both name the files with nothing more to pass
    for read in (PriceTable.from_settings, Limits.from_settings):
        with pytest.raises(SettingsError) as stopped:
            read(local)
        assert str(stopped.value).startswith(f"{both}: [usage")
    assert PriceTable.from_settings(alone) == PriceTable.from_settings(alone.usage)
    words = Messages(**{f.name: "{reason} words" for f in dataclasses.fields(Messages) if f.name != "account_daily_limit"})
    with pytest.raises(SettingsError) as stopped:
        desk_settings(local, words, at_once_per_visitor=2, forget_over=100)
    assert str(stopped.value).startswith(f"{both}: the briefing desk cannot be built: ")


def _one_level_deep(config: Path, local: Path | None) -> dict:
    """The settings as every site's own loader read them: one level deep."""
    import tomllib

    raw = tomllib.loads(config.read_text(encoding="utf-8"))
    if local is not None:
        for section, values in tomllib.loads(local.read_text(encoding="utf-8")).items():
            raw.setdefault(section, {}).update(values)
    return raw


def _sites_settings_files() -> list[Path]:
    """Each site's real ``config/settings.toml``: in its checkout (``WTS_SITES_DIR``, or beside this repository on
    the build machine) and, on the build machine, in its adoption worktree."""
    import os

    named = os.environ.get("WTS_SITES_DIR")
    homes = [Path(named)] if named else [Path("/home/user"), Path("/home/user/wt")]
    repos = ("wherempsstand", "wherecountriesstand", "wherecouncilsstand", "wherelandlordsstand",
             "mps-adopt", "countries-adopt", "councils-adopt", "landlords-adopt")
    return [home / repo / "config" / "settings.toml" for home in homes for repo in repos
            if (home / repo / "config" / "settings.toml").is_file()]


@pytest.mark.parametrize("config", _sites_settings_files() or [None],
                         ids=lambda path: "none" if path is None else path.parts[-3])
def test_the_deeper_merge_reads_every_sites_real_settings_as_before(config, tmp_path):
    """With no local file, and with one that holds only plain keys (all that a site's own commands write, and all
    that the deploy notes had asked an owner to write before prices), nothing a site reads has changed."""
    if config is None:
        pytest.skip("no site's config/settings.toml beside this repository or under WTS_SITES_DIR")
    site = Site(name="A site", package="site", env_prefix="SITE", root=config.parents[1])
    data = tmp_path / "data"
    env = {"SITE_DATA_DIR": str(data), "SITE_CONFIG": str(config)}
    assert load_settings(Settings, site, env=env).raw == _one_level_deep(config, None)

    sections = _one_level_deep(config, None)
    plain = {name: {key: value for key, value in values.items() if not isinstance(value, dict)}
             for name, values in sections.items() if isinstance(values, dict)}
    first = next(name for name, values in plain.items() if values)
    data.mkdir()
    local = data / "settings.local.toml"
    save_local_settings(data, {first: {key: plain[first][key] for key in list(plain[first])[:2]},
                               "usage": {"daily_spend_cap_usd": 1.5, "a_new_key": "x"},
                               "a_new_section": {"flag": True, "n": 3}}, "the test")
    read = load_settings(Settings, site, env=env)
    assert read.raw == _one_level_deep(config, local) and read.local_path == local
    assert read.raw["usage"]["daily_spend_cap_usd"] == 1.5 and read.raw["a_new_section"] == {"flag": True, "n": 3}


def test_old_tables_may_be_dropped_so_many_days_after_the_import_ran_whatever_day_that_was(tmp_path):
    """Found by Where MPs Stand's adoption: the old tables should go no later than the copy of the file made
    before the import, which is deleted so many days after it was made. A date fixed in the code cannot keep to
    that, since nobody knows on what day the owner will deploy. Counted from the import, the two keep step."""
    from wts_core.state import OldTables

    path = tmp_path / "state.db"
    sqlite3.connect(path).executescript("CREATE TABLE usage (id INTEGER PRIMARY KEY); INSERT INTO usage VALUES (1);")
    old = OldTables(tables=("usage",), drop_after_days=60)
    bring = Import("spending", ("INSERT INTO wts_kv (key, value) SELECT 'rows', count(*) FROM usage",),
                   needs=("usage",))
    clock = FixedClock("2026-12-03T10:00:00+00:00")  # the day the owner happened to deploy
    db = StateDB(path, imports=[bring], clock=clock, old_tables=old)
    assert db.old_tables_due() == date(2027, 2, 1)
    assert (tmp_path / "state.pre-wts-core.2026-12-03.db").exists()
    clock.set("2027-01-31T03:00:00+00:00")
    retired = db.retire_old()
    assert (retired.dropped, retired.left, retired.due) == ((), ("usage",), date(2027, 2, 1))
    assert db.forget_old_copies(60) == []  # the copy made before the import is still there to go back to
    clock.set("2027-02-01T03:00:00+00:00")
    assert db.retire_old().dropped == ("usage",)
    clock.set("2027-02-02T03:00:00+00:00")
    assert len(db.forget_old_copies(60)) == 1  # and goes the night after


def test_old_tables_counted_from_an_import_that_has_not_run_are_not_dropped_and_have_no_day_yet(tmp_path):
    from wts_core.state import OldTables

    path = tmp_path / "state.db"
    sqlite3.connect(path).executescript("CREATE TABLE usage (id INTEGER PRIMARY KEY);")
    never = Import("spending", ("SELECT 1",), needs=("usage", "briefings"))  # this database has no "briefings"
    clock = FixedClock("2030-01-01T03:00:00+00:00")
    db = StateDB(path, imports=[never], clock=clock, old_tables=OldTables(tables=("usage",), drop_after_days=0))
    retired = db.retire_old()
    assert (retired.dropped, retired.left, retired.due, db.old_tables_due()) == ((), ("usage",), None, None)
    assert StateDB(path, clock=clock).old_tables_due() is None  # a site that declared none


def test_the_day_old_tables_are_dropped_is_given_one_way_and_not_both():
    from wts_core.state import OldTables

    for wrong in ({}, {"drop_on": date(2027, 2, 1), "drop_after_days": 60}):
        with pytest.raises(ValueError, match="drop_on .a date. or drop_after_days .* and not both"):
            OldTables(tables=("usage",), **wrong)
    for wrong in (-1, 1.5, True):
        with pytest.raises(ValueError, match="a whole number of days"):
            OldTables(tables=("usage",), drop_after_days=wrong)
    assert OldTables(("usage",), date(2027, 2, 1)).drop_on == date(2027, 2, 1)  # as every adopted site writes it


# Going back to the old code, and coming forward again (0.3.0)


def _moved(tmp_path, clock, **more):
    """A site that has moved onto the package: its old tables, and an import that has copied them."""
    from wts_core.state import OldTables

    path = tmp_path / "state.db"
    if not path.exists():
        sqlite3.connect(path).executescript(
            "CREATE TABLE usage (id INTEGER PRIMARY KEY, at TEXT, cost REAL);"
            "CREATE TABLE briefings (id TEXT PRIMARY KEY, created_at TEXT, question TEXT);"
            "CREATE TABLE statements (id INTEGER PRIMARY KEY, at TEXT, email TEXT);"
            "INSERT INTO usage VALUES (1, '2026-11-12T10:00:00+00:00', 0.03);"
            "INSERT INTO briefings VALUES ('abc', '2026-11-12T10:00:05+00:00', 'A question?');"
            "INSERT INTO statements VALUES (1, '2026-08-01T09:00:00+00:00', 'sender@example.org');")
    made = [Migration(10, "spending", ("CREATE TABLE wts_spent (id INTEGER PRIMARY KEY, at TEXT, cost REAL)",))]
    bring = Import("the-move", ("INSERT INTO wts_spent (id, at, cost) SELECT id, at, cost FROM usage",),
                   needs=("usage", "briefings"),
                   written_at=more.pop("written_at", {"usage": "at", "briefings": "created_at", "statements": "at"}))
    old = OldTables(tables=("usage", "briefings", "statements"), drop_on=date(2027, 2, 1), nightly=(
        "UPDATE statements SET email = NULL WHERE at < :now", "DELETE FROM usage WHERE at < '2026-01-01'"))
    return StateDB(path, migrations=made, imports=[bring], clock=clock, old_tables=old)


def test_a_site_put_back_on_its_old_code_and_then_deployed_again_is_stopped_before_it_runs_without_what_was_written(tmp_path):
    """Found by the independent review of Where MPs Stand's adoption. The import is marked as done, so the second
    deploy skips it, and what the old code wrote meanwhile is in none of the package's tables: the spending no
    longer counts towards the caps, and the briefings saved are at no address. Nothing said so."""
    from wts_core.state import StateError

    clock = FixedClock("2026-11-13T12:00:00+00:00")
    db = _moved(tmp_path, clock)
    assert _all(db, "SELECT count(*) FROM wts_spent") == [(1,)]
    clock.advance(days=2)
    _moved(tmp_path, clock)  # every start since, on the new code: nothing is newer, nothing is said
    # the owner goes back: the earlier commit is checked out, and the old code serves for a day
    con = sqlite3.connect(db.path)
    con.execute("INSERT INTO usage VALUES (2, '2026-11-16T09:00:00+00:00', 0.04)")
    con.execute("INSERT INTO usage VALUES (3, '2026-11-16T09:30:00+00:00', 0.05)")
    con.execute("INSERT INTO briefings VALUES ('def', '2026-11-16T09:30:05+00:00', 'Asked on the old code?')")
    con.commit()
    con.close()
    clock.advance(days=2)  # and comes forward again
    with pytest.raises(StateError) as stopped:
        _moved(tmp_path, clock)
    said = str(stopped.value)
    assert "usage has 2 rows written after the import 'the-move' ran (2026-11-13T12:00:00+00:00)" in said
    assert "briefings has 1 row written after the import 'the-move' ran" in said and "statements" not in said
    assert "run the site's script for undoing the move" in said and "start the site again" in said
    assert "Asked on the old code" not in said  # counts and table names: never a row
    assert _all(StateDB(db.path), "SELECT count(*) FROM wts_spent") == [(1,)]  # and nothing was changed
    # the mend: the site's undo script clears the mark and the package's rows, and the next start imports it all
    con = sqlite3.connect(db.path)
    con.executescript("DELETE FROM wts_schema WHERE name = 'import:the-move'; DELETE FROM wts_spent;")
    con.close()
    assert _all(_moved(tmp_path, clock), "SELECT count(*) FROM wts_spent") == [(3,)]


def test_the_nightly_tidy_of_the_old_tables_never_looks_like_the_old_code_writing(tmp_path):
    """It changes rows and deletes them, and adds none: no row's time moves past the import's mark."""
    clock = FixedClock("2026-11-13T12:00:00+00:00")
    db = _moved(tmp_path, clock)
    for _ in range(5):  # night after night, with a start after each
        clock.advance(days=1)
        assert db.retire_old().changed >= 0
        db = _moved(tmp_path, clock)
    assert _all(db, "SELECT email FROM statements") == [(None,)]  # the tidy did do its work
    clock.set("2027-02-01T03:00:00+00:00")
    assert db.retire_old().dropped == ("usage", "briefings", "statements")
    _moved(tmp_path, clock)  # the old tables are gone: there is nothing to look at, and nothing is asked


def test_an_old_table_whose_times_are_kept_another_way_is_asked_about_with_a_query(tmp_path):
    from wts_core.state import StateError

    asked: list[str] = []

    def newer(con: sqlite3.Connection, mark: str) -> int:
        asked.append(mark)
        return con.execute("SELECT count(*) FROM usage WHERE cost > 1").fetchone()[0]  # this site's own way

    clock = FixedClock("2026-11-13T12:00:00+00:00")
    db = _moved(tmp_path, clock, written_at={"usage": newer})
    assert asked == []  # the import had not run when the database was opened: nothing to compare with
    _moved(tmp_path, clock, written_at={"usage": newer})
    assert asked == ["2026-11-13T12:00:00+00:00"]  # asked of the table that is there, with the import's time
    sqlite3.connect(db.path).executescript("INSERT INTO usage VALUES (9, 'yesterday', 2.0);")
    with pytest.raises(StateError, match="usage has 1 row written after the import 'the-move' ran"):
        _moved(tmp_path, clock, written_at={"usage": newer})
    _moved(tmp_path, clock, written_at={})  # a site that declares nothing is asked nothing, as before 0.3.0


def test_a_slip_in_what_is_declared_is_refused_and_does_not_hide_a_loss(tmp_path):
    """Found by the independent review of 0.3.0, with the upgrade guide's own example: it named
    ``briefings.created_at`` for two sites whose old ``briefings`` keeps its time in ``at``. The check passed over
    the table without a word, so a briefing the old code saved after the move was lost as silently as before."""
    from wts_core.state import StateError

    clock = FixedClock("2026-11-13T12:00:00+00:00")
    wrong_column = {"usage": "at", "briefings": "at"}  # this site's old briefings are timed by created_at
    db = _moved(tmp_path, clock, written_at=wrong_column)  # the move itself: the import had not run, nothing is asked
    con = sqlite3.connect(db.path)
    con.execute("INSERT INTO briefings VALUES ('def', '2026-11-14T09:30:05+00:00', 'Asked on the old code?')")
    con.commit()
    con.close()
    clock.advance(days=2)
    with pytest.raises(StateError) as stopped:
        _moved(tmp_path, clock, written_at=wrong_column)
    assert ("the import 'the-move' says rows of briefings are timed by its column 'at', and briefings has no such "
            "column (it has created_at, id, question)") in str(stopped.value)
    with pytest.raises(StateError, match="briefings has 1 row written after the import"):
        _moved(tmp_path, clock)  # with the right column, the briefing is seen
    # a mistyped table is refused when it is declared, before the database is touched: on the very first start
    for mistyped in ({"usgae": "at"}, {"usage": "at", "breifings": lambda con, mark: 0}):
        (tmp_path / "new").mkdir(exist_ok=True)
        with pytest.raises(StateError, match="which is not a table the import needs or one of the site's old "
                                             r"tables \(briefings, statements, usage\)"):
            _moved(tmp_path / "new", clock, written_at=mistyped)
        made = sqlite3.connect(tmp_path / "new" / "state.db")
        assert not made.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'wts_%'").fetchone()[0]
        made.close()
    # a table that is declared, named among the old tables, and not there (an older backup has none; or it was
    # dropped on its day) is passed over
    sqlite3.connect(db.path).executescript("DELETE FROM briefings WHERE id = 'def'; DROP TABLE statements;")
    _moved(tmp_path, clock)


@pytest.mark.parametrize(("written", "after"), [
    ("2026-11-13T13:00:00+00:00", True),            # as the package writes a time
    ("2026-11-13T13:00:00Z", True),
    ("2026-11-13T12:00:00Z", False),                # the import's own second, written with a Z: not after it
    ("2026-11-13T12:00:00.400000+00:00", False),    # nor are four tenths of that second
    ("2026-11-13T12:00:01.000001+00:00", True),
    ("2026-11-13 15:00:00", True),                  # as SQLite's datetime('now') writes one: UTC, with a space
    ("2026-11-13 11:59:59", False),
    ("2026-11-13T12:30:00+01:00", False),           # half past eleven in UTC: before the move
    ("2026-11-13T13:30:00+01:00", True),
    ("2026-11-12T23:30:00-05:00", False),           # 04:30 UTC on the day of the move, before it
    ("2026-11-13T09:00:00-05:00", True),            # 14:00 UTC
    ("2026-11-14", True),                           # a day alone is its midnight
])
def test_times_in_an_old_table_are_compared_as_times_however_they_were_written(tmp_path, written, after):
    """The first version compared text with text, so a time written with a Z, with microseconds, in another zone
    or with a space was "after" or "before" by its spelling."""
    from wts_core.state import StateError

    clock = FixedClock("2026-11-13T12:00:00+00:00")
    db = _moved(tmp_path, clock)
    con = sqlite3.connect(db.path)
    con.execute("INSERT INTO usage VALUES (2, ?, 0.04)", (written,))
    con.commit()
    con.close()
    clock.advance(seconds=5)
    if after:
        with pytest.raises(StateError, match="usage has 1 row written after the import"):
            _moved(tmp_path, clock)
    else:
        _moved(tmp_path, clock)


def test_a_time_that_cannot_be_read_never_stops_the_site_and_is_said(tmp_path, caplog):
    """What the check cannot see is passed over, and said in the log where it can be: it must never be the reason
    a site does not start."""
    import logging

    clock = FixedClock("2026-11-13T12:00:00+00:00")
    db = _moved(tmp_path, clock)
    con = sqlite3.connect(db.path)
    con.executemany("INSERT INTO usage VALUES (?, ?, 0.04)", [
        (2, "yesterday"), (3, "2026-13-45T99:00:00"), (4, None), (5, 1794000000), (6, "2026-11-13T12:00:00+00:00")])
    con.commit()
    con.close()
    clock.advance(days=1)
    with caplog.at_level(logging.WARNING, logger="wts_core.state"):
        _moved(tmp_path, clock)  # it starts
    # the two that are words and no time are counted, and the one kept as seconds since 1970 (for which a site
    # gives a function); the one with no time at all and the row in the import's own second are what the check
    # cannot see (Import.written_at)
    assert "3 values of usage.at could not be read as a time and were passed over" in caplog.text


def test_the_line_each_site_declares_names_columns_its_old_tables_have():
    """docs/UPGRADING.md gives each of the four sites its exact ``written_at``. Read against each site's old
    schema where its adoption is there to read (``tests/golden/old-state.sql``); the lines here are the guide's."""
    import re

    lines = {
        "councils": {"usage": "at", "answer_cache": "at", "briefings": "at", "reports": "at", "statements": "at"},
        "countries": {"usage": "at", "answer_cache": "created_at", "failures": "at", "briefings": "at",
                      "reports": "at", "statements": "at"},
        "landlords": {"reports": "at", "statements": "at", "statement_log": "at"},
        "mps": {"usage": "at", "answer_cache": "created_at", "briefings": "created_at", "failures": "at",
                "reports": "at", "statements": "at"},
    }
    guide = (Path(__file__).parent.parent / "docs" / "UPGRADING.md").read_text(encoding="utf-8")
    read = 0
    for site, line in lines.items():
        said = "written_at={" + ", ".join(f'"{table}": "{column}"' for table, column in line.items()) + "}"
        assert " ".join(said.split()) in " ".join(guide.split()), f"the guide's line for {site} is not {said}"
        schema = Path(f"/home/user/wt/{site}-adopt/tests/golden/old-state.sql")
        if not schema.is_file():
            continue
        read += 1
        text = schema.read_text(encoding="utf-8")
        for table, column in line.items():
            made = re.search(rf'CREATE TABLE (?:IF NOT EXISTS )?"?{table}"?\s*\((.*?)\);', text, re.S)
            assert made, f"{site}: no old table {table}"
            assert re.search(rf'(^|[(,])\s*"?{column}"?\s', made.group(1)), f"{site}: {table} has no column {column}"
    if not read:
        pytest.skip("no adoption worktree of a site is here to read its old schema from")


def test_a_time_kept_as_a_number_or_written_day_first_is_said_too(tmp_path, caplog):
    """The second review: these sort before any date, so the reading never reached them and the warning the
    docstring promises was never given. They are counted without being read."""
    import logging

    clock = FixedClock("2026-11-13T12:00:00+00:00")
    db = _moved(tmp_path, clock)
    con = sqlite3.connect(db.path)
    con.executemany("INSERT INTO usage VALUES (?, ?, 0.04)", [
        (2, 1794000000), (3, 1794000000.5), (4, "16/11/2026 13:00"), (5, "13 November 2026"), (6, None)])
    con.commit()
    con.close()
    clock.advance(days=1)
    with caplog.at_level(logging.WARNING, logger="wts_core.state"):
        _moved(tmp_path, clock)  # it starts: none of these can be read as a time, so none can be called newer
    assert "4 values of usage.at could not be read as a time and were passed over" in caplog.text
    caplog.clear()
    sqlite3.connect(db.path).executescript("DELETE FROM usage WHERE id > 1;")
    with caplog.at_level(logging.WARNING, logger="wts_core.state"):
        _moved(tmp_path, clock)
    assert "could not be read" not in caplog.text  # and nothing is said of a table whose times are all times
