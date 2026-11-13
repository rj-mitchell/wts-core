"""Runs kept, compared and held to a site's thresholds.

``save`` writes a run under the site's ``eval/runs/`` as ``<YYYYMMDD-HHMMSS>-eval-<config id>.json``: the date
first, as Where MPs Stand names its runs today, so a folder lists them in order, and a middle word of its own, so
the file is caught by none of that site's older patterns (``*-plans-*``, ``*-sources-*``, ``*-briefings-*``).
``load`` reads one back. It reads only runs saved here: the runs the sites' own commands saved before the package
(how questions were read, sources graded, two models' briefings judged side by side) hold other things, and stay
readable by the site's own code.

``compare`` sets two runs side by side, figure by figure and question by question, and says of each which way it
went. "Better" and "worse" are always the second run against the first. A question that ended differently in
the two runs (a briefing in one, an error or "no records" in the other) is compared on how it ended and nothing
else.

``check_thresholds`` holds a run to the site's thresholds: each is ``min_`` or ``max_`` and the name of one of
the summary's figures (``min_grounded_ratio``, ``max_invalid_citations``, ``max_unsupported_rate``,
``max_p95_ms_to_end``), and a name that is neither is an error, never passed over. A run that meets them all, over
the whole of the site's set, is noted by ``mark_passed`` as one line in ``<folder>/passed.jsonl``, and
``has_passed`` is what the experiment guard reads (ADR 0012): a configuration that has not passed cannot go live.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from wts_core.eval.run import FIGURES, CaseResult, Run

__all__ = ["PASSED_FILE", "Change", "Comparison", "Verdict", "check_thresholds", "compare", "has_passed", "load",
           "mark_passed", "passed_line", "save"]

PASSED_FILE = "passed.jsonl"
_FORMAT = 1

type Verdict = Literal["better", "worse", "unchanged", "changed"]

_LABELS: Mapping[str, str] = {
    "cases": "Questions in the set", "questions": "Questions asked", "not_run": "Questions not asked",
    "completed": "Briefings written", "no_records": "Answers of \"no records\"", "errors": "Errors",
    "error_rate": "Share of questions that ended in an error",
    "grounded_ratio": "Grounded ratio (mean)", "citations": "Citations",
    "invalid_citations": "Citations not found in their source",
    "invalid_citation_rate": "Share of citations not found in their source",
    "unsupported": "Unsupported sentences", "unsupported_rate": "Share of briefings with an unsupported sentence",
    "quotations": "Quotations", "unverified_quotations": "Quotations not found word for word",
    "unverified_quotation_rate": "Share of quotations not found word for word",
    "loaded_words": "Loaded words", "loaded_rate": "Share of briefings with a loaded word",
    "judged": "Judged score (mean)", "judged_questions": "Briefings judged",
    "sources": "Sources for a briefing (mean)", "groups": "Groups among a briefing's sources (mean)",
    "largest_group_share": "Share of a briefing's sources from its largest group (mean)",
    "median_ms_to_first_word": "Time to the first word, median (ms)",
    "p95_ms_to_first_word": "Time to the first word, 95th percentile (ms)",
    "median_ms_to_end": "Time to the end, median (ms)", "p95_ms_to_end": "Time to the end, 95th percentile (ms)",
    "cost_usd": "Cost (US dollars)", "cost_per_question_usd": "Cost for each question (US dollars)",
    "input_tokens": "Input tokens", "output_tokens": "Output tokens", "cache_read_tokens": "Tokens read from the cache",
    "cache_write_tokens": "Tokens written to the cache",
    "expectations_checked": "Questions with expectations checked",
    "expectations_met_rate": "Share of those that met every expectation",
}
# a question's own figures: the field of ``CaseResult``, how it is named in a sentence, and which way is better
_BY_QUESTION: tuple[tuple[str, str, Literal["higher", "lower"]], ...] = (
    ("grounded_ratio", "grounded ratio", "higher"), ("citations_invalid", "citations not found", "lower"),
    ("unsupported", "unsupported sentences", "lower"), ("quotes_unverified", "quotations not found", "lower"),
    ("loaded_words", "loaded words", "lower"), ("judged", "judged score", "higher"),
    ("ms_to_first_word", "ms to the first word", "lower"), ("ms_to_end", "ms to the end", "lower"),
    ("cost_usd", "cost in dollars", "lower"),
)

# ---- saving and loading ----------------------------------------------------------------------------------------


def _when(run: Run) -> datetime:
    return datetime.fromisoformat(run.started_at)


def _day(run: Run) -> str:
    when = _when(run)
    return f"{when.day} {when:%B %Y}"


def save(run: Run, folder: Path) -> Path:
    """Write a run as JSON under ``folder`` (the site's ``eval/runs/``), named by its date and configuration."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._]+", "-", run.config_id).strip("-") or "config"
    path = folder / f"{_when(run):%Y%m%d-%H%M%S}-eval-{name}.json"
    data = {"stage": "eval", "format": _FORMAT, "config_id": run.config_id, "started_at": run.started_at,
            "config": run.config, "summary": run.summary, "results": [asdict(r) for r in run.results]}
    path.write_text(json.dumps(data, indent=1, default=str, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load(path: Path) -> Run:
    """A run saved by ``save``."""
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("stage") != "eval" or not isinstance(raw.get("results"), list):
        stage = raw.get("stage") if isinstance(raw, dict) else None
        raise ValueError(f"{path} is not a run saved by wts_core.eval" + (f" (its stage is {stage!r})" if stage else "")
                         + ": a run saved by a site's own evaluation is read by that site's code")
    known = {f.name for f in fields(CaseResult)}  # a later version's extra fields are passed over
    results = [CaseResult(**{k: v for k, v in row.items() if k in known}) for row in raw["results"]]
    return Run(str(raw.get("config_id") or ""), dict(raw.get("config") or {}), str(raw.get("started_at") or ""),
               results, dict(raw.get("summary") or {}))


# ---- two runs side by side -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """One figure in two runs. ``verdict`` is the second against the first; "changed" where neither way is better
    (how many sources, how the question ended) or one run has no figure."""

    figure: str
    a: Any
    b: Any
    verdict: Verdict


def _change(figure: str, a: Any, b: Any, better: str, same_within: float) -> Change:
    if a == b:
        return Change(figure, a, b, "unchanged")
    if not isinstance(a, int | float) or not isinstance(b, int | float) or isinstance(a, bool) or isinstance(b, bool):
        return Change(figure, a, b, "changed")
    if abs(b - a) <= same_within * abs(a):
        return Change(figure, a, b, "unchanged")
    if better == "neither":
        return Change(figure, a, b, "changed")
    return Change(figure, a, b, "better" if (b > a) == (better == "higher") else "worse")


def _number(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.0f}" if value == int(value) and abs(value) >= 1000 else f"{value:.6g}"
    return f"{value:,}" if isinstance(value, int) else str(value)


@dataclass(frozen=True)
class Comparison:
    """Two runs side by side: ``a`` the earlier or the one in use, ``b`` the one being tried."""

    a: Run
    b: Run
    figures: tuple[Change, ...]  # the summaries, figure by figure
    questions: Mapping[str, tuple[Change, ...]]  # for each question asked in both, what differs
    only_in_a: tuple[str, ...]  # questions asked in one run and not the other
    only_in_b: tuple[str, ...]

    def _with(self, verdict: Verdict) -> tuple[str, ...]:
        return tuple(q for q, changes in self.questions.items() if self.verdict(q) == verdict)

    def verdict(self, question: str) -> Verdict:
        """A question is worse if any of its figures is worse; better if any is better and none worse."""
        found = {c.verdict for c in self.questions[question]}
        order: tuple[Verdict, ...] = ("worse", "better", "changed")
        return next((v for v in order if v in found), "unchanged")

    @property
    def better(self) -> tuple[str, ...]:
        return self._with("better")

    @property
    def worse(self) -> tuple[str, ...]:
        return self._with("worse")

    @property
    def unchanged(self) -> tuple[str, ...]:
        return tuple(q for q in self.questions if self.verdict(q) in ("unchanged", "changed"))

    def to_markdown(self) -> str:
        """The comparison as a short document in the family's plain style."""
        a, b = self.a.config_id, self.b.config_id
        lines = [f"# Evaluation: {b} compared with {a}", "",
                 f"The first run, {a}, was made on {_day(self.a)} and asked {_number(self.a.summary.get('questions', 0))} "
                 f"questions. The second, {b}, was made on {_day(self.b)} and asked "
                 f"{_number(self.b.summary.get('questions', 0))}. \"Better\" and \"worse\" are the second against "
                 "the first.", "", "## Overall", "", f"| Figure | {a} | {b} | |", "|---|---|---|---|"]
        lines += [f"| {_LABELS.get(c.figure, c.figure)} | {_number(c.a)} | {_number(c.b)} |"
                  + ("" if c.verdict == "unchanged" else f" {c.verdict}") + " |" for c in self.figures]
        lines += ["", "## Question by question", "",
                  f"Of {len(self.questions)} questions asked in both runs: {len(self.better)} better, "
                  f"{len(self.worse)} worse, {len(self.unchanged)} neither."]
        differing = {q: [c for c in changes if c.verdict != "unchanged"] for q, changes in self.questions.items()}
        if any(differing.values()):
            lines += ["", "| Question | What changed |", "|---|---|"]
            lines += [f"| {q} | " + "; ".join(f"{c.figure}: {_number(c.a)} to {_number(c.b)}"
                                              + ("" if c.verdict == "changed" else f" ({c.verdict})")
                                              for c in changes) + " |"
                      for q, changes in differing.items() if changes]
        for run, ids in ((a, self.only_in_a), (b, self.only_in_b)):
            if ids:
                lines += ["", f"Asked only in {run}: {', '.join(ids)}."]
        return "\n".join(lines) + "\n"


def _asked(run: Run) -> dict[str, CaseResult]:
    return {r.id: r for r in run.results if r.outcome != "not_run"}


def compare(a: Run, b: Run, *, same_within: float = 0.0) -> Comparison:
    """Set two runs side by side. ``same_within``: how far a figure may move, as a share of its first value, and
    still count as unchanged (0.05 for five per cent: two runs of one configuration never take exactly as long)."""
    figures = tuple(_change(name, a.summary.get(name), b.summary.get(name), better, same_within)
                    for name, better in FIGURES.items() if name in a.summary or name in b.summary)
    first, second = _asked(a), _asked(b)
    questions: dict[str, tuple[Change, ...]] = {}
    for qid, ra in first.items():
        rb = second.get(qid)
        if rb is None:
            continue
        if ra.outcome != rb.outcome:
            went: Verdict = ("better" if rb.outcome == "completed" and ra.outcome == "error"
                             else "worse" if rb.outcome == "error" else "changed")
            # a briefing's time and cost are not set against an error's or a "no records" answer's
            questions[qid] = (Change("outcome", ra.outcome, rb.outcome, went),)
            continue
        changes: list[Change] = []
        for name, label, better in _BY_QUESTION:
            x, y = getattr(ra, name), getattr(rb, name)
            if x is not None or y is not None:
                changes.append(_change(label, x, y, better, same_within))
        if ra.expect_met or rb.expect_met:
            met_a, met_b = bool(ra.expect_met) and all(ra.expect_met.values()), \
                bool(rb.expect_met) and all(rb.expect_met.values())
            changes.append(Change("expectations met", met_a, met_b,
                                  "unchanged" if met_a == met_b else "better" if met_b else "worse"))
        questions[qid] = tuple(changes)
    return Comparison(a, b, figures, questions, tuple(q for q in first if q not in second),
                      tuple(q for q in second if q not in first))


# ---- thresholds, and the note of a pass ------------------------------------------------------------------------


def _failures(summary: Mapping[str, Any], thresholds: Mapping[str, float]) -> list[str]:
    failures: list[str] = []
    for name, limit in thresholds.items():
        kind, _, figure = name.partition("_")
        if kind not in ("min", "max") or figure not in FIGURES:
            raise ValueError(f"unknown threshold {name!r}: a threshold is min_ or max_ followed by one of "
                             + ", ".join(FIGURES))
        value = summary.get(figure)
        label = _LABELS[figure]
        if value is None:
            failures.append(f"{label}: the run has no such figure, and {name} is set to {_number(limit)}.")
        elif kind == "min" and value < limit:
            failures.append(f"{label}: {_number(value)} is below the least allowed, {_number(limit)}.")
        elif kind == "max" and value > limit:
            failures.append(f"{label}: {_number(value)} is above the most allowed, {_number(limit)}.")
    return failures


def check_thresholds(run: Run, thresholds: Mapping[str, float]) -> list[str]:
    """What the run fails on, each in a plain sentence; nothing means it passed. A threshold on a figure the run
    does not have (no briefing was judged, say) is a failure. A threshold with an unknown name is an error."""
    return _failures(run.summary, thresholds)


def passed_line(run: Run, thresholds: Mapping[str, float]) -> dict[str, Any]:
    """The note of a pass: the configuration, the date, the thresholds it was held to and its figures. Refused
    for a run that did not pass, that was held to nothing, or that did not ask the whole of the site's set."""
    if not run.config_id:
        raise ValueError("the run has no configuration id, so a pass cannot be noted against one")
    if not thresholds:
        raise ValueError("no thresholds were given: a run held to nothing has passed nothing")
    asked, cases = run.summary.get("questions", 0), run.summary.get("cases", 0)
    if not asked or asked < cases:
        raise ValueError(f"{_number(asked)} of the set's {_number(cases)} questions were asked: a pass is for the "
                         "whole set")
    failures = _failures(run.summary, thresholds)
    if failures:
        raise ValueError("the run did not pass: " + " ".join(failures))
    return {"config_id": run.config_id, "date": f"{_when(run):%Y-%m-%d}", "started_at": run.started_at,
            "thresholds": dict(thresholds), "figures": dict(run.summary)}


def mark_passed(run: Run, thresholds: Mapping[str, float], folder: Path) -> Path:
    """Add the note of a pass to ``<folder>/passed.jsonl`` (``passed_line`` says when it is refused)."""
    line = passed_line(run, thresholds)
    path = Path(folder) / PASSED_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def has_passed(folder: Path, config_id: str, thresholds: Mapping[str, float] | None = None) -> bool:
    """Whether a pass is noted for exactly this configuration in ``<folder>/passed.jsonl``. With ``thresholds``
    (the site's as they stand now), a pass counts only if its figures meet those too: thresholds raised since the
    run was made are not got round by an old pass."""
    path = Path(folder) / PASSED_FILE
    if not config_id or not path.exists():
        return False
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not text.strip():
            continue
        try:
            line = json.loads(text)
            if line["config_id"] != config_id:
                continue
            figures = line["figures"]
        except (ValueError, KeyError, TypeError):
            raise ValueError(f"{path}, line {number}: not the note of a pass (remove or mend the line)") from None
        if thresholds is None or not _failures(figures, thresholds):
            return True
    return False
