"""Live runs: a site's test questions asked of one configuration, and what was measured.

The site supplies an ``EvalSite``: its questions, a way to ask one (its whole pipeline, sending the events a reader
would be sent), and the group a source belongs to. ``run`` asks each question and keeps, for each: what the checks
found (straight from the report on the ``final`` event), the spread of its sources by group, the time to the first
word and to the end, what it cost, and how it ended. ``summarise`` turns those into the run's figures.

What a site may add, each by having the method (``run`` looks for it; nothing need be declared):

* ``judge(case, answer) -> float | None``: a score for the briefing, where the site's set has judged answers
  (``Judges``). What a judge costs is the site's to count: the harness cannot see it.
* ``score(case, plan, sources) -> Mapping[str, bool]``: the site's own expectations, each met or not (``Scores``):
  how the question was read, filter by filter, and whether the evidence holds a source from each of ``include``.
  The harness itself scores one key of ``Case.expect``, ``no_records``: whether "no records" was the outcome.
* ``usages(event) -> Iterable[(kind, model, usage)]``: further model calls an event reports, beside the two the
  harness counts itself (``Spends``): the same shape as the briefing desk's ``Hooks.usages``, so a site with a
  third call (Where MPs Stand matches registered interests, and reports the token counts on the final event as
  ``interests_usage``) has it counted in a run's cost as it is in a reader's briefing. Without it such a call
  was left out, and a run looked cheaper than the briefings it measured.
* ``recording(case) -> Recording | None``: what the model was given and what it wrote for the question just asked
  (``Records``). The events a reader is sent carry neither the model's blocks nor the documents, and nothing here
  pretends to rebuild them: a site that wants fixtures for the replay half keeps them in its ``ask`` (its pipeline
  has both in hand when it calls the checks) and hands them over here. Without it, ``record_fixtures`` saves
  nothing.

Money. The cost of a question is the usage on its ``plan`` event (reading the question) and on its ``final`` event
(writing the briefing), each priced by the ``Pricing`` passed in: the first at ``config["parse_model"]``, the
second at the model the ``final`` event names, or ``config["model"]``; and whatever the site's ``usages`` names
for an event, each at the model it gives. Usage a site reports under keys of its own and names in no ``usages``
is not counted, nor the cost of a briefing that failed before its ``final`` event. ``max_cost_usd`` stops a run
between questions once the spend so far has reached it, and the rest are marked ``not_run``: the charity's budget
for evaluation is small.

A run can be recorded in the site's own spending (``run(..., spending=…)``): each call the harness counts is
then added to the site's spending record, under the kind ``eval`` unless another is given, with no visitor. So a
run's cost shows in the owner's spending figures beside readers' briefings and counts towards the site's daily
and monthly caps, as money spent at the same provider on the same day should. Without a record given, nothing
is written anywhere but the run's own file.

Percentiles are by the nearest-rank method: of ``n`` values in order, the ``p``th percentile is the value at place
``ceil(p / 100 * n)``. So the median of four is the second, and the 95th percentile of fewer than twenty is the
slowest.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from wts_core.eval.cases import Case
from wts_core.eval.replay import Fixture, save_fixture
from wts_core.events import Answer, Block, Event
from wts_core.ports import SYSTEM_CLOCK, Clock, Document, Pricing, SpendingRecord, Usage

__all__ = ["FIGURES", "CaseOutcome", "CaseResult", "EvalSite", "Judges", "Recording", "Records", "Run", "Scores",
           "Spends", "percentile", "run", "summarise"]

type CaseOutcome = Literal["completed", "no_records", "sources_only", "cached", "error", "not_run"]


class EvalSite(Protocol):
    """What a site gives the harness."""

    def cases(self) -> Sequence[Case]:
        """Its test questions (``load_cases`` on its ``eval/questions.toml``)."""
        ...

    def ask(self, case: Case, config: Mapping[str, Any]) -> Iterator[Event]:
        """Ask one question of the site's pipeline, set up as ``config`` says, and send what a reader would be
        sent. Never through the answer cache, and never in an experiment."""
        ...

    def group_of(self, source: Mapping[str, Any]) -> str:
        """The group one of its source cards belongs to: a party, a region, a body."""
        ...


@dataclass(frozen=True)
class Recording:
    """What the model was given for a question and what it wrote back, for a fixture."""

    documents: tuple[Document, ...]
    blocks: tuple[Block, ...]
    headings: tuple[str, ...] = ()  # one for each document, where the site's sources have headings


@runtime_checkable
class Judges(Protocol):
    def judge(self, case: Case, answer: Answer) -> float | None: ...


@runtime_checkable
class Scores(Protocol):
    def score(self, case: Case, plan: Mapping[str, Any] | None,
              sources: Sequence[Mapping[str, Any]]) -> Mapping[str, bool]: ...


@runtime_checkable
class Records(Protocol):
    def recording(self, case: Case) -> Recording | None: ...


@runtime_checkable
class Spends(Protocol):
    def usages(self, event: Event) -> Iterable[tuple[str, str | None, Usage | Mapping[str, Any] | None]]:
        """More model calls this event reports: each a kind, the model it is priced as, and the token counts."""
        ...


@dataclass
class CaseResult:
    """One question's result. The checks' figures are None where no briefing was written."""

    id: str
    question: str
    category: str = ""
    outcome: CaseOutcome = "not_run"
    error_type: str | None = None  # the exception's class name; "ErrorEvent" when the pipeline sent an error
    note: str | None = None  # the pipeline's own words with an error or a sources-only answer
    # what the checks found
    citations_total: int | None = None
    citations_invalid: int | None = None
    grounded_ratio: float | None = None
    unsupported: int | None = None  # sentences with no citation that state a claim
    quotes_total: int | None = None
    quotes_unverified: int | None = None
    loaded_words: int | None = None
    judged: float | None = None
    # balance
    sources: int = 0
    spread: dict[str, int] = field(default_factory=dict)  # sources in each group
    # speed, in milliseconds from the moment the question was asked
    ms_to_first_word: int | None = None
    ms_to_end: int | None = None
    # cost
    cost_usd: float = 0.0
    input_tokens: int = 0  # as the sites store them: cache writes are counted here too
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model: str | None = None  # the model the briefing's final event named
    stop_reason: str | None = None
    # the site's expectations that could be scored, each met or not
    expect_met: dict[str, bool] = field(default_factory=dict)
    fixture: str | None = None  # the fixture saved for it, by name


@dataclass
class Run:
    """One configuration's results on a site's questions."""

    config_id: str
    config: dict[str, Any]
    started_at: str  # ISO 8601, UTC, to the second
    results: list[CaseResult]
    summary: dict[str, float]


# Every figure a summary may hold, and which way is better: what ``compare`` and ``check_thresholds`` know.
FIGURES: Mapping[str, Literal["higher", "lower", "neither"]] = {
    "cases": "neither", "questions": "neither", "not_run": "lower", "completed": "neither", "no_records": "neither",
    "errors": "lower", "error_rate": "lower",
    "grounded_ratio": "higher", "citations": "neither", "invalid_citations": "lower", "invalid_citation_rate": "lower",
    "unsupported": "lower", "unsupported_rate": "lower", "quotations": "neither", "unverified_quotations": "lower",
    "unverified_quotation_rate": "lower", "loaded_words": "lower", "loaded_rate": "lower",
    "judged": "higher", "judged_questions": "neither",
    "sources": "neither", "groups": "neither", "largest_group_share": "neither",
    "median_ms_to_first_word": "lower", "p95_ms_to_first_word": "lower", "median_ms_to_end": "lower",
    "p95_ms_to_end": "lower",
    "cost_usd": "lower", "cost_per_question_usd": "lower", "input_tokens": "neither", "output_tokens": "neither",
    "cache_read_tokens": "neither", "cache_write_tokens": "neither",
    "expectations_checked": "neither", "expectations_met_rate": "higher",
}


def percentile(values: Sequence[float], p: float) -> float:
    """The ``p``th percentile by the nearest-rank method: the value at place ``ceil(p / 100 * n)`` of ``n`` in
    order. No value is made up between two that were measured."""
    if not values:
        raise ValueError("no values to take a percentile of")
    ordered = sorted(values)
    return ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1]


def summarise(results: Sequence[CaseResult], *, cases: int | None = None) -> dict[str, float]:
    """A run's figures. The checks' figures, the timings and the spread are over the briefings that were written
    (``completed``): a "no records" answer or an error is quick and flags nothing, and would flatter them. A
    figure with nothing to work it out from is left out, not given as nought. ``cases``: how many questions the
    site's set has, when that is more than were chosen."""
    asked = [r for r in results if r.outcome != "not_run"]
    done = [r for r in asked if r.outcome == "completed"]
    out: dict[str, float] = {
        "cases": len(results) if cases is None else cases, "questions": len(asked),
        "not_run": len(results) - len(asked), "completed": len(done),
        "no_records": sum(1 for r in asked if r.outcome == "no_records"),
        "errors": sum(1 for r in asked if r.outcome == "error"),
    }
    if asked:
        out["error_rate"] = round(out["errors"] / len(asked), 3)
    if done:
        n = len(done)
        citations = sum(r.citations_total or 0 for r in done)
        quotations = sum(r.quotes_total or 0 for r in done)
        out |= {
            "grounded_ratio": round(sum(r.grounded_ratio or 0.0 for r in done) / n, 3),
            "citations": citations,
            "invalid_citations": sum(r.citations_invalid or 0 for r in done),
            "unsupported": sum(r.unsupported or 0 for r in done),
            "unsupported_rate": round(sum(1 for r in done if r.unsupported) / n, 3),
            "quotations": quotations,
            "unverified_quotations": sum(r.quotes_unverified or 0 for r in done),
            "loaded_words": sum(r.loaded_words or 0 for r in done),
            "loaded_rate": round(sum(1 for r in done if r.loaded_words) / n, 3),
        }
        if citations:
            out["invalid_citation_rate"] = round(out["invalid_citations"] / citations, 3)
        if quotations:
            out["unverified_quotation_rate"] = round(out["unverified_quotations"] / quotations, 3)
        for name in ("ms_to_first_word", "ms_to_end"):
            times = [float(t) for t in (getattr(r, name) for r in done) if t is not None]
            if times:
                out[f"median_{name}"] = percentile(times, 50)
                out[f"p95_{name}"] = percentile(times, 95)
        spread = [r for r in done if r.sources]
        if spread:
            out["sources"] = round(sum(r.sources for r in spread) / len(spread), 2)
            out["groups"] = round(sum(len(r.spread) for r in spread) / len(spread), 2)
            out["largest_group_share"] = round(
                sum(max(r.spread.values(), default=0) / r.sources for r in spread) / len(spread), 3)
    judged = [r.judged for r in asked if r.judged is not None]
    if judged:
        out["judged"] = round(sum(judged) / len(judged), 3)
        out["judged_questions"] = len(judged)
    if asked:
        out["cost_usd"] = round(sum(r.cost_usd for r in asked), 6)
        out["cost_per_question_usd"] = round(out["cost_usd"] / len(asked), 6)
        for name in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
            out[name] = sum(getattr(r, name) for r in asked)
    scored = [r for r in asked if r.expect_met]
    if scored:
        out["expectations_checked"] = len(scored)
        out["expectations_met_rate"] = round(sum(1 for r in scored if all(r.expect_met.values())) / len(scored), 3)
    return out


