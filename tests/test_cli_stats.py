"""The statistics commands (stats, weekly-report, tidy), on the hand-built week the statistics' own tests use: ten
readers' questions in the seven days to noon on 13 November 2026, of which one ended in an error."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from cli_sites import Said, mounted, run
from test_observe_log import SITE, record
from test_observe_stats import LIBRARIES, NOW, PRICES, the_week
from wts_core import observe
from wts_core.cli import StatsNames, last_day_figures, stats_commands
from wts_core.observe import SqliteBriefingLog, count, stats, tripped, weeks
from wts_core.state import StateDB
from wts_core.testing import FixedClock
from wts_core.testing.index import RecordingEmbedder

TOO_STRICT = {"error_rate": 0.05, "daily_cost_usd": 0.02}
# what every tidy says of its own deletions, and its last line: the file written out afresh
NO_SECRETS = "Deleted 0 visitor secrets of earlier days."
AFRESH = "Wrote the database out afresh: nothing deleted is left in the file."
ERRORS = ("The share of questions that ended in an error was 10.0% (1 of 10): 5.0 percentage points over the "
          "threshold of 5.0%.")
COST = "Briefings cost $0.0217 a day: $0.0017 over the threshold of $0.0200."


class Office:
    """A site's state database with the week in its record, its reports folder and its [alerts] settings (none
    set, until a test sets some), and the commands as the site would add them."""

    def __init__(self, tmp_path: Path, **more: Any) -> None:
        self.root = tmp_path
        self.clock = FixedClock(NOW)
        self.db = StateDB(tmp_path / "state.db", migrations=observe.migrations(), clock=self.clock)
        self.log = SqliteBriefingLog(self.db, clock=self.clock)
        for row in the_week():
            self.log.write(row)
        self.alerts: dict[str, Any] = {}
        self.opened = 0
        self.app = mounted(stats_commands(SITE, self.state, thresholds=lambda: self.alerts,
                                          folder=lambda: tmp_path / "reports", pricing=lambda: PRICES,
                                          clock=self.clock, **more))

    def state(self) -> StateDB:
        self.opened += 1
        return self.db

    def __call__(self, *args: Any) -> Said:
        return run(self.app, list(args), self.root)


@pytest.fixture
def office(tmp_path: Path) -> Office:
    return Office(tmp_path)


# Stats


def test_stats_prints_the_page_the_figures_make(office):
    said = office("stats")
    expected = stats(office.log, since=timedelta(days=7), pricing=PRICES, clock=office.clock)
    assert said == Said(0, expected.to_markdown(SITE, thresholds={}), "", None)
    assert "Where Councils Stand" in said.stdout
    assert office("stats", "--since", "7d") == said and office("stats", "--since", "1w") == said
    assert office("stats", "--since", "2026-11-06T12:00") == said
    assert office("stats", "--since", "168h", "--until", "2026-11-13T12:00:00+00:00") == said
    shorter = office("stats", "--since", "24h")
    assert shorter.exit_code == 0 and shorter != said


def test_stats_as_json_is_the_figures_what_tripped_and_the_daily_totals(office):
    office.alerts = dict(TOO_STRICT)
    count(office.db, "why-not-a-chatbot", office.clock, n=3)
    said = office("stats", "--json")
    body = json.loads(said.stdout)
    expected = stats(office.log, since=timedelta(days=7), pricing=PRICES, clock=office.clock)
    assert said.exit_code == 0 and body["stats"] == json.loads(expected.to_json())
    assert body["tripped"] == [ERRORS, COST] and body["counts"] == {"why-not-a-chatbot": {"2026-11-13": 3}}


def test_the_daily_totals_follow_the_page(office):
    assert "## Daily totals" not in office("stats").stdout  # nothing has been counted
    office.clock.advance(days=-2)
    count(office.db, "why-not-a-chatbot", office.clock, n=1200)
    office.clock.advance(days=2)
    count(office.db, "why-not-a-chatbot", office.clock, n=3)
    count(office.db, "a-source-opened", office.clock)
    office.clock.advance(days=-30)
    count(office.db, "why-not-a-chatbot", office.clock, n=99)  # before the period: not in it
    office.clock.advance(days=30)
    said = office("stats")
    assert said.stdout.endswith("\n## Daily totals\n\n- a-source-opened: 1 since 2026-11-06 (2026-11-13 1)\n"
                                "- why-not-a-chatbot: 1,203 since 2026-11-06 (2026-11-11 1,200, 2026-11-13 3)\n")


def test_the_page_says_what_tripped_when_thresholds_are_set(office):
    office.alerts = dict(TOO_STRICT)
    said = office("stats")
    assert said.exit_code == 0 and ERRORS in said.stdout and COST in said.stdout  # the page itself is not an alarm


def test_stats_check_prints_only_what_tripped_and_fails_if_anything_did(office):
    assert office("stats", "--check") == Said(0, "", "", None)  # no threshold set: nothing can trip
    office.alerts = {"error_rate": 0.5}
    assert office("stats", "--check") == Said(0, "", "", None)
    office.alerts = dict(TOO_STRICT)
    assert office("stats", "--check") == Said(1, f"{ERRORS}\n{COST}\n", "", None)


@pytest.mark.parametrize("args, says", [
    (("--since", "soon"), "'soon' is not a period: write 24h, 7d or 4w, or a date or time such as 2026-11-12"),
    (("--since", "0d"), "the period must be at least one hour"),
    (("--until", "Friday"), "'Friday' is not a date or time: write 2026-11-12 or 2026-11-12T04:30"),
    (("--since", "2026-11-14"), "the period must begin before it ends"),
])
def test_a_period_that_cannot_be_read_is_said_in_a_line(office, args, says):
    assert office("stats", *args) == Said(1, "", says + "\n", None)


def test_a_mistake_in_the_alerts_settings_is_named_and_stops_the_command(office):
    office.alerts = {"eror_rate": 0.1}
    for command in (("stats",), ("stats", "--check"), ("weekly-report",)):
        said = office(*command)
        assert said.exit_code == 1 and said.stdout == "" and said.error is None, command
        assert said.stderr.startswith("[alerts] eror_rate is not a threshold the package knows: the names are ")
    assert not (office.root / "reports").exists()  # and no report was written with a mistake in it


def test_themes_use_the_sites_embedder_only_when_asked(tmp_path, office):
    assert office("stats", "--themes") == Said(
        1, "", "This site has given no embedding model to group questions with: leave --themes out, and questions "
               "are grouped by their words.\n", None)
    embedder = RecordingEmbedder()
    loaded: list[str] = []

    def load() -> RecordingEmbedder:
        loaded.append("the model")
        return embedder

    theirs = Office(tmp_path / "with", embedder=load, similarity=0.5)
    plain = theirs("stats", "--json")
    assert json.loads(plain.stdout)["stats"]["themes_by"] == "text" and loaded == [] and embedder.texts == []
    by_meaning = theirs("stats", "--json", "--themes")
    assert json.loads(by_meaning.stdout)["stats"]["themes_by"] == "meaning" and loaded == ["the model"]
    assert LIBRARIES in embedder.texts  # the questions went to the site's own embedder, and nowhere else
    with pytest.raises(ValueError, match="an embedder needs similarity too"):
        stats_commands(SITE, theirs.state, thresholds=dict, folder=Path, embedder=load)


# Weekly-report


def test_the_weekly_report_is_saved_and_with_no_thresholds_set_proposes_them(office):
    said = office("weekly-report", "--week", "2026-W46")  # Monday 9 November to Sunday 15 November
    page, data = office.root / "reports" / "2026-W46.md", office.root / "reports" / "2026-W46.json"
    lines = said.stdout.splitlines()
    assert said.exit_code == 0 and said.stderr == "" and lines[:2] == ["<root>/reports/2026-W46.md",
                                                                      "<root>/reports/2026-W46.json"]
    assert lines[2] == ("No alert thresholds are set yet. These are proposed from 2026-W46's figures, for [alerts] "
                        "in the site's settings:")
    saved = json.loads(data.read_text())
    assert saved["week"] == "2026-W46" and saved["tripped"] == [] and saved["proposed_thresholds"]
    assert lines[3:] == [f"{name} = {value:g}" for name, value in saved["proposed_thresholds"].items()]
    assert (saved["stats"]["since"], saved["stats"]["until"]) == ("2026-11-09T00:00:00+00:00",
                                                                  "2026-11-16T00:00:00+00:00")
    assert page.read_text().startswith("#") and "2026-W46" in weeks(office.db)
    # what is proposed can be written into the settings as it is, and nothing trips on the week it came from
    office.alerts = dict(line.split(" = ") for line in lines[3:])
    office.alerts = {name: float(value) for name, value in office.alerts.items()}
    assert office("weekly-report", "--week", "2026-W46") == Said(0, "\n".join(lines[:2]) + "\n", "", None)


def test_the_weekly_report_fails_with_one_sentence_for_each_figure_over_its_threshold(office):
    office.alerts = {"error_rate": 0.05, "daily_cost_usd": 100}
    said = office("weekly-report", "--week", "2026-11-12")  # a day in the week
    found = stats(office.log, since=office.clock.now().replace(day=9, hour=0), until=office.clock.now().replace(
        day=16, hour=0), embedder=None, pricing=PRICES, clock=office.clock)
    sentences = tripped(found, office.alerts)
    assert len(sentences) == 1 and sentences[0].startswith("The share of questions that ended in an error was ")
    assert said == Said(1, "<root>/reports/2026-W46.md\n<root>/reports/2026-W46.json\n" + sentences[0] + "\n", "", None)
    saved = json.loads((office.root / "reports" / "2026-W46.json").read_text())
    assert saved["tripped"] == sentences and saved["thresholds"] == {"error_rate": 0.05, "daily_cost_usd": 100.0}


def test_with_no_week_named_it_is_the_last_whole_week(office):
    said = office("weekly-report", "--folder", office.root / "elsewhere")  # run on Friday 13 November
    assert said.stdout.splitlines()[:2] == ["<root>/elsewhere/2026-W45.md", "<root>/elsewhere/2026-W45.json"]
    saved = json.loads((office.root / "elsewhere" / "2026-W45.json").read_text())
    assert (saved["stats"]["since"], saved["stats"]["until"]) == ("2026-11-02T00:00:00+00:00",
                                                                  "2026-11-09T00:00:00+00:00")
    assert not (office.root / "reports").exists()
    assert office("weekly-report", "--week", "the first") == Said(
        1, "", "'the first' is not a week: write a day in it (2026-11-12) or its name (2026-W46)\n", None)
    assert office("weekly-report", "--week", "2026-W99").exit_code == 1


def test_the_weekly_report_groups_questions_with_the_sites_embedder_where_it_has_one(tmp_path):
    embedder = RecordingEmbedder()
    office = Office(tmp_path, embedder=lambda: embedder, similarity=0.5)
    assert office("weekly-report", "--week", "2026-W46").exit_code == 0
    assert json.loads((tmp_path / "reports" / "2026-W46.json").read_text())["stats"]["themes_by"] == "meaning"
    assert embedder.texts


# Tidy


def test_tidy_applies_the_retention_the_owner_accepted_and_says_what_went(office):
    office.log.write(record("old", "2025-09-01T10:00:00+00:00", question="An old question"))  # over 13 months
    office.log.write(record("failed", "2026-07-01T10:00:00+00:00", "error", question="A question that failed"))
    reports = office.root / "reports"
    reports.mkdir()
    for name in ("2025-W30.md", "2025-W30.json", "2026-W45.md", "notes.txt"):
        (reports / name).write_text("x")
    before = len(office.log.since("2000-01-01T00:00:00+00:00", kinds=("reader", "check", "eval")))
    assert office("tidy") == Said(0, "Deleted 1 record of briefings older than 13 months.\n"
                                     "Removed the question from 1 record of failed briefings older than 90 days.\n"
                                     "Deleted 2 weekly report files older than 13 months.\n"
                                     f"{NO_SECRETS}\n{AFRESH}\n", "", None)
    rows = {r.id: r for r in office.log.since("2000-01-01T00:00:00+00:00", kinds=("reader", "check", "eval"))}
    assert len(rows) == before - 1 and "old" not in rows and rows["failed"].question == ""
    assert sorted(p.name for p in reports.iterdir()) == ["2026-W45.md", "notes.txt"]
    assert office("tidy").stdout.startswith("Deleted 0 records")  # and again: nothing more to do


def test_tidy_runs_the_rest_of_the_sites_nightly_housekeeping_and_prints_what_each_says(tmp_path):
    done: list[str] = []

    def replies_step() -> list[str]:
        done.append("replies")
        return ["2 statements lapsed", "1 address deleted"]

    def another() -> list[str]:
        done.append("another")
        return []

    office = Office(tmp_path, also_tidy=[replies_step, another])
    assert done == [] and office("stats", "--check").exit_code == 0 and done == []  # only tidy runs them
    said = office("tidy")
    assert said.exit_code == 0 and done == ["replies", "another"]
    assert said.stdout.splitlines() == [
        "Deleted 0 records of briefings older than 13 months.",
        "Removed the question from 0 records of failed briefings older than 90 days.",
        "Deleted 0 weekly report files older than 13 months.", NO_SECRETS,
        "2 statements lapsed", "1 address deleted", AFRESH]


def test_tidy_keeps_a_sites_old_tables_within_its_promises_and_drops_them_on_the_day_stated(tmp_path):
    """What becomes of the tables a site's imports copied from is declared on its state database
    (``state.OldTables``); the one nightly command applies it, and says what it did."""
    import sqlite3
    from datetime import date

    from wts_core.state import OldTables

    office = Office(tmp_path)
    assert "old tables" not in office("tidy").stdout  # a site that declared none: nothing is said of them
    con = sqlite3.connect(office.db.path)
    con.executescript("CREATE TABLE failures (id INTEGER PRIMARY KEY, at TEXT, question TEXT);"
                      "INSERT INTO failures VALUES (1, '2026-05-01T09:00:00+00:00', 'An old question that failed?');"
                      "CREATE TABLE usage (id INTEGER PRIMARY KEY);")
    con.close()
    old = OldTables(tables=("failures", "usage"), drop_on=date(2026, 11, 20),
                    nightly=("DELETE FROM failures WHERE substr(at, 1, 10) < date(:today, '-90 days')",))
    office.db = StateDB(office.db.path, migrations=observe.migrations(), clock=office.clock, old_tables=old)
    said = office("tidy")
    assert said.exit_code == 0 and said.stdout.splitlines()[-2:] == [
        "Kept the site's old tables within what it promises: 1 row changed or deleted. They are dropped on "
        "2026-11-20.", AFRESH]
    office.clock.set("2026-11-20T03:00:00+00:00")
    said = office("tidy")
    assert said.exit_code == 0 and said.stdout.splitlines()[-2:] == [
        "Dropped the site's old tables, kept since it moved to the shared package: failures, usage.", AFRESH]
    assert not {"failures", "usage"} & office.db.tables()
    assert "old tables" not in office("tidy").stdout  # gone: nothing more is said, night after night


def test_tidy_fails_when_old_tables_are_kept_past_their_day_because_an_import_never_ran(tmp_path):
    """The rest of the housekeeping is done first; then the timer that runs the command fails, so the server's
    own alerting tells the owner. Rows that were never brought across must not be dropped unseen."""
    import sqlite3
    from datetime import date

    from wts_core.state import Import, OldTables

    done: list[str] = []
    office = Office(tmp_path, also_tidy=[lambda: done.append("replies") or ["the right of reply's line"]])
    sqlite3.connect(office.db.path).executescript("CREATE TABLE usage (id INTEGER PRIMARY KEY);")
    never = Import("spending", ("SELECT 1",), needs=("usage", "briefings"))  # this backup has no "briefings"
    office.db = StateDB(office.db.path, migrations=observe.migrations(), imports=[never], clock=office.clock,
                        old_tables=OldTables(tables=("usage",), drop_on=date(2026, 11, 1)))
    said = office("tidy")
    assert said.exit_code == 1 and done == ["replies"] and "usage" in office.db.tables()
    assert said.stdout.splitlines()[-4:] == [
        "the right of reply's line",
        "Kept the site's old tables within what it promises: 0 rows changed or deleted.",
        "The site's old tables (usage) were due to be dropped on 2026-11-01 and were not, because 1 import has not "
        "run: spending. The log from the site's start says which table each is waiting for. Until that is settled "
        "the old tables are kept past the day the site stated.", AFRESH]


def test_tidy_goes_over_the_old_tables_after_the_right_of_replys_deletions_not_before(tmp_path):
    """An address the right of reply deletes tonight must be gone from the site's old row tonight. The old
    tables' nightly statements copy the package's deletions (blank the old address wherever the package's row has
    none), so they run after the site's own steps."""
    import sqlite3
    from datetime import date

    from wts_core.state import Migration, OldTables

    address = "sender@old-statements.example"
    new = Migration(30, "statements", ("CREATE TABLE wts_statements (id INTEGER PRIMARY KEY, email TEXT)",))
    old = OldTables(tables=("statements",), drop_on=date(2027, 1, 1), nightly=(
        "UPDATE statements SET email = NULL WHERE email IS NOT NULL AND id IN "
        "(SELECT id FROM wts_statements WHERE email IS NULL)",))
    clock = FixedClock(NOW)
    path = tmp_path / "state.db"
    db = StateDB(path, migrations=(*observe.migrations(), new), clock=clock, old_tables=old)
    con = sqlite3.connect(path)
    con.executescript("CREATE TABLE statements (id INTEGER PRIMARY KEY, email TEXT);"
                      f"INSERT INTO statements VALUES (1, '{address}');"
                      f"INSERT INTO wts_statements VALUES (1, '{address}');")
    con.close()

    def the_right_of_reply() -> list[str]:
        with db.connect() as con:  # tonight is the night this sender's three months are up
            con.execute("UPDATE wts_statements SET email = NULL")
        return ["1 address deleted"]

    app = mounted(stats_commands(SITE, lambda: db, thresholds=dict, folder=lambda: tmp_path / "reports",
                                 also_tidy=[the_right_of_reply], clock=clock))
    said = run(app, ["tidy"], tmp_path)
    assert said.exit_code == 0
    lines = said.stdout.splitlines()
    assert lines.index("1 address deleted") < lines.index(
        "Kept the site's old tables within what it promises: 1 row changed or deleted. They are dropped on "
        "2027-01-01.") < lines.index(AFRESH)
    with db.connect() as con:
        assert con.execute("SELECT email FROM statements").fetchone()["email"] is None
    assert address.encode() not in path.read_bytes()  # and it is in the file nowhere, the same night


