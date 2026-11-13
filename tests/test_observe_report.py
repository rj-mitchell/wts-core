"""Alerts and the weekly report, on the same hand-built week as the statistics. The week's figures: 95 in 100
briefings fully written within 20,000 ms; errors 1 in 10; a check found a problem in 2 of 4; not useful 2 of 3
rated; $0.152 over 7 days."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from test_observe_log import SITE, record
from test_observe_stats import BUDGET, FAILED, LIBRARIES, MOON, NOT_SAVED, NOW, PRICES, WITHDRAWN, experiment, the_week
from wts_core import observe
from wts_core.observe import (
    ALERTS,
    OWNER_ACCEPTED,
    SqliteBriefingLog,
    proposed_thresholds,
    stats,
    tidy_reports,
    tripped,
    weekly_report,
    weeks,
)
from wts_core.observe.report import week_name
from wts_core.state import StateDB
from wts_core.testing import FixedClock

NOT_SET = "No alert thresholds are set yet: these are proposed from this week's figures"


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def db(tmp_path, clock) -> StateDB:
    return StateDB(tmp_path / "state.db", migrations=observe.migrations(), clock=clock)


@pytest.fixture
def log(db, clock) -> SqliteBriefingLog:
    made = SqliteBriefingLog(db, clock=clock)
    for row in the_week():
        made.write(row)
    return made


@pytest.fixture
def week(log, clock):
    return stats(log, since=timedelta(days=7), pricing=PRICES, clock=clock)


def quiet_week(tmp_path, clock, briefings: int = 200):
    """A week in which nothing went wrong: every briefing written in a second, checked clean, none rated."""
    log = SqliteBriefingLog(StateDB(tmp_path / "quiet.db", migrations=observe.migrations(), clock=clock),
                            clock=clock)
    for n in range(briefings):
        log.write(record(f"q{n}", "2026-11-10T10:00:00+00:00", cost_usd=0.07, citations_invalid=0, unsupported=0,
                         quotes_unverified=0, loaded_words=0, t_written=1000))
    return stats(log, since=timedelta(days=7), clock=clock)


# ---- thresholds --------------------------------------------------------------------------------------------------


def test_the_alerts_are_the_five_the_owner_asked_for():
    assert ALERTS == ("p95_full_briefing_ms", "error_rate", "check_failure_rate", "not_useful_rate",
                      "daily_cost_usd")


def test_thresholds_are_proposed_from_the_weeks_figures_plus_a_quarter(week):
    assert proposed_thresholds(week) == {
        "p95_full_briefing_ms": 25000.0,  # 20,000 × 1.25
        "error_rate": 0.125,  # 0.1 × 1.25
        "check_failure_rate": 0.625,  # 0.5 × 1.25
        "not_useful_rate": 0.8334,  # 0.6667 × 1.25 = 0.83333…, rounded up
        "daily_cost_usd": 0.03,  # 0.021714 × 1.25 = 0.0271…, rounded up to the cent
    }


def test_another_margin_may_be_passed(week):
    assert proposed_thresholds(week, margin=0.5) == {
        "p95_full_briefing_ms": 30000.0, "error_rate": 0.15, "check_failure_rate": 0.75, "not_useful_rate": 1.0,
        "daily_cost_usd": 0.04}  # 0.0326 rounded up
    assert proposed_thresholds(week, margin=0.0)["p95_full_briefing_ms"] == 20000.0


def test_a_rate_of_nought_is_proposed_as_one_briefing_and_a_figure_with_nothing_behind_it_not_at_all(tmp_path, clock):
    quiet = quiet_week(tmp_path, clock)
    assert proposed_thresholds(quiet) == {
        "p95_full_briefing_ms": 1250.0,
        "error_rate": 0.0063,  # no errors in 200: taken as 1 in 200 = 0.005, × 1.25 = 0.00625, rounded up
        "check_failure_rate": 0.0063,
        "daily_cost_usd": 2.5,  # 200 × 0.07 = 14.00 over 7 days = 2.00 a day, × 1.25
    }  # nobody was asked whether a briefing was useful: no proposal for that
    empty = stats(SqliteBriefingLog(StateDB(tmp_path / "e.db", migrations=observe.migrations(), clock=clock),
                                    clock=clock), since=timedelta(days=7), clock=clock)
    assert proposed_thresholds(empty) == {}


def test_proposed_thresholds_do_not_trip_on_the_week_they_came_from(week, tmp_path, clock):
    assert tripped(week, proposed_thresholds(week)) == []
    assert tripped(week, proposed_thresholds(week, margin=0.0)) == []  # at the figure is not over it
    quiet = quiet_week(tmp_path, clock)
    assert tripped(quiet, proposed_thresholds(quiet)) == []


def test_with_no_thresholds_set_nothing_trips(week):
    assert tripped(week, {}) == []
    assert tripped(week, None) == []
    assert tripped(week, {"error_rate": None, "daily_cost_usd": ""}) == []  # left empty in the settings file


def test_what_tripped_is_said_in_plain_sentences_with_by_how_much(week):
    assert tripped(week, {"p95_full_briefing_ms": 15000, "error_rate": 0.05, "check_failure_rate": 0.4,
                          "not_useful_rate": 0.5, "daily_cost_usd": 0.02}) == [
        "The time within which 95 in every 100 briefings were fully written was 20.0 seconds: 5.0 seconds over the "
        "threshold of 15.0 seconds.",
        "The share of questions that ended in an error was 10.0% (1 of 10): 5.0 percentage points over the "
        "threshold of 5.0%.",
        "The share of checked briefings in which a check found a problem was 50.0% (2 of 4): 10.0 percentage "
        "points over the threshold of 40.0%.",
        "The share of rated briefings that readers said were not useful was 66.7% (2 of 3): 16.7 percentage points "
        "over the threshold of 50.0%.",
        "Briefings cost $0.0217 a day: $0.0017 over the threshold of $0.0200.",
    ]


def test_only_what_is_over_its_threshold_trips(week):
    assert tripped(week, {"p95_full_briefing_ms": 20000, "error_rate": 0.1, "check_failure_rate": 0.5,
                          "not_useful_rate": 0.67, "daily_cost_usd": 0.022}) == []  # at, or just under
    [said] = tripped(week, {"p95_full_briefing_ms": 19999, "error_rate": 0.1, "daily_cost_usd": 5})
    assert said.startswith("The time within which 95 in every 100 briefings were fully written was 20.0 seconds: "
                           "1 millisecond over")
    assert len(tripped(week, {"error_rate": 0.0999})) == 1


def test_a_figure_with_nothing_behind_it_cannot_trip(tmp_path, clock):
    quiet = quiet_week(tmp_path, clock)
    assert tripped(quiet, {"not_useful_rate": 0.0, "error_rate": 0.0, "check_failure_rate": 0.0}) == []
    [said] = tripped(quiet, {"daily_cost_usd": 1.5})
    assert said == "Briefings cost $2.00 a day: $0.50 over the threshold of $1.50."


def test_a_threshold_the_package_does_not_know_or_cannot_read_is_said_not_passed_over(week):
    with pytest.raises(ValueError, match=r"\[alerts\] p95_ms is not a threshold the package knows: the names are "
                                         "p95_full_briefing_ms, error_rate"):
        tripped(week, {"p95_ms": 100})
    with pytest.raises(ValueError, match=r"\[alerts\] error_rate must be a number that is not negative, not '5%'"):
        tripped(week, {"error_rate": "5%"})
    with pytest.raises(ValueError, match=r"\[alerts\] error_rate must be a number"):
        tripped(week, {"error_rate": True})
    with pytest.raises(ValueError, match="not negative"):
        tripped(week, {"daily_cost_usd": -1})


# ---- the page ----------------------------------------------------------------------------------------------------


def test_with_no_thresholds_the_page_says_so_and_proposes_them(week):
    page = week.to_markdown(SITE)
    assert NOT_SET + "." in page
    for line in ("- `p95_full_briefing_ms = 25000` (the time within which 95 in every 100 briefings were fully "
                 "written was 20.0 seconds)",
                 "- `error_rate = 0.125` (the share of questions that ended in an error was 10.0% (1 of 10))",
                 "- `check_failure_rate = 0.625` ", "- `not_useful_rate = 0.8334` ",
                 "- `daily_cost_usd = 0.03` (briefings cost $0.0217 a day)"):
        assert line in page
    assert "over the threshold" not in page
    assert "`error_rate = 0.15`" in week.to_markdown(SITE, margin=0.5)


def test_with_thresholds_the_page_says_what_tripped_or_that_nothing_did(week):
    page = week.to_markdown(SITE, thresholds={"error_rate": 0.05, "daily_cost_usd": 10})
    assert NOT_SET not in page
    assert ("- The share of questions that ended in an error was 10.0% (1 of 10): 5.0 percentage points over the "
            "threshold of 5.0%.") in page
    assert "No threshold is set for `p95_full_briefing_ms`, `check_failure_rate`, `not_useful_rate`." in page
    calm = week.to_markdown(SITE, thresholds=proposed_thresholds(week))
    assert "Nothing is over its threshold." in calm and "No threshold is set for" not in calm


def test_the_page_gives_each_figure_beside_the_weeks_before(week):
    page = week.to_markdown(SITE)
    assert page.startswith("# Where Councils Stand: how the briefings went, 6 November 2026 to 13 November 2026\n")
    assert "the 4 weeks before (9 October 2026 to 6 November 2026)" in page
    for line in (
        "| Questions asked | 10 | 4 | 1 |",  # four in four weeks is one in a week
        "| A briefing was written | 4 | 2 | 0.5 |",
        "| The nightly check's questions | 1 | 1 | 0.2 |",
        "| Until the full briefing | 8.0 seconds | 20.0 seconds | 4 | 5.0 seconds | 6.0 seconds | 2 |",
        "| Until the question was read | 300 milliseconds | 500 milliseconds | 8 | none | none | 0 |",
        "| Writing | 6.2 seconds | 17.0 seconds | 4 | 3.5 seconds | 4.0 seconds | 2 |",
        "| In all | $0.15 | $0.0600 ($0.0150 at that rate) |",
        "| A day | $0.0217 | $0.0021 |",
        "| A briefing written | $0.0350 | $0.0300 |",
        "The dearest day was 8 November 2026: $0.0800.",
        "- Answered from the cache: 20.0% (2 of 10); the 4 weeks before: 25.0% (1 of 4).",
        "reading saved $0.2250 and writing cost $0.0160 more than plain input, so prompt caching paid back.",
        "- The 4 weeks before: 0 tokens read from the prompt cache and 0 written to it; prompt caching was not used.",
        "| Any check found a problem | 50.0% (2 of 4) | 50.0% (1 of 2) |",
        "| An unverified quotation | 25.0% (1 of 4) | 0.0% (0 of 2) |",
        "| Rated not useful, of those rated | 66.7% (2 of 3) | 50.0% (1 of 2) |",
        "| The reader left early | 10.0% (1 of 10) | 0.0% (0 of 4) |",
        "Where readers left: writing: 1.",
        "- This period: 10.0% (1 of 10); the 4 weeks before: 25.0% (1 of 4).",
        "- `APITimeoutError`: 1 (the 4 weeks before: 0)",
        "- `RateLimitError`: 0 (the 4 weeks before: 1)",
        "- 20.0 seconds to the full briefing (3.0 seconds to its first words): a briefing that is not saved, "
        "record w3, 8 November 2026",
        f"- 9.0 seconds to the full briefing (2.0 seconds to its first words): “{LIBRARIES}” (saved as b1), "
        "record w1, 7 November 2026",
        "a briefing since withdrawn or corrected (saved as b4), record w4, 9 November 2026",
        "- Invalid citations 1, unsupported sentences 2, unverified quotations 0, loaded words 0, grounded 90.0%: "
        f"“{BUDGET}” (saved as b2), record w2, 8 November 2026",
        f"- “{MOON}” (asked 2 times)",
        "Grouped by their words, with case and punctuation set aside.",
        f"- “{LIBRARIES}”: asked 3 times",
        "| `B` | 4 | 2 | 2.0 seconds | 12.5 seconds | 20.0 seconds | $0.0350 | 50.0% (1 of 2) | 100.0% (1 of 1) | "
        "25.0% (1 of 4) | 25.0% (1 of 4) | 0.0% (0 of 4) |",
        "In the 4 weeks before:",
    ):
        assert line in page, line
    assert "By experiment arm" not in page


def test_the_page_never_quotes_a_failed_a_withdrawn_or_an_unsaved_briefings_question(week):
    page = week.to_markdown(SITE)
    assert FAILED not in page and WITHDRAWN not in page and NOT_SAVED not in page
    assert "nightly question" not in page and "test question" not in page


def test_the_page_says_when_prices_were_not_given_and_when_there_is_nothing_to_list(log, tmp_path, clock):
    unpriced = stats(log, since=timedelta(days=7), clock=clock).to_markdown(SITE)
    assert "no prices were given, so whether it paid back is not worked out" in unpriced
    empty = stats(SqliteBriefingLog(StateDB(tmp_path / "e.db", migrations=observe.migrations(), clock=clock),
                                    clock=clock), since=timedelta(days=7), compare_weeks=1, clock=clock)
    page = empty.to_markdown(SITE)
    for line in (NOT_SET + ", and there are too few figures yet to propose any.", "No briefing was written.",
                 "The checks found no problem.", "Every question found records.",
                 "No question was asked more than once.", "No questions were asked.", "the week before",
                 "| Questions asked | 0 | 0 | 0 |",
                 "| Rated not useful, of those rated | none to count | none to count |"):
        assert line in page, line


def test_a_readers_question_cannot_change_the_page_around_it(tmp_path, clock):
    log = SqliteBriefingLog(StateDB(tmp_path / "s.db", migrations=observe.migrations(), clock=clock), clock=clock)
    nasty = "<script>alert(1)</script> | **bold** [link](http://x)\n# heading `code`"
    log.write(record("r1", "2026-11-12T10:00:00+00:00", "no_records", question=nasty))
    log.write(record("r2", "2026-11-12T11:00:00+00:00", "no_records", question="long " * 100))
    page = stats(log, since=timedelta(days=7), clock=clock).to_markdown(SITE)
    assert "<script>" not in page and "\n# heading" not in page
    assert ("- “&lt;script&gt;alert\\(1\\)&lt;/script&gt; \\| \\*\\*bold\\*\\* \\[link\\]\\(http://x\\) \\# heading "
            "\\`code\\`”") in page
    [long] = [line for line in page.splitlines() if line.startswith("- “long")]
    assert len(long) < 220 and long.endswith("…”")


def test_the_page_sets_the_arms_of_an_experiment_side_by_side_and_names_the_test(tmp_path, clock):
    told = stats(experiment(tmp_path, clock, {"a": (100, 20), "b": (100, 35)}), since=timedelta(days=7),
                 decided_by="not_useful", clock=clock).to_markdown(SITE)
    assert "## By experiment arm" in told and "### “shorter”" in told
    assert "| `a` | 100 | 100 |" in told and "| `b` | 100 | 100 |" in told
    assert ("- `a` against `b` on \"rated not useful\": 20.0% (20 of 100) against 35.0% (35 of 100): the difference "
            "is unlikely to be chance (p = 0.018). The test is a two-proportion z-test (pooled, two-sided) at the "
            "5% level, made only when each arm would expect at least 5 briefings either way.") in told


def test_the_page_says_too_few_briefings_to_tell_until_a_difference_is_unlikely_to_be_chance(tmp_path, clock):
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    few = stats(experiment(tmp_path / "one", clock, {"a": (50, 10), "b": (50, 14)}), since=timedelta(days=7),
                decided_by="not_useful", clock=clock).to_markdown(SITE)
    assert "20.0% (10 of 50) against 28.0% (14 of 50): too few briefings to tell (p = 0.349)." in few
    tiny = stats(experiment(tmp_path / "two", clock, {"a": (8, 0), "b": (8, 3)}), since=timedelta(days=7),
                 decided_by="not_useful", clock=clock).to_markdown(SITE)
    assert "0.0% (0 of 8) against 37.5% (3 of 8): too few briefings to tell. The test is" in tiny
    undecided = stats(experiment(tmp_path, clock, {"a": (8, 0), "b": (8, 3)}), since=timedelta(days=7),
                      clock=clock).to_markdown(SITE)
    assert "No figure was named to decide the experiment, so the arms are not compared." in undecided


# ---- the weekly report -------------------------------------------------------------------------------------------


def test_the_weekly_report_is_written_as_a_page_and_as_json_under_the_weeks_name(week, tmp_path, db, clock):
    page, data = weekly_report(week, tmp_path / "data" / "reports", site=SITE, week=date(2026, 11, 13), db=db,
                               clock=clock)
    assert (page, data) == (tmp_path / "data" / "reports" / "2026-W46.md",
                            tmp_path / "data" / "reports" / "2026-W46.json")
    assert page.read_text() == week.to_markdown(SITE)
    saved = json.loads(data.read_text())
    assert (saved["site"], saved["week"]) == ("councils", "2026-W46")
    assert saved["stats"] == json.loads(week.to_json())
    assert (saved["thresholds"], saved["tripped"]) == ({}, [])
    assert saved["proposed_thresholds"] == proposed_thresholds(week)
    assert sorted(p.name for p in page.parent.iterdir()) == ["2026-W46.json", "2026-W46.md"]  # nothing half-written


def test_the_weekly_report_says_what_tripped_in_both_files(week, tmp_path, db, clock):
    thresholds = {"error_rate": 0.05, "daily_cost_usd": 10}
    page, data = weekly_report(week, tmp_path, site=SITE, week=date(2026, 11, 13), db=db, thresholds=thresholds,
                               clock=clock)
    saved = json.loads(data.read_text())
    assert saved["thresholds"] == {"error_rate": 0.05, "daily_cost_usd": 10.0}
    assert saved["tripped"] == tripped(week, thresholds) and len(saved["tripped"]) == 1
    assert saved["proposed_thresholds"] == {}  # the owner has set them: nothing is proposed over the owner's head
    assert saved["tripped"][0] in page.read_text()


def test_a_weeks_name_is_its_iso_week():
    assert week_name(date(2026, 11, 13)) == "2026-W46"
    assert week_name(date(2026, 11, 9)) == week_name(date(2026, 11, 15)) == "2026-W46"  # Monday to Sunday
    assert week_name(date(2026, 1, 5)) == "2026-W02"
    assert week_name(date(2027, 1, 1)) == "2026-W53"  # a Friday: still the last week of 2026


def test_the_weeks_totals_are_kept_for_the_site_and_for_each_configuration_with_no_question_in_them(
        week, tmp_path, db, clock):
    weekly_report(week, tmp_path, site=SITE, week=date(2026, 11, 13), db=db, clock=clock)
    kept = weeks(db)
    assert list(kept) == ["2026-W46"] and list(kept["2026-W46"]) == ["", "A", "B"]
    site = kept["2026-W46"][""]
    assert (site["questions"], site["written"], site["cost_usd"]) == (10, 4, 0.152)
    assert site["full_briefing"] == {"n": 4, "median": 8000.0, "p95": 20000.0}
    assert site["errors"] == {"count": 1, "of": 10, "rate": 0.1}
    assert site["by_outcome"]["cached"] == 2 and site["by_kind"] == {"reader": 10, "check": 1, "eval": 1}
    assert (site["since"], site["until"]) == ("2026-11-06T12:00:00+00:00", NOW)
    assert kept["2026-W46"]["B"]["questions"] == 4 and kept["2026-W46"]["B"]["not_useful"]["rate"] == 1.0
    with db.connect() as con:
        stored = " ".join(r["figures"] for r in con.execute("SELECT figures FROM wts_weekly"))
    for row in the_week():
        if row.question:
            assert row.question not in stored
    # writing the week again replaces it
    weekly_report(week, tmp_path, site=SITE, week=date(2026, 11, 13), db=db, clock=clock)
    assert list(weeks(db)["2026-W46"]) == ["", "A", "B"]


def test_old_reports_are_deleted_when_the_rows_they_quote_would_be(tmp_path, clock):
    # thirteen months before noon on 13 November 2026 is noon on 13 October 2025. Week 41 of 2025 ran from Monday
    # 6 October to Sunday 12 October: it ended before then. Week 42 ended on Sunday 19 October: after.
    names = ["2025-W41.md", "2025-W41.json", "2025-W42.md", "2025-W42.json", "2024-W52.md", "2026-W46.md",
             "notes.md", "2025-W41.txt", "2025-W41.md.bak", "1999-W99.md"]
    for name in names:
        (tmp_path / name).write_text("x")
    assert tidy_reports(tmp_path, OWNER_ACCEPTED, clock=clock) == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        set(names) - {"2025-W41.md", "2025-W41.json", "2024-W52.md"})  # and nothing that is not a report
    assert tidy_reports(tmp_path, OWNER_ACCEPTED, clock=clock) == 0
    assert tidy_reports(tmp_path / "not-there", OWNER_ACCEPTED, clock=clock) == 0
