"""The statistics, figure by figure, against a small week of briefings whose right answers are worked out here by
hand. The medians are the middle value (or the mean of the middle two); the p95s are by nearest rank: the value at
rank ceil(0.95 × n) of the values in order."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from statistics import NormalDist

import pytest

from test_observe_log import record
from wts_core import observe
from wts_core.observe import SqliteBriefingLog, stats, two_proportion_test
from wts_core.observe.stats import (
    Asked,
    Headline,
    PromptCache,
    Rate,
    Spread,
    Theme,
    TwoProportions,
    median,
    p95,
)
from wts_core.ports import BriefingRecord, Price
from wts_core.state import StateDB
from wts_core.testing import FixedClock
from wts_core.usage import PriceTable

NOW = "2026-11-13T12:00:00+00:00"  # the period is the seven days before: from noon on 6 November
LIBRARIES = "What did the council decide on libraries?"
BUDGET = "Who voted for the budget?"
MOON = "What about the moon base?"
NOT_SAVED = "WHAT did the council decide on libraries"  # the same question, from a briefing that was not saved
WITHDRAWN = "Housing targets"
FAILED = "Secret question that failed"
ALL_GOOD = {"citations_invalid": 0, "unsupported": 0, "quotes_unverified": 0, "loaded_words": 0}


def times(parse=None, search=None, rank=None, sent=None, first=None, written=None, checked=None, total=None):
    return {"t_parse": parse, "t_search": search, "t_rank": rank, "t_sources_sent": sent, "t_first_token": first,
            "t_written": written, "t_checked": checked, "t_total": total}


def the_week() -> list[BriefingRecord]:
    """Ten readers' questions in the period, a nightly check and a test run; five rows in the four weeks before
    (one of them a nightly check); and one row from before that, which nothing should count."""
    return [
        # ---- the period: four briefings written
        record("w1", "2026-11-07T10:00:00+00:00", question=LIBRARIES, briefing_id="b1", config_id="A", model="large",
               cost_usd=0.04, cache_read_tokens=30000, citations_total=10, grounded_ratio=1.0, useful=True,
               **ALL_GOOD, **times(300, 700, 800, 820, 2000, 9000, 9500, 9600)),
        record("w2", "2026-11-08T10:00:00+00:00", question=BUDGET, briefing_id="b2", config_id="A", model="large",
               cost_usd=0.03, cache_read_tokens=30000, citations_total=8, grounded_ratio=0.9, useful=False,
               reported=True, **{**ALL_GOOD, "citations_invalid": 1, "unsupported": 2},
               **times(200, 500, 600, 610, 1500, 7000, 7400, 7500)),
        record("w3", "2026-11-08T11:00:00+00:00", question=NOT_SAVED, config_id="B", model="small", cost_usd=0.05,
               cache_write_tokens=32000, citations_total=12, grounded_ratio=0.8,
               **{**ALL_GOOD, "quotes_unverified": 1, "loaded_words": 1},
               **times(400, 900, 1000, 1010, 3000, 20000, 20600, 20700)),
        record("w4", "2026-11-09T10:00:00+00:00", question=WITHDRAWN, briefing_id="b4", config_id="B", model="small",
               cost_usd=0.02, cache_read_tokens=10000, citations_total=5, grounded_ratio=1.0, useful=False,
               corrected=True, followed_up=True, **ALL_GOOD, **times(100, 300, 350, 360, 1000, 5000, 5200, 5300)),
        # ---- two answered from the cache
        record("c1", "2026-11-09T11:00:00+00:00", "cached", question=BUDGET, briefing_id="b2", config_id="A",
               **times(total=40)),
        record("c2", "2026-11-09T12:00:00+00:00", "cached", question=LIBRARIES, briefing_id="b1", config_id="A",
               **times(total=60)),
        # ---- two that found no records, one reader who left, one error
        record("n1", "2026-11-10T10:00:00+00:00", "no_records", question=MOON, config_id="A", cost_usd=0.001,
               **times(250, 650, total=660)),
        record("n2", "2026-11-10T11:00:00+00:00", "no_records", question="what about the Moon base", config_id="B",
               cost_usd=0.001, **times(350, 750, total=760)),
        record("l1", "2026-11-11T10:00:00+00:00", "left", question="Bin collections", config_id="A", cost_usd=0.01,
               left_at="writing", **times(300, 600, 700, 710, 2500, total=4000)),
        record("e1", "2026-11-12T10:00:00+00:00", "error", question=FAILED, config_id="B",
               error_type="APITimeoutError", **times(500, total=30000)),
        # ---- not readers: counted by kind and nowhere else
        record("k1", "2026-11-10T03:00:00+00:00", kind="check", question="the nightly question", config_id="A",
               cost_usd=0.03, **{**ALL_GOOD, "loaded_words": 9}, **times(100, 200, 300, 310, 900, 90000, 90100, 90200)),
        record("v1", "2026-11-10T04:00:00+00:00", "error", kind="eval", question="a test question", config_id="A",
               cost_usd=0.5, error_type="TestError"),
        # ---- the four weeks before: from noon on 9 October to noon on 6 November
        record("o1", "2026-10-10T10:00:00+00:00", question="an earlier question", briefing_id="o1", config_id="A",
               cost_usd=0.02, useful=True, **ALL_GOOD, **times(first=1000, written=4000, total=4100)),
        record("o2", "2026-10-20T10:00:00+00:00", question="another earlier question", briefing_id="o2",
               config_id="A", cost_usd=0.04, useful=False, **{**ALL_GOOD, "citations_invalid": 2},
               **times(first=2000, written=6000, total=6100)),
        record("o3", "2026-10-21T10:00:00+00:00", "cached", question="an earlier question", briefing_id="o1",
               config_id="A", **times(total=30)),
        record("o4", "2026-11-06T11:59:59+00:00", "error", question="it failed a second before the period",
               config_id="A", error_type="RateLimitError", **times(total=100)),
        record("ok", "2026-10-15T03:00:00+00:00", kind="check", config_id="A", cost_usd=0.03),
        # ---- before even that
        record("ancient", "2026-10-09T11:59:59+00:00", "error", question="too long ago", config_id="Z",
               cost_usd=9.0, error_type="AncientError", **times(total=999999)),
    ]


PRICES = PriceTable(base=Price(input=4.0, output=20.0, cache_read=0.4, cache_write_multiplier=1.25),
                    models=(("small", Price(input=1.0, output=5.0, cache_read=0.1, cache_write_multiplier=1.5)),))


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def log(tmp_path, clock) -> SqliteBriefingLog:
    made = SqliteBriefingLog(StateDB(tmp_path / "state.db", migrations=observe.migrations(), clock=clock),
                             clock=clock)
    for row in the_week():
        made.write(row)
    return made


@pytest.fixture
def week(log, clock):
    return stats(log, since=timedelta(days=7), pricing=PRICES, clock=clock)


# ---- the arithmetic ----------------------------------------------------------------------------------------------


def test_the_median_is_the_middle_value_or_the_mean_of_the_middle_two():
    assert median([5]) == 5
    assert median([9, 1, 5]) == 5
    assert median([4, 1, 3, 2]) == 2.5
    assert median([]) is None


def test_the_p95_is_the_value_at_the_nearest_rank():
    assert p95([]) is None
    assert p95([7]) == 7  # rank ceil(0.95) = 1
    assert p95(range(1, 11)) == 10  # rank ceil(9.5) = 10
    assert p95(range(1, 20)) == 19  # rank ceil(18.05) = 19: with fewer than 20 values, the largest
    assert p95(range(1, 21)) == 19  # rank ceil(19.0) = 19: exactly, not 20
    assert p95(range(1, 22)) == 20  # rank ceil(19.95) = 20
    assert p95(range(1, 101)) == 95
    assert p95(range(1, 102)) == 96  # rank ceil(95.95) = 96
    assert p95([30, 10, 20]) == 30  # in order first


# ---- the period, figure by figure --------------------------------------------------------------------------------


def test_the_period_is_the_seven_days_before_now_and_the_earlier_one_the_four_weeks_before_that(week):
    assert (week.since, week.until, week.compare_weeks) == ("2026-11-06T12:00:00+00:00", NOW, 4)
    assert (week.period.start, week.period.end, week.period.days) == ("2026-11-06T12:00:00+00:00", NOW, 7.0)
    assert (week.earlier.start, week.earlier.end, week.earlier.days) == (
        "2026-10-09T12:00:00+00:00", "2026-11-06T12:00:00+00:00", 28.0)
    assert week.scale == 0.25  # seven days over twenty-eight


def test_volumes_by_outcome_and_by_kind(week):
    assert week.period.questions == 10
    assert week.period.by_outcome == {"completed": 4, "cached": 2, "no_records": 2, "sources_only": 0,
                                      "paused_cap": 0, "paused_limit": 0, "busy": 0, "left": 1, "error": 1}
    assert week.period.by_kind == {"reader": 10, "check": 1, "eval": 1}
    assert week.earlier.questions == 4
    assert week.earlier.by_outcome == {"completed": 2, "cached": 1, "no_records": 0, "sources_only": 0,
                                       "paused_cap": 0, "paused_limit": 0, "busy": 0, "left": 0, "error": 1}
    assert week.earlier.by_kind == {"reader": 4, "check": 1, "eval": 0}


def test_the_time_to_each_point_over_questions_not_answered_from_the_cache(week):
    t = week.period.times
    # in order: 100 200 250 300 300 350 400 500: the middle two are 300 and 300; rank ceil(7.6) = 8
    assert t["t_parse"] == Spread(8, 300, 500)
    # 300 500 600 650 700 750 900: the fourth; rank ceil(6.65) = 7
    assert t["t_search"] == Spread(7, 650, 900)
    # 350 600 700 800 1000
    assert t["t_rank"] == Spread(5, 700, 1000)
    # 360 610 710 820 1010
    assert t["t_sources_sent"] == Spread(5, 710, 1010)
    # 1000 1500 2000 2500 3000: the reader who left had seen the first words
    assert t["t_first_token"] == Spread(5, 2000, 3000)
    # 5000 7000 9000 20000: (7000 + 9000) / 2; rank ceil(3.8) = 4
    assert t["t_written"] == Spread(4, 8000, 20000)
    # 5200 7400 9500 20600: (7400 + 9500) / 2
    assert t["t_checked"] == Spread(4, 8450, 20600)
    # 660 760 4000 5300 7500 9600 20700 30000: (5300 + 7500) / 2
    assert t["t_total"] == Spread(8, 6400, 30000)
    # the two answers from the cache are apart: 40 and 60; rank ceil(1.9) = 2
    assert week.period.cached_total == Spread(2, 50, 60)


def test_how_long_each_step_took_from_the_point_before(week):
    s = week.period.steps
    assert s["t_parse"] == Spread(8, 300, 500)  # the first step is the time to the first point
    # 400 300 500 200 400 400 300, in order 200 300 300 400 400 400 500
    assert s["t_search"] == Spread(7, 400, 500)
    # 100 100 100 50 100
    assert s["t_rank"] == Spread(5, 100, 100)
    # 20 10 10 10 10
    assert s["t_sources_sent"] == Spread(5, 10, 20)
    # 1180 890 1990 640 1790, in order 640 890 1180 1790 1990
    assert s["t_first_token"] == Spread(5, 1180, 1990)
    # 7000 5500 17000 4000, in order 4000 5500 7000 17000
    assert s["t_written"] == Spread(4, 6250, 17000)
    # 500 400 600 200, in order 200 400 500 600
    assert s["t_checked"] == Spread(4, 450, 600)
    # the end, from the last point reached: 100 100 100 100, then 660 − 650, 760 − 750, 4000 − 2500, 30000 − 500
    assert s["t_total"] == Spread(8, 100, 29500)


def test_a_step_is_never_less_than_nothing_where_two_stages_ran_at_once(tmp_path, clock):
    log = SqliteBriefingLog(StateDB(tmp_path / "s.db", migrations=observe.migrations(), clock=clock), clock=clock)
    # the search finished before the question was read: the two ran side by side
    log.write(record("r1", "2026-11-12T10:00:00+00:00", **times(parse=300, search=250, rank=400)))
    steps = stats(log, since=timedelta(days=7), clock=clock).period.steps
    assert (steps["t_parse"].median, steps["t_search"].median, steps["t_rank"].median) == (300, 0, 100)


def test_cost_in_all_a_briefing_a_question_and_a_day(week):
    p = week.period
    assert p.cost_usd == 0.152  # 0.04 + 0.03 + 0.05 + 0.02 + 0.001 + 0.001 + 0.01: not the check's or the test's
    assert p.cost_per_written_usd == 0.035  # 0.14 over the four written
    assert p.cost_per_question_usd == 0.0152  # over all ten
    assert p.cost_per_day_usd == 0.021714  # 0.152 / 7, to six places
    assert p.cost_by_day == {"2026-11-07": 0.04, "2026-11-08": 0.08, "2026-11-09": 0.02, "2026-11-10": 0.002,
                             "2026-11-11": 0.01, "2026-11-12": 0.0}
    e = week.earlier
    assert (e.cost_usd, e.cost_per_written_usd, e.cost_per_question_usd) == (0.06, 0.03, 0.015)
    assert e.cost_per_day_usd == 0.002143  # 0.06 / 28


def test_the_answer_cache_hit_rate_is_cached_over_all(week):
    assert week.period.cache_hits == Rate(2, 10, 0.2)
    assert week.earlier.cache_hits == Rate(1, 4, 0.25)


def test_whether_prompt_caching_paid_back_priced_by_each_briefings_model(week):
    # read: 60,000 tokens at the large model's prices save 60,000 × (4.0 − 0.4) / 1,000,000 = 0.216, and 10,000
    # at the small model's save 10,000 × (1.0 − 0.1) / 1,000,000 = 0.009. Written: 32,000 at the small model's
    # cost 32,000 × 1.0 × (1.5 − 1) / 1,000,000 = 0.016 more than plain input.
    assert week.period.prompt_cache == PromptCache(read_tokens=70000, write_tokens=32000, saved_usd=0.225,
                                                   extra_usd=0.016, paid_back=True)
    assert week.earlier.prompt_cache == PromptCache(0, 0, 0.0, 0.0, None)  # not used: nothing to say


def test_without_prices_only_the_token_sums_are_given(log, clock):
    unpriced = stats(log, since=timedelta(days=7), clock=clock)
    assert unpriced.period.prompt_cache == PromptCache(70000, 32000, None, None, None)


def test_prompt_caching_that_writes_more_than_it_saves_did_not_pay_back(tmp_path, clock):
    log = SqliteBriefingLog(StateDB(tmp_path / "s.db", migrations=observe.migrations(), clock=clock), clock=clock)
    log.write(record("r1", "2026-11-12T10:00:00+00:00", model="large", cache_write_tokens=100000,
                     cache_read_tokens=1000))
    # saved 1,000 × 3.6 / 1,000,000 = 0.0036; extra 100,000 × 4.0 × 0.25 / 1,000,000 = 0.1
    assert stats(log, since=timedelta(days=7), pricing=PRICES, clock=clock).period.prompt_cache == PromptCache(
        1000, 100000, 0.0036, 0.1, False)


def test_check_failure_rates_are_over_the_briefings_whose_checks_ran(week):
    p = week.period
    assert p.invalid_citation == Rate(1, 4, 0.25)  # w2
    assert p.unsupported == Rate(1, 4, 0.25)  # w2
    assert p.unverified_quote == Rate(1, 4, 0.25)  # w3
    assert p.loaded_word == Rate(1, 4, 0.25)  # w3: the nightly check's nine loaded words are not a reader's
    assert p.any_check == Rate(2, 4, 0.5)  # w2 and w3
    assert week.earlier.any_check == week.earlier.invalid_citation == Rate(1, 2, 0.5)
    assert week.earlier.unsupported == Rate(0, 2, 0.0)


def test_no_records_not_useful_and_early_leaving_rates(week):
    p = week.period
    assert p.no_records == Rate(2, 10, 0.2)
    assert p.not_useful == Rate(2, 3, 2 / 3)  # of the three rated: w1 yes, w2 and w4 no
    assert p.left == Rate(1, 10, 0.1)
    assert p.left_at == {"writing": 1}
    e = week.earlier
    assert (e.no_records, e.not_useful, e.left, e.left_at) == (Rate(0, 4, 0.0), Rate(1, 2, 0.5), Rate(0, 4, 0.0), {})


def test_what_readers_did_next_is_over_saved_briefings_each_counted_once(week):
    p = week.period  # saved: w1, w2 and w4; the two replays from the cache are the same briefings again
    assert p.reported == Rate(1, 3, 1 / 3)
    assert p.corrected == Rate(1, 3, 1 / 3)
    assert p.followed_up == Rate(1, 3, 1 / 3)
    assert week.earlier.reported == Rate(0, 2, 0.0)


def test_errors_by_type(week):
    assert week.period.errors == Rate(1, 10, 0.1)
    assert week.period.errors_by_type == {"APITimeoutError": 1}  # not the test run's TestError
    assert week.earlier.errors == Rate(1, 4, 0.25)
    assert week.earlier.errors_by_type == {"RateLimitError": 1}  # and not the AncientError from before


def test_a_rate_with_nothing_to_count_in_is_none_not_nought(tmp_path, clock):
    log = SqliteBriefingLog(StateDB(tmp_path / "s.db", migrations=observe.migrations(), clock=clock), clock=clock)
    empty = stats(log, since=timedelta(days=7), clock=clock)
    assert empty.period.questions == 0
    assert empty.period.errors == empty.period.not_useful == empty.period.any_check == Rate(0, 0, None)
    assert empty.period.times["t_written"] == Spread(0, None, None)
    assert (empty.period.cost_usd, empty.period.cost_per_written_usd, empty.period.cost_per_day_usd) == (
        0.0, None, 0.0)
    assert (empty.by_config, empty.by_arm, empty.slowest, empty.themes) == ({}, {}, (), ())
    json.loads(empty.to_json())


# ---- the lists ---------------------------------------------------------------------------------------------------


def test_the_slowest_briefings_with_the_question_only_where_the_briefing_is_saved(week):
    assert [(b.id, b.t_written, b.question) for b in week.slowest] == [
        ("w3", 20000, None),  # not saved: its question is not public
        ("w1", 9000, LIBRARIES),
        ("w2", 7000, BUDGET),
        ("w4", 5000, None),  # saved, but since withdrawn or corrected
    ]
    assert [b.briefing_id for b in week.slowest] == [None, "b1", "b2", "b4"]
    assert (week.slowest[0].t_first_token, week.slowest[0].t_total, week.slowest[0].config_id) == (3000, 20700, "B")


def test_the_worst_checked_briefings_by_how_many_problems_were_found(week):
    # w2: one invalid citation and two unsupported sentences; w3: one unverified quotation and one loaded word
    assert [(b.id, b.question, b.citations_invalid, b.unsupported, b.quotes_unverified, b.loaded_words,
             b.grounded_ratio) for b in week.worst_checked] == [
        ("w2", BUDGET, 1, 2, 0, 0, 0.9), ("w3", None, 0, 0, 1, 1, 0.8)]


def test_among_equally_faulty_briefings_the_least_grounded_is_first_and_only_five_are_listed(tmp_path, clock):
    log = SqliteBriefingLog(StateDB(tmp_path / "s.db", migrations=observe.migrations(), clock=clock), clock=clock)
    for n, grounded in enumerate([0.9, 0.5, 0.7, None, 0.6, 0.8, 0.95]):
        log.write(record(f"r{n}", "2026-11-12T10:00:00+00:00", unsupported=1, grounded_ratio=grounded,
                         **times(written=1000 + n)))
    found = stats(log, since=timedelta(days=7), clock=clock)
    assert [b.id for b in found.worst_checked] == ["r1", "r4", "r2", "r5", "r0"]
    assert [b.id for b in found.slowest] == ["r6", "r5", "r4", "r3", "r2"]


def test_questions_that_found_no_records_with_how_often(week):
    assert week.no_record_questions == (Asked(MOON, 2),)  # asked twice, in two spellings: as it was first asked


def test_themes_by_text_when_there_is_no_embedder(week):
    assert week.themes_by == "text"
    assert week.themes == (
        Theme(LIBRARIES, 3, 1),  # w1, w3 and the replay c2: case and punctuation set aside
        Theme(MOON, 2, 1),  # then the two asked twice, in the order of their words
        Theme(BUDGET, 2, 1),
    )  # "Bin collections" was asked once: not a theme


def test_no_question_from_a_failed_or_withdrawn_briefing_is_ever_quoted(week):
    everything = week.to_json()
    assert FAILED not in everything and WITHDRAWN not in everything and NOT_SAVED not in everything
    assert "the nightly question" not in everything and "a test question" not in everything


class Meanings:
    """An embedder that knows what the week's questions are about (``ports.Embedder``), and counts its calls."""

    id = "test-meanings"
    dimension = 3

    def __init__(self) -> None:
        self.asked: list[list[str]] = []

    def embed_documents(self, texts):
        self.asked.append(list(texts))
        return tuple(self.embed_query(t) for t in texts)

    def embed_query(self, text):
        lower = text.lower()
        if "libraries" in lower:
            return (1, 0, 0)
        if "budget" in lower:
            return (0.0, 1.0, 0.0)
        if "moon" in lower:
            return (0.0, 0.0, 2.0)  # length does not matter: the likeness is the cosine
        return (3.0, 4.0, 0.0)  # bins: 0.6 like libraries, 0.8 like the budget


