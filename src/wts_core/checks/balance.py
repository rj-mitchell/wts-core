"""The three small pieces every site's ranking shares, which decide which voices a briefing hears.

Each site's ``rank/composite.py`` and ``rank/evidence.py`` follow its own record (its groups, its caps, its weights
for office or role) and stay with it. Three pieces are the same lines in all three, and a fix to one had to be made
three times: the blend of the two relevance scores, the recency factor, and the round-robin across groups. They are
here as the sites have them, statement for statement, so the arithmetic gives the same numbers to the last place;
the grouping, the caps and every weight are passed in, and the package has a default for none of them.

Dates are passed in: nothing here reads the clock.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from datetime import date

__all__ = ["blend", "recency_factor", "round_robin"]


def blend(word_scores: Sequence[float | None], meaning_scores: Sequence[float | None], *, word_weight: float,
          meaning_floor: float, meaning_ceiling: float) -> list[float]:
    """Relevance, from 0 to 1, for each of a set of candidates found by words, by meaning or by both.

    ``word_scores``: each candidate's score from the search by words (BM25), or None; it is divided by the best in
    the set. ``meaning_scores``: its similarity from the search by meaning (cosine), or None; it is placed within
    the embedding model's range, ``meaning_floor`` to ``meaning_ceiling``, so a weak match is not inflated. The two
    are weighed by ``word_weight`` when the set has both kinds of score; with only one kind, that one is all.
    """
    best = max((b for b in word_scores if b), default=0.0)
    has_meaning = any(c is not None for c in meaning_scores)
    w = word_weight if (best and has_meaning) else (1.0 if best else 0.0)
    span = max(meaning_ceiling - meaning_floor, 1e-6)
    out: list[float] = []
    for b, c in zip(word_scores, meaning_scores, strict=True):
        kw = (b or 0.0) / best if best else 0.0
        sem = 0.0 if c is None else min(max((c - meaning_floor) / span, 0.0), 1.0)
        out.append(w * kw + (1 - w) * sem)
    return out


def recency_factor(d: date, today: date, *, recency: float, floor: float, min_half_life_years: float) -> float:
    """What a record's relevance is multiplied by for its age: 1 for one dated today (or later), halving towards
    ``floor`` with every half-life. ``recency`` is the reader's slider, from 0 to 1: at 0 age counts for nothing,
    and at 1 the half-life is ``min_half_life_years``, the shortest a site allows."""
    if recency <= 0:
        return 1.0
    half_life = min_half_life_years / recency
    age_years = max((today - d).days, 0) / 365.25
    factor: float = floor + (1 - floor) * 0.5 ** (age_years / half_life)
    return factor


def round_robin[T](pool: Sequence[T], limit: int, *, group_of: Callable[[T], str], key_of: Callable[[T], str],
                   score_of: Callable[[T], float], caps: Sequence[tuple[Callable[[T], str], int]] = (),
                   seeds: Sequence[T] = ()) -> list[T]:
    """Up to ``limit`` of ``pool``, taken a group at a time so that no group crowds out the others.

    ``pool``: the records relevant enough to be heard, best first (the site has already dropped those below its
    relevance floor). ``group_of``: the group a record belongs to, by the site's own grouping. ``key_of``: the
    record's id; none is taken twice. ``score_of``: its score. ``caps``: pairs of a function naming what is capped
    (the speaker, the country, the council, the meeting) and how many records of each may be taken. ``seeds``:
    records to take first, if the caps allow (Where MPs Stand's members who keep raising the subject).

    The groups take turns, the group with the best record first, each giving its best record still allowed, until
    there are enough or no group can give one; any places left are filled by score. The result is in order of
    score, then id.
    """
    groups: dict[str, list[T]] = defaultdict(list)
    for s in pool:  # already in score order
        groups[group_of(s)].append(s)
    order = sorted(groups, key=lambda g: -score_of(groups[g][0]))
    chosen: list[T] = []
    taken: set[str] = set()
    counts: list[Counter[str]] = [Counter() for _ in caps]

    def take(s: T) -> bool:
        key = key_of(s)
        capped = [of(s) for of, _ in caps]
        if key in taken or any(counts[i][c] >= caps[i][1] for i, c in enumerate(capped)):
            return False
        chosen.append(s)
        taken.add(key)
        for i, c in enumerate(capped):
            counts[i][c] += 1
        return True

    for s in seeds:
        if len(chosen) < limit:
            take(s)

    progress = True
    while len(chosen) < limit and progress:
        progress = False
        for g in order:
            for s in groups[g]:
                if take(s):
                    progress = True
                    break
            if len(chosen) >= limit:
                break
    for s in pool:  # fill by score if the groups ran dry
        if len(chosen) >= limit:
            break
        take(s)
    chosen.sort(key=lambda s: (-score_of(s), key_of(s)))
    return chosen