def _ask(site: EvalSite, case: Case, config: Mapping[str, Any], clock: Clock, pricing: Pricing,
         spending: SpendingRecord | None, spent_as: str) -> tuple[CaseResult, Answer | None]:
    """Ask one question: its result, and the checked report where a briefing was written."""
    result = CaseResult(case.id, case.question, str(case.expect.get("category") or ""))
    plan: Mapping[str, Any] | None = None
    cards: list[Mapping[str, Any]] = []
    final: Mapping[str, Any] | None = None
    error: Mapping[str, Any] | None = None
    usage = Usage()
    started = clock.monotonic()

    def ms() -> int:
        return round((clock.monotonic() - started) * 1000)

    def spend(used: Usage | Mapping[str, Any] | None, model: str | None) -> None:
        """One model call counted: priced, added to the question's cost, and to the site's spending if given."""
        nonlocal usage
        if not used:
            return
        counts = used if isinstance(used, Usage) else Usage.from_mapping(used)
        usage += counts
        result.cost_usd += (pricing.cost(counts, model) if spending is None
                            else spending.add(spent_as, model, counts))

    try:
        for event in site.ask(case, config):  # the site's own events and keys pass through too
            kind = event.get("type")
            if isinstance(site, Spends):  # the site's further calls, before the event's own, as the desk has them
                for _, model, used in site.usages(event):
                    spend(used, model)
            if kind == "text":
                if result.ms_to_first_word is None:
                    result.ms_to_first_word = ms()
            elif kind == "plan":
                plan = event
                spend(event.get("usage"), config.get("parse_model"))
            elif kind == "sources":
                cards = list(event.get("sources") or [])
            elif kind == "final":
                final = event
            elif kind == "error":
                error = event
    except Exception as exc:  # a question that fails is a result, not the end of the run
        result.outcome, result.error_type = "error", type(exc).__name__
    result.ms_to_end = ms()

    result.sources = len(cards)
    result.spread = dict(sorted(Counter(site.group_of(card) for card in cards).items()))
    answer: Answer | None = None
    if final is not None:
        answer = final.get("answer")
        result.model, result.stop_reason = final.get("model"), final.get("stop_reason")
        if not final.get("cached"):
            spend(final.get("usage"), result.model or config.get("model"))
    result.cost_usd = round(result.cost_usd, 6)
    stored = usage.as_stored()
    result.input_tokens, result.output_tokens = stored["input_tokens"], stored["output_tokens"]
    result.cache_read_tokens, result.cache_write_tokens = stored["cache_read_tokens"], stored["cache_write_tokens"]

    if result.outcome == "error":
        return result, None
    if error is not None:
        result.outcome, result.error_type, result.note = "error", "ErrorEvent", str(error.get("message") or "")
        return result, None
    if final is None:
        result.outcome, result.error_type = "error", "NoFinalEvent"
        return result, None
    if answer is None:
        result.outcome, result.note = "sources_only", final.get("note")
    else:
        result.outcome = ("cached" if final.get("cached") else "no_records" if answer.get("no_records")
                          else "completed")
        result.citations_total = answer.get("citations_total")
        result.citations_invalid = answer.get("citations_invalid")
        result.grounded_ratio = answer.get("grounded_ratio")
        result.unsupported = answer.get("unsupported_segments")
        result.quotes_total = answer.get("quotes_total")
        result.quotes_unverified = answer.get("quotes_unverified")
        result.loaded_words = answer.get("loaded_words")
    if "no_records" in case.expect:
        result.expect_met["no_records"] = (result.outcome == "no_records") == bool(case.expect["no_records"])
    if isinstance(site, Scores):
        result.expect_met |= {k: bool(v) for k, v in site.score(case, (plan or {}).get("plan"), cards).items()
                              if k != "no_records"}
    if isinstance(site, Judges) and answer is not None and result.outcome == "completed":
        try:
            result.judged = site.judge(case, answer)
        except Exception as exc:  # the briefing was written and paid for: keep its figures
            result.note = f"the judge failed: {type(exc).__name__}"
    return result, answer