def test_themes_by_meaning_join_the_group_a_question_is_most_like(log, clock):
    embedder = Meanings()
    found = stats(log, since=timedelta(days=7), embedder=embedder, similarity=0.5, clock=clock)
    assert found.themes_by == "meaning"
    # bins are like libraries (0.6) and more like the budget (0.8): they join the budget, though libraries came first
    assert found.themes == (Theme(LIBRARIES, 3, 1), Theme(BUDGET, 3, 2), Theme(MOON, 2, 1))
    # one call, with each wording once, the most asked first; no question from a failed or withdrawn briefing
    assert embedder.asked == [[LIBRARIES, MOON, BUDGET, "Bin collections"]]


def test_themes_by_meaning_keep_apart_what_is_not_alike_enough(log, clock):
    apart = stats(log, since=timedelta(days=7), embedder=Meanings(), similarity=0.81, clock=clock)
    assert apart.themes == (Theme(LIBRARIES, 3, 1), Theme(MOON, 2, 1), Theme(BUDGET, 2, 1))
    at_the_line = stats(log, since=timedelta(days=7), embedder=Meanings(), similarity=0.8, clock=clock)
    assert Theme(BUDGET, 3, 2) in at_the_line.themes  # 0.8 is "at least" 0.8


def test_themes_by_meaning_are_the_same_whatever_order_the_records_come_in(tmp_path, clock):
    rows = [r for r in the_week() if r.kind == "reader"]
    found = []
    for name, ordered in (("a", rows), ("b", list(reversed(rows)))):
        log = SqliteBriefingLog(StateDB(tmp_path / f"{name}.db", migrations=observe.migrations(), clock=clock),
                                clock=clock)
        for row in ordered:
            log.write(row)
        found.append(stats(log, since=timedelta(days=7), embedder=Meanings(), similarity=0.5, clock=clock).themes)
    assert found[0] == found[1]


