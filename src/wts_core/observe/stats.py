"""What the record of briefings says: every figure the owner asked for (the brief's 3.7), each beside the same
figure for the weeks before, so a change can be seen to have helped or not (ADR 0012).

How the figures are worked out, kept to throughout:

- **Whose briefings.** Every figure is for readers' questions (``kind`` ``reader``). The nightly check's question
  and the evaluation harness's are counted in ``by_kind`` and nowhere else.
- **The median** is the middle value, or the mean of the two middle values where there is an even number.
- **The p95** is by the nearest-rank method: with the values in order, the one at rank ``ceil(0.95 × n)``,
  counting from 1. It is always a value that was measured; with fewer than 20 values it is the largest.
- **Times** are milliseconds from the question's arrival to each point (as ``ports.BriefingRecord`` stores them),
  over the questions that were not answered from the cache and reached that point. **Steps** are the time from
  the point before (the latest earlier point the briefing reached) to this one, never less than nothing where two
  stages ran at once. The time to serve an answer from the cache is given on its own (``cached_total``).
- **A rate** is a count over what it could have been counted in (``Rate``: ``count``, ``of`` and ``rate``, which
  is None when there was nothing to count in). Check failures are over the briefings whose checks ran; "not
  useful" over the briefings readers rated; what readers did next over saved briefings (each once: not its
  replays from the cache); the rest over all readers' questions.
- **Cost a day** is the period's cost over its length in days, so a quiet day counts.
- **The earlier period** is the ``compare_weeks`` weeks ending where the period begins. Its counts and costs are
  for the whole of those weeks: ``Stats.scale`` is what to multiply them by to compare like with like.

Question text is given sparingly. The slowest and worst-checked briefings carry their question only where the
briefing is saved (it has a ``briefing_id``) and has not been withdrawn or corrected: that question is already
public at the briefing's own address. Questions that found no records and the commonest themes need their words to
be of any use; a question whose briefing ended in an error, or was withdrawn or corrected, is never among them.

Themes are grouped with the site's own embedder where one is given, so no question leaves the server: greedily, the
most asked wording first, each joining the group whose first member it is most like if the cosine similarity is
at least ``similarity``, or starting a group of its own. The same questions always give the same groups. With no
embedder, questions are grouped by their text with case, punctuation and spacing set aside.

Two arms of an experiment are compared by a two-proportion z-test (``two_proportion_test``), named in the output.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from wts_core.observe.log import KINDS, OUTCOMES
from wts_core.ports import SYSTEM_CLOCK, BriefingRecord, Clock, Embedder, Pricing
from wts_core.settings import Site

__all__ = [
    "MARKS",
    "PROPORTIONS",
    "ArmComparison",
    "Asked",
    "BriefingHistory",
    "Figures",
    "Headline",
    "Listed",
    "PromptCache",
    "Rate",
    "Spread",
    "Stats",
    "Theme",
    "TwoProportions",
    "median",
    "p95",
    "stats",
    "two_proportion_test",
]

# the points a briefing passes, in order: each is a time from the question's arrival
MARKS = ("t_parse", "t_search", "t_rank", "t_sources_sent", "t_first_token", "t_written", "t_checked", "t_total")
# the rates an experiment may be decided by
PROPORTIONS = ("cache_hits", "any_check", "no_records", "not_useful", "left", "errors")

LISTED = 5  # how many of the slowest, and of the worst-checked, are listed
NO_RECORDS_LISTED = 20  # how many questions that found no records
THEMES_LISTED = 10  # how many themes
THEME_MIN = 2  # questions that make a theme: one question asked once is not a theme

LEVEL = 0.05  # the level at which two arms are said to differ
EXPECTED_MIN = 5  # the least each arm should expect of both answers for the test's approximation to hold
TEST = ("a two-proportion z-test (pooled, two-sided) at the 5% level, made only when each arm would expect at "
        "least 5 briefings either way")


class BriefingHistory(Protocol):
    """What ``stats`` needs of a record of briefings: ``SqliteBriefingLog`` is one."""

    def since(self, start: datetime, end: datetime | None = None,
              kinds: Sequence[str] = ("reader",)) -> Sequence[BriefingRecord]: ...


# ---- the small values -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Spread:
    """How a time was spread: how many were measured, the median and the p95 (nearest rank), in milliseconds."""

    n: int
    median: float | None
    p95: float | None


@dataclass(frozen=True)
class Rate:
    """``count`` out of ``of``; ``rate`` is None when there was nothing to count in."""

    count: int
    of: int
    rate: float | None


@dataclass(frozen=True)
class PromptCache:
    """Whether prompt caching paid back. Reading from the cache is cheaper than sending the tokens again; writing
    to it is dearer. With prices: ``saved_usd`` is what the reads saved, ``extra_usd`` what the writes cost over
    plain input, and ``paid_back`` whether the first is the greater. With no prices: the token sums only."""

    read_tokens: int
    write_tokens: int
    saved_usd: float | None
    extra_usd: float | None
    paid_back: bool | None


@dataclass(frozen=True)
class Figures:
    """Every figure for one period."""

    start: str
    end: str
    days: float
    questions: int
    by_outcome: dict[str, int]
    by_kind: dict[str, int]
    times: dict[str, Spread]
    steps: dict[str, Spread]
    cached_total: Spread
    cost_usd: float
    cost_per_written_usd: float | None
    cost_per_question_usd: float | None
    cost_per_day_usd: float | None
    cost_by_day: dict[str, float]
    cache_hits: Rate
    prompt_cache: PromptCache
    invalid_citation: Rate
    unsupported: Rate
    unverified_quote: Rate
    loaded_word: Rate
    any_check: Rate
    no_records: Rate
    not_useful: Rate
    left: Rate
    left_at: dict[str, int]
    errors: Rate
    errors_by_type: dict[str, int]
    reported: Rate
    corrected: Rate
    followed_up: Rate


@dataclass(frozen=True)
class Headline:
    """The headline figures for one configuration or one arm of an experiment, with how many briefings they rest
    on. No question text: these are what ``wts_weekly`` keeps."""

    questions: int
    written: int
    first_token: Spread
    full_briefing: Spread
    cost_per_written_usd: float | None
    cache_hits: Rate
    any_check: Rate
    no_records: Rate
    not_useful: Rate
    left: Rate
    errors: Rate


@dataclass(frozen=True)
class TwoProportions:
    z: float | None
    p_value: float | None
    enough: bool


@dataclass(frozen=True)
class ArmComparison:
    """Two arms of an experiment, on the figure that decides it. ``enough`` is whether they can be told apart:
    until it is true, there are too few briefings to tell."""

    experiment: str
    figure: str
    a: str
    b: str
    a_rate: Rate
    b_rate: Rate
    z: float | None
    p_value: float | None
    enough: bool
    test: str


@dataclass(frozen=True)
class Listed:
    """One briefing in a list of the slowest or the worst checked. ``question`` is None unless the briefing is
    saved and has not been withdrawn or corrected since."""

    id: str
    at: str
    config_id: str
    briefing_id: str | None
    question: str | None
    t_first_token: int | None
    t_written: int | None
    t_total: int | None
    citations_invalid: int | None
    unsupported: int | None
    quotes_unverified: int | None
    loaded_words: int | None
    grounded_ratio: float | None
    corrected: bool


@dataclass(frozen=True)
class Asked:
    question: str
    times: int


@dataclass(frozen=True)
class Theme:
    """Questions that ask the same thing: one of them as an example (the most asked wording), how many questions
    there were, and in how many different wordings."""

    example: str
    questions: int
    wordings: int


@dataclass(frozen=True)
class Stats:
    since: str
    until: str
    compare_weeks: int
    scale: float  # the period's length over the earlier period's: multiply an earlier count or cost by it
    period: Figures
    earlier: Figures
    headline: Headline
    by_config: dict[str, Headline]
    by_config_earlier: dict[str, Headline]
    by_arm: dict[str, dict[str, Headline]]  # experiment, then arm
    decided_by: str | None
    arms: tuple[ArmComparison, ...]
    slowest: tuple[Listed, ...]
    worst_checked: tuple[Listed, ...]
    no_record_questions: tuple[Asked, ...]
    themes: tuple[Theme, ...]
    themes_by: str  # "meaning" (with an embedder) or "text"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)

    def to_markdown(self, site: Site, *, thresholds: Mapping[str, Any] | None = None,
                    margin: float | None = None) -> str:
        """The figures as a page to read, in plain words, with what tripped an alert (or, with no thresholds
        set, the thresholds proposed from these figures)."""
        # imported here because the report is built on this module, not the other way round
        from wts_core.observe.report import MARGIN, markdown

        return markdown(self, site, thresholds=thresholds, margin=MARGIN if margin is None else margin)


# ---- arithmetic --------------------------------------------------------------------------------------------------


def median(values: Iterable[float]) -> float | None:
    """The middle value, or the mean of the two middle values; None of nothing."""
    ordered = sorted(values)
    if not ordered:
        return None
    half = len(ordered) // 2
    return float(ordered[half]) if len(ordered) % 2 else (ordered[half - 1] + ordered[half]) / 2


def p95(values: Iterable[float]) -> float | None:
    """The 95th percentile by the nearest-rank method: the value at rank ``ceil(0.95 × n)``; None of nothing."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = (95 * len(ordered) + 99) // 100  # the ceiling, in whole numbers
    return float(ordered[rank - 1])


