"""The weekly report and the alerts: the statistics as a page to read, and a plain list of what got worse.

**The weekly report** is ``stats`` for a week, saved as ``<year>-W<week>.md`` and ``.json`` in a folder the site
names (``data/reports/``), with the week's totals kept in ``wts_weekly``. The files quote a few questions
(those that found no records, the commonest themes), so they are not kept longer than the rows they came from:
``tidy_reports`` removes the files of weeks that ended longer ago than the record's own retention. The totals in
``wts_weekly`` hold no question text and stay.

**Alerts** compare five figures with thresholds the owner has written under ``[alerts]`` in the site's settings:

- ``p95_full_briefing_ms``: the time within which 95 in every 100 briefings were fully written, in milliseconds;
- ``error_rate``: the share of readers' questions that ended in an error (0.02 is 2%);
- ``check_failure_rate``: the share of checked briefings in which any check found a problem;
- ``not_useful_rate``: the share of rated briefings that readers said were not useful;
- ``daily_cost_usd``: what briefings cost a day, taken over the whole period.

A figure trips when it is over its threshold, not when it equals it. **Thresholds start unset,** and an alert
never fires from a guessed number: with none set ``tripped`` returns nothing, and the report proposes values from
its own figures, each the figure plus a margin (``MARGIN``, a quarter, unless another is passed), for the owner to
write into settings or change. A rate that was nought this period is proposed as if there had been one such
briefing, so that a single failure next week is not an alert; a time or a cost with nothing to go on is not
proposed at all.
"""

from __future__ import annotations

import html
import json
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from wts_core.observe.log import Retention, months_before, save_week
from wts_core.observe.stats import MARKS, Figures, Headline, Listed, Rate, Spread, Stats
from wts_core.ports import SYSTEM_CLOCK, Clock
from wts_core.settings import Site
from wts_core.state import StateDB

__all__ = ["ALERTS", "MARGIN", "markdown", "proposed_thresholds", "tidy_reports", "tripped", "week_name",
           "weekly_report"]

MARGIN = 0.25  # how far over this period's figure a proposed threshold is set: a proposal, for the owner to change

_NO_THRESHOLDS = "No alert thresholds are set yet: these are proposed from this week's figures"


# ---- how figures are written ------------------------------------------------------------------------------------


def _day(when: str | datetime) -> str:
    moment = datetime.fromisoformat(when) if isinstance(when, str) else when
    return f"{moment.day} {moment:%B %Y}"


def _seconds(ms: float | None) -> str:
    if ms is None:
        return "none"
    if abs(ms) >= 1000:
        return f"{ms / 1000:.1f} seconds"
    return f"{ms:.0f} millisecond" + ("" if round(abs(ms)) == 1 else "s")


def _percent(share: float) -> str:
    return f"{share * 100:.1f}%"


def _rate(rate: Rate) -> str:
    return "none to count" if rate.rate is None else f"{_percent(rate.rate)} ({rate.count} of {rate.of})"


def _usd(usd: float | None, places: int | None = None) -> str:
    """Dollars, as the AI service prices them: to the cent, or to a hundredth of a cent for sums under ten cents."""
    if usd is None:
        return "none"
    return f"${usd:.{(2 if abs(usd) >= 0.1 or not usd else 4) if places is None else places}f}"


def _number(n: float) -> str:
    return f"{n:.1f}".removesuffix(".0")


_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|~-])")


def _quoted(question: str) -> str:
    """A reader's question, made safe to put in a page: on one line, cut to 200 characters, with nothing in it
    that Markdown or HTML would act on."""
    text = " ".join(question.split())
    if len(text) > 200:
        text = text[:199].rstrip() + "…"
    return "“" + _SPECIAL.sub(r"\\\1", html.escape(text, quote=False)) + "”"


def _table(head: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(" --- " for _ in head) + "|"]
    return [*lines, *("| " + " | ".join(row) + " |" for row in rows), ""]


# ---- alerts ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Alert:
    figure: Callable[[Figures], float | None]
    counted_in: Callable[[Figures], int | None]  # for a rate, what it was counted in
    says: Callable[[Figures], str]  # the figure, in a sentence without its full stop
    amount: Callable[[float], str]  # a figure or a difference, in words


def _points(share: float) -> str:
    return f"{share * 100:.1f} percentage points"