def test_an_embedder_needs_its_similarity_said(log, clock):
    with pytest.raises(ValueError, match="similarity"):
        stats(log, since=timedelta(days=7), embedder=Meanings(), clock=clock)


# ---- by configuration and by arm --------------------------------------------------------------------------------


def test_the_headline_figures_for_each_configuration_with_how_many_briefings_each_rests_on(week):
    assert list(week.by_config) == ["A", "B"]
    assert week.by_config["A"] == Headline(
        questions=6, written=2,  # w1 w2 c1 c2 n1 l1
        first_token=Spread(3, 2000, 2500),  # 1500 2000 2500
        full_briefing=Spread(2, 8000, 9000),  # 7000 9000
        cost_per_written_usd=0.035, cache_hits=Rate(2, 6, 1 / 3), any_check=Rate(1, 2, 0.5),
        no_records=Rate(1, 6, 1 / 6), not_useful=Rate(1, 2, 0.5), left=Rate(1, 6, 1 / 6), errors=Rate(0, 6, 0.0))
    assert week.by_config["B"] == Headline(
        questions=4, written=2,  # w3 w4 n2 e1
        first_token=Spread(2, 2000, 3000),  # 1000 3000
        full_briefing=Spread(2, 12500, 20000),  # 5000 20000
        cost_per_written_usd=0.035, cache_hits=Rate(0, 4, 0.0), any_check=Rate(1, 2, 0.5),
        no_records=Rate(1, 4, 0.25), not_useful=Rate(1, 1, 1.0), left=Rate(0, 4, 0.0), errors=Rate(1, 4, 0.25))
    assert list(week.by_config_earlier) == ["A"]
    assert week.by_config_earlier["A"].questions == 4 and week.by_config_earlier["A"].written == 2
    assert week.by_config_earlier["A"].full_briefing == Spread(2, 5000, 6000)
    # and the whole period's, which the weekly totals keep
    assert week.headline == Headline(
        questions=10, written=4, first_token=Spread(5, 2000, 3000), full_briefing=Spread(4, 8000, 20000),
        cost_per_written_usd=0.035, cache_hits=Rate(2, 10, 0.2), any_check=Rate(2, 4, 0.5),
        no_records=Rate(2, 10, 0.2), not_useful=Rate(2, 3, 2 / 3), left=Rate(1, 10, 0.1), errors=Rate(1, 10, 0.1))


