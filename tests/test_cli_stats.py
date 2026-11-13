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


# ---- stats ---------------------------------------------------------------------------------------------------------


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


# ---- weekly-report -------------------------------------------------------------------------------------------------


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


# ---- tidy ----------------------------------------------------------------------------------------------------------


def test_tidy_applies_the_retention_the_owner_accepted_and_says_what_went(office):
    office.log.write(record("old", "2025-09-01T10:00:00+00:00", question="An old question"))  # over 13 months
    office.log.write(record("failed", "2026-07-01T10:00:00+00:00", "error", question="A question that failed"))
    reports = office.root / "reports"
    reports.mkdir()
    for name in ("2025-W30.md", "2025-W30.json", "2026-W45.md", "notes.txt"):
        (reports / name).write_text("x")
    before = len(office.log.since("2000-01-01T00:00:00+00:00", kinds=("reader", "check", "eval")))
    assert office("tidy") == Said(0, "Deleted 1 records of briefings older than 13 months.\n"
                                     "Removed the question from 1 records of failed briefings older than 90 days.\n"
                                     "Deleted 2 weekly report files older than 13 months.\n", "", None)
    rows = {r.id: r for r in office.log.since("2000-01-01T00:00:00+00:00", kinds=("reader", "check", "eval"))}
    assert len(rows) == before - 1 and "old" not in rows and rows["failed"].question == ""
    assert sorted(p.name for p in reports.iterdir()) == ["2026-W45.md", "notes.txt"]
    assert office("tidy").stdout.startswith("Deleted 0 records")  # and again: nothing more to do


# ---- names, and what the nightly check is given --------------------------------------------------------------------


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