_ALERTS: dict[str, _Alert] = {
    "p95_full_briefing_ms": _Alert(
        lambda f: f.times["t_written"].p95, lambda f: None,
        lambda f: "The time within which 95 in every 100 briefings were fully written was "
                  + _seconds(f.times["t_written"].p95),
        _seconds),
    "error_rate": _Alert(
        lambda f: f.errors.rate, lambda f: f.errors.of,
        lambda f: f"The share of questions that ended in an error was {_rate(f.errors)}", _percent),
    "check_failure_rate": _Alert(
        lambda f: f.any_check.rate, lambda f: f.any_check.of,
        lambda f: f"The share of checked briefings in which a check found a problem was {_rate(f.any_check)}",
        _percent),
    "not_useful_rate": _Alert(
        lambda f: f.not_useful.rate, lambda f: f.not_useful.of,
        lambda f: f"The share of rated briefings that readers said were not useful was {_rate(f.not_useful)}",
        _percent),
    "daily_cost_usd": _Alert(
        lambda f: f.cost_per_day_usd or None, lambda f: None,
        lambda f: f"Briefings cost {_usd(f.cost_per_day_usd)} a day", _usd),
}
ALERTS = tuple(_ALERTS)  # the names a site may set under [alerts]


def _round_up(value: float, places: int) -> float:
    return float(math.ceil(round(value * 10 ** places, 6)) / 10 ** places)


def proposed_thresholds(stats: Stats, margin: float = MARGIN) -> dict[str, float]:
    """A threshold for each alert, from this period's figures: the figure plus ``margin`` of itself (0.25: a
    quarter more), rounded up. A rate of nought is taken as one briefing in however many there were; a figure with
    nothing behind it (no briefing written, nobody asked whether it was useful, nothing spent) has no proposal."""
    proposed: dict[str, float] = {}
    for name, alert in _ALERTS.items():
        figure = alert.figure(stats.period)
        counted_in = alert.counted_in(stats.period)
        if figure is None:
            continue
        if counted_in:
            figure = max(figure, 1 / counted_in)
        places = 0 if name.endswith("_ms") else 2 if name.endswith("_usd") else 4
        proposed[name] = _round_up(figure * (1 + margin), places)
    return proposed


def _thresholds(thresholds: Mapping[str, Any] | None) -> dict[str, float]:
    """The thresholds that are set, checked: an unknown name or a value that is not a number is the owner's
    mistake in ``[alerts]``, and is said rather than passed over."""
    found: dict[str, float] = {}
    for name, value in (thresholds or {}).items():
        if name not in _ALERTS:
            raise ValueError(f"[alerts] {name} is not a threshold the package knows: the names are "
                             + ", ".join(_ALERTS))
        if value is None or value == "":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"[alerts] {name} must be a number that is not negative, not {value!r}")
        found[name] = float(value)
    return found


def tripped(stats: Stats, thresholds: Mapping[str, Any] | None) -> list[str]:
    """What got worse than the owner allows: one plain sentence for each figure over its threshold, saying by how
    much. Empty when nothing tripped, and always empty when no threshold is set."""
    said: list[str] = []
    for name, threshold in _thresholds(thresholds).items():
        alert = _ALERTS[name]
        figure = alert.figure(stats.period)
        if figure is None or figure <= threshold:
            continue
        over = _points(figure - threshold) if name.endswith("_rate") else alert.amount(figure - threshold)
        said.append(f"{alert.says(stats.period)}: {over} over the threshold of {alert.amount(threshold)}.")
    return said


# ---- the page ----------------------------------------------------------------------------------------------------

_OUTCOMES = {
    "completed": "A briefing was written", "cached": "Answered from the cache", "no_records": "No records found",
    "sources_only": "Sources shown without a briefing", "paused_cap": "Paused by a spending cap",
    "paused_limit": "Paused by the reader's daily limit", "busy": "Turned away while the site was busy",
    "left": "The reader left early", "error": "Ended in an error",
}
_KINDS = {"reader": "Readers' questions", "check": "The nightly check's questions", "eval": "Test runs' questions"}
_POINTS = {
    "t_parse": "the question was read", "t_search": "the search was done", "t_rank": "the sources were chosen",
    "t_sources_sent": "the sources were sent to the reader", "t_first_token": "the briefing's first words",
    "t_written": "the full briefing", "t_checked": "the checks were done", "t_total": "everything was finished",
}
_STEPS = {
    "t_parse": "Reading the question", "t_search": "Searching", "t_rank": "Ranking and choosing the sources",
    "t_sources_sent": "Sending the sources", "t_first_token": "Waiting for the first words",
    "t_written": "Writing", "t_checked": "Checking", "t_total": "Finishing",
}
_RATES = {
    "cache_hits": "Answered from the cache", "any_check": "A check found a problem", "no_records": "No records found",
    "not_useful": "Rated not useful", "left": "The reader left early", "errors": "Ended in an error",
}