def experiment(tmp_path, clock, arms: dict[str, tuple[int, int]]) -> SqliteBriefingLog:
    """A record with an experiment in it: for each arm, how many briefings were rated and how many not useful."""
    log = SqliteBriefingLog(StateDB(tmp_path / "x.db", migrations=observe.migrations(), clock=clock), clock=clock)
    for arm, (rated, not_useful) in arms.items():
        for n in range(rated):
            log.write(record(f"{arm}{n}", "2026-11-10T10:00:00+00:00", experiment="shorter", arm=arm,
                             config_id=f"cfg-{arm}", useful=n >= not_useful, briefing_id=f"{arm}{n}"))
    log.write(record("outside", "2026-11-10T10:00:00+00:00", useful=False))  # in no experiment
    return log


def test_two_arms_that_can_be_told_apart(tmp_path, clock):
    log = experiment(tmp_path, clock, {"a": (100, 20), "b": (100, 35)})
    found = stats(log, since=timedelta(days=7), decided_by="not_useful", clock=clock)
    assert list(found.by_arm) == ["shorter"] and list(found.by_arm["shorter"]) == ["a", "b"]
    assert found.by_arm["shorter"]["a"].questions == 100
    assert found.by_arm["shorter"]["a"].not_useful == Rate(20, 100, 0.2)
    assert found.by_arm["shorter"]["b"].not_useful == Rate(35, 100, 0.35)
    [compared] = found.arms
    assert (compared.experiment, compared.figure, compared.a, compared.b) == ("shorter", "not_useful", "a", "b")
    assert compared.z == pytest.approx(-2.3754, abs=1e-4) and compared.p_value == pytest.approx(0.0175, abs=1e-4)
    assert compared.enough is True
    assert "two-proportion z-test" in compared.test and "5% level" in compared.test
    assert found.decided_by == "not_useful"


