"""The three functions the sites' rankings share (wts_core.checks.balance).

The arithmetic tests are Where MPs Stand's (tests/test_scoring.py), the only site that tests it directly, with its
own numbers passed in. No site tests the round-robin on its own (docs/study/ai-slice.md, section 5): those cases are
here. That each gives exactly what each site's own function gives is shown in test_checks_parity.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from wts_core.checks import blend, recency_factor, round_robin

TODAY = date(2026, 10, 1)
MPS = {"floor": 0.35, "min_half_life_years": 0.5}  # Where MPs Stand's settings
OTHERS = {"floor": 0.35, "min_half_life_years": 3.0}  # Where Countries Stand's and Where Councils Stand's

# ---- the recency factor -----------------------------------------------------------------------------------------


def test_recency_factor_properties():
    # Where MPs Stand's default slider, 0.25: a half-life of two years
    assert recency_factor(TODAY, TODAY, recency=0.25, **MPS) == pytest.approx(1.0)
    assert recency_factor(date(2024, 10, 1), TODAY, recency=0.25, **MPS) == pytest.approx(0.35 + 0.65 * 0.5, abs=0.005)
    assert recency_factor(date(2012, 1, 1), TODAY, recency=0.0, **MPS) == 1.0


def test_the_slider_reaches_a_six_month_half_life():
    # 12 November 2026: testers wanted recent contributions to lead much more strongly than a 2-year half-life allowed
    assert recency_factor(date(2026, 4, 1), TODAY, recency=1.0, **MPS) == pytest.approx(0.35 + 0.65 * 0.5, abs=0.01)
    assert recency_factor(date(2024, 10, 1), TODAY, recency=1.0, **MPS) < 0.4  # two years old: close to the floor


def test_the_floor_is_what_keeps_an_old_record():
    # a 16-year-old record keeps 35% of its weight, however hard the slider is pushed
    assert recency_factor(date(2010, 6, 1), TODAY, recency=1.0, **MPS) == pytest.approx(0.35, abs=0.01)
    assert recency_factor(date(1990, 1, 1), TODAY, recency=1.0, **OTHERS) > 0.35


def test_each_sites_half_life_is_its_own():
    three_years = date(2023, 10, 1)
    assert recency_factor(three_years, TODAY, recency=1.0, **OTHERS) == pytest.approx(0.35 + 0.65 * 0.5, abs=0.001)
    assert recency_factor(three_years, TODAY, recency=0.4, **OTHERS) > recency_factor(three_years, TODAY, recency=1.0,
                                                                                    **OTHERS)


def test_a_record_dated_after_today_counts_as_todays():
    assert recency_factor(date(2027, 1, 1), TODAY, recency=1.0, **MPS) == 1.0
    assert recency_factor(TODAY, TODAY, recency=-1.0, **MPS) == 1.0  # a slider below nought is nought


# ---- the blend of relevance scores ------------------------------------------------------------------------------


def test_hybrid_relevance_combines_keyword_and_semantic():
    # "kw-only", "sem-only", "both"
    rel = blend([10.0, None, 8.0], [None, 0.8, 0.7], word_weight=0.5, meaning_floor=0.0, meaning_ceiling=0.8)
    assert rel[0] == pytest.approx(0.5) and rel[1] == pytest.approx(0.5)
    assert rel[2] == max(rel)


def test_weak_semantic_matches_are_not_inflated():
    """A semantic-only hit near the model's 'unrelated' similarity must not outrank a strong keyword hit,
    even when it is the best semantic hit in the candidate set."""
    weak_semantic, strong_keyword = blend([None, 15.0], [0.52, None], word_weight=0.5, meaning_floor=0.5,
                                          meaning_ceiling=0.85)
    assert strong_keyword > weak_semantic and weak_semantic < 0.05


def test_with_one_kind_of_score_that_kind_is_all():
    assert blend([4.0, 2.0, None, 0.0], [None] * 4, word_weight=0.5, meaning_floor=0.5, meaning_ceiling=0.85) == [
        1.0, 0.5, 0.0, 0.0]
    assert blend([None, 0.0], [0.85, 0.5], word_weight=0.5, meaning_floor=0.5, meaning_ceiling=0.85) == [1.0, 0.0]
    assert blend([None, None], [None, None], word_weight=0.5, meaning_floor=0.5, meaning_ceiling=0.85) == [0.0, 0.0]
    assert blend([], [], word_weight=0.5, meaning_floor=0.5, meaning_ceiling=0.85) == []


def test_similarity_is_placed_within_the_models_range():
    rel = blend([None] * 3, [0.2, 0.675, 0.99], word_weight=0.5, meaning_floor=0.5, meaning_ceiling=0.85)
    assert rel == [0.0, pytest.approx(0.5), 1.0]
    # a ceiling at or below the floor divides by nothing
    assert blend([None], [0.9], word_weight=0.5, meaning_floor=0.8, meaning_ceiling=0.8) == [1.0]


def test_every_candidate_has_both_scores_or_none_is_given():
    with pytest.raises(ValueError):
        blend([1.0, 2.0], [0.5], word_weight=0.5, meaning_floor=0.5, meaning_ceiling=0.85)


# ---- the round-robin across groups ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Record:
    id: str
    group: str
    score: float
    speaker: str = ""
    meeting: str = ""


def pick(pool: list[Record], limit: int, **more) -> list[str]:
    chosen = round_robin(pool, limit, group_of=lambda r: r.group, key_of=lambda r: r.id, score_of=lambda r: r.score,
                         **more)
    return [r.id for r in chosen]


def in_score_order(*records: Record) -> list[Record]:
    return sorted(records, key=lambda r: -r.score)


POOL = in_score_order(Record("a1", "a", 0.9), Record("a2", "a", 0.8), Record("a3", "a", 0.7), Record("b1", "b", 0.6),
                      Record("c1", "c", 0.5), Record("b2", "b", 0.4))


def test_the_groups_take_turns_so_the_strongest_group_does_not_crowd_out_the_rest():
    assert pick(POOL, 3) == ["a1", "b1", "c1"]  # by score alone it would be a1, a2, a3
    assert pick(POOL, 4) == ["a1", "a2", "b1", "c1"]  # the second round starts again with the best group
    assert pick(POOL, 5) == ["a1", "a2", "b1", "c1", "b2"]


def test_the_result_is_in_order_of_score_then_id():
    tied = [Record("z", "a", 0.5), Record("y", "b", 0.5), Record("x", "c", 0.5), Record("w", "a", 0.9)]
    assert pick(in_score_order(*tied), 4) == ["w", "x", "y", "z"]


def test_groups_with_the_same_best_score_take_turns_in_the_order_they_were_met():
    pool = [Record("b1", "b", 0.5), Record("a1", "a", 0.5), Record("b2", "b", 0.4), Record("a2", "a", 0.4)]
    assert pick(pool, 1) == ["b1"] and pick(pool, 3) == ["a1", "b1", "b2"]


def test_a_limit_larger_than_the_pool_takes_everything_once():
    assert pick(POOL, 100) == ["a1", "a2", "a3", "b1", "c1", "b2"]
    assert pick(POOL, 0) == [] and pick(POOL, -1) == [] and pick([], 5) == []
    assert pick([POOL[0], POOL[0], POOL[1]], 5) == ["a1", "a2"]  # a record met twice is taken once


def test_a_cap_holds_however_many_places_are_left():
    pool = in_score_order(Record("a1", "a", 0.9, speaker="smith"), Record("a2", "a", 0.8, speaker="smith"),
                          Record("a3", "a", 0.7, speaker="smith"), Record("b1", "b", 0.6, speaker="jones"),
                          Record("a4", "a", 0.3, speaker="patel"))
    assert pick(pool, 5, caps=[(lambda r: r.speaker, 2)]) == ["a1", "a2", "b1", "a4"]
    assert pick(pool, 5, caps=[(lambda r: r.speaker, 1)]) == ["a1", "b1", "a4"]


def test_every_cap_must_allow_a_record():
    # Where Councils Stand's two: two records to a council, one to a meeting
    pool = in_score_order(Record("x:1:a", "lab", 0.9, speaker="x", meeting="x:1"),
                          Record("x:1:b", "lab", 0.8, speaker="x", meeting="x:1"),
                          Record("x:2:a", "lab", 0.7, speaker="x", meeting="x:2"),
                          Record("x:3:a", "lab", 0.6, speaker="x", meeting="x:3"),
                          Record("y:1:a", "con", 0.5, speaker="y", meeting="y:1"))
    caps = [(lambda r: r.speaker, 2), (lambda r: r.meeting, 1)]
    assert pick(pool, 5, caps=caps) == ["x:1:a", "x:2:a", "y:1:a"]


def test_when_a_group_runs_dry_the_others_fill_its_places():
    pool = in_score_order(Record("a1", "a", 0.9), Record("b1", "b", 0.8), Record("b2", "b", 0.7),
                          Record("b3", "b", 0.6))
    assert pick(pool, 4) == ["a1", "b1", "b2", "b3"]


def test_seeds_are_taken_first_within_the_caps_and_the_limit():
    seeds = [POOL[2], POOL[5]]  # a3 and b2: neither would be chosen in three by turns
    assert pick(POOL, 3, seeds=seeds) == ["a1", "a3", "b2"]
    assert pick(POOL, 1, seeds=seeds) == ["a3"]
    capped = pick(POOL, 4, seeds=[POOL[2], POOL[1]], caps=[(lambda r: r.group, 1)])
    assert capped == ["a3", "b1", "c1"]  # the second seed is over its cap, and so is every other record of "a"