def test_tidy_deletes_yesterdays_visitor_secret_on_a_day_with_no_visitor(tmp_path):
    """The secret a day's visitor codes are made with is deleted when the next day's first visitor comes. On a day
    nobody comes it would stay beside that day's codes: the night's tidy deletes it whoever visits."""
    from wts_core.usage import visitor_code

    office = Office(tmp_path)
    visitor_code(office.db, "203.0.113.9", clock=office.clock)
    made = f"visitor_salt:{NOW[:10]}"
    secret = office.db.get(made)
    assert secret and NO_SECRETS in office("tidy").stdout  # today's is kept: the day's codes need it
    assert office.db.get(made) == secret
    office.clock.advance(days=1)  # the next night: nobody has come
    assert "Deleted 1 visitor secret of earlier days." in office("tidy").stdout
    assert office.db.get(made) is None
    assert secret.encode() not in office.db.path.read_bytes()


def test_tidy_deletes_the_note_of_a_failed_briefing_past_its_ninety_days_on_a_site_where_nothing_else_fails(tmp_path):
    """Found by Where MPs Stand's adoption: old notes went only when the next failure was noted, so on a site
    that then ran without a fault a failed question was kept past the 90 days its privacy notice gives it."""
    from wts_core import usage
    from wts_core.usage import Failures

    clock = FixedClock(NOW)
    db = StateDB(tmp_path / "state.db", migrations=(*observe.migrations(), *usage.migrations()), clock=clock)
    failures = Failures(db, clock=clock)
    failures.note("briefing", "A question whose briefing could not be written?", "RuntimeError: no answer")
    app = mounted(stats_commands(SITE, lambda: db, thresholds=dict, folder=lambda: tmp_path / "reports", clock=clock))
    clock.advance(days=90)
    assert "Deleted 0 notes of failed briefings older than 90 days." in run(app, ["tidy"], tmp_path).stdout
    assert len(failures.recent()) == 1  # ninety days old: kept
    clock.advance(days=1)  # and nothing has failed since
    assert "Deleted 1 note of failed briefings older than 90 days." in run(app, ["tidy"], tmp_path).stdout
    assert failures.recent() == [] and b"could not be written" not in db.path.read_bytes()
    assert failures.tidy() == 0


