"""Live runs, with a site that says what it is told: wts_core.eval.run.

The scripted site sends events written out by hand and moves a fixed clock between them, so every figure of every
result, and of the summary, is worked out in the test and compared exactly. No model is called.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest

from checks_sites import COUNCILS
from eval_briefings import BLOCKS, DOCUMENTS, HEADINGS, QUESTION
from wts_core.eval import (
    Case,
    CaseResult,
    EvalSite,
    Judges,
    Recording,
    Records,
    Scores,
    checked,
    load_fixture,
    percentile,
    replay,
    run,
    summarise,
)
from wts_core.events import Answer, Event
from wts_core.ports import Price
from wts_core.testing import FixedClock
from wts_core.usage import PriceTable

# dollars for each million tokens: the briefing model's are the base prices, the model that reads questions has its own
PRICES = PriceTable(base=Price(input=3.0, output=15.0, cache_read=0.3, cache_write_multiplier=1.25),
                    models=(("small", Price(input=1.0, output=5.0, cache_read=0.1)),))
CONFIG = {"model": "big", "parse_model": "small", "sources": 24}

CASES = (
    Case("wind", "Where do rural and city MPs differ on onshore wind?", {"category": "topic", "houses": ["commons"]}),
    Case("nhs", "What has been said about NHS waiting lists?", {"category": "topic"}),
    Case("none", "What was said about bins in 1995?", {"category": "sparse", "no_records": True}),
    Case("boom", "What breaks?", {"category": "awkward"}),
    Case("declined", "What is declined?", {"category": "awkward"}),
    Case("evidence", "What is found when nothing can be written?", {"category": "topic", "no_records": False}),
    Case("third", "What about potholes?", {"category": "topic"}),
)


def usage(inp: int, out: int, read: int = 0, write: int = 0) -> dict[str, int]:
    """Token counts as the sites store them: the input count includes the cache writes."""
    return {"input_tokens": inp, "output_tokens": out, "cache_read_tokens": read, "cache_write_tokens": write}


def answer(grounded: float, citations: int, invalid: int, unsupported: int, loaded: int, quotes: int,
           unverified: int, no_records: bool = False) -> Answer:
    return {"segments": [], "markdown": "", "no_records": no_records, "citations_total": citations,
            "citations_invalid": invalid, "grounded_ratio": grounded, "unsupported_segments": unsupported,
            "loaded_words": loaded, "quotes_total": quotes, "quotes_unverified": unverified, "rules": 1}


def cards(*parties: str) -> dict[str, Any]:
    return {"type": "sources", "sources": [{"n": n, "party": p} for n, p in enumerate(parties, start=1)]}


NO_RECORDS: Answer = {"segments": [], "markdown": "No records found.", "no_records": True, "citations_total": 0,
                      "citations_invalid": 0, "grounded_ratio": 1.0, "unsupported_segments": 0}

# What each question's pipeline does: a number moves the clock on by that many seconds, an exception is raised,
# anything else is an event sent.
SCRIPTS: dict[str, list[Any]] = {
    # the plan at 200 ms, the sources at 500, the first word at 1,500, the end at 4,000
    "wind": [0.2, {"type": "plan", "plan": {"houses": ["commons"]}, "usage": usage(1000, 100)},
             0.3, cards("Labour", "Labour", "Conservative", "Liberal Democrat"),
             1.0, {"type": "text", "text": "Rural "}, 0.5, {"type": "citation", "search_result_index": 0,
                                                            "cited_text": "…"},
             {"type": "text", "text": "members said…"},
             2.0, {"type": "final", "answer": answer(0.9, 10, 1, 2, 1, 4, 1), "usage": usage(5000, 800, 2000, 1000),
                   "model": "big-2026", "stop_reason": "end_turn"}],
    # a plan read by the built-in rules (no usage); the final event names no model
    "nhs": [{"type": "plan", "plan": {}, "usage": None}, cards("Labour", "Conservative"),
            0.5, {"type": "text", "text": "Ministers "}, 1.5,
            {"type": "final", "answer": answer(1.0, 6, 0, 0, 0, 0, 0), "usage": usage(2000, 400)}],
    "none": [0.3, {"type": "sources", "sources": []}, {"type": "final", "answer": NO_RECORDS, "usage": None}],
    "boom": [{"type": "plan", "plan": {}, "usage": usage(1000, 100)}, 1.0, RuntimeError("the index is not there")],
    "declined": [0.7, {"type": "error", "message": "The model declined to answer this question."}],
    "evidence": [cards("Labour"), 0.1, {"type": "final", "answer": None, "usage": None,
                                        "note": "Showing the evidence set only."}],
    "third": [cards("Labour", "Labour", "Labour"), 0.9, {"type": "text", "text": "Councils "}, 8.1,
              {"type": "final", "answer": answer(0.8, 5, 0, 1, 0, 2, 0), "usage": usage(1000, 1000), "model": "big"}],
}


class Plain:
    """A site with only what every site must give."""

    def __init__(self, clock: FixedClock, scripts: Mapping[str, list[Any]] = SCRIPTS,
                 cases: Sequence[Case] = CASES) -> None:
        self.clock, self.scripts, self._cases = clock, scripts, cases
        self.asked: list[tuple[str, Mapping[str, Any]]] = []

    def cases(self) -> Sequence[Case]:
        return self._cases

    def ask(self, case: Case, config: Mapping[str, Any]) -> Iterator[Event]:
        self.asked.append((case.id, config))
        for step in self.scripts[case.id]:
            if isinstance(step, int | float):
                self.clock.advance(step)
            elif isinstance(step, Exception):
                raise step
            else:
                yield step

    def group_of(self, source: Mapping[str, Any]) -> str:
        return str(source["party"])


class Full(Plain):
    """A site that also judges briefings, scores its own expectations and keeps what the model wrote."""

    judged = {"wind": 0.5, "nhs": 1.0, "third": None}

    def judge(self, case: Case, answer: Answer) -> float | None:
        return self.judged[case.id]

    def score(self, case: Case, plan: Mapping[str, Any] | None,
              sources: Sequence[Mapping[str, Any]]) -> Mapping[str, bool]:
        if case.id != "wind":
            return {}
        assert plan == {"houses": ["commons"]} and len(sources) == 4
        return {"houses": plan["houses"] == case.expect["houses"], "portfolios": False}

    def recording(self, case: Case) -> Recording | None:
        return None


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock("2026-11-13T09:30:00+00:00")


def by_id(results: list[CaseResult]) -> dict[str, CaseResult]:
    return {r.id: r for r in results}


def test_the_scripted_sites_are_what_the_harness_asks_for(clock):
    plain: EvalSite = Plain(clock)
    full: EvalSite = Full(clock)
    assert not isinstance(plain, Judges | Scores | Records)
    assert isinstance(full, Judges) and isinstance(full, Scores) and isinstance(full, Records)


def test_every_figure_of_every_question(clock):
    site = Full(clock)
    done = run(site, CONFIG, config_id="abc123def456", pricing=PRICES, clock=clock)
    assert (done.config_id, done.config, done.started_at) == ("abc123def456", CONFIG, "2026-11-13T09:30:00+00:00")
    assert [r.id for r in done.results] == [c.id for c in CASES]
    assert [config for _, config in site.asked] == [CONFIG] * 7
    r = by_id(done.results)

    # reading the question: 1,000 input at $1 and 100 output at $5 a million = 0.001 + 0.0005
    # the briefing: 4,000 uncached at $3 (0.012), 1,000 written to the cache at $3 x 1.25 (0.00375), 800 output at
    # $15 (0.012), 2,000 read from the cache at $0.30 (0.0006) = 0.02835
    assert r["wind"] == CaseResult(
        id="wind", question="Where do rural and city MPs differ on onshore wind?", category="topic",
        outcome="completed", citations_total=10, citations_invalid=1, grounded_ratio=0.9, unsupported=2,
        quotes_total=4, quotes_unverified=1, loaded_words=1, judged=0.5, sources=4,
        spread={"Conservative": 1, "Labour": 2, "Liberal Democrat": 1}, ms_to_first_word=1500, ms_to_end=4000,
        cost_usd=0.02985, input_tokens=6000, output_tokens=900, cache_read_tokens=2000, cache_write_tokens=1000,
        model="big-2026", stop_reason="end_turn", expect_met={"houses": True, "portfolios": False})
    # no model named on the final event: priced as the configuration's, 2,000 at $3 and 400 at $15
    assert r["nhs"] == CaseResult(
        id="nhs", question="What has been said about NHS waiting lists?", category="topic", outcome="completed",
        citations_total=6, citations_invalid=0, grounded_ratio=1.0, unsupported=0, quotes_total=0,
        quotes_unverified=0, loaded_words=0, judged=1.0, sources=2, spread={"Conservative": 1, "Labour": 1},
        ms_to_first_word=500, ms_to_end=2000, cost_usd=0.012, input_tokens=2000, output_tokens=400)
    # "no records" was expected and was the outcome; an answer from before the quotation check has no such counts
    assert r["none"] == CaseResult(
        id="none", question="What was said about bins in 1995?", category="sparse", outcome="no_records",
        citations_total=0, citations_invalid=0, grounded_ratio=1.0, unsupported=0, ms_to_end=300,
        expect_met={"no_records": True})
    # an exception: its class and never its message; the question's reading was still paid for
    assert r["boom"] == CaseResult(
        id="boom", question="What breaks?", category="awkward", outcome="error", error_type="RuntimeError",
        ms_to_end=1000, cost_usd=0.0015, input_tokens=1000, output_tokens=100)
    assert r["declined"] == CaseResult(
        id="declined", question="What is declined?", category="awkward", outcome="error", error_type="ErrorEvent",
        note="The model declined to answer this question.", ms_to_end=700)
    assert r["evidence"] == CaseResult(
        id="evidence", question="What is found when nothing can be written?", category="topic",
        outcome="sources_only", note="Showing the evidence set only.", sources=1, spread={"Labour": 1},
        ms_to_end=100, expect_met={"no_records": True})
    assert r["third"] == CaseResult(
        id="third", question="What about potholes?", category="topic", outcome="completed", citations_total=5,
        citations_invalid=0, grounded_ratio=0.8, unsupported=1, quotes_total=2, quotes_unverified=0, loaded_words=0,
        sources=3, spread={"Labour": 3}, ms_to_first_word=900, ms_to_end=9000, cost_usd=0.018, input_tokens=1000,
        output_tokens=1000, model="big")


def test_every_figure_of_the_summary(clock):
    done = run(Full(clock), CONFIG, config_id="abc123def456", pricing=PRICES, clock=clock)
    assert done.summary == {
        "cases": 7, "questions": 7, "not_run": 0, "completed": 3, "no_records": 1, "errors": 2,
        "error_rate": 0.286,  # 2 of 7
        # over the three briefings written: wind, nhs, third
        "grounded_ratio": 0.9,  # (0.9 + 1.0 + 0.8) / 3
        "citations": 21, "invalid_citations": 1, "invalid_citation_rate": 0.048,  # 1 of 21
        "unsupported": 3, "unsupported_rate": 0.667,  # two of the three have one
        "quotations": 6, "unverified_quotations": 1, "unverified_quotation_rate": 0.167,
        "loaded_words": 1, "loaded_rate": 0.333,
        # nearest rank: of 500, 900, 1,500 the median is the 2nd and the 95th percentile the 3rd
        "median_ms_to_first_word": 900, "p95_ms_to_first_word": 1500,
        "median_ms_to_end": 4000, "p95_ms_to_end": 9000,  # of 2,000, 4,000, 9,000
        "sources": 3.0,  # (4 + 2 + 3) / 3
        "groups": 2.0,  # (3 + 2 + 1) / 3
        "largest_group_share": 0.667,  # (2/4 + 1/2 + 3/3) / 3
        "judged": 0.75, "judged_questions": 2,  # 0.5 and 1.0; the third was not judged
        "cost_usd": 0.06135,  # 0.02985 + 0.012 + 0.0015 + 0.018
        "cost_per_question_usd": 0.008764,  # over all seven asked
        "input_tokens": 10000, "output_tokens": 2400, "cache_read_tokens": 2000, "cache_write_tokens": 1000,
        "expectations_checked": 3,  # wind, none, evidence
        "expectations_met_rate": 0.667,  # wind's portfolios were not met
    }
    assert summarise(done.results, cases=7) == done.summary


def test_a_site_with_only_the_three_methods_is_enough(clock):
    done = run(Plain(clock), CONFIG, config_id="c", pricing=PRICES, clock=clock)
    r = by_id(done.results)
    assert r["wind"].judged is None and r["wind"].expect_met == {} and r["wind"].fixture is None
    assert "judged" not in done.summary
    assert (done.summary["expectations_checked"], done.summary["expectations_met_rate"]) == (2, 1.0)


def test_percentiles_are_by_nearest_rank():
    assert percentile([3, 1, 2], 50) == 2
    assert percentile([4, 1, 3, 2], 50) == 2  # the second of four: never a value between two that were measured
    assert percentile(list(range(1, 21)), 95) == 19
    assert percentile(list(range(1, 20)), 95) == 19  # of fewer than twenty, the slowest
    assert percentile([7], 95) == 7 and percentile([7, 9], 0) == 7 and percentile([7, 9], 100) == 9
    with pytest.raises(ValueError):
        percentile([], 50)


def test_a_figure_with_nothing_behind_it_is_left_out(clock):
    done = run(Plain(clock), CONFIG, config_id="c", pricing=PRICES, clock=clock, only=["boom", "declined"])
    assert done.summary == {"cases": 7, "questions": 2, "not_run": 0, "completed": 0, "no_records": 0, "errors": 2,
                            "error_rate": 1.0, "cost_usd": 0.0015, "cost_per_question_usd": 0.00075,
                            "input_tokens": 1000, "output_tokens": 100, "cache_read_tokens": 0,
                            "cache_write_tokens": 0}
    assert summarise([]) == {"cases": 0, "questions": 0, "not_run": 0, "completed": 0, "no_records": 0, "errors": 0}


# ---- choosing questions, and stopping at a budget ------------------------------------------------------------


def test_only_asks_the_named_questions_in_the_files_order(clock):
    site = Plain(clock)
    done = run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock, only=["none", "wind"])
    assert [r.id for r in done.results] == ["wind", "none"] == [qid for qid, _ in site.asked]
    assert (done.summary["cases"], done.summary["questions"]) == (7, 2)
    with pytest.raises(ValueError, match="no question with the id nothing, nowhere"):
        run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock, only=["wind", "nowhere", "nothing"])


def test_limit_asks_no_more_than_that_many_from_the_start(clock):
    site = Plain(clock)
    assert [r.id for r in run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock, limit=2).results] == [
        "wind", "nhs"]
    both = run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock, only=["third", "none", "boom"], limit=2)
    assert [r.id for r in both.results] == ["none", "boom"]
    assert run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock, limit=0).results == []


def test_the_run_stops_cleanly_once_the_budget_is_spent(clock):
    """Three cents: the first briefing costs 2.985 cents, so the second is still asked; with 4.185 cents spent, no
    more are, and the rest are marked as not run."""
    site = Full(clock)
    seen: list[str] = []
    done = run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock, max_cost_usd=0.03,
               progress=lambda r: seen.append(f"{r.id}:{r.outcome}"))
    assert [qid for qid, _ in site.asked] == ["wind", "nhs"]
    assert seen == ["wind:completed", "nhs:completed", "none:not_run", "boom:not_run", "declined:not_run",
                    "evidence:not_run", "third:not_run"]
    assert done.results[2] == CaseResult("none", "What was said about bins in 1995?", "sparse")
    assert (done.summary["cases"], done.summary["questions"], done.summary["not_run"]) == (7, 2, 5)
    assert done.summary["cost_usd"] == 0.04185 and done.summary["completed"] == 2


def test_a_budget_of_nothing_asks_nothing_and_a_generous_one_asks_everything(clock):
    site = Plain(clock)
    none = run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock, max_cost_usd=0)
    assert site.asked == [] and {r.outcome for r in none.results} == {"not_run"}
    assert run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock, max_cost_usd=1.0).summary["not_run"] == 0


# ---- the ways a question can end -----------------------------------------------------------------------------


def test_a_stream_that_ends_without_a_final_event_is_an_error(clock):
    site = Plain(clock, {"wind": [cards("Labour"), {"type": "text", "text": "Rural"}, 0.4]}, CASES[:1])
    (result,) = run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock).results
    assert (result.outcome, result.error_type, result.ms_to_first_word, result.ms_to_end) == (
        "error", "NoFinalEvent", 0, 400)


def test_an_answer_from_the_cache_is_marked_and_kept_out_of_the_figures(clock):
    """A site's evaluation should never be served from the answer cache; if it is, the briefing is not counted as
    written, timed or paid for."""
    final = {"type": "final", "answer": answer(1.0, 3, 0, 0, 0, 0, 0), "usage": usage(2000, 400), "cached": True}
    site = Plain(clock, {"wind": [cards("Labour"), 0.01, final]}, CASES[:1])
    done = run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock)
    assert (done.results[0].outcome, done.results[0].cost_usd, done.results[0].input_tokens) == ("cached", 0.0, 0)
    assert done.summary["completed"] == 0 and "grounded_ratio" not in done.summary


def test_a_judge_that_fails_does_not_lose_the_briefings_figures(clock):
    class Failing(Plain):
        def judge(self, case: Case, answer: Answer) -> float | None:
            raise TimeoutError("the judge took too long")

    (result,) = run(Failing(clock), CONFIG, config_id="c", pricing=PRICES, clock=clock, only=["nhs"]).results
    assert (result.outcome, result.grounded_ratio, result.judged) == ("completed", 1.0, None)
    assert result.note == "the judge failed: TimeoutError"


def test_only_a_briefing_that_was_written_is_judged(clock):
    class Counting(Plain):
        seen: list[str] = []

        def judge(self, case: Case, answer: Answer) -> float | None:
            self.seen.append(case.id)
            return 1.0

    run(Counting(clock), CONFIG, config_id="c", pricing=PRICES, clock=clock)
    assert Counting.seen == ["wind", "nhs", "third"]


def test_the_sites_own_score_cannot_overrule_the_harness_on_no_records(clock):
    class Generous(Plain):
        def score(self, case: Case, plan: Mapping[str, Any] | None,
                  sources: Sequence[Mapping[str, Any]]) -> Mapping[str, bool]:
            return {"no_records": True, "read": True}

    site = Generous(clock, {"none": SCRIPTS["wind"]}, [CASES[2]])  # records were found where none were expected
    (result,) = run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock).results
    assert result.expect_met == {"no_records": False, "read": True}


# ---- fixtures for the replay half ----------------------------------------------------------------------------


class Keeping(Plain):
    """A site whose pipeline keeps what the model was given and what it wrote, and hands it over when asked."""

    def __init__(self, clock: FixedClock) -> None:
        report = checked(BLOCKS, DOCUMENTS, COUNCILS.verifier, COUNCILS.loaded_words, headings=HEADINGS)
        scripts = {"bins": [cards("Labour", "Liberal Democrat"), 0.5, {"type": "text", "text": "Two councils "}, 1.0,
                            {"type": "final", "answer": report, "usage": usage(3000, 500), "model": "big"}],
                   "nhs": SCRIPTS["nhs"], "none": SCRIPTS["none"]}
        super().__init__(clock, scripts, [Case("bins", QUESTION, {}), CASES[1], CASES[2]])
        self.handed: list[str] = []

    def recording(self, case: Case) -> Recording | None:
        self.handed.append(case.id)
        return Recording(DOCUMENTS, BLOCKS, HEADINGS) if case.id == "bins" else None


def test_a_briefing_is_saved_as_a_fixture_where_the_site_hands_over_what_the_model_wrote(clock, tmp_path):
    site = Keeping(clock)
    done = run(site, CONFIG, config_id="c", pricing=PRICES, clock=clock, record_fixtures=tmp_path / "fixtures")
    # asked only for briefings that were written; the site kept nothing for the second
    assert site.handed == ["bins", "nhs"]
    assert [r.fixture for r in done.results] == ["bins", None, None]
    assert sorted(p.name for p in (tmp_path / "fixtures").iterdir()) == ["bins.jsonl", "bins.report.json"]
    saved = load_fixture(tmp_path / "fixtures" / "bins.jsonl")
    assert (saved.question, saved.documents, saved.blocks, saved.headings) == (QUESTION, DOCUMENTS, BLOCKS, HEADINGS)
    # the report kept is the pipeline's own, from the final event: replayed with the same checks, nothing differs
    assert saved.report == site.scripts["bins"][-1]["answer"]
    assert replay([saved], COUNCILS.verifier, COUNCILS.loaded_words) == []


def test_nothing_is_saved_unless_asked_or_where_the_site_keeps_nothing(clock, tmp_path):
    keeping = Keeping(clock)
    assert [r.fixture for r in run(keeping, CONFIG, config_id="c", pricing=PRICES, clock=clock).results] == [None] * 3
    assert keeping.handed == []
    done = run(Plain(clock), CONFIG, config_id="c", pricing=PRICES, clock=clock, record_fixtures=tmp_path / "f")
    assert all(r.fixture is None for r in done.results) and not (tmp_path / "f").exists()


# ---- what the module may lean on -----------------------------------------------------------------------------


def test_the_harness_imports_only_the_foundation_the_checks_and_the_recording_format():
    """Nothing of the right of reply, nothing of the briefing record (the configuration's id is passed in), no
    outside library: so it runs on any machine with nothing installed."""
    import ast
    import sys
    from pathlib import Path

    import wts_core.eval

    allowed = ("wts_core.ports", "wts_core.events", "wts_core.checks", "wts_core.testing.models", "wts_core.eval")
    for path in sorted(Path(wts_core.eval.__file__).parent.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                if name.startswith("wts_core"):
                    assert name.startswith(allowed), f"{path.name} imports {name}"
                else:
                    assert name.split(".")[0] in sys.stdlib_module_names, f"{path.name} imports {name}"
