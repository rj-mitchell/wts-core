"""The briefing desk: the order of the flow, what each ending leaves behind, the hooks, and the one record of each
briefing. The comparison with each site's own flow is in ``test_briefing_parity.py``; here the desk is run on its
own, with each site's messages and limits in turn (the fixture ``site``)."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from test_usage_sites import COUNCILS, MPS, SiteFacts, site  # noqa: F401
from wts_core import usage as core_usage
from wts_core.briefing import Ask, BriefingDesk, Hooks, TooManyRequests, current_stages, sse
from wts_core.ports import BriefingConfig, BriefingRecord
from wts_core.state import StateDB
from wts_core.testing import FixedClock, FixedRandom
from wts_core.usage import (
    BriefingArchive,
    BriefingsInProgress,
    Caps,
    Failures,
    Limits,
    PriceTable,
    RateLimiter,
    Spending,
    SqliteAnswerCache,
    cache_key,
)

Q = "What have councils decided about weekly bin collections?"
VISITOR = "c0ffee" * 4  # a visitor's code, which must never reach a record
PARSE = {"input_tokens": 1000, "output_tokens": 100, "cache_read_tokens": 0, "cache_write_tokens": 0}
WRITE = {"input_tokens": 8000, "output_tokens": 600, "cache_read_tokens": 2000, "cache_write_tokens": 1000}
CARDS = [{"n": 1, "party": "LAB"}, {"n": 2, "party": "LD"}, {"n": 3, "party": "LAB"}, {"n": 4}]
ANSWER = {"segments": [{"text": "The motion was lost.", "sources": [1], "cited": [], "status": "cited"}],
          "markdown": "The motion was lost.", "no_records": False, "citations_total": 3, "citations_invalid": 1,
          "grounded_ratio": 0.75, "unsupported_segments": 2, "loaded_words": 1, "quotes_total": 4,
          "quotes_unverified": 1}
NO_RECORDS = {"segments": [], "markdown": "No records found.", "no_records": True, "citations_total": 0,
              "citations_invalid": 0, "grounded_ratio": 1.0}


class ListLog:
    def __init__(self) -> None:
        self.records: list[BriefingRecord] = []

    def write(self, record: BriefingRecord) -> None:
        self.records.append(record)

    def mark(self, briefing_id: str, **what: Any) -> None:
        raise NotImplementedError


class Told:
    """A desk on a site's messages, and what it is built from, for a test to look into."""

    def __init__(self, facts: SiteFacts, folder: Path, **more: Any) -> None:
        self.facts, self.messages = facts, facts.messages
        self.clock = FixedClock()
        self.db = StateDB(folder / "state.db", migrations=core_usage.migrations(), clock=self.clock)
        self.model = facts.models[0]
        self.spending = Spending(self.db, PriceTable.from_settings(facts.usage), clock=self.clock)
        self.cache = SqliteAnswerCache(self.db, clock=self.clock)
        self.archive = BriefingArchive(self.db, new_id=iter(f"saved{n}" for n in range(1, 50)).__next__,
                                       clock=self.clock)
        self.failures = Failures(self.db, clock=self.clock)
        self.limits = more.pop("limits", None) or Limits(
            per_visitor_daily=2, per_account_daily=2 if facts.messages.account_daily_limit else None,
            daily_cap_usd=10.0, monthly_cap_usd=100.0)
        self.caps = Caps(self.spending, self.limits, facts.messages, self.clock)
        self.in_progress = BriefingsInProgress(more.pop("per_key", 2), more.pop("total", 8), 0.15)
        self.log = ListLog()
        self.sources_only_calls: list[tuple[str, bool]] = []
        args: dict[str, Any] = dict(
            messages=facts.messages, limiter=RateLimiter(2, forget_over=100, clock=self.clock), caps=self.caps,
            in_progress=self.in_progress, spending=self.spending, cache=self.cache, cache_hours=168.0,
            archive=self.archive, failures=self.failures, log=self.log,
            config=BriefingConfig(config_id="abc123def456", model=self.model, parse_model=facts.models[-1],
                                  instructions="v7", package_version="0.1.0", site_version="2026.11"),
            group_of=lambda card: card.get("party"), clock=self.clock, random=FixedRandom(), strict=True)
        args.update(more)
        self.desk = BriefingDesk(**args)

    # a site's two functions

    def sources_only(self, note: str, free: bool) -> Iterator[dict[str, Any]]:
        self.sources_only_calls.append((note, free))
        yield {"type": "plan", "plan": {"parser": "offline" if free else "model"}, "usage": None}
        self.clock.advance(0.05)
        yield {"type": "sources", "sources": CARDS, "candidates": 9}
        yield {"type": "final", "answer": None, "usage": None, "note": note}

    def written(self, *, final: dict[str, Any] | None = None, plan: dict[str, Any] | None = None,
                fail: BaseException | None = None, error: dict[str, Any] | None = None) -> Callable[[], Iterator[Any]]:
        """A pipeline that takes the time a real one does, and marks the stages only it can see."""

        def write() -> Iterator[dict[str, Any]]:
            tick, stages = self.clock.advance, current_stages()
            tick(0.2)
            yield {"type": "plan", "plan": {"parser": "model"}, "usage": dict(PARSE), **(plan or {})}
            tick(0.1)
            stages.mark("searched")
            tick(0.05)
            stages.mark("ranked")
            tick(0.05)
            yield {"type": "sources", "sources": CARDS, "candidates": 9}
            tick(1.0)
            # as the model really sends them: a citation comes before the text of the block it belongs to
            yield {"type": "citation", "search_result_index": 0, "cited_text": "the motion was lost"}
            yield {"type": "text", "text": "The motion "}
            if fail is not None:
                raise fail
            yield {"type": "text", "text": "was lost."}
            tick(2.0)
            stages.mark("written")
            if error is not None:
                yield error
                return
            tick(0.3)
            yield final or {"type": "final", "answer": dict(ANSWER), "usage": dict(WRITE), "model": self.model,
                            "stop_reason": "end_turn"}

        return write

    def ask(self, **more: Any) -> Ask:
        args: dict[str, Any] = dict(question=Q, visitor=VISITOR, write=self.written(),
                                    sources_only=self.sources_only, cache_key="k" * 64, options={"mode": "summary"})
        args.update(more)
        return Ask(**args)

    def run(self, **more: Any) -> list[dict[str, Any]]:
        return list(self.desk.handle(self.ask(**more)))

    @property
    def record(self) -> BriefingRecord:
        assert len(self.log.records) == 1, "exactly one record for one question"
        return self.log.records[0]

    def rows(self, table: str) -> list[dict[str, Any]]:
        with self.db.connect() as con:
            return [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY rowid")]


@pytest.fixture
def told(site: SiteFacts, tmp_path: Path) -> Told:  # noqa: F811
    return Told(site, tmp_path)


def types(events: list[dict[str, Any]]) -> list[str]:
    return [e["type"] for e in events]


# ---- the per-minute limit ---------------------------------------------------------------------------------------


def test_over_the_per_minute_limit_the_site_is_told_in_its_own_words(told):
    told.desk.allow("visitor")
    told.desk.allow("visitor")
    told.desk.allow("another visitor")
    with pytest.raises(TooManyRequests) as refused:
        told.desk.allow("visitor")
    assert refused.value.message == told.messages.too_many_requests == str(refused.value)
    assert told.log.records == []  # a request refused here was never a question to the desk


# ---- a briefing written -----------------------------------------------------------------------------------------


def test_a_briefing_is_passed_on_as_it_comes_then_saved_costed_and_cached(told):
    events = told.run()
    assert types(events) == ["plan", "sources", "citation", "text", "text", "final"]
    final = events[-1]
    assert final["briefing_id"] == "saved1" and final["usage"] == WRITE and "cached" not in final
    assert [(r["kind"], r["model"], r["visitor"], r["account"]) for r in told.rows("wts_spending")] == [
        ("parse", told.facts.models[-1], VISITOR, None), ("answer", told.model, VISITOR, None)]
    saved = told.archive.get("saved1")
    assert saved.question == Q and saved.options == {"mode": "summary"}
    assert types(saved.events) == ["plan", "sources", "text", "final"]
    assert saved.events[2]["text"] == "The motion was lost."
    assert saved.events[3] == {**final, "usage": None}  # token counts are never kept with a briefing
    assert told.cache.get("k" * 64, 168) == saved.events[:3] + [{**final, "usage": None, "cached": True}]
    assert told.in_progress.running == {} and told.rows("wts_failures") == []


def test_the_same_question_again_is_played_from_the_cache_at_no_cost(told):
    first = told.run()
    again = told.run(write=lambda: pytest.fail("the model was asked twice"))
    assert types(again) == ["plan", "sources", "text", "final"]
    assert again[-1] == {**first[-1], "usage": None, "cached": True}
    assert len(told.rows("wts_spending")) == 2 and len(told.rows("wts_briefings")) == 1
    assert [r.outcome for r in told.log.records] == ["completed", "cached"]
    cached = told.log.records[1]
    assert (cached.briefing_id, cached.cost_usd, cached.input_tokens, cached.sources) == ("saved1", 0.0, 0, 4)
    assert cached.citations_total == 3 and cached.t_parse is None


def test_a_question_with_no_key_is_never_cached_or_looked_for(told):
    told.run(cache_key=None)
    told.run(cache_key=None)
    assert told.rows("wts_answer_cache") == [] and [r.outcome for r in told.log.records] == ["completed"] * 2


def test_with_no_hours_to_keep_an_answer_the_cache_is_not_used(site, tmp_path):  # noqa: F811
    told = Told(site, tmp_path, cache_hours=0.0)
    told.run()
    told.run()
    assert told.rows("wts_answer_cache") == [] and len(told.rows("wts_briefings")) == 2


def test_the_order_is_cache_caps_place_caps_again_then_the_pipeline(told):
    calls: list[str] = []

    class Watched:
        def __init__(self, name: str, inner: Any) -> None:
            self._name, self._inner = name, inner

        def __getattr__(self, method: str) -> Any:
            def call(*args: Any, **kwargs: Any) -> Any:
                calls.append(f"{self._name}.{method}" + (":pending" if "pending_usd" in kwargs else ""))
                return getattr(self._inner, method)(*args, **kwargs)
            return call

    def write() -> Iterator[dict[str, Any]]:
        calls.append("pipeline")
        yield from told.written()()

    desk = BriefingDesk(
        messages=told.messages, limiter=RateLimiter(9, forget_over=9), caps=Watched("caps", told.caps),
        in_progress=Watched("in_progress", told.in_progress), spending=told.spending,
        cache=Watched("cache", told.cache), cache_hours=168.0, archive=told.archive, failures=told.failures,
        log=told.log, config=told.desk._config, clock=told.clock)
    stream = desk.handle(told.ask(write=write))
    assert calls == ["cache.get", "caps.refusal"]  # before anything is sent: a fault here is the route's to answer
    list(stream)
    assert calls == ["cache.get", "caps.refusal", "in_progress.start", "in_progress.pending_usd",
                     "caps.refusal:pending", "pipeline", "cache.put", "in_progress.finish"]


def test_sources_always_go_before_text(told, site, tmp_path, caplog):  # noqa: F811
    def backwards() -> Iterator[dict[str, Any]]:
        yield {"type": "plan", "plan": {}, "usage": None}
        yield {"type": "text", "text": "A claim "}
        yield {"type": "text", "text": "with nothing to check it against."}
        yield {"type": "sources", "sources": CARDS}
        yield {"type": "final", "answer": None, "usage": None}

    with pytest.raises(AssertionError, match="before its sources"):
        told.run(write=backwards)
    assert told.in_progress.running == {} and told.record.error_type == "AssertionError"
    # outside tests the briefing goes on, and the fault is logged once for the briefing, with no word of it
    lenient = Told(site, tmp_path / "lenient", strict=False)
    with caplog.at_level(logging.ERROR, logger="wts_core.briefing.desk"):
        assert types(lenient.run(write=backwards)) == ["plan", "text", "text", "sources", "final"]
    logged = [r.getMessage() for r in caplog.records]
    assert len(logged) == 1 and "before the sources" in logged[0] and "claim" not in logged[0]


def test_a_citation_may_come_before_any_text_and_is_the_models_first_word(told):
    """The model sends a citation before the text of the block it belongs to: nothing here expects text first. The
    sources must still have gone before either."""
    def write() -> Iterator[dict[str, Any]]:
        yield {"type": "plan", "plan": {}, "usage": None}
        yield {"type": "sources", "sources": CARDS}
        told.clock.advance(0.5)
        yield {"type": "citation", "search_result_index": 0, "cited_text": "the motion was lost"}
        told.clock.advance(0.5)
        yield {"type": "text", "text": "The motion was lost."}
        yield {"type": "citation", "search_result_index": 1, "cited_text": "the strategy be adopted"}
        yield {"type": "final", "answer": dict(ANSWER), "usage": None}

    events = told.run(write=write)
    assert types(events) == ["plan", "sources", "citation", "text", "citation", "final"]
    assert told.record.t_first_token == 500 and told.record.outcome == "completed"
    assert types(told.cache.get("k" * 64, 168)) == ["plan", "sources", "text", "final"]  # citations are not replayed
    assert told.archive.get("saved1").events[2] == {"type": "text", "text": "The motion was lost."}


def test_the_pipelines_own_stages_and_the_desks_are_timed_from_the_questions_arrival(told):
    told.run()
    r = told.record
    assert (r.t_parse, r.t_search, r.t_rank, r.t_sources_sent, r.t_first_token, r.t_written, r.t_checked,
            r.t_total) == (200, 300, 350, 400, 1400, 3400, 3700, 3700)
    assert r.at == "2026-11-13T12:00:00+00:00"  # when the question arrived, not when the record was written


def test_the_record_of_a_completed_briefing(told):
    told.run(follow_up=True, mode="comprehensive", filters_set=("date_from", "party"))
    r = told.record
    assert (r.outcome, r.kind, r.question, r.follow_up, r.mode, r.filters_set) == (
        "completed", "reader", Q, True, "comprehensive", ("date_from", "party"))
    assert (r.config_id, r.model, r.parse_model, r.instructions, r.package_version, r.site_version, r.experiment,
            r.arm) == ("abc123def456", told.model, told.facts.models[-1], "v7", "0.1.0", "2026.11", None, None)
    assert (r.sources, r.spread) == (4, {"LAB": 2, "LD": 1})  # a card with no group is counted among the sources
    assert (r.input_tokens, r.output_tokens, r.cache_read_tokens, r.cache_write_tokens) == (9000, 700, 2000, 1000)
    assert r.cost_usd == pytest.approx(sum(row["cost_usd"] for row in told.rows("wts_spending")), abs=1e-6)
    assert r.cost_usd > 0 and r.stop_reason == "end_turn"
    assert (r.citations_total, r.citations_invalid, r.grounded_ratio, r.unsupported, r.quotes_unverified,
            r.loaded_words) == (3, 1, 0.75, 2, 1, 1)
    assert (r.briefing_id, r.left_at, r.error_type) == ("saved1", None, None)
    assert VISITOR not in repr(r)


def test_no_record_is_written_until_a_site_turns_the_record_on(site, tmp_path):  # noqa: F811
    told = Told(site, tmp_path, log=None)
    assert types(told.run())[-1] == "final" and told.log.records == []


def test_a_fault_in_the_log_never_reaches_the_reader(site, tmp_path, caplog):  # noqa: F811
    class Broken(ListLog):
        def write(self, record: BriefingRecord) -> None:
            raise OSError("disk full")

    told = Told(site, tmp_path, log=Broken())
    with caplog.at_level(logging.ERROR):
        assert types(told.run())[-1] == "final"
    assert "could not be written" in caplog.text and Q not in caplog.text


# ---- no records, no model, sources only -------------------------------------------------------------------------


def test_no_records_is_cached_but_not_saved(told):
    events = told.run(write=told.written(final={"type": "final", "answer": dict(NO_RECORDS), "usage": None}))
    assert "briefing_id" not in events[-1]
    assert told.rows("wts_briefings") == [] and len(told.rows("wts_answer_cache")) == 1
    assert [r["kind"] for r in told.rows("wts_spending")] == ["parse"]  # no answer: nothing towards the limit
    assert (told.record.outcome, told.record.briefing_id, told.record.t_checked) == ("no_records", None, None)


def test_without_a_model_the_pipeline_runs_with_no_place_reserved_and_nothing_kept(told):
    final = {"type": "final", "answer": None, "usage": None, "note": "Showing the evidence only."}
    started: list[str] = []
    told.in_progress.start = lambda key: started.append(key)  # type: ignore[method-assign]
    events = told.run(model_available=False, write=told.written(final=final, plan={"usage": None}))
    assert events[-1] == final and started == []
    assert told.rows("wts_spending") == told.rows("wts_answer_cache") == told.rows("wts_briefings") == []
    assert told.record.outcome == "sources_only"


def test_sources_only_is_the_sites_own_stream_with_its_note(told):
    told.run()  # a cached answer is not looked for when only the sources were asked for
    events = told.run(only_sources=True, write=lambda: pytest.fail("a briefing was written"))
    assert types(events) == ["plan", "sources", "final"] and events[-1]["note"] == told.messages.sources_only
    assert told.sources_only_calls == [(told.messages.sources_only, False)]  # the model may read the question
    r = told.log.records[1]
    assert (r.outcome, r.sources, r.t_parse, r.t_sources_sent, r.t_total) == ("sources_only", 4, 0, 50, 50)


def test_sources_only_is_free_once_the_sites_spending_cap_is_reached(site, tmp_path):  # noqa: F811
    told = Told(site, tmp_path, limits=Limits(per_visitor_daily=2, per_account_daily=None if site is not MPS else 2,
                                              daily_cap_usd=0.0, monthly_cap_usd=100.0))
    told.run(only_sources=True)
    assert told.sources_only_calls == [(told.messages.sources_only, True)]


# ---- refused: the sources, with the reason ----------------------------------------------------------------------


def spend(told: Told, kind: str = "answer", usd: float = 0.0, **who: Any) -> None:
    tokens = int(usd / told.spending._pricing.price_for(told.model).output * 1e6) if usd else 10
    told.spending.add(kind, told.model, {"input_tokens": 0, "output_tokens": tokens}, **who)


def refused_with(told: Told, reason: str, *, others: dict[str, int] | None = None, **more: Any) -> BriefingRecord:
    events = told.run(write=lambda: pytest.fail("a briefing was written"), **more)
    assert types(events) == ["plan", "sources", "final"]
    assert events[-1]["answer"] is None and events[-1]["note"] == told.messages.with_sources(reason)
    assert told.sources_only_calls[-1] == (f"{reason} The sources found are shown below.", True)  # free to read
    assert told.in_progress.running == (others or {}) and told.rows("wts_briefings") == []
    return told.log.records[-1]


def test_the_visitors_daily_limit(told):
    spend(told, visitor=VISITOR)
    spend(told, visitor=VISITOR)
    assert refused_with(told, told.messages.visitor_daily_limit).outcome == "paused_limit"
    assert len(told.log.records) == 1


def test_a_signed_in_accounts_daily_limit(told):
    if told.messages.account_daily_limit is None:
        pytest.skip("only Where MPs Stand has signed-in accounts")
    spend(told, account=7)
    spend(told, account=7)
    record = refused_with(told, told.messages.account_daily_limit, visitor=None, account=7, limiter_key="user:7")
    assert record.outcome == "paused_limit"


def test_the_daily_cap(site, tmp_path):  # noqa: F811
    told = Told(site, tmp_path)
    spend(told, "topic", usd=10.0)
    assert refused_with(told, told.messages.daily_cap).outcome == "paused_cap"


def test_the_monthly_cap(site, tmp_path):  # noqa: F811
    told = Told(site, tmp_path)
    told.clock.set("2026-11-02T09:00:00+00:00")
    for _ in range(11):  # spent earlier in the month: today's cap is not reached, the month's is
        spend(told, "topic", usd=9.5)
    told.clock.set("2026-11-13T12:00:00+00:00")
    assert refused_with(told, told.messages.monthly_cap).outcome == "paused_cap"


def test_one_place_too_many_for_the_visitor(site, tmp_path):  # noqa: F811
    told = Told(site, tmp_path, per_key=1)
    assert told.in_progress.start(VISITOR) is None  # their other briefing, still being written
    assert refused_with(told, told.messages.busy_visitor, others={VISITOR: 1}, cache_key=None).outcome == "busy"
    told.in_progress.finish(VISITOR)
    assert types(told.run())[-1] == "final"


def test_one_place_too_many_for_the_site(site, tmp_path):  # noqa: F811
    told = Told(site, tmp_path, total=1)
    assert told.in_progress.start("someone else") is None
    # a refused visitor leaves nothing behind
    assert refused_with(told, told.messages.busy_site, others={"someone else": 1}).outcome == "busy"


def test_the_second_check_of_the_caps_counts_the_others_in_progress(site, tmp_path):  # noqa: F811
    told = Told(site, tmp_path, limits=Limits(per_visitor_daily=2, per_account_daily=None if site is not MPS else 2,
                                              daily_cap_usd=0.25, monthly_cap_usd=100.0))
    told.in_progress.start("one")
    told.in_progress.start("two")  # two others at $0.15 each: over the cap, though nothing is spent yet
    # this reader's place is given back
    assert refused_with(told, told.messages.daily_cap, others={"one": 1, "two": 1}).outcome == "paused_cap"
    told.in_progress.finish("two")  # one other: $0.15 pending, under the cap
    assert types(told.run())[-1] == "final"


def test_the_place_is_counted_by_the_sites_key_for_the_reader(told):
    seen: list[dict[str, int]] = []

    def write() -> Iterator[dict[str, Any]]:
        seen.append(told.in_progress.running)
        yield from told.written()()

    told.run(write=write, limiter_key="user:7", account=7 if told.facts is MPS else None, cache_key=None)
    told.run(write=write, cache_key=None)
    assert seen == [{"user:7": 1}, {VISITOR: 1}] and told.in_progress.running == {}


# ---- when it goes wrong -----------------------------------------------------------------------------------------


def test_a_failure_while_writing_becomes_the_sites_error_event(told, caplog):
    with caplog.at_level(logging.ERROR):
        events = told.run(write=told.written(fail=RuntimeError("the stream broke")))
    assert types(events) == ["plan", "sources", "citation", "text", "error"]
    assert events[-1] == {"type": "error", "message": told.messages.briefing_failed}
    assert [(f["kind"], f["question"], f["error"]) for f in told.rows("wts_failures")] == [
        ("briefing", Q, "RuntimeError: the stream broke")]
    assert [r["kind"] for r in told.rows("wts_spending")] == ["parse"]  # the answer's tokens are not known
    assert told.rows("wts_answer_cache") == told.rows("wts_briefings") == [] and told.in_progress.running == {}
    r = told.record
    assert (r.outcome, r.error_type, r.left_at, r.t_first_token, r.t_written) == (
        "error", "RuntimeError", None, 1400, None)
    assert "the stream broke" not in repr(r)  # the class of the error, never its message


def test_a_pipeline_that_cannot_even_start_is_an_error_event_too(told):
    def write() -> Iterator[dict[str, Any]]:
        raise ConnectionError("the index could not be opened")

    assert told.run(write=write) == [{"type": "error", "message": told.messages.briefing_failed}]
    assert (told.record.outcome, told.record.error_type) == ("error", "ConnectionError")
    assert told.in_progress.running == {}


def test_a_site_that_keeps_no_notes_of_failures(site, tmp_path):  # noqa: F811
    told = Told(site, tmp_path, failures=None)
    assert told.run(write=told.written(fail=RuntimeError("x"), plan={"parse_error": "bad key"}))[-1]["type"] == "error"
    assert told.rows("wts_failures") == []


def test_a_question_the_model_could_not_read_is_noted_and_the_reader_not_told(told):
    events = told.run(write=told.written(plan={"parse_error": "AuthenticationError: bad key"}))
    assert events[0] == {"type": "plan", "plan": {"parser": "model"}, "usage": PARSE}
    assert [(f["kind"], f["error"]) for f in told.rows("wts_failures")] == [
        ("question reading", "AuthenticationError: bad key")]
    assert "parse_error" not in str(told.cache.get("k" * 64, 168)) + str(told.archive.get("saved1").events)
    assert told.record.outcome == "completed"


def test_the_model_declining_is_the_pipelines_own_error_event(told):
    declined = {"type": "error", "message": told.messages.model_declined, "usage": dict(WRITE), "model": told.model}
    events = told.run(write=told.written(error=declined))
    assert events[-1] == {"type": "error", "message": told.messages.model_declined}  # its token counts are not sent
    assert [r["kind"] for r in told.rows("wts_spending")] == ["parse", "answer"]  # but the call was paid for
    assert [(f["kind"], f["error"]) for f in told.rows("wts_failures")] == [
        ("briefing", told.messages.model_declined)]
    assert told.rows("wts_answer_cache") == told.rows("wts_briefings") == []
    r = told.record
    assert (r.outcome, r.error_type, r.output_tokens, r.t_written) == ("error", "ModelDeclined", 700, 3400)


def test_a_pipeline_that_ends_without_a_final_event(told):
    def write() -> Iterator[dict[str, Any]]:
        yield {"type": "plan", "plan": {}, "usage": None}

    assert types(told.run(write=write)) == ["plan"]
    assert (told.record.outcome, told.record.error_type) == ("error", "NoFinalEvent")


def test_a_failure_in_the_sources_only_search_is_not_hidden(told):
    """As on every site today: the search itself failing is not turned into an event; the streamer raises it and
    the connection is cut. The record is still written."""
    def broken(note: str, free: bool) -> Iterator[dict[str, Any]]:
        yield {"type": "plan", "plan": {}, "usage": None}
        raise LookupError("the index is missing")

    with pytest.raises(LookupError):
        told.run(only_sources=True, sources_only=broken)
    assert (told.record.outcome, told.record.error_type) == ("error", "LookupError")


def test_a_fault_before_anything_is_sent_is_raised_to_the_route_and_recorded(site, tmp_path):  # noqa: F811
    class NoCache:
        def get(self, key: str, max_hours: float) -> Any:
            raise OSError("database is locked")

    told = Told(site, tmp_path, cache=NoCache())
    with pytest.raises(OSError, match="locked"):
        told.desk.handle(told.ask())  # raised by handle itself, before a response has begun
    assert (told.record.outcome, told.record.error_type) == ("error", "OSError")


# ---- the reader leaving -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("taken", "left_at", "t_total"), [(1, "parsed", 200), (2, "sources_sent", 400),
                                                           (3, "first_token", 1400)])
