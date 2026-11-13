"""The site's settings, its prefix, and its state database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from wts_core.ports import UnknownModel
from wts_core.settings import SettingsError
from wts_core.testing import FixedClock

from parks.site import IMPORTS, ROOT, SITE, ParksSettings, load, open_state

SETTINGS = (ROOT / "config" / "settings.toml").read_text(encoding="utf-8")


def test_the_sites_own_prefix_names_its_environment_variables(tmp_path: Path) -> None:
    settings = load(env={"PARKS_DATA_DIR": str(tmp_path), "PARKS_PROVIDER": "anthropic", "PARKS_BEHIND_PROXY": "yes",
                         "COUNCILS_DATA_DIR": "/another/sites"})
    assert isinstance(settings, ParksSettings)
    assert settings.data_dir == tmp_path and settings.state_db == tmp_path / "state.db"
    assert settings.answer["provider"] == "anthropic"  # an EnvSetting the site declares
    assert settings.section("server")["behind_proxy"] is True
    assert SITE.env_name("CHECK_TOKEN") == "PARKS_CHECK_TOKEN"


def test_the_sites_own_accessor_finds_its_record(settings: ParksSettings) -> None:
    assert settings.minutes_file == ROOT / "data_static" / "minutes.json" and settings.minutes_file.exists()
    assert settings.backups_dir == settings.data_dir / "backups"


def test_settings_are_layered_the_file_then_the_installations_own_then_overrides(tmp_path: Path) -> None:
    (tmp_path / "settings.local.toml").write_text("[usage]\ndaily_spend_cap_usd = 1.5\nrequests_per_minute = 5\n")
    settings = load(env={"PARKS_DATA_DIR": str(tmp_path)}, **{"usage.requests_per_minute": 9})
    assert settings.usage["daily_spend_cap_usd"] == 1.5  # the installation's own file
    assert settings.usage["requests_per_minute"] == 9  # an override wins
    assert settings.usage["monthly_spend_cap_usd"] == 50.0  # the rest is the site's file


@pytest.mark.parametrize("named", [
    "daily_spend_cap_usd",  # a limit the package reads
    "price_output_per_mtok",  # a price the package reads
    "answer_cache_hours",  # a setting the site reads and hands to the package
    "query_parse_model",
])
def test_a_missing_setting_stops_the_site_and_names_the_key(tmp_path: Path, named: str) -> None:
    lines = SETTINGS.splitlines()
    del lines[next(i for i, text in enumerate(lines) if text.startswith(named + " ="))]  # the first place it is set
    config = tmp_path / "settings.toml"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SettingsError, match=named):
        load(config, env={"PARKS_DATA_DIR": str(tmp_path)})


def test_a_model_with_no_price_of_its_own_stops_the_site(tmp_path: Path) -> None:
    with pytest.raises(UnknownModel, match="a-new-model"):
        load(env={"PARKS_DATA_DIR": str(tmp_path)}, **{"answer.model": "a-new-model"})


def test_the_packages_tables_sit_in_the_sites_state_database(settings: ParksSettings) -> None:
    tables = open_state(settings).tables()
    assert {"wts_schema", "wts_kv", "wts_spending", "wts_answer_cache", "wts_briefings", "wts_failures",
            "wts_reports", "wts_statements", "wts_statement_log", "wts_hidden", "wts_briefing_log",
            "wts_configs", "wts_weekly"} <= tables
    assert all(name.startswith("wts_") or name.startswith("sqlite_") for name in tables)  # the site has none of its own


def test_a_sites_import_copies_its_old_rows_across_once_and_leaves_the_old_table_alone(settings: ParksSettings) -> None:
    # a state database from before the site took the package: its briefings in a table of its own
    settings.data_dir.mkdir(parents=True)
    old = sqlite3.connect(settings.state_db)
    old.execute("CREATE TABLE briefings (id TEXT PRIMARY KEY, created_at TEXT, question TEXT, events TEXT)")
    old.execute("INSERT INTO briefings VALUES ('oldone01', '2026-10-01T09:00:00+00:00', 'An old question?', '[]')")
    old.commit()
    old.close()

    clock = FixedClock("2026-11-13T12:00:00+00:00")
    db = open_state(settings, clock)
    with db.connect() as con:
        assert [tuple(r) for r in con.execute("SELECT id, question FROM wts_briefings")] \
            == [("oldone01", "An old question?")]
        assert con.execute("SELECT count(*) FROM briefings").fetchone()[0] == 1  # untouched
        con.execute("DELETE FROM wts_briefings")
    # a copy of the whole file was made first, in case the deploy has to be undone
    assert (settings.data_dir / "state.pre-wts-core.2026-11-13.db").exists()
    # the import is not run a second time
    with open_state(settings, clock).connect() as con:
        assert con.execute("SELECT count(*) FROM wts_briefings").fetchone()[0] == 0
    assert IMPORTS[0].needs == ("briefings",)  # with no such table, as on a new site, it waits and nothing happens