def test_two_arms_with_too_few_briefings_to_tell(tmp_path, clock):
    log = experiment(tmp_path, clock, {"a": (50, 10), "b": (50, 14)})
    [compared] = stats(log, since=timedelta(days=7), decided_by="not_useful", clock=clock).arms
    assert compared.enough is False and compared.p_value == pytest.approx(0.349, abs=1e-3)


def test_three_arms_are_compared_two_at_a_time_and_none_without_a_deciding_figure(tmp_path, clock):
    log = experiment(tmp_path, clock, {"a": (40, 10), "b": (40, 10), "c": (40, 30)})
    found = stats(log, since=timedelta(days=7), decided_by="not_useful", clock=clock)
    assert [(c.a, c.b, c.enough) for c in found.arms] == [("a", "b", False), ("a", "c", True), ("b", "c", True)]
    assert stats(log, since=timedelta(days=7), clock=clock).arms == ()
    with pytest.raises(ValueError, match="cannot be decided by 'cost'"):
        stats(log, since=timedelta(days=7), decided_by="cost", clock=clock)


# ---- the two-proportion test, against examples worked by hand ---------------------------------------------------


def test_the_two_proportion_test_first_worked_example():
    # 20 of 100 against 35 of 100. Pooled: 55 / 200 = 0.275. Standard error:
    # sqrt(0.275 × 0.725 × (1/100 + 1/100)) = sqrt(0.0039875) = 0.063147.
    # z = (0.20 − 0.35) / 0.063147 = −2.3754. Two-sided p = 2 × (1 − Φ(2.3754)) = 0.0175: under 0.05.
    result = two_proportion_test(20, 100, 35, 100)
    assert result.z == pytest.approx(-0.15 / math.sqrt(0.0039875))
    assert result.z == pytest.approx(-2.3754, abs=1e-4)
    assert result.p_value == pytest.approx(0.0175, abs=1e-4)
    assert result.p_value == pytest.approx(2 * (1 - NormalDist().cdf(2.37542)), abs=1e-6)
    assert result.enough is True