def test_the_reader_leaving_is_recorded_with_the_stage_they_left_at(told, taken, left_at, t_total):
    stopped: list[bool] = []

    def write() -> Iterator[dict[str, Any]]:
        try:
            yield from told.written()()
        finally:
            stopped.append(True)

    stream = told.desk.handle(told.ask(write=write))
    for _ in range(taken):
        next(stream)
    stream.close()  # what the streamer does when the reader has gone
    assert stopped == [True] and told.in_progress.running == {}  # the pipeline, and with it the model, stopped
    r = told.record
    assert (r.outcome, r.left_at, r.t_total, r.briefing_id) == ("left", left_at, t_total, None)
    assert [row["kind"] for row in told.rows("wts_spending")] == ["parse"]  # what was spent before they left
    assert r.output_tokens == PARSE["output_tokens"] and r.cost_usd > 0
    assert told.rows("wts_answer_cache") == told.rows("wts_briefings") == []


def test_the_reader_leaving_through_the_streamer(told):
    import threading

    entered, go, stopped = threading.Event(), threading.Event(), threading.Event()

    def write() -> Iterator[dict[str, Any]]:
        try:
            yield {"type": "plan", "plan": {}, "usage": dict(PARSE)}
            current_stages().mark("searched")  # in the streamer's thread: the desk's stages are there
            yield {"type": "sources", "sources": CARDS}
            yield {"type": "text", "text": "The "}
            entered.set()
            assert go.wait(10)
            yield {"type": "text", "text": "motion "}
            yield {"type": "text", "text": "never reaches the reader"}
        finally:
            stopped.set()

    response = sse(told.desk.handle(told.ask(write=write)), keep_alive=5)
    received = [next(response) for _ in range(3)]
    assert received[-1].startswith(b"event: text") and entered.wait(10)
    response.close()
    go.set()
    assert stopped.wait(10)
    for thread in threading.enumerate():
        if thread.name == "sse":
            thread.join(10)
    r = told.record
    assert (r.outcome, r.left_at, r.t_search) == ("left", "first_token", 0) and told.in_progress.running == {}