def _alerts_section(stats: Stats, thresholds: Mapping[str, Any] | None, margin: float) -> list[str]:
    lines = ["## Alerts", ""]
    if not _thresholds(thresholds):
        proposed = proposed_thresholds(stats, margin)
        lines += [_NO_THRESHOLDS + ("." if proposed else ", and there are too few figures yet to propose any."), ""]
        for name, value in proposed.items():
            alert = _ALERTS[name]
            lines.append(f"- `{name} = {_number(value) if name.endswith('_ms') else value}` "
                         f"({alert.says(stats.period)[0].lower()}{alert.says(stats.period)[1:]})")
        return [*lines, ""] if proposed else lines
    said = tripped(stats, thresholds)
    lines += [f"- {sentence}" for sentence in said] if said else ["Nothing is over its threshold."]
    unset = [f"`{name}`" for name in _ALERTS if name not in _thresholds(thresholds)]
    if unset:
        lines += ["", "No threshold is set for " + ", ".join(unset) + "."]
    return [*lines, ""]


def _times(period: dict[str, Spread], earlier: dict[str, Spread], names: Mapping[str, str]) -> list[str]:
    rows = [(names[m], _seconds(period[m].median), _seconds(period[m].p95), str(period[m].n),
             _seconds(earlier[m].median), _seconds(earlier[m].p95), str(earlier[m].n)) for m in MARKS]
    return _table(("", "Median", "95 in 100 within", "Measured", "Median before", "95 in 100 before",
                   "Measured before"), rows)


def _briefing(item: Listed) -> str:
    said = (_quoted(item.question) if item.question
            else "a briefing since withdrawn or corrected" if item.corrected else "a briefing that is not saved")
    where = f" (saved as {item.briefing_id})" if item.briefing_id else ""
    return f"{said}{where}, record {item.id}, {_day(item.at)}"


def _headlines(found: Mapping[str, Headline], first: str) -> list[str]:
    rows = [(f"`{name}`" if name else "(none)", str(h.questions), str(h.written), _seconds(h.first_token.median),
             _seconds(h.full_briefing.median), _seconds(h.full_briefing.p95), _usd(h.cost_per_written_usd, 4),
             _rate(h.any_check), _rate(h.not_useful), _rate(h.errors), _rate(h.no_records), _rate(h.left))
            for name, h in found.items()]
    return _table((first, "Questions", "Briefings written", "Median to first words", "Median to full briefing",
                   "95 in 100 within", "Cost a briefing written", "A check found a problem", "Rated not useful",
                   "Errors", "No records", "Left early"), rows)