def test_the_two_proportion_test_second_worked_example():
    # 10 of 50 against 14 of 50. Pooled: 24 / 100 = 0.24. Standard error:
    # sqrt(0.24 × 0.76 × (1/50 + 1/50)) = sqrt(0.007296) = 0.085417.
    # z = (0.20 − 0.28) / 0.085417 = −0.9366. Two-sided p = 2 × (1 − Φ(0.9366)) = 0.349: not under 0.05.
    result = two_proportion_test(10, 50, 14, 50)
    assert result.z == pytest.approx(-0.9366, abs=1e-4)
    assert result.p_value == pytest.approx(0.349, abs=1e-3)
    assert result.enough is False


def test_the_two_proportion_test_is_not_made_on_too_few():
    # 0 of 8 against 3 of 8: pooled 3/16, so each arm would expect 1.5: under 5, too few for the approximation
    assert two_proportion_test(0, 8, 3, 8) == TwoProportions(None, None, False)
    assert two_proportion_test(0, 50, 0, 50) == TwoProportions(None, None, False)  # nothing either way to compare
    assert two_proportion_test(5, 0, 5, 10) == TwoProportions(None, None, False)
    # 0 of 100 against 30 of 100: pooled 0.15, each expects 15 and 85: the test is made, and they differ
    assert two_proportion_test(0, 100, 30, 100).enough is True
    # the same proportion: z is nought and p is one
    same = two_proportion_test(25, 100, 50, 200)
    assert (same.z, same.p_value, same.enough) == (0.0, 1.0, False)
    # the sign follows the first arm
    assert two_proportion_test(35, 100, 20, 100).z == pytest.approx(2.3754, abs=1e-4)