def test_a_reader_who_goes_before_the_first_event_still_leaves_a_record(told):
    stream = told.desk.handle(told.ask(write=lambda: pytest.fail("the pipeline was run for nobody")))
    stream.close()
    stream.close()
    assert (told.record.outcome, told.record.left_at) == ("left", "start")
    assert told.in_progress.running == {} and list(stream) == []


def test_a_reader_who_goes_as_the_last_event_is_handed_over_has_a_completed_briefing(told):
    """The briefing was written, paid for and saved; whether its last event arrived cannot be known here. As on
    the sites today it is not cached: that happens once the pipeline has finished."""
    stream = told.desk.handle(told.ask())
    assert [next(stream)["type"] for _ in range(6)][-1] == "final"
    stream.close()
    r = told.record
    assert (r.outcome, r.left_at, r.briefing_id) == ("completed", "checked", "saved1")
    assert told.rows("wts_answer_cache") == [] and len(told.rows("wts_briefings")) == 1


def test_a_refusal_stays_a_refusal_if_the_reader_goes_before_its_sources_are_sent(told):
    spend(told, visitor=VISITOR)
    spend(told, visitor=VISITOR)
    stream = told.desk.handle(told.ask())
    next(stream)
    stream.close()
    assert (told.record.outcome, told.record.left_at) == ("paused_limit", "parsed")