def run(site: EvalSite, config: Mapping[str, Any], *, config_id: str, pricing: Pricing, clock: Clock = SYSTEM_CLOCK,
        record_fixtures: Path | None = None, only: Sequence[str] | None = None, limit: int | None = None,
        max_cost_usd: float | None = None, progress: Callable[[CaseResult], None] | None = None,
        spending: SpendingRecord | None = None, kind: str = "eval") -> Run:
    """Ask a site's questions of one configuration.

    ``config`` is the site's own (the harness reads only ``model`` and ``parse_model`` from it, to price by) and
    ``config_id`` the id the site's record of briefings gives that configuration. ``only``: the ids of the
    questions to ask; ``limit``: no more than that many, from the start of the file. ``max_cost_usd``: once the
    spend so far has reached it, no further question is asked and the rest are marked ``not_run``.
    ``record_fixtures``: a folder to save each briefing in as a fixture for ``replay``, where the site hands over
    a ``Recording``. ``progress`` is called with each question's result as it is done.

    ``spending`` is the site's spending record, where the run's cost should show in the site's spending and count
    towards its caps: each model call counted is added to it as ``kind`` ("eval": a kind of its own, so the
    owner's figures tell a run from readers' briefings), with no visitor. The cost of each question is then what
    the record itself priced it at. Left out, nothing is recorded.
    """
    cases = list(site.cases())
    chosen = cases
    if only is not None:
        unknown = sorted(set(only) - {c.id for c in cases})
        if unknown:
            raise ValueError("no question with the id " + ", ".join(unknown))
        chosen = [c for c in cases if c.id in set(only)]
    if limit is not None:
        chosen = chosen[:max(0, limit)]
    started_at = clock.now().isoformat(timespec="seconds")
    results: list[CaseResult] = []
    spent = 0.0
    for case in chosen:
        if max_cost_usd is not None and spent >= max_cost_usd:
            result = CaseResult(case.id, case.question, str(case.expect.get("category") or ""))
        else:
            result, answer = _ask(site, case, config, clock, pricing, spending, kind)
            spent += result.cost_usd
            if record_fixtures is not None and isinstance(site, Records) and answer is not None \
                    and result.outcome == "completed":
                result.fixture = _record(site, case, answer, record_fixtures)
        results.append(result)
        if progress is not None:
            progress(result)
    return Run(config_id, dict(config), started_at, results, summarise(results, cases=len(cases)))


def _record(site: Records, case: Case, answer: Answer, folder: Path) -> str | None:
    """Save the briefing just written as a fixture: what the site kept of it, and the report its pipeline made."""
    recording = site.recording(case)
    if recording is None:
        return None
    save_fixture(Fixture(case.id, case.question, recording.documents, recording.blocks, answer, recording.headings),
                 folder)
    return case.id