# ---- periods -----------------------------------------------------------------------------------------------------


def test_a_period_may_be_given_by_its_start_and_its_end(log, clock, week):
    start, end = datetime.fromisoformat("2026-11-06T12:00:00+00:00"), datetime.fromisoformat(NOW)
    assert stats(log, since=start, until=end, pricing=PRICES, clock=FixedClock("2027-01-01T00:00:00+00:00")) == week
    assert stats(log, since=start, pricing=PRICES, clock=clock) == week
    with pytest.raises(ValueError, match="timezone"):
        stats(log, since=datetime(2026, 11, 6, 12), clock=clock)
    with pytest.raises(ValueError, match="begin before it ends"):
        stats(log, since=end, until=start, clock=clock)


def test_a_briefing_on_the_line_belongs_to_the_period_that_starts_there(tmp_path, clock):
    log = SqliteBriefingLog(StateDB(tmp_path / "s.db", migrations=observe.migrations(), clock=clock), clock=clock)
    log.write(record("at-earlier-start", "2026-10-09T12:00:00+00:00"))
    log.write(record("at-start", "2026-11-06T12:00:00+00:00"))
    log.write(record("at-end", NOW))
    found = stats(log, since=timedelta(days=7), clock=clock)
    assert (found.earlier.questions, found.period.questions) == (1, 1)