# ---- the hooks --------------------------------------------------------------------------------------------------


def test_hooks_are_called_in_order_and_what_is_for_one_reader_stays_with_them(site, tmp_path):  # noqa: F811
    calls: list[str] = []

    class Site(Hooks):
        def usages(self, ask: Ask, event: dict[str, Any]) -> Any:
            calls.append(f"usages:{event['type']}")
            if event["type"] == "final":  # as Where MPs Stand's check of registered interests
                return [("interests", site.models[-1], event["interests_usage"])]
            return []

        def on_event(self, ask: Ask, event: dict[str, Any]) -> dict[str, Any] | None:
            calls.append(f"on_event:{event['type']}")
            if event["type"] == "progress":
                return None
            return {k: v for k, v in event.items() if k != "interests_usage"}

        def finish(self, ask: Ask, final: dict[str, Any], kept: list[dict[str, Any]]) -> dict[str, Any]:
            calls.append("finish:" + ",".join(e["type"] for e in kept))
            return {**final, "briefing_key": ask.cache_key}

        def for_this_reader(self, ask: Ask, final: dict[str, Any]) -> dict[str, Any]:
            calls.append("for_this_reader")
            final["answer"] = {**final["answer"], "only_here": True}  # even changed in place, it goes no further
            return {**final, "support_reminder": 10}

    told = Told(site, tmp_path, hooks=Site())
    final = {"type": "final", "answer": dict(ANSWER), "usage": dict(WRITE), "model": told.model,
             "interests_usage": dict(PARSE)}

    def write() -> Iterator[dict[str, Any]]:
        yield {"type": "progress", "step": "reading"}
        yield from told.written(final=final)()

    events = told.run(write=write)
    assert "progress" not in types(events)  # dropped by the hook
    assert calls == ["usages:progress", "on_event:progress", "usages:plan", "on_event:plan", "usages:sources",
                     "on_event:sources", "usages:citation", "on_event:citation", "usages:text", "on_event:text",
                     "usages:text", "on_event:text", "usages:final", "on_event:final", "finish:plan,sources",
                     "for_this_reader"]
    sent = events[-1]
    assert list(sent)[-3:] == ["briefing_key", "briefing_id", "support_reminder"] and sent["support_reminder"] == 10
    assert "interests_usage" not in sent and sent["answer"]["only_here"] is True
    # the hook's own model call is recorded before the event's
    assert [r["kind"] for r in told.rows("wts_spending")] == ["parse", "interests", "answer"]
    kept = str(told.cache.get("k" * 64, 168)) + str(told.archive.get("saved1").events)
    assert "support_reminder" not in kept and "only_here" not in kept and "interests_usage" not in kept
    assert kept.count("briefing_key") == 2  # what finish adds is in every copy
    assert told.record.output_tokens == 100 + 100 + 600 and VISITOR not in repr(told.record)


