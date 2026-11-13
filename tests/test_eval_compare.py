"""Runs kept, set side by side and held to thresholds: wts_core.eval.compare."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from adapters_sites import sites_dir
from wts_core.eval import (
    FIGURES,
    PASSED_FILE,
    CaseResult,
    Change,
    Run,
    check_thresholds,
    compare,
    has_passed,
    load,
    mark_passed,
    passed_line,
    save,
    summarise,
)


def briefing(qid: str, grounded: float, invalid: int, unsupported: int, first: int, end: int, cost: float,
             **more: object) -> CaseResult:
    return CaseResult(id=qid, question=f"What about {qid}?", category="topic", outcome="completed",
                      citations_total=10, citations_invalid=invalid, grounded_ratio=grounded,
                      unsupported=unsupported, quotes_total=2, quotes_unverified=0, loaded_words=0, sources=4,
                      spread={"Labour": 2, "Conservative": 2}, ms_to_first_word=first, ms_to_end=end, cost_usd=cost,
                      input_tokens=5000, output_tokens=800, **more)  # type: ignore[arg-type]  # a test's shorthand


def a_run(config_id: str, started_at: str, results: list[CaseResult], cases: int | None = None) -> Run:
    return Run(config_id, {"model": "big", "sources": 24}, started_at, results, summarise(results, cases=cases))


@pytest.fixture
def first() -> Run:
    return a_run("aaaa1111bbbb", "2026-11-06T09:30:00+00:00", [
        briefing("wind", 0.9, 1, 2, 1500, 4000, 0.03, expect_met={"houses": True}),
        briefing("nhs", 1.0, 0, 0, 500, 2000, 0.012),
        briefing("bins", 0.8, 0, 1, 900, 9000, 0.018, judged=0.5),
        CaseResult("boom", "What breaks?", "awkward", outcome="error", error_type="RuntimeError", ms_to_end=1000),
        briefing("old", 1.0, 0, 0, 400, 1000, 0.01),
    ])


@pytest.fixture
def second() -> Run:
    return a_run("cccc2222dddd", "2026-11-13T14:05:09+00:00", [
        briefing("wind", 1.0, 0, 0, 1200, 4100, 0.02, expect_met={"houses": False}),  # better checks, slower end
        briefing("nhs", 1.0, 0, 0, 500, 2000, 0.012),  # the same
        briefing("bins", 0.7, 0, 2, 900, 9000, 0.018, judged=0.75),  # less grounded, judged better
        briefing("boom", 1.0, 0, 0, 800, 3000, 0.02),  # no longer an error
        briefing("new", 1.0, 0, 0, 400, 1000, 0.01),
    ])


# ---- saving and loading --------------------------------------------------------------------------------------


def test_a_run_is_saved_under_its_date_and_configuration_and_read_back_whole(first, tmp_path):
    path = save(first, tmp_path / "eval" / "runs")
    # the date first, as Where MPs Stand names its runs, so the folder lists them in order
    assert path == tmp_path / "eval" / "runs" / "20261106-093000-eval-aaaa1111bbbb.json"
    assert load(path) == first
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert (raw["stage"], raw["format"], raw["config_id"]) == ("eval", 1, "aaaa1111bbbb")
    assert raw["summary"] == first.summary and len(raw["results"]) == 5


def test_runs_sort_by_date_whatever_their_configuration(first, second, tmp_path):
    names = [save(run, tmp_path).name for run in (second, first)]
    assert sorted(names) == ["20261106-093000-eval-aaaa1111bbbb.json", "20261113-140509-eval-cccc2222dddd.json"]
    # caught by none of Where MPs Stand's patterns for its own runs, which its .gitignore and its commands use
    assert not any(part in name for name in names for part in ("-plans-", "-sources-", "-briefings-"))


def test_a_configuration_id_that_is_no_file_name_is_made_one(first, tmp_path):
    assert save(replace(first, config_id="arm b/2"), tmp_path).name == "20261106-093000-eval-arm-b-2.json"


def test_a_later_versions_extra_fields_are_passed_over(first, tmp_path):
    path = save(first, tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["results"][0]["something_new"] = 1
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load(path) == first


def test_a_file_that_is_not_a_run_saved_here_is_refused_by_name(tmp_path):
    path = tmp_path / "20261011-125201-plans-a-model.json"
    path.write_text(json.dumps({"stage": "plans", "rows": [], "summary": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="is not a run saved by wts_core.eval .its stage is 'plans'.") as refused:
        load(path)
    assert str(path) in str(refused.value)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="is not a run saved by wts_core.eval"):
        load(path)


def test_where_mps_stands_runs_from_before_the_package_stay_with_its_own_code():
    """Its saved runs are of how questions were read, sources graded and two models' briefings judged: none holds
    what a run here holds, so each is refused plainly, not half read."""
    home = sites_dir()
    runs = sorted((home / "wherempsstand" / "eval" / "runs").glob("*.json")) if home else []
    if not runs:
        pytest.skip("no eval/runs in a checkout of wherempsstand beside this repository or under WTS_SITES_DIR")
    for path in runs:
        with pytest.raises(ValueError, match="is not a run saved by wts_core.eval"):
            load(path)


# ---- two runs side by side -----------------------------------------------------------------------------------


def test_each_figure_and_each_question_is_set_side_by_side(first, second):
    c = compare(first, second)
    overall = {x.figure: x for x in c.figures}
    assert set(overall) == set(first.summary) | set(second.summary) and set(overall) <= set(FIGURES)
    # grounded: (0.9 + 1.0 + 0.8 + 1.0) / 4 against (1.0 + 1.0 + 0.7 + 1.0 + 1.0) / 5
    assert overall["grounded_ratio"] == Change("grounded_ratio", 0.925, 0.94, "better")
    assert overall["invalid_citations"] == Change("invalid_citations", 1, 0, "better")
    assert overall["unsupported"] == Change("unsupported", 3, 2, "better")
    assert overall["errors"] == Change("errors", 1, 0, "better")
    assert overall["judged"] == Change("judged", 0.5, 0.75, "better")
    assert overall["p95_ms_to_end"] == Change("p95_ms_to_end", 9000, 9000, "unchanged")
    assert overall["median_ms_to_end"] == Change("median_ms_to_end", 2000, 3000, "worse")  # 2nd of 4; 3rd of 5
    assert overall["cost_usd"] == Change("cost_usd", 0.07, 0.08, "worse")
    assert overall["completed"] == Change("completed", 4, 5, "changed")  # neither way is better in itself
    assert overall["expectations_met_rate"] == Change("expectations_met_rate", 1.0, 0.0, "worse")

    assert list(c.questions) == ["wind", "nhs", "bins", "boom"] and (c.only_in_a, c.only_in_b) == (("old",), ("new",))
    assert [x for x in c.questions["wind"] if x.verdict != "unchanged"] == [
        Change("grounded ratio", 0.9, 1.0, "better"), Change("citations not found", 1, 0, "better"),
        Change("unsupported sentences", 2, 0, "better"), Change("ms to the first word", 1500, 1200, "better"),
        Change("ms to the end", 4000, 4100, "worse"), Change("cost in dollars", 0.03, 0.02, "better"),
        Change("expectations met", True, False, "worse")]
    assert {x.verdict for x in c.questions["nhs"]} == {"unchanged"}
    assert [x for x in c.questions["bins"] if x.verdict != "unchanged"] == [
        Change("grounded ratio", 0.8, 0.7, "worse"), Change("unsupported sentences", 1, 2, "worse"),
        Change("judged score", 0.5, 0.75, "better")]
    # ended differently: compared on that alone, not a briefing's time and cost against an error's
    assert c.questions["boom"] == (Change("outcome", "error", "completed", "better"),)
    # a question is worse if any of its figures is worse
    assert (c.better, c.worse, c.unchanged) == (("boom",), ("wind", "bins"), ("nhs",))


def test_a_small_movement_can_count_as_unchanged(first, second):
    c = compare(first, second, same_within=0.05)
    assert Change("ms to the end", 4000, 4100, "unchanged") in c.questions["wind"]  # two and a half per cent
    assert Change("ms to the first word", 1500, 1200, "better") in c.questions["wind"]  # a fifth
    assert Change("grounded_ratio", 0.925, 0.94, "unchanged") in c.figures


def test_a_run_compared_with_itself_has_nothing_better_or_worse(first):
    c = compare(first, first)
    assert {x.verdict for x in c.figures} == {"unchanged"}
    assert (c.better, c.worse, c.only_in_a, c.only_in_b) == ((), (), (), ())
    assert "| Question | What changed |" not in c.to_markdown()


def test_a_question_that_now_fails_is_worse_and_one_not_run_is_not_compared(first):
    failing = replace(first, results=[
        CaseResult("wind", "What about wind?", "topic", outcome="error", error_type="TimeoutError", ms_to_end=9),
        CaseResult("nhs", "What about nhs?", "topic")])  # not run: the budget ran out
    c = compare(first, failing)
    assert c.questions["wind"] == (Change("outcome", "completed", "error", "worse"),)
    assert list(c.questions) == ["wind"] and c.only_in_a == ("nhs", "bins", "boom", "old")


def test_the_comparison_as_a_document(first, second):
    assert compare(first, second).to_markdown() == """\