def test_the_weeks_compared_with_can_be_changed(log, clock):
    one = stats(log, since=timedelta(days=7), compare_weeks=1, clock=clock)
    assert (one.earlier.start, one.earlier.days, one.scale) == ("2026-10-30T12:00:00+00:00", 7.0, 1.0)
    assert one.earlier.questions == 1 and one.earlier.errors_by_type == {"RateLimitError": 1}  # only o4
    with pytest.raises(ValueError, match="compare_weeks"):
        stats(log, since=timedelta(days=7), compare_weeks=0, clock=clock)


def test_the_json_form_holds_every_figure(week):
    data = json.loads(week.to_json())
    assert data == json.loads(json.dumps(week.as_dict()))
    assert data["period"]["times"]["t_written"] == {"n": 4, "median": 8000.0, "p95": 20000.0}
    assert data["period"]["errors"] == {"count": 1, "of": 10, "rate": 0.1}
    assert data["earlier"]["questions"] == 4 and data["scale"] == 0.25
    assert data["by_config"]["B"]["written"] == 2
    assert data["slowest"][1]["question"] == LIBRARIES and data["slowest"][0]["question"] is None
    assert data["themes"][0] == {"example": LIBRARIES, "questions": 3, "wordings": 1}
    assert data["no_record_questions"] == [{"question": MOON, "times": 2}]
