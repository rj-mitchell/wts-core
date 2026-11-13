"""The record of each briefing in the state database: writing, marking, reading, retention, the configuration ids
and the daily totals. And that nothing about a reader is in it."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import fields
from datetime import date
from pathlib import Path

import pytest

from wts_core import observe
from wts_core.observe import OWNER_ACCEPTED, Retention, SqliteBriefingLog, Tidied, config_id, count, counts
from wts_core.observe.log import months_before, save_week, weeks
from wts_core.ports import BriefingLog, BriefingRecord
from wts_core.settings import Site
from wts_core.state import StateDB
from wts_core.testing import FixedClock

SITE = Site(name="Where Councils Stand", package="councils", env_prefix="COUNCILS", root=Path("."))


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock("2026-11-13T12:00:00+00:00")


@pytest.fixture
def db(tmp_path, clock) -> StateDB:
    return StateDB(tmp_path / "state.db", migrations=observe.migrations(), clock=clock)


@pytest.fixture
def log(db, clock) -> SqliteBriefingLog:
    return SqliteBriefingLog(db, clock=clock)


def record(id: str, at: str = "2026-11-13T12:00:00+00:00", outcome: str = "completed", **fields_) -> BriefingRecord:
    return BriefingRecord(id=id, at=at, outcome=outcome, **fields_)


FULL = BriefingRecord(
    id="r1", at="2026-11-13T11:59:58+00:00", outcome="left", kind="check", question="What did the council decide?",
    follow_up=True, mode="comprehensive", filters_set=("body", "year"), config_id="0123456789ab", model="model-a",
    parse_model="model-b", instructions="v7", package_version="0.1.0", site_version="2.3", experiment="shorter",
    arm="b", sources=24, spread={"Labour": 9, "Conservative": 8, "Green": 7}, input_tokens=41000,
    cache_read_tokens=30000, cache_write_tokens=2000, output_tokens=900, cost_usd=0.0412, stop_reason="end_turn",
    citations_total=14, citations_invalid=1, grounded_ratio=0.93, unsupported=2, quotes_unverified=1, loaded_words=3,
    t_parse=310, t_search=620, t_rank=700, t_sources_sent=710, t_first_token=1900, t_written=9400, t_checked=9900,
    t_total=9950, left_at="writing", error_type="Overloaded", briefing_id="abc123", useful=False, reported=True,
    corrected=True, followed_up=True)


def columns(db: StateDB, table: str) -> list[str]:
    with db.connect() as con:
        return [r["name"] for r in con.execute(f"PRAGMA table_info({table})")]


# ---- writing and reading ---------------------------------------------------------------------------------------


def test_a_record_comes_back_exactly_as_it_was_written(log):
    log.write(FULL)
    assert log.since("2026-11-01T00:00:00+00:00", kinds=("check",)) == [FULL]


def test_a_record_with_nothing_but_its_outcome_comes_back_with_the_defaults(log):
    log.write(record("r1", outcome="busy"))
    assert log.since("2026-11-01T00:00:00+00:00") == [record("r1", outcome="busy")]


def test_the_table_has_one_column_for_each_field_of_the_record_and_no_other(db):
    assert columns(db, "wts_briefing_log") == [f.name for f in fields(BriefingRecord)]


def test_the_log_is_what_the_briefing_desk_is_promised(log):
    desk_sees: BriefingLog = log
    desk_sees.write(record("r1"))
    desk_sees.mark("nothing-by-this-name", useful=True)


def test_the_spread_and_the_filters_are_stored_as_json(db, log):
    log.write(FULL)
    with db.connect() as con:
        row = con.execute("SELECT spread, filters_set FROM wts_briefing_log").fetchone()
    assert json.loads(row["spread"]) == {"Labour": 9, "Conservative": 8, "Green": 7}
    assert json.loads(row["filters_set"]) == ["body", "year"]


def test_a_record_is_written_once(log):
    log.write(record("r1"))
    with pytest.raises(sqlite3.IntegrityError):
        log.write(record("r1"))


def test_an_outcome_or_a_kind_the_record_does_not_know_is_refused(log):
    with pytest.raises(ValueError, match="cannot end as 'vanished'"):
        log.write(record("r1", outcome="vanished"))
    with pytest.raises(ValueError, match="kind 'visitor'"):
        log.write(record("r1", kind="visitor"))
    assert log.since("2000-01-01T00:00:00+00:00", kinds=observe.log.KINDS) == []


def test_a_time_with_no_timezone_is_refused_and_another_zone_is_stored_as_utc(log):
    with pytest.raises(ValueError, match="timezone"):
        log.write(record("r1", at="2026-11-13T12:00:00"))
    log.write(record("r2", at="2026-11-13T13:00:00+01:00"))
    assert [r.at for r in log.since("2026-11-13T00:00:00+00:00")] == ["2026-11-13T12:00:00+00:00"]


def test_since_takes_a_start_an_end_that_is_left_out_and_the_kinds(log, clock):
    log.write(record("a", at="2026-11-10T00:00:00+00:00"))
    log.write(record("b", at="2026-11-11T00:00:00+00:00"))
    log.write(record("c", at="2026-11-12T00:00:00+00:00"))
    log.write(record("night", at="2026-11-11T03:00:00+00:00", kind="check"))
    log.write(record("test", at="2026-11-11T04:00:00+00:00", kind="eval"))
    ids = lambda rows: [r.id for r in rows]  # noqa: E731
    assert ids(log.since("2026-11-10T00:00:00+00:00")) == ["a", "b", "c"]
    assert ids(log.since("2026-11-10T00:00:01+00:00")) == ["b", "c"]
    assert ids(log.since("2026-11-10T00:00:00+00:00", "2026-11-12T00:00:00+00:00")) == ["a", "b"]
    assert ids(log.since(clock.now().replace(day=11, hour=0), kinds=("reader", "check", "eval"))) == [
        "b", "night", "test", "c"]
    assert ids(log.since("2026-11-10T00:00:00+00:00", kinds=("check",))) == ["night"]


# ---- what the reader did next ----------------------------------------------------------------------------------


def test_mark_notes_each_signal_on_the_briefings_record(log):
    log.write(record("r1", briefing_id="abc"))
    log.write(record("r2", briefing_id="xyz"))
    log.mark("abc", useful=False)
    log.mark("abc", reported=True)
    log.mark("abc", corrected=True)
    log.mark("abc", followed_up=True)
    marked, other = log.since("2026-11-01T00:00:00+00:00")
    assert (marked.useful, marked.reported, marked.corrected, marked.followed_up) == (False, True, True, True)
    assert other == record("r2", briefing_id="xyz")


def test_a_later_mark_adds_and_never_takes_back(log):
    log.write(record("r1", briefing_id="abc"))
    log.mark("abc", useful=True, reported=True)
    log.mark("abc", followed_up=True)  # says nothing of usefulness or reports: they stand
    [marked] = log.since("2026-11-01T00:00:00+00:00")
    assert (marked.useful, marked.reported, marked.corrected, marked.followed_up) == (True, True, False, True)
    log.mark("abc", useful=False)  # the reader changed their answer: the later one counts
    assert log.since("2026-11-01T00:00:00+00:00")[0].useful is False


def test_a_briefing_served_again_from_the_cache_is_marked_once_on_its_first_record(log):
    log.write(record("written", at="2026-11-13T09:00:00+00:00", briefing_id="abc"))
    log.write(record("again", at="2026-11-13T10:00:00+00:00", outcome="cached", briefing_id="abc"))
    log.mark("abc", useful=False, followed_up=True)
    written, again = log.since("2026-11-01T00:00:00+00:00")
    assert (written.useful, written.followed_up) == (False, True)
    assert (again.useful, again.followed_up) == (None, False)


def test_marking_a_briefing_with_no_record_changes_nothing(log):
    log.write(record("r1"))  # not saved: it has no briefing id
    log.mark("abc", useful=True, reported=True)
    log.mark("", reported=True)
    assert log.since("2026-11-01T00:00:00+00:00") == [record("r1")]


def test_a_follow_up_is_a_yes_or_no_and_never_a_link_between_two_questions(db, log):
    log.write(record("first", briefing_id="abc"))
    log.write(record("second", follow_up=True))
    log.mark("abc", followed_up=True)
    with db.connect() as con:
        second = dict(con.execute("SELECT * FROM wts_briefing_log WHERE id = 'second'").fetchone())
    assert "abc" not in second.values() and "first" not in second.values()


# ---- retention ---------------------------------------------------------------------------------------------------


def test_the_owner_accepted_thirteen_months_and_ninety_days():
    assert OWNER_ACCEPTED == Retention(months=13, failed_question_days=90)
    with pytest.raises(TypeError):
        Retention()


@pytest.mark.parametrize(("now", "months", "then"), [
    ("2026-03-31T12:00:00+00:00", 13, "2025-02-28T12:00:00+00:00"),  # no 31 February: the month's last day
    ("2025-03-31T12:00:00+00:00", 13, "2024-02-29T12:00:00+00:00"),  # a leap year's
    ("2026-11-13T12:00:00+00:00", 13, "2025-10-13T12:00:00+00:00"),
    ("2026-01-15T00:00:00+00:00", 13, "2024-12-15T00:00:00+00:00"),
    ("2026-12-31T00:00:00+00:00", 1, "2026-11-30T00:00:00+00:00"),
    ("2026-05-31T00:00:00+00:00", 3, "2026-02-28T00:00:00+00:00"),
])
def test_months_are_counted_as_the_sites_count_them(now, months, then):
    assert months_before(FixedClock(now).now(), months) == FixedClock(then).now()


def test_a_row_is_deleted_thirteen_calendar_months_on_to_the_second(log, clock):
    clock.set("2026-03-31T12:00:00+00:00")
    log.write(record("too-old", at="2025-02-28T11:59:59+00:00"))
    log.write(record("just-kept", at="2025-02-28T12:00:00+00:00"))
    log.write(record("recent", at="2026-03-30T12:00:00+00:00"))
    assert log.tidy(OWNER_ACCEPTED) == Tidied(deleted=1, blanked=0)
    assert [r.id for r in log.since("2000-01-01T00:00:00+00:00")] == ["just-kept", "recent"]


def test_a_row_written_on_the_last_day_of_february_goes_on_the_last_day_of_march_the_year_after(log, clock):
    log.write(record("r1", at="2025-02-28T09:00:00+00:00"))
    clock.set("2026-03-30T23:59:59+00:00")  # thirteen months before is 28 February 2025, at a minute to midnight
    assert log.tidy(OWNER_ACCEPTED).deleted == 1
    log.write(record("r2", at="2025-02-28T09:00:00+00:00"))
    clock.set("2026-03-28T08:59:59+00:00")  # thirteen months before is a second before it was written
    assert log.tidy(OWNER_ACCEPTED).deleted == 0
    clock.set("2026-03-28T09:00:01+00:00")
    assert log.tidy(OWNER_ACCEPTED).deleted == 1


def test_the_question_of_a_failed_briefing_is_blanked_after_ninety_days_and_only_that(log, clock):
    asked = "why did it fail?"
    log.write(record("old-error", at="2026-08-15T11:59:59+00:00", outcome="error", question=asked,
                     error_type="Overloaded"))
    log.write(record("error-in-time", at="2026-08-15T12:00:00+00:00", outcome="error", question=asked))
    log.write(record("old-but-written", at="2026-08-01T12:00:00+00:00", question=asked))
    log.write(record("old-no-records", at="2026-08-01T12:00:00+00:00", outcome="no_records", question=asked))
    assert log.tidy(OWNER_ACCEPTED) == Tidied(deleted=0, blanked=1)  # 15 August is 90 days before 13 November
    rows = {r.id: r for r in log.since("2000-01-01T00:00:00+00:00")}
    assert rows["old-error"] == record("old-error", at="2026-08-15T11:59:59+00:00", outcome="error", question="",
                                       error_type="Overloaded")
    assert {i: r.question for i, r in rows.items() if i != "old-error"} == {
        "error-in-time": asked, "old-but-written": asked, "old-no-records": asked}
    assert log.tidy(OWNER_ACCEPTED) == Tidied(deleted=0, blanked=0)  # nothing is counted twice


def test_another_retention_is_applied_as_given(log, clock):
    log.write(record("r1", at="2026-10-13T11:59:59+00:00"))
    log.write(record("r2", at="2026-11-11T12:00:00+00:00", outcome="error", question="q"))
    assert log.tidy(Retention(months=1, failed_question_days=2)) == Tidied(deleted=1, blanked=0)
    clock.advance(1)
    assert log.tidy(Retention(months=1, failed_question_days=2)) == Tidied(deleted=0, blanked=1)


# ---- nothing about a reader --------------------------------------------------------------------------------------


def test_nothing_about_a_reader_is_stored(db, log, clock):
    log.write(FULL)
    log.write(record("r2", outcome="error", question="q", error_type="Timeout"))
    log.mark("abc123", useful=True, reported=True, corrected=True, followed_up=True)
    log.remember_config("0123456789ab", {"model": "model-a"})
    count(db, "why-not-a-chatbot", clock)
    save_week(db, "2026-W46", "", {"questions": 2}, clock)
    forbidden = ("visitor", "address", "ip", "header", "user_agent", "cookie")
    ours = sorted(t for t in db.tables() if t in ("wts_briefing_log", "wts_configs", "wts_counts", "wts_weekly"))
    assert ours == ["wts_briefing_log", "wts_configs", "wts_counts", "wts_weekly"]
    for table in ours:
        for column in columns(db, table):
            assert not [bad for bad in forbidden if bad in column.lower()], f"{table}.{column}"
    # and the record itself has no such field to store
    for f in fields(BriefingRecord):
        assert not [bad for bad in forbidden if bad in f.name.lower()], f.name


def test_the_tables_are_the_packages_own_and_numbered_forty_to_forty_nine():
    made = observe.migrations()
    assert [m.number for m in made] == sorted({m.number for m in made})
    assert all(40 <= m.number <= 49 for m in made)
    assert all("wts_" in s for m in made for s in m.statements)


# ---- configurations ----------------------------------------------------------------------------------------------

PARTS = {"model": "model-a", "parse_model": "model-b", "instructions": "v7",
         "retrieval": {"candidates": 60, "kept": 24, "hybrid": True, "weights": [0.7, 0.3]},
         "package_version": "0.1.0", "site_version": "2.3", "arm": None}


def test_a_configuration_id_is_twelve_hex_characters_and_the_same_in_any_key_order():
    made = config_id(PARTS)
    assert len(made) == 12 and set(made) <= set("0123456789abcdef")
    backwards = dict(reversed(list(PARTS.items())))
    backwards["retrieval"] = dict(reversed(list(PARTS["retrieval"].items())))
    assert list(backwards) != list(PARTS) and config_id(backwards) == made
    assert config_id(json.loads(json.dumps(PARTS))) == made  # as it comes back from wts_configs


@pytest.mark.parametrize("change", [
    {"model": "model-c"}, {"parse_model": None}, {"instructions": "v8"}, {"package_version": "0.1.1"},
    {"site_version": "2.4"}, {"arm": "b"}, {"retrieval": {**PARTS["retrieval"], "kept": 25}},
    {"retrieval": {**PARTS["retrieval"], "hybrid": False}},
    {"retrieval": {**PARTS["retrieval"], "weights": [0.3, 0.7]}},
    {"added": 1},
])
def test_any_changed_value_gives_another_configuration_id(change):
    assert config_id({**PARTS, **change}) != config_id(PARTS)


def test_a_configuration_id_is_the_start_of_a_sha256_of_the_canonical_json():
    # worked by hand: the keys in order, no spaces
    import hashlib

    assert config_id({"b": 1, "a": "x"}) == hashlib.sha256(b'{"a":"x","b":1}').hexdigest()[:12]


def test_sets_paths_and_dates_are_given_one_form_and_anything_else_is_refused():
    assert config_id({"filters": {"b", "a"}, "root": Path("data"), "on": date(2026, 11, 13)}) == config_id(
        {"filters": ["a", "b"], "root": "data", "on": "2026-11-13"})
    with pytest.raises(TypeError, match="the configuration.retrieval.ranker is a function"):
        config_id({"retrieval": {"ranker": lambda: None}})


def test_the_settings_behind_an_id_are_kept_once(db, log, clock):
    made = config_id(PARTS)
    log.remember_config(made, PARTS)
    clock.advance(days=3)
    log.remember_config(made, {**PARTS, "model": "something else"})  # the first is the truth: an id never changes
    assert log.config(made) == PARTS
    assert log.config("000000000000") is None
    with db.connect() as con:
        assert [tuple(r) for r in con.execute("SELECT config_id, first_seen FROM wts_configs")] == [
            (made, "2026-11-13T12:00:00+00:00")]


# ---- daily and weekly totals -------------------------------------------------------------------------------------


def test_a_count_is_a_daily_total_and_nothing_more(db, clock):
    count(db, "why-not-a-chatbot", clock)
    count(db, "why-not-a-chatbot", clock)
    count(db, "sources-opened", clock, n=3)
    clock.advance(days=1)
    count(db, "why-not-a-chatbot", clock)
    assert counts(db, "2026-11-13") == {"sources-opened": {"2026-11-13": 3},
                                        "why-not-a-chatbot": {"2026-11-13": 2, "2026-11-14": 1}}
    assert counts(db, date(2026, 11, 14)) == {"why-not-a-chatbot": {"2026-11-14": 1}}
    assert columns(db, "wts_counts") == ["day", "name", "n"]


def test_a_weeks_totals_are_kept_by_week_and_configuration_and_replaced_when_written_again(db, clock):
    save_week(db, "2026-W45", "", {"questions": 90}, clock)
    save_week(db, "2026-W46", "", {"questions": 100}, clock)
    save_week(db, "2026-W46", "0123456789ab", {"questions": 60}, clock)
    save_week(db, "2026-W46", "", {"questions": 101}, clock)
    assert weeks(db) == {"2026-W45": {"": {"questions": 90}},
                         "2026-W46": {"": {"questions": 101}, "0123456789ab": {"questions": 60}}}
    assert list(weeks(db, "2026-W46")) == ["2026-W46"]


def test_tidying_leaves_the_weekly_totals_and_the_counts_alone(db, log, clock):
    save_week(db, "2024-W01", "", {"questions": 5}, clock)
    count(db, "why-not-a-chatbot", FixedClock("2024-01-03T00:00:00+00:00"))
    log.write(record("ancient", at="2024-01-03T00:00:00+00:00"))
    assert log.tidy(OWNER_ACCEPTED).deleted == 1
    assert weeks(db) == {"2024-W01": {"": {"questions": 5}}}
    assert counts(db, "2024-01-01") == {"why-not-a-chatbot": {"2024-01-03": 1}}