# Evaluation: cccc2222dddd compared with aaaa1111bbbb

The first run, aaaa1111bbbb, was made on 6 November 2026 and asked 5 questions. The second, cccc2222dddd, was made \
on 13 November 2026 and asked 5. "Better" and "worse" are the second against the first.

## Overall

| Figure | aaaa1111bbbb | cccc2222dddd | |
|---|---|---|---|
| Questions in the set | 5 | 5 | |
| Questions asked | 5 | 5 | |
| Questions not asked | 0 | 0 | |
| Briefings written | 4 | 5 | changed |
| Answers of "no records" | 0 | 0 | |
| Errors | 1 | 0 | better |
| Share of questions that ended in an error | 0.2 | 0 | better |
| Grounded ratio (mean) | 0.925 | 0.94 | better |
| Citations | 40 | 50 | changed |
| Citations not found in their source | 1 | 0 | better |
| Share of citations not found in their source | 0.025 | 0 | better |
| Unsupported sentences | 3 | 2 | better |
| Share of briefings with an unsupported sentence | 0.5 | 0.2 | better |
| Quotations | 8 | 10 | changed |
| Quotations not found word for word | 0 | 0 | |
| Share of quotations not found word for word | 0 | 0 | |
| Loaded words | 0 | 0 | |
| Share of briefings with a loaded word | 0 | 0 | |
| Judged score (mean) | 0.5 | 0.75 | better |
| Briefings judged | 1 | 1 | |
| Sources for a briefing (mean) | 4 | 4 | |
| Groups among a briefing's sources (mean) | 2 | 2 | |
| Share of a briefing's sources from its largest group (mean) | 0.5 | 0.5 | |
| Time to the first word, median (ms) | 500 | 800 | worse |
| Time to the first word, 95th percentile (ms) | 1,500 | 1,200 | better |
| Time to the end, median (ms) | 2,000 | 3,000 | worse |
| Time to the end, 95th percentile (ms) | 9,000 | 9,000 | |
| Cost (US dollars) | 0.07 | 0.08 | worse |
| Cost for each question (US dollars) | 0.014 | 0.016 | worse |
| Input tokens | 20,000 | 25,000 | changed |
| Output tokens | 3,200 | 4,000 | changed |
| Tokens read from the cache | 0 | 0 | |
| Tokens written to the cache | 0 | 0 | |
| Questions with expectations checked | 1 | 1 | |
| Share of those that met every expectation | 1 | 0 | worse |