def two_proportion_test(x1: int, n1: int, x2: int, n2: int) -> TwoProportions:
    """Whether ``x1`` of ``n1`` and ``x2`` of ``n2`` are different proportions, by the two-proportion z-test with
    a pooled proportion, two-sided, at the 5% level.

    ``z = (p1 − p2) / sqrt(p(1 − p)(1/n1 + 1/n2))`` where ``p = (x1 + x2) / (n1 + n2)``, and the p-value is
    ``erfc(|z| / sqrt(2))``. The test leans on the normal approximation, so it is only made when each arm would
    expect at least 5 either way (``n × p`` and ``n × (1 − p)``): otherwise there are too few to tell, and
    ``enough`` is false with no ``z``."""
    if n1 <= 0 or n2 <= 0:
        return TwoProportions(None, None, False)
    pooled = (x1 + x2) / (n1 + n2)
    if min(n1 * pooled, n1 * (1 - pooled), n2 * pooled, n2 * (1 - pooled)) < EXPECTED_MIN:
        return TwoProportions(None, None, False)
    z = (x1 / n1 - x2 / n2) / math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    p_value = math.erfc(abs(z) / math.sqrt(2))
    return TwoProportions(z, p_value, p_value < LEVEL)


def _spread(values: Sequence[float]) -> Spread:
    return Spread(len(values), median(values), p95(values))