def test_tidy_deletes_cached_answers_past_the_hours_the_site_keeps_them(tmp_path):
    """A cached answer holds a reader's question. The cache drops old answers when it stores a new one; on a
    site where nothing new is written they would stay, so the night's tidy drops them, given the site's hours."""
    from wts_core import usage
    from wts_core.usage import SqliteAnswerCache

    hours: list[float] = []

    def cache_hours() -> float:
        hours.append(168)
        return 168

    clock = FixedClock(NOW)
    db = StateDB(tmp_path / "state.db", migrations=(*observe.migrations(), *usage.migrations()), clock=clock)
    cache = SqliteAnswerCache(db, clock=clock)
    cache.put("old", [{"type": "text", "text": "An answer to a question asked a fortnight ago"}], 168)
    clock.advance(days=8)
    cache.put("new", [{"type": "text", "text": "A newer answer"}], 0)  # stored without the cache's own clearing
    with db.connect() as con:  # the old one put back, as on a site where nothing was stored after it went stale
        con.execute("INSERT OR REPLACE INTO wts_answer_cache (key, created_at, events) VALUES "
                    "('old', '2026-11-13T12:00:00+00:00', '[\"a fortnight ago\"]')")
    app = mounted(stats_commands(SITE, lambda: db, thresholds=dict, folder=lambda: tmp_path / "reports",
                                 cache_hours=cache_hours, clock=clock))
    assert hours == []  # read when the command runs, so it can come from settings
    said = run(app, ["tidy"], tmp_path)
    assert said.exit_code == 0 and "Deleted 1 cached answer older than the 168 hours the site keeps one." in said.stdout
    with db.connect() as con:
        assert [r["key"] for r in con.execute("SELECT key FROM wts_answer_cache")] == ["new"]
    assert b"a fortnight ago" not in db.path.read_bytes()
    # a site that gives no hours is told nothing and loses nothing
    plain = mounted(stats_commands(SITE, lambda: db, thresholds=dict, folder=lambda: tmp_path / "reports",
                                   clock=clock))
    assert "cached answer" not in run(plain, ["tidy"], tmp_path).stdout