def test_a_cached_answer_passes_through_the_sites_hook_before_it_is_replayed(site, tmp_path):  # noqa: F811
    class Rechecking(Hooks):
        def on_cached(self, ask: Ask, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{**e, "rechecked": True} if e["type"] == "final" else e for e in events]

    told = Told(site, tmp_path, hooks=Rechecking())
    told.run()
    assert told.run()[-1]["rechecked"] is True
    assert "rechecked" not in str(told.cache.get("k" * 64, 168))


def test_a_site_takes_token_counts_out_of_every_copy_with_on_event(site, tmp_path):  # noqa: F811
    """Where Councils Stand's way: what its hook takes out is not sent, not saved and not cached, and the cost is
    recorded all the same."""
    class NoCounts(Hooks):
        def on_event(self, ask: Ask, event: dict[str, Any]) -> dict[str, Any] | None:
            return {k: v for k, v in event.items() if k != "usage"}

    told = Told(site, tmp_path, hooks=NoCounts())
    events = told.run()
    assert all("usage" not in e for e in events)
    assert "usage" not in str(told.cache.get("k" * 64, 168)) + str(told.archive.get("saved1").events)
    assert told.cache.get("k" * 64, 168)[-1] == {**events[-1], "cached": True}
    assert [r["kind"] for r in told.rows("wts_spending")] == ["parse", "answer"]