def _rate(count: int, of: int) -> Rate:
    return Rate(count, of, count / of if of else None)


def _share(rows: Sequence[BriefingRecord], test: Callable[[BriefingRecord], bool]) -> Rate:
    return _rate(sum(1 for r in rows if test(r)), len(rows))


def _tally(names: Iterable[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for name in names:
        found[name] = found.get(name, 0) + 1
    return dict(sorted(found.items(), key=lambda kv: (-kv[1], kv[0])))


def _when(at: str) -> datetime:
    moment = datetime.fromisoformat(at)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError(f"a period's times must say their timezone: {moment!r} does not")
    return moment.astimezone(UTC)


def _text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _steps(record: BriefingRecord) -> dict[str, int]:
    """The time from each point's predecessor to it, for the points this briefing reached."""
    steps: dict[str, int] = {}
    before = 0
    for mark in MARKS:
        reached = getattr(record, mark)
        if reached is None:
            continue
        steps[mark] = max(0, reached - before)
        before = max(before, reached)
    return steps


def _problems(record: BriefingRecord) -> int:
    return sum(n or 0 for n in (record.citations_invalid, record.unsupported, record.quotes_unverified,
                                record.loaded_words))


def _checked(record: BriefingRecord) -> bool:
    return any(n is not None for n in (record.citations_invalid, record.unsupported, record.quotes_unverified,
                                       record.loaded_words))


def _prompt_cache(rows: Sequence[BriefingRecord], pricing: Pricing | None) -> PromptCache:
    reads = sum(r.cache_read_tokens for r in rows)
    writes = sum(r.cache_write_tokens for r in rows)
    if pricing is None:
        return PromptCache(reads, writes, None, None, None)
    saved = extra = 0.0
    for r in rows:
        if not (r.cache_read_tokens or r.cache_write_tokens):
            continue
        price = pricing.price_for(r.model)
        saved += r.cache_read_tokens * (price.input - price.cache_read) / 1_000_000
        extra += r.cache_write_tokens * price.input * (price.cache_write_multiplier - 1) / 1_000_000
    saved, extra = round(saved, 6), round(extra, 6)
    return PromptCache(reads, writes, saved, extra, saved > extra if (reads or writes) else None)


def _figures(rows: Sequence[BriefingRecord], start: datetime, end: datetime, pricing: Pricing | None) -> Figures:
    """Every figure for the rows of one period (of every kind: all but ``by_kind`` use the readers' only)."""
    readers = [r for r in rows if r.kind == "reader"]
    fresh = [r for r in readers if r.outcome != "cached"]
    written = [r for r in readers if r.outcome == "completed"]
    checked = [r for r in readers if _checked(r)]
    rated = [r for r in readers if r.useful is not None]
    saved = [r for r in fresh if r.briefing_id]  # each saved briefing once: not its replays from the cache
    days = (end - start).total_seconds() / 86400
    cost = round(sum(r.cost_usd for r in readers), 6)
    by_day: dict[str, float] = {}
    for r in readers:
        day = _text(_when(r.at))[:10]
        by_day[day] = by_day.get(day, 0.0) + r.cost_usd
    steps = [_steps(r) for r in fresh]
    return Figures(
        start=_text(start), end=_text(end), days=days, questions=len(readers),
        by_outcome={o: sum(1 for r in readers if r.outcome == o) for o in OUTCOMES},
        by_kind={k: sum(1 for r in rows if r.kind == k) for k in KINDS},
        times={m: _spread([v for r in fresh if (v := getattr(r, m)) is not None]) for m in MARKS},
        steps={m: _spread([s[m] for s in steps if m in s]) for m in MARKS},
        cached_total=_spread([r.t_total for r in readers if r.outcome == "cached" and r.t_total is not None]),
        cost_usd=cost,
        cost_per_written_usd=round(sum(r.cost_usd for r in written) / len(written), 6) if written else None,
        cost_per_question_usd=round(cost / len(readers), 6) if readers else None,
        cost_per_day_usd=round(cost / days, 6) if days > 0 else None,
        cost_by_day={day: round(usd, 6) for day, usd in sorted(by_day.items())},
        cache_hits=_share(readers, lambda r: r.outcome == "cached"),
        prompt_cache=_prompt_cache(readers, pricing),
        invalid_citation=_share([r for r in checked if r.citations_invalid is not None],
                                lambda r: bool(r.citations_invalid)),
        unsupported=_share([r for r in checked if r.unsupported is not None], lambda r: bool(r.unsupported)),
        unverified_quote=_share([r for r in checked if r.quotes_unverified is not None],
                                lambda r: bool(r.quotes_unverified)),
        loaded_word=_share([r for r in checked if r.loaded_words is not None], lambda r: bool(r.loaded_words)),
        any_check=_share(checked, lambda r: _problems(r) > 0),
        no_records=_share(readers, lambda r: r.outcome == "no_records"),
        not_useful=_share(rated, lambda r: r.useful is False),
        left=_share(readers, lambda r: r.outcome == "left"),
        left_at=_tally(r.left_at or "unknown" for r in readers if r.outcome == "left"),
        errors=_share(readers, lambda r: r.outcome == "error"),
        errors_by_type=_tally(r.error_type or "unknown" for r in readers if r.outcome == "error"),
        reported=_share(saved, lambda r: r.reported),
        corrected=_share(saved, lambda r: r.corrected),
        followed_up=_share(saved, lambda r: r.followed_up),
    )


def _headline(figures: Figures) -> Headline:
    return Headline(
        questions=figures.questions, written=figures.by_outcome["completed"],
        first_token=figures.times["t_first_token"], full_briefing=figures.times["t_written"],
        cost_per_written_usd=figures.cost_per_written_usd, cache_hits=figures.cache_hits,
        any_check=figures.any_check, no_records=figures.no_records, not_useful=figures.not_useful,
        left=figures.left, errors=figures.errors)


def _by_config(readers: Sequence[BriefingRecord], start: datetime, end: datetime) -> dict[str, Headline]:
    ids = sorted({r.config_id for r in readers})
    return {c: _headline(_figures([r for r in readers if r.config_id == c], start, end, None)) for c in ids}


def _by_arm(readers: Sequence[BriefingRecord], start: datetime, end: datetime) -> dict[str, dict[str, Headline]]:
    found: dict[str, dict[str, Headline]] = {}
    for experiment, arm in sorted({(r.experiment, r.arm) for r in readers if r.experiment and r.arm}):
        mine = [r for r in readers if r.experiment == experiment and r.arm == arm]
        found.setdefault(str(experiment), {})[str(arm)] = _headline(_figures(mine, start, end, None))
    return found


def _compare_arms(by_arm: Mapping[str, Mapping[str, Headline]], figure: str) -> tuple[ArmComparison, ...]:
    found: list[ArmComparison] = []
    for experiment, arms in by_arm.items():
        names = sorted(arms)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ra: Rate = getattr(arms[a], figure)
                rb: Rate = getattr(arms[b], figure)
                result = two_proportion_test(ra.count, ra.of, rb.count, rb.of)
                found.append(ArmComparison(experiment, figure, a, b, ra, rb, result.z, result.p_value,
                                           result.enough, TEST))
    return tuple(found)


# ---- lists of briefings and of questions -----------------------------------------------------------------------


def _listed(record: BriefingRecord) -> Listed:
    public = bool(record.briefing_id) and not record.corrected
    return Listed(
        id=record.id, at=record.at, config_id=record.config_id, briefing_id=record.briefing_id or None,
        question=record.question if public and record.question else None, t_first_token=record.t_first_token,
        t_written=record.t_written, t_total=record.t_total, citations_invalid=record.citations_invalid,
        unsupported=record.unsupported, quotes_unverified=record.quotes_unverified,
        loaded_words=record.loaded_words, grounded_ratio=record.grounded_ratio, corrected=record.corrected)


def _slowest(readers: Sequence[BriefingRecord]) -> tuple[Listed, ...]:
    timed = [r for r in readers if r.outcome == "completed" and r.t_written is not None]
    timed.sort(key=lambda r: (-(r.t_written or 0), r.at, r.id))
    return tuple(_listed(r) for r in timed[:LISTED])


def _worst_checked(readers: Sequence[BriefingRecord]) -> tuple[Listed, ...]:
    """The briefings with the most problems found (invalid citations, unsupported sentences, unverified
    quotations and loaded words, added up); among equals, the least grounded first."""
    faulty = [r for r in readers if _problems(r) > 0]
    faulty.sort(key=lambda r: (-_problems(r), 1.0 if r.grounded_ratio is None else r.grounded_ratio, r.at, r.id))
    return tuple(_listed(r) for r in faulty[:LISTED])


_NOT_WORDS = re.compile(r"[\W_]+")


def _normal(question: str) -> str:
    """A question with case, punctuation and spacing set aside."""
    return _NOT_WORDS.sub(" ", question.casefold()).strip()


@dataclass
class _Wording:
    first: str  # as it was first asked
    times: int = 0


def _wordings(rows: Iterable[BriefingRecord]) -> dict[str, _Wording]:
    """Questions that may be quoted, by their normalised text: none from a briefing that ended in an error (its
    question is removed after 90 days, and must not outlive that in a report) or was withdrawn or corrected."""
    found: dict[str, _Wording] = {}
    for r in sorted(rows, key=lambda r: (r.at, r.id)):
        key = _normal(r.question)
        if not key or r.outcome == "error" or r.corrected:
            continue
        found.setdefault(key, _Wording(" ".join(r.question.split()))).times += 1
    return found


def _most_asked(wordings: Mapping[str, _Wording]) -> list[tuple[str, _Wording]]:
    return sorted(wordings.items(), key=lambda kv: (-kv[1].times, kv[0]))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0


def _themes(readers: Sequence[BriefingRecord], embedder: Embedder | None, similarity: float) -> tuple[Theme, ...]:
    asked = _most_asked(_wordings(readers))
    groups: list[list[_Wording]] = []
    if embedder is None or not asked:
        groups = [[w] for _, w in asked]
    else:
        vectors = [[float(x) for x in list(v)] for v in list(embedder.embed_documents([w.first for _, w in asked]))]
        firsts: list[list[float]] = []
        for (_, wording), vector in zip(asked, vectors, strict=True):
            best, best_likeness = -1, similarity
            for i, first in enumerate(firsts):
                likeness = _cosine(first, vector)
                if likeness >= similarity and (best < 0 or likeness > best_likeness):
                    best, best_likeness = i, likeness
            if best < 0:
                firsts.append(vector)
                groups.append([wording])
            else:
                groups[best].append(wording)
    themes = [Theme(g[0].first, sum(w.times for w in g), len(g)) for g in groups]
    themes = [t for t in themes if t.questions >= THEME_MIN]
    themes.sort(key=lambda t: (-t.questions, _normal(t.example)))
    return tuple(themes[:THEMES_LISTED])


# ---- the whole ---------------------------------------------------------------------------------------------------


def stats(log: BriefingHistory, *, since: datetime | timedelta, until: datetime | None = None,
          compare_weeks: int = 4, embedder: Embedder | None = None, similarity: float | None = None,
          pricing: Pricing | None = None, decided_by: str | None = None, clock: Clock = SYSTEM_CLOCK) -> Stats:
    """The figures for the period from ``since`` (a time, or how long before ``until``) up to ``until`` (now, if
    not given), each beside the same figure for the ``compare_weeks`` weeks before.

    ``embedder`` groups questions by meaning, and then ``similarity`` must be given too: the cosine similarity at
    which two questions count as one theme depends on the site's embedding model, so the package has no number of
    its own. ``pricing`` puts whether prompt caching paid back in dollars. ``decided_by`` names the rate that
    decides the site's experiment (one of ``PROPORTIONS``): with it, each pair of arms is tested.
    """
    if compare_weeks < 1:
        raise ValueError("compare_weeks must be at least 1: the figures are compared with the weeks before")
    if embedder is not None and similarity is None:
        raise ValueError("grouping questions by meaning needs similarity as well as an embedder: the cosine "
                         "similarity at which two questions are one theme, which depends on the site's model")
    if decided_by is not None and decided_by not in PROPORTIONS:
        raise ValueError(f"an experiment cannot be decided by {decided_by!r}: the rates are " + ", ".join(PROPORTIONS))
    end = _aware(until or clock.now())
    start = end - since if isinstance(since, timedelta) else _aware(since)
    if start >= end:
        raise ValueError("the period must begin before it ends")
    earlier_start = start - timedelta(weeks=compare_weeks)
    rows = list(log.since(earlier_start, end, kinds=KINDS))
    now = [r for r in rows if _when(r.at) >= start]
    before = [r for r in rows if _when(r.at) < start]
    readers = [r for r in now if r.kind == "reader"]
    period = _figures(now, start, end, pricing)
    by_arm = _by_arm(readers, start, end)
    return Stats(
        since=_text(start), until=_text(end), compare_weeks=compare_weeks,
        scale=(end - start) / (start - earlier_start),
        period=period, earlier=_figures(before, earlier_start, start, pricing), headline=_headline(period),
        by_config=_by_config(readers, start, end),
        by_config_earlier=_by_config([r for r in before if r.kind == "reader"], earlier_start, start),
        by_arm=by_arm, decided_by=decided_by,
        arms=_compare_arms(by_arm, decided_by) if decided_by else (),
        slowest=_slowest(readers), worst_checked=_worst_checked(readers),
        no_record_questions=tuple(
            Asked(w.first, w.times)
            for _, w in _most_asked(_wordings(r for r in readers if r.outcome == "no_records"))[:NO_RECORDS_LISTED]),
        themes=_themes(readers, embedder, similarity if similarity is not None else 1.0),
        themes_by="text" if embedder is None else "meaning",
    )