def test_tidy_says_so_when_the_file_cannot_be_written_out_afresh_and_tries_again_the_next_night(tmp_path, monkeypatch):
    """Another connection holds the file. The rest of the night's work is done, the command says the last step
    was left, and it is not a failure: the next night's tidy does it."""
    import sqlite3

    office = Office(tmp_path)
    monkeypatch.setattr(StateDB, "_open", lambda self, alone=False: _impatient(self.path, alone))
    # a writer in the middle of its write: the file cannot be rewritten under it
    writer = sqlite3.connect(office.db.path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO wts_kv (key, value) VALUES ('held', 'x')")
    try:
        assert office.db.compact() is False
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    # a database with a write-ahead log, and a reader part-way through reading it: the night's deletions go
    # through, and the log cannot be emptied
    sqlite3.connect(office.db.path).execute("PRAGMA journal_mode = WAL").close()
    reader = sqlite3.connect(office.db.path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM wts_kv").fetchone()
    try:
        said = office("tidy")
    finally:
        reader.execute("ROLLBACK")
        reader.close()
    missed = ("The database was NOT written out afresh tonight: the site was using it at that moment. What was "
              "deleted tonight may still be in the file's unused space or in its write-ahead log. It will be tried "
              "again at the next tidy.")
    assert said.exit_code == 0 and said.stdout.splitlines()[-1] == missed  # one such night is ordinary
    assert office("tidy").stdout.splitlines()[-1] == AFRESH  # the next night: done, and the count begins again
    assert office.db.get("tidy:nights_not_written_afresh") is None
    # two nights running is not ordinary: the command ends with status 1, so the timer fails and the owner is told
    reader = sqlite3.connect(office.db.path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM wts_kv").fetchone()
    try:
        first, again = office("tidy"), office("tidy")  # the owner runs it again by hand, the same night
        office.clock.advance(days=1)
        second = office("tidy")
    finally:
        reader.execute("ROLLBACK")
        reader.close()
    assert (first.exit_code, first.stdout.splitlines()[-1]) == (0, missed)
    assert (again.exit_code, again.stdout.splitlines()[-1]) == (0, missed)  # nights are counted, not runs
    assert (second.exit_code, second.stdout.splitlines()[-1]) == (1, f"{missed} That is 2 nights running.")
    assert "Deleted 0 records" in second.stdout  # everything else was done first
    assert (office("tidy").exit_code, office("tidy").stdout.splitlines()[-1]) == (0, AFRESH)



def test_a_site_with_a_nightly_command_of_its_own_writes_afresh_the_same_way(tmp_path, monkeypatch):
    """Where Landlords Stand has no stats group: its own nightly command calls ``cli.write_afresh`` last, prints
    what it says and ends with status 1 on the second night running."""
    import sqlite3

    from wts_core.cli import write_afresh

    office = Office(tmp_path)
    monkeypatch.setattr(StateDB, "_open", lambda self, alone=False: _impatient(self.path, alone))
    said: list[str] = []
    assert write_afresh(office.db, said.append) == 0 and said == [AFRESH]
    sqlite3.connect(office.db.path).execute("PRAGMA journal_mode = WAL").close()
    reader = sqlite3.connect(office.db.path, isolation_level=None)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM wts_kv").fetchone()
    try:
        with office.db.connect() as con:  # something for the log to hold
            con.execute("INSERT INTO wts_kv (key, value) VALUES ('tonight', 'x')")
        assert [write_afresh(office.db, said.append), write_afresh(office.db, said.append)] == [1, 1]  # one night
        office.clock.advance(days=1)
        assert write_afresh(office.db, said.append) == 2
    finally:
        reader.execute("ROLLBACK")
        reader.close()
    assert said[1].startswith("The database was NOT written out afresh tonight") and "running" not in said[1]
    assert "running" not in said[2] and said[3].endswith("That is 2 nights running.")
    assert write_afresh(office.db, said.append) == 0 and said[-1] == AFRESH


def _impatient(path: Path, alone: bool):
    """A connection as ``StateDB`` makes it, that waits a moment for a lock and not thirty seconds."""
    import sqlite3

    con = sqlite3.connect(path, timeout=0.05, isolation_level=None) if alone else sqlite3.connect(path, timeout=0.05)
    con.execute("PRAGMA secure_delete = ON")
    con.row_factory = sqlite3.Row
    return con


def test_the_similarity_may_be_read_when_a_command_runs_so_it_can_come_from_settings(tmp_path):
    read: list[float] = []

    def from_settings() -> float:
        read.append(0.5)
        return 0.5

    embedder = RecordingEmbedder()
    office = Office(tmp_path, embedder=lambda: embedder, similarity=from_settings)
    assert read == [] and office("stats").exit_code == 0 and read == []  # asked for only with the embedder
    assert office("weekly-report", "--week", "2026-W46").exit_code == 0 and read == [0.5]
    by_callable = json.loads((tmp_path / "reports" / "2026-W46.json").read_text())["stats"]
    plain = Office(tmp_path / "plain", embedder=lambda: RecordingEmbedder(), similarity=0.5)
    assert plain("weekly-report", "--week", "2026-W46").exit_code == 0
    by_value = json.loads((tmp_path / "plain" / "reports" / "2026-W46.json").read_text())["stats"]
    assert by_callable["themes_by"] == "meaning" and by_callable["themes"] == by_value["themes"]
    with pytest.raises(ValueError, match="an embedder needs similarity too"):
        Office(tmp_path / "none", embedder=lambda: embedder)


# Names, and what the nightly check is given


def test_a_site_may_rename_the_commands_or_leave_one_out(tmp_path):
    office = Office(tmp_path, names=StatsNames(stats="briefing-stats", tidy=None))
    assert office("briefing-stats", "--check").exit_code == 0 and office("weekly-report").exit_code == 0
    assert office("stats").exit_code == 2 and office("tidy").exit_code == 2


def test_nothing_is_opened_until_a_command_runs(tmp_path):
    office = Office(tmp_path)
    assert office.opened == 0 and office("--help").exit_code == 0 and office.opened == 0
    office("stats", "--check")
    assert office.opened == 1


def test_the_last_days_figures_for_the_nightly_check_are_numbers_only(office):
    office.log.write(record("today1", "2026-11-13T09:00:00+00:00", question="A question asked this morning"))
    office.log.write(record("today2", "2026-11-13T09:30:00+00:00", "error", question="One that failed"))
    office.log.write(record("today3", "2026-11-13T10:00:00+00:00", "paused_cap"))
    office.log.write(record("night", "2026-11-13T02:10:00+00:00", kind="check", question="The nightly question"))
    figures = last_day_figures(office.log, clock=office.clock)
    week = [r for r in the_week() if r.kind == "reader" and r.at >= "2026-11-12T12:00:00+00:00"]
    assert figures["briefings"] == len(week) + 3 and figures["errors"] >= 1 and figures["hours"] == 24
    assert figures["by_outcome"]["paused_cap"] == 1 and sum(figures["by_outcome"].values()) == figures["briefings"]
    assert figures["error_rate"] == round(figures["errors"] / figures["briefings"], 4)
    assert figures["checks"] == 1 + len([r for r in the_week() if r.kind == "check"
                                         and r.at >= "2026-11-12T12:00:00+00:00"])
    assert "question" not in json.dumps(figures).lower()
    # through the check's route it passes whole: every key is the plain name of a figure
    from wts_core.cli import check_route

    status, body = check_route(SITE, token="t0ken-for-the-check", clock=office.clock,
                               figures=lambda: last_day_figures(office.log, clock=office.clock))("t0ken-for-the-check")
    assert status == 200 and body["figures"] == figures
    office.clock.advance(days=30)
    assert last_day_figures(office.log, clock=office.clock) == {
        "hours": 24, "briefings": 0, "by_outcome": {}, "errors": 0, "error_rate": None, "checks": 0}


def test_the_latest_weeks_totals_for_the_nightly_check_are_numbers_only_whatever_the_table_holds(office):
    """ADR 0010: the check route returns the latest weekly figures, so the charity's nightly check can write the
    family's summary without reaching any server. Totals only: a question planted in the table, as a fault might
    put one there, does not leave in the answer."""
    from wts_core.cli import check_route, latest_week_figures
    from wts_core.observe import save_week

    assert latest_week_figures(office.db) == {"week": None, "figures": {}}  # no report saved yet
    assert office("weekly-report", "--week", "2026-W45").exit_code == 0
    assert office("weekly-report", "--week", "2026-W46").exit_code == 0
    latest = latest_week_figures(office.db)
    kept = weeks(office.db)["2026-W46"][""]
    assert latest["week"] == "2026-W46" and latest["figures"]["questions"] == kept["questions"] > 0
    assert latest["figures"]["by_outcome"] == kept["by_outcome"] and latest["figures"]["cost_usd"] == kept["cost_usd"]
    assert latest["figures"]["errors"] == kept["errors"]  # a rate, as it is kept: count, of and rate
    assert "since" not in latest["figures"]  # a text: the week's name says when
    # a question planted where only totals belong, under a key of its own and as a key
    planted = "Did Councillor Planted of Barnsley miss the vote on the budget?"
    save_week(office.db, "2026-W47", "", {**kept, "worst_question": planted, planted: 3,
                                          "by_outcome": {**kept["by_outcome"], planted: 1},
                                          "listed": [planted, 4]}, office.clock)
    status, body = check_route(SITE, token="t0ken-for-the-check", clock=office.clock,
                               weekly=lambda: latest_week_figures(office.db))("Bearer t0ken-for-the-check")
    assert status == 200 and body["weekly"]["week"] == "2026-W47"
    assert body["weekly"]["figures"]["questions"] == kept["questions"]
    assert body["weekly"]["figures"]["listed"] == [4]
    said = json.dumps(body)
    assert "Planted" not in said and "Barnsley" not in said and "worst_question" not in said
    # a week's name that is not one does not pass either, and a route given no weekly figures says nothing of them
    odd = check_route(SITE, token="t", clock=office.clock,
                      weekly=lambda: {"week": planted, "figures": {"questions": 1}})("t")[1]
    assert odd["weekly"] == {"week": None, "figures": {"questions": 1}}
    assert "weekly" not in check_route(SITE, token="t", clock=office.clock)("t")[1]
    # only one configuration's week, and no whole-site row: nothing is the latest
    fresh = StateDB(office.root / "other.db", migrations=observe.migrations(), clock=office.clock)
    save_week(fresh, "2026-W46", "abc123def456", {"questions": 5}, office.clock)
    assert latest_week_figures(fresh) == {"week": None, "figures": {}}
    assert latest_week_figures(StateDB(office.root / "bare.db")) == {"week": None, "figures": {}}  # no such table