def test_a_site_with_its_own_shape_of_saved_briefing_saves_it_itself(told):
    """Where MPs Stand's way: the plan, the sources and the final event, with what only it records."""
    def save(final: dict[str, Any], kept: list[dict[str, Any]], text: str) -> dict[str, Any]:
        assert text == "The motion was lost." and types(kept) == ["plan", "sources"]
        events = kept + [{k: v for k, v in final.items() if k != "usage"}]
        saved = told.archive.save(Q, {"mode": "summary"}, events, extra={"records_up_to": "2026-11-12"})
        return {"briefing_id": saved.id, "prepared_at": saved.created_at, "records_up_to": "2026-11-12"}

    final = told.run(save=save)[-1]
    assert list(final)[-3:] == ["briefing_id", "prepared_at", "records_up_to"]
    saved = told.archive.get(final["briefing_id"])
    assert types(saved.events) == ["plan", "sources", "final"] and saved.extra == {"records_up_to": "2026-11-12"}
    assert told.cache.get("k" * 64, 168)[-1]["prepared_at"] == final["prepared_at"]
    assert told.record.briefing_id == "saved1"


def test_a_briefing_id_already_taken_is_replaced_in_every_copy(told):
    told.archive.save("an earlier question", {}, [], id="saved1")
    final = told.run()[-1]
    assert final["briefing_id"] == "saved2"
    assert told.archive.get("saved2").events[-1]["briefing_id"] == "saved2"
    assert told.cache.get("k" * 64, 168)[-1]["briefing_id"] == "saved2" and told.record.briefing_id == "saved2"