def markdown(stats: Stats, site: Site, *, thresholds: Mapping[str, Any] | None = None,
             margin: float = MARGIN) -> str:
    """The statistics as a page: what ``Stats.to_markdown`` returns."""
    now, was, weeks = stats.period, stats.earlier, stats.compare_weeks
    before = f"the {weeks} weeks before" if weeks != 1 else "the week before"
    lines = [
        f"# {site.name}: how the briefings went, {_day(now.start)} to {_day(now.end)}", "",
        f"Each figure is given beside the same figure for {before} ({_day(was.start)} to {_day(was.end)}). "
        "Counts and costs for those weeks are also given at their rate for a period of this length "
        f"({_number(now.days)} days). The figures are for readers' questions: the nightly check's questions and "
        "test runs are counted under \"Questions by kind\" and nowhere else. \"95 in 100 within\" is the time "
        "within which 95 in every 100 were done (the 95th percentile, by nearest rank).", "",
        *_alerts_section(stats, thresholds, margin),
        "## How the questions ended", "",
    ]

    def counts(name: str, a: float, b: float) -> tuple[str, ...]:
        return (name, _number(a), _number(b), _number(b * stats.scale))

    head = ("", "This period", before[0].upper() + before[1:], "At that rate")
    lines += _table(head, [counts("Questions asked", now.questions, was.questions),
                           *(counts(_OUTCOMES[o], now.by_outcome[o], was.by_outcome[o]) for o in now.by_outcome)])
    lines += ["### Questions by kind", ""]
    lines += _table(head, [counts(_KINDS[k], now.by_kind[k], was.by_kind[k]) for k in now.by_kind])

    lines += ["## How long it took", "", "From the question's arrival until each point, for questions not answered "
              "from the cache:", ""]
    lines += _times(now.times, was.times, {m: f"Until {text}" for m, text in _POINTS.items()})
    lines += ["How long each step took (from the point before):", ""]
    lines += _times(now.steps, was.steps, _STEPS)
    lines += [f"An answer from the cache took a median of {_seconds(now.cached_total.median)}, and 95 in 100 came "
              f"within {_seconds(now.cached_total.p95)} ({before}: {_seconds(was.cached_total.median)} and "
              f"{_seconds(was.cached_total.p95)}).", ""]

    lines += ["## What it cost", ""]
    lines += _table(("", "This period", before[0].upper() + before[1:]), [
        ("In all", _usd(now.cost_usd), f"{_usd(was.cost_usd)} ({_usd(was.cost_usd * stats.scale)} at that rate)"),
        ("A day", _usd(now.cost_per_day_usd), _usd(was.cost_per_day_usd)),
        ("A briefing written", _usd(now.cost_per_written_usd, 4), _usd(was.cost_per_written_usd, 4)),
        ("A question asked", _usd(now.cost_per_question_usd, 4), _usd(was.cost_per_question_usd, 4)),
    ])
    if now.cost_by_day:
        dearest = max(now.cost_by_day.items(), key=lambda kv: (kv[1], kv[0]))
        lines += [f"The dearest day was {_day(dearest[0])}: {_usd(dearest[1])}.", ""]

    lines += ["## The answer cache and prompt caching", "",
              f"- Answered from the cache: {_rate(now.cache_hits)}; {before}: {_rate(was.cache_hits)}."]
    for label, cache in (("This period", now.prompt_cache), (before[0].upper() + before[1:], was.prompt_cache)):
        tokens = f"{cache.read_tokens} tokens read from the prompt cache and {cache.write_tokens} written to it"
        if cache.paid_back is None:
            verdict = ("prompt caching was not used" if not (cache.read_tokens or cache.write_tokens)
                       else "no prices were given, so whether it paid back is not worked out")
        else:
            verdict = (f"reading saved {_usd(cache.saved_usd, 4)} and writing cost {_usd(cache.extra_usd, 4)} more "
                       f"than plain input, so prompt caching {'paid back' if cache.paid_back else 'did not pay back'}")
        lines.append(f"- {label}: {tokens}; {verdict}.")
    lines.append("")

    def rates(pairs: list[tuple[str, Rate, Rate]]) -> list[str]:
        return _table(("", "This period", before[0].upper() + before[1:]),
                      [(n, _rate(a), _rate(b)) for n, a, b in pairs])

    lines += ["## What the checks found", "", "Of the briefings whose checks ran:", ""]
    lines += rates([("Any check found a problem", now.any_check, was.any_check),
                    ("An invalid citation", now.invalid_citation, was.invalid_citation),
                    ("An unsupported sentence", now.unsupported, was.unsupported),
                    ("An unverified quotation", now.unverified_quote, was.unverified_quote),
                    ("A loaded word", now.loaded_word, was.loaded_word)])

    lines += ["## How readers fared", ""]
    lines += rates([("No records were found", now.no_records, was.no_records),
                    ("Rated not useful, of those rated", now.not_useful, was.not_useful),
                    ("The reader left early", now.left, was.left),
                    ("A problem was reported, of saved briefings", now.reported, was.reported),
                    ("Withdrawn or corrected, of saved briefings", now.corrected, was.corrected),
                    ("A follow-up was asked, of saved briefings", now.followed_up, was.followed_up)])
    if now.left_at:
        lines += ["Where readers left: " + "; ".join(f"{stage}: {n}" for stage, n in now.left_at.items()) + ".", ""]

    lines += ["## Errors", "", f"- This period: {_rate(now.errors)}; {before}: {_rate(was.errors)}."]
    kinds = sorted({*now.errors_by_type, *was.errors_by_type},
                   key=lambda t: (-now.errors_by_type.get(t, 0), -was.errors_by_type.get(t, 0), t))
    lines += [f"- `{t}`: {now.errors_by_type.get(t, 0)} ({before}: {was.errors_by_type.get(t, 0)})" for t in kinds]
    lines.append("")

    lines += ["## The slowest briefings", ""]
    lines += [f"- {_seconds(item.t_written)} to the full briefing ({_seconds(item.t_first_token)} to its first "
              f"words): {_briefing(item)}" for item in stats.slowest] or ["No briefing was written."]
    lines += ["", "## The worst-checked briefings", ""]
    lines += [f"- Invalid citations {item.citations_invalid or 0}, unsupported sentences {item.unsupported or 0}, "
              f"unverified quotations {item.quotes_unverified or 0}, loaded words {item.loaded_words or 0}"
              + ("" if item.grounded_ratio is None else f", grounded {_percent(item.grounded_ratio)}")
              + f": {_briefing(item)}" for item in stats.worst_checked] or ["The checks found no problem."]

    lines += ["", "## Questions that found no records", ""]
    lines += [f"- {_quoted(q.question)}" + (f" (asked {q.times} times)" if q.times > 1 else "")
              for q in stats.no_record_questions] or ["Every question found records."]
    lines += ["", "## The most common questions", "",
              ("Grouped by meaning with the site's own embedder." if stats.themes_by == "meaning"
               else "Grouped by their words, with case and punctuation set aside."), ""]
    lines += [f"- {_quoted(t.example)}: asked {t.questions} times"
              + (f", in {t.wordings} wordings" if t.wordings > 1 else "") for t in stats.themes] or [
                  "No question was asked more than once."]

    lines += ["", "## By configuration", ""]
    lines += _headlines(stats.by_config, "Configuration") if stats.by_config else ["No questions were asked.", ""]
    if stats.by_config_earlier:
        lines += [f"In {before}:", "", *_headlines(stats.by_config_earlier, "Configuration")]
    if stats.by_arm:
        lines += ["## By experiment arm", ""]
        for experiment, arms in stats.by_arm.items():
            lines += [f"### {_quoted(experiment)}", "", *_headlines(arms, "Arm")]
        if not stats.arms:
            lines += ["No figure was named to decide the experiment, so the arms are not compared.", ""]
        for c in stats.arms:
            verdict = ("the difference is unlikely to be chance" if c.enough else "too few briefings to tell")
            lines += [f"- `{c.a}` against `{c.b}` on \"{_RATES[c.figure].lower()}\": {_rate(c.a_rate)} against "
                      f"{_rate(c.b_rate)}: {verdict}"
                      + ("" if c.p_value is None else f" (p = {c.p_value:.3f})") + f". The test is {c.test}."]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---- the weekly report ------------------------------------------------------------------------------------------