## Question by question

Of 4 questions asked in both runs: 1 better, 2 worse, 1 neither.

| Question | What changed |
|---|---|
| wind | grounded ratio: 0.9 to 1 (better); citations not found: 1 to 0 (better); unsupported sentences: 2 to 0 \
(better); ms to the first word: 1,500 to 1,200 (better); ms to the end: 4,000 to 4,100 (worse); cost in dollars: \
0.03 to 0.02 (better); expectations met: yes to no (worse) |
| bins | grounded ratio: 0.8 to 0.7 (worse); unsupported sentences: 1 to 2 (worse); judged score: 0.5 to 0.75 \
(better) |
| boom | outcome: error to completed (better) |

Asked only in aaaa1111bbbb: old.

Asked only in cccc2222dddd: new.
"""


# ---- thresholds ----------------------------------------------------------------------------------------------

THRESHOLDS = {"min_grounded_ratio": 0.9, "max_invalid_citations": 1, "max_unsupported_rate": 0.5,
              "max_p95_ms_to_end": 9000}


def test_a_run_that_meets_every_threshold_passes(first):
    # each exactly at its limit or within it: grounded 0.925, one invalid citation, half with an unsupported
    # sentence, 9,000 ms
    assert check_thresholds(first, THRESHOLDS) == []
    assert check_thresholds(first, {}) == []


@pytest.mark.parametrize(("name", "limit", "says"), [
    ("min_grounded_ratio", 0.95, "Grounded ratio (mean): 0.925 is below the least allowed, 0.95."),
    ("max_invalid_citations", 0, "Citations not found in their source: 1 is above the most allowed, 0."),
    ("max_unsupported_rate", 0.25, "Share of briefings with an unsupported sentence: 0.5 is above the most allowed, "
                                   "0.25."),
    ("max_p95_ms_to_end", 8000, "Time to the end, 95th percentile (ms): 9,000 is above the most allowed, 8,000."),
    ("max_error_rate", 0.1, "Share of questions that ended in an error: 0.2 is above the most allowed, 0.1."),
    ("min_judged", 0.6, "Judged score (mean): 0.5 is below the least allowed, 0.6."),
    ("max_cost_per_question_usd", 0.01, "Cost for each question (US dollars): 0.014 is above the most allowed, 0.01."),
])
def test_each_threshold_that_is_missed_is_said_in_a_sentence(first, name, limit, says):
    assert check_thresholds(first, {**THRESHOLDS, name: limit}) == [says]


def test_every_threshold_missed_is_listed(first):
    assert len(check_thresholds(first, {"min_grounded_ratio": 0.99, "max_invalid_citations": 0,
                                        "max_unsupported_rate": 0.1, "max_p95_ms_to_end": 1})) == 4


def test_a_threshold_on_a_figure_the_run_does_not_have_is_a_failure(second):
    without_judging = replace(second, summary={k: v for k, v in second.summary.items() if k != "judged"})
    assert check_thresholds(without_judging, {"min_judged": 0.5}) == [
        "Judged score (mean): the run has no such figure, and min_judged is set to 0.5."]


@pytest.mark.parametrize("name", ["min_grounded", "max_p95", "grounded_ratio", "minimum_grounded_ratio", "max_",
                                  "least_grounded_ratio"])
def test_an_unknown_threshold_is_an_error_and_never_passed_over(first, name):
    with pytest.raises(ValueError, match=f"unknown threshold '{name}'"):
        check_thresholds(first, {name: 1.0})


# ---- the note of a pass, which the experiment guard reads ----------------------------------------------------


def test_a_run_that_passes_is_noted_and_its_configuration_has_then_passed(first, tmp_path):
    folder = tmp_path / "eval" / "runs"
    assert not has_passed(folder, "aaaa1111bbbb")  # no file yet
    path = mark_passed(first, THRESHOLDS, folder)
    assert path == folder / PASSED_FILE == folder / "passed.jsonl"
    (line,) = [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()]
    assert line == {"config_id": "aaaa1111bbbb", "date": "2026-11-06", "started_at": "2026-11-06T09:30:00+00:00",
                    "thresholds": THRESHOLDS, "figures": first.summary} == passed_line(first, THRESHOLDS)
    assert has_passed(folder, "aaaa1111bbbb")
    # exactly that configuration: no other, and none at all for an empty id
    assert not has_passed(folder, "cccc2222dddd") and not has_passed(folder, "aaaa1111") and not has_passed(folder, "")


def test_passes_are_added_to_and_never_overwritten(first, second, tmp_path):
    mark_passed(first, THRESHOLDS, tmp_path)
    mark_passed(second, {"min_grounded_ratio": 0.9}, tmp_path)
    assert len((tmp_path / PASSED_FILE).read_text(encoding="utf-8").splitlines()) == 2
    assert has_passed(tmp_path, "aaaa1111bbbb") and has_passed(tmp_path, "cccc2222dddd")


def test_a_run_that_fails_cannot_be_noted_as_a_pass(first, tmp_path):
    with pytest.raises(ValueError, match="the run did not pass: Grounded ratio .mean.: 0.925 is below"):
        mark_passed(first, {"min_grounded_ratio": 0.95}, tmp_path)
    assert not (tmp_path / PASSED_FILE).exists() and not has_passed(tmp_path, "aaaa1111bbbb")


def test_a_run_held_to_nothing_has_passed_nothing(first, tmp_path):
    with pytest.raises(ValueError, match="held to nothing"):
        mark_passed(first, {}, tmp_path)
    with pytest.raises(ValueError, match="no configuration id"):
        passed_line(replace(first, config_id=""), THRESHOLDS)


def test_a_pass_is_for_the_whole_set(first, tmp_path):
    """A run of a few chosen questions, or one stopped by the budget, meets the thresholds on what it asked and
    still cannot let a configuration go live."""
    chosen = a_run("aaaa1111bbbb", first.started_at, first.results[:2], cases=5)
    with pytest.raises(ValueError, match="2 of the set's 5 questions were asked"):
        mark_passed(chosen, {"min_grounded_ratio": 0.9}, tmp_path)
    stopped = a_run("aaaa1111bbbb", first.started_at, [*first.results[:2], CaseResult("bins", "What about bins?")])
    assert (stopped.summary["questions"], stopped.summary["cases"]) == (2, 3)
    with pytest.raises(ValueError, match="2 of the set's 3 questions were asked"):
        mark_passed(stopped, {"min_grounded_ratio": 0.9}, tmp_path)
    with pytest.raises(ValueError, match="0 of the set's 0 questions"):
        mark_passed(a_run("aaaa1111bbbb", first.started_at, []), {"max_errors": 0}, tmp_path)


def test_thresholds_raised_since_are_not_got_round_by_an_old_pass(first, tmp_path):
    mark_passed(first, THRESHOLDS, tmp_path)
    assert has_passed(tmp_path, "aaaa1111bbbb", THRESHOLDS)
    assert not has_passed(tmp_path, "aaaa1111bbbb", {**THRESHOLDS, "min_grounded_ratio": 0.95})
    # a later run of the same configuration that meets the raised threshold counts
    better = a_run("aaaa1111bbbb", "2026-11-13T10:00:00+00:00", [replace(r, grounded_ratio=1.0) if r.outcome ==
                                                                 "completed" else r for r in first.results])
    mark_passed(better, {**THRESHOLDS, "min_grounded_ratio": 0.95}, tmp_path)
    assert has_passed(tmp_path, "aaaa1111bbbb", {**THRESHOLDS, "min_grounded_ratio": 0.95})
    with pytest.raises(ValueError, match="unknown threshold"):
        has_passed(tmp_path, "aaaa1111bbbb", {"min_everything": 1})


def test_a_line_that_is_no_note_of_a_pass_is_named_for_the_owner(first, tmp_path: Path):
    mark_passed(first, THRESHOLDS, tmp_path)
    with (tmp_path / PASSED_FILE).open("a", encoding="utf-8") as fh:
        fh.write("\nnot json\n")
    assert has_passed(tmp_path, "aaaa1111bbbb")  # found before the bad line is reached
    with pytest.raises(ValueError, match="passed.jsonl, line 3: not the note of a pass"):
        has_passed(tmp_path, "cccc2222dddd")