def test_in_an_experiment_each_version_has_its_own_cached_answers(site, tmp_path):  # noqa: F811
    seen: list[str | None] = []

    class Keys(Hooks):
        def finish(self, ask: Ask, final: dict[str, Any], kept: list[dict[str, Any]]) -> dict[str, Any]:
            seen.append(ask.cache_key)
            return final

    config = BriefingConfig(config_id="c1", model="m", parse_model=None, instructions="v7", package_version="0.2.0",
                            site_version="1", experiment="shorter-instructions", arm="a")
    a = Told(site, tmp_path, config=config, hooks=Keys())
    a.run()
    a.desk._config = dataclasses.replace(config, arm="b")  # the other version, over the same cache
    assert "cached" not in a.run()[-1]
    a.desk._config = config
    assert a.run()[-1]["cached"] is True
    assert seen == [cache_key({"key": "k" * 64, "experiment": "shorter-instructions", "arm": arm}, length=64)
                    for arm in "ab"]
    assert [(r.experiment, r.arm, r.outcome) for r in a.log.records] == [
        ("shorter-instructions", "a", "completed"), ("shorter-instructions", "b", "completed"),
        ("shorter-instructions", "a", "cached")]


def test_the_nightly_check_and_the_evaluation_are_recorded_as_what_they_are(told):
    told.run(kind="check", visitor=None, cache_key=None)
    assert told.record.kind == "check" and told.in_progress.running == {}
    assert told.rows("wts_spending")[0]["visitor"] is None