def week_name(week: date) -> str:
    """The ISO week ``week`` falls in, as the report's files are named: ``2026-W46``."""
    year, number, _ = week.isocalendar()
    return f"{year}-W{number:02d}"


def _write(path: Path, text: str) -> None:
    partial = path.with_name(path.name + ".partial")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, path)


def weekly_report(stats: Stats, folder: Path, *, site: Site, week: date, db: StateDB,
                  thresholds: Mapping[str, Any] | None = None, margin: float = MARGIN,
                  clock: Clock = SYSTEM_CLOCK) -> tuple[Path, Path]:
    """Save ``stats`` as the report for the ISO week that the day ``week`` falls in: ``<folder>/<year>-W<week>.md``
    to read and ``.json`` for the family summary, with what tripped (or the proposed thresholds) in both; and
    keep the week's totals, for the site and for each configuration, in ``wts_weekly``. Returns the two paths,
    the page first. Writing a week again replaces it."""
    name = week_name(week)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    page, data = folder / f"{name}.md", folder / f"{name}.json"
    set_already = bool(_thresholds(thresholds))
    extra: dict[str, Any] = {
        "site": site.package, "week": name, "thresholds": _thresholds(thresholds),
        "tripped": tripped(stats, thresholds),
        "proposed_thresholds": {} if set_already else proposed_thresholds(stats, margin),
    }
    _write(page, markdown(stats, site, thresholds=thresholds, margin=margin))
    _write(data, json.dumps({**extra, "stats": stats.as_dict()}, indent=2, ensure_ascii=False) + "\n")
    whole = {**asdict(stats.headline), "cost_usd": stats.period.cost_usd, "by_outcome": stats.period.by_outcome,
             "by_kind": stats.period.by_kind, "since": stats.since, "until": stats.until}
    save_week(db, name, "", whole, clock)
    for config, headline in stats.by_config.items():
        if config:
            save_week(db, name, config, asdict(headline), clock)
    return page, data


_REPORT = re.compile(r"(\d{4})-W(\d{2})\.(?:md|json)")


def tidy_reports(folder: Path, retention: Retention, *, clock: Clock = SYSTEM_CLOCK) -> int:
    """Delete the weekly reports of weeks that ended more than ``retention.months`` calendar months ago, so that
    no question quoted in a report is kept longer than its row in the record. Only files named as
    ``weekly_report`` names them are touched. Returns how many files were deleted."""
    too_old = months_before(clock.now(), retention.months)
    deleted = 0
    for path in sorted(Path(folder).glob("*-W*.*")):
        named = _REPORT.fullmatch(path.name)
        if not named:
            continue
        try:
            sunday = date.fromisocalendar(int(named[1]), int(named[2]), 7)
        except ValueError:
            continue
        ended = datetime(sunday.year, sunday.month, sunday.day, tzinfo=UTC) + timedelta(days=1)
        if ended < too_old:
            path.unlink()
            deleted += 1
    return deleted