def test_the_desk_is_the_same_for_every_site():
    """No branch for any site: neither a site's name nor its package appears in the desk's code."""
    import wts_core.briefing.desk as desk

    code = "\n".join(line.split("#")[0] for line in Path(desk.__file__).read_text().split('"""')[2::2])
    for word in ("hansard", "wcs", "councils", "Where MPs", "Where Countries", "Where Councils", COUNCILS.package):
        assert word not in code, word
    assert SimpleNamespace  # (imported for the fakes above)


def test_the_cost_of_reading_the_question_on_a_sources_only_request_reaches_its_record(told):
    """A sources-only stream carries no token counts (``usage: null``, as the sites send today), so the desk cannot
    see what the model's reading of the question cost. The site's function records the spending itself, as today,
    and tells the briefing's stages, so the record of that question is not shown as free."""

    def sources_only(note: str, free: bool) -> Iterator[dict[str, Any]]:
        cost = told.spending.add("parse", told.facts.models[-1], dict(PARSE), visitor=VISITOR)
        current_stages().spent(dict(PARSE), cost)
        yield from told.sources_only(note, free)

    events = told.run(only_sources=True, sources_only=sources_only)
    assert types(events) == ["plan", "sources", "final"] and events[0]["usage"] is None  # the reader's bytes: as today
    [row] = told.rows("wts_spending")  # one row, the site's own: the desk records nothing a second time
    r = told.record
    assert (r.outcome, r.input_tokens, r.output_tokens) == ("sources_only", row["input_tokens"], row["output_tokens"])
    assert r.cost_usd == round(row["cost_usd"], 6) > 0


def test_each_briefing_leaves_its_lines_in_the_structured_log_where_a_site_has_one(site, tmp_path):  # noqa: F811
    """ADR 0012: one line for each stage reached and one for how the briefing ended. Each holds the record's id, a
    stage, milliseconds and an error's class name: never the question, the visitor's code or any text."""
    import json
    import logging

    from wts_core import observe
    from wts_core.briefing import desk as desk_module
    from wts_core.ports import SystemRandom
    from wts_core.settings import Site

    told = Told(site, tmp_path, random=SystemRandom())  # ids as a real site's are: the log takes no other shape
    assert desk_module._lines_log.name == observe.LOGGER
    path = tmp_path / "logs" / "briefings.jsonl"
    handler = observe.json_logging(path, site=Site(name="Where Parks Stand", package="parks", env_prefix="PARKS",
                                                   root=tmp_path), max_bytes=1_000_000, keep=1, days=14,
                                   clock=told.clock)
    logger = logging.getLogger(observe.LOGGER)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        told.run(cache_key="n" * 64)  # a fresh briefing
        told.run(cache_key="e" * 64, write=told.written(fail=RuntimeError(f"{Q} {VISITOR}")))
    finally:
        logger.removeHandler(handler)
        handler.close()
    text = path.read_text()
    lines = [json.loads(line) for line in text.splitlines()]
    fresh, failed = told.log.records
    mine = [line for line in lines if line["briefing"] == fresh.id]
    assert [(line["event"], line["stage"], line["ms"]) for line in mine] == [
        ("briefing.stage", "parsed", fresh.t_parse), ("briefing.stage", "searched", fresh.t_search),
        ("briefing.stage", "ranked", fresh.t_rank), ("briefing.stage", "sources_sent", fresh.t_sources_sent),
        ("briefing.stage", "first_token", fresh.t_first_token), ("briefing.stage", "written", fresh.t_written),
        ("briefing.stage", "checked", fresh.t_checked), ("briefing.completed", None, fresh.t_total)]
    ended = [line for line in lines if line["briefing"] == failed.id][-1]
    assert (ended["event"], ended["level"], ended["error_type"]) == ("briefing.error", "ERROR", "RuntimeError")
    assert Q not in text and VISITOR not in text and all(set(line) == set(observe.FIELDS) for line in lines)
