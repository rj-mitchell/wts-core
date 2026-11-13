"""The evidence that readers will see no change: the package's checks give what each site's own copy gives.

Each site's own modules are loaded from its checkout (``checks_sites.theirs``; the tests are skipped where there is
none) and run beside the package's, with that site's inputs, on a few hundred generated briefings and on every
fragment they are made of. The package stamps its reports with ``rules``; nothing else may differ.
"""

from __future__ import annotations

import random
import re
from collections import defaultdict
from datetime import date, timedelta
from itertools import product
from typing import Any

import pytest

from checks_sites import (
    CITED,
    CLAIMS,
    COUNTRIES,
    JOINS,
    LEAD_INS,
    NOTES,
    RECORDS,
    SITES,
    SiteChecks,
    as_saved,
    briefings,
    theirs,
)
from wts_core.checks import (
    Segment,
    Verification,
    blend,
    britishise_segments,
    curl_answer,
    curl_events,
    curl_quotes,
    outside_quotes,
    recency_factor,
    round_robin,
    to_british,
)
from wts_core.checks import british as our_british
from wts_core.checks import typography as our_typography
from wts_core.checks import verify as our_verify

COUNT = 400  # generated briefings for each site
FRAGMENTS = (*LEAD_INS, *CLAIMS, *NOTES, *JOINS, *RECORDS, *(said for said, _ in CITED))


@pytest.fixture(params=SITES, ids=lambda s: s.name)
def site(request: pytest.FixtureRequest) -> SiteChecks:
    return request.param


def unstamped(answer: dict[str, Any]) -> dict[str, Any]:
    assert answer["rules"] == 1
    return {k: v for k, v in answer.items() if k != "rules"}


def as_dicts(segments: list[Any]) -> list[dict[str, Any]]:
    return [s.to_dict() for s in segments]


def texts(count: int = COUNT) -> list[str]:
    """Whole briefings' texts and every fragment they are made of."""
    return [*FRAGMENTS, *("".join(b["text"] for b in blocks) for blocks, _ in briefings(count))]


# ---- the same rules ---------------------------------------------------------------------------------------------


def test_each_sites_inputs_are_what_its_own_copy_has(site):
    t = theirs(site)
    assert site.no_records == t.prompts.NO_RECORDS
    v = site.verifier
    assert (v._honorific_dot.pattern, v._honorific_dot.flags) == (t.verify._HONORIFIC_DOT.pattern,
                                                                  t.verify._HONORIFIC_DOT.flags)
    assert (site.evidence_notes.pattern, site.evidence_notes.flags) == (t.verify._EVIDENCE_NOTE.pattern,
                                                                        t.verify._EVIDENCE_NOTE.flags)
    assert (site.loaded.pattern, site.loaded.flags) == (t.neutral.LOADED.pattern, t.neutral.LOADED.flags)
    assert site.curled == hasattr(t, "typography")


def test_every_other_pattern_word_list_and_limit_is_the_sites(site):
    """Whatever is not passed in is the same, character for character, in the package and in each site."""
    t = theirs(site)
    pairs = [(our_verify, t.verify), (our_british, t.british)]
    if site.curled:
        pairs.append((our_typography, t.typography))
    compared = 0
    for ours, their in pairs:
        for name, value in vars(their).items():
            if name in ("_HONORIFIC_DOT", "_EVIDENCE_NOTE", "NO_RECORDS") or name.startswith("__"):  # passed in
                continue
            if isinstance(value, re.Pattern):
                mine = getattr(ours, name)
                assert (mine.pattern, mine.flags) == (value.pattern, value.flags), name
                compared += 1
            elif isinstance(value, int | str | dict | set | frozenset) and not isinstance(value, bool):
                assert getattr(ours, name) == value, name
                compared += 1
    assert compared >= 14  # the verifier's twelve patterns and limits, and the spelling lists


# ---- a new briefing ---------------------------------------------------------------------------------------------


def test_verify_gives_the_sites_report(site):
    t = theirs(site)
    v = site.verifier
    seen: dict[str, int] = defaultdict(int)
    for blocks, sources in briefings(COUNT):
        mine, their = v.verify(blocks, sources), t.verify.verify(blocks, sources)
        assert unstamped(mine.to_dict()) == their.to_dict()
        assert (mine.unsupported_chars, mine.cited_chars, mine.grounded_ratio, mine.markdown()) == (
            their.unsupported_chars, their.cited_chars, their.grounded_ratio, their.markdown())
        for s in mine.segments:
            seen[s.status] += 1
        seen["no records"] += mine.no_records
    assert min(seen[k] for k in ("cited", "connective", "unsupported", "invalid", "no records")) > 0, dict(seen)


def test_every_uncited_fragment_is_classed_as_the_site_classes_it(site):
    t = theirs(site)
    v = site.verifier
    pieces = [*FRAGMENTS, *(a + b for a, b in product(CLAIMS[:12] + NOTES + JOINS, LEAD_INS))]
    assert len(pieces) > 1000
    for text, next_is_cited, flagged in product(pieces, (False, True), (False, True)):
        mine = v._classify_uncited(text, next_is_cited, flagged)
        their = t.verify._classify_uncited(text, next_is_cited, flagged)
        assert as_dicts(mine) == as_dicts(their), (text, next_is_cited, flagged)
    for text in pieces:
        assert v._is_lead_in_piece(text) == t.verify._is_lead_in_piece(text), text


def test_drop_preambles_gives_what_the_sites_gives(site):
    t = theirs(site)
    for text in texts():
        mine, their = [Segment(text)], [t.verify.Segment(text)]
        assert site.verifier.drop_preambles(mine) == t.verify.drop_preambles(their) and mine[0].text == their[0].text


def test_check_quotes_gives_what_the_sites_gives(site):
    t = theirs(site)
    v = site.verifier
    quotes = bad = 0
    for blocks, sources in briefings(COUNT):
        mine, their = v.verify(blocks, sources), t.verify.verify(blocks, sources)
        assert v.check_quotes(mine, sources) == t.verify.check_quotes(their, sources)
        assert as_dicts(mine.segments) == as_dicts(their.segments)
        assert (mine.quotes_total, mine.quotes_unverified) == (their.quotes_total, their.quotes_unverified)
        quotes, bad = quotes + mine.quotes_total, bad + mine.quotes_unverified
        # and with no citation to go by: every quotation looked for in every source
        mine = Verification([Segment(s.text, status="connective") for s in mine.segments], False, 0, 0, 0, 0)
        their = t.verify.Verification([t.verify.Segment(s.text, status="connective") for s in their.segments],
                                      False, 0, 0, 0, 0)
        assert v.check_quotes(mine, sources) == t.verify.check_quotes(their, sources)
        assert as_dicts(mine.segments) == as_dicts(their.segments)
    assert 0 < bad < quotes
    for text, record in product(FRAGMENTS, RECORDS):
        assert our_verify._found(text, our_verify._words(record)) == t.verify._found(text, t.verify._words(record))


def test_the_whole_run_of_checks_gives_the_sites_answer(site):
    """Every check, in the order all three pipelines run them, and the answer as it is sent and saved."""
    t = theirs(site)
    loaded = 0
    for blocks, sources in briefings(COUNT):
        mine = site.check(blocks, sources)
        assert unstamped(mine) == t.check(blocks, sources)
        loaded += mine["loaded_words"]
    assert loaded > 0


# ---- a saved briefing, shown again ------------------------------------------------------------------------------


def test_recheck_gives_what_the_sites_recheck_gives(site):
    """On answers with no stamp, which is every answer saved before the package: as a new briefing was sent, and as
    one saved under older rules might be (passages flagged that today's rules clear)."""
    t = theirs(site)
    v = site.verifier
    rng = random.Random(4)
    cleared = kept = 0
    for blocks, sources in briefings(COUNT):
        fresh = unstamped(site.check(blocks, sources))
        for saved in (fresh, as_saved(fresh, rng), as_saved(fresh, rng)):
            mine, their = v.recheck(saved, curled=site.curled), t.recheck(saved)
            assert mine == their
            assert (mine is saved) == (their is saved)  # an answer with nothing to clear comes back itself
            cleared, kept = cleared + (mine is not saved), kept + (mine is saved)
            # the plain recheck, which every site's copy has
            plain, their_plain = v.recheck(saved), t.verify.recheck_flags(saved)
            assert plain == their_plain and (plain is saved) == (their_plain is saved)
    assert cleared > COUNT // 4 and kept > COUNT // 4
    for nothing in (None, {}, {"segments": []}, {"segments": None}):
        assert v.recheck(nothing) == t.verify.recheck_flags(nothing)


def test_a_saved_briefing_is_shown_as_the_site_shows_it(site):
    """The recheck and the loaded-word marks together, as each site's app does when a briefing is opened again."""
    t = theirs(site)
    rng = random.Random(5)
    changed = 0
    for blocks, sources in briefings(COUNT):
        fresh = unstamped(site.check(blocks, sources))
        for saved in (fresh, as_saved(fresh, rng)):
            mine = site.shown_again(saved)
            assert mine == t.shown_again(saved)
            changed += mine != saved
    assert changed > COUNT // 4
    assert site.shown_again(None) is None and t.shown_again(None) is None


# ---- loaded words -----------------------------------------------------------------------------------------------


def test_flag_loaded_gives_what_the_sites_gives(site):
    t = theirs(site)
    found = 0
    for text in texts():
        mine, their = [Segment(text)], [t.verify.Segment(text)]
        assert site.loaded_words.flag(mine) == t.neutral.flag_loaded(their)
        assert mine[0].loaded == their[0].loaded
        found += len(mine[0].loaded)
    assert found > 100
    for blocks, sources in briefings(COUNT):  # across segments, where a quotation may open in one and close in another
        mine, their = site.verifier.verify(blocks, sources).segments, t.verify.verify(blocks, sources).segments
        assert site.loaded_words.flag(mine) == t.neutral.flag_loaded(their)
        assert [s.loaded for s in mine] == [s.loaded for s in their]


def test_still_loaded_gives_what_the_sites_gives(site):
    t = theirs(site)
    rng = random.Random(6)
    dropped = 0
    for blocks, sources in briefings(COUNT):
        saved = as_saved(site.check(blocks, sources), rng)
        mine, their = site.loaded_words.still_loaded(saved), t.neutral.still_loaded(saved)
        assert mine == their and (mine is saved) == (their is saved)
        dropped += saved["loaded_words"] - mine["loaded_words"]
    assert dropped > 100
    for nothing in (None, {}, {"segments": []}):
        assert site.loaded_words.still_loaded(nothing) == t.neutral.still_loaded(nothing)


# ---- spelling and typography ------------------------------------------------------------------------------------


def test_to_british_gives_what_the_sites_gives(site):
    t = theirs(site)
    # every word on the list and every word kept from the -ise rule, in each place a capital changes the answer
    listed = sorted({*t.british._WORDS, *t.british._IZE_KEEP, "organize", "recognized", "analyzing", "citizens",
                     "emphasized", "privatization", "organizers", "seizure", "horizon", "bizarre"})
    spelt = [f'The {w} was noted. {w.capitalize()} too, by the {w.capitalize()} Party, in {w.upper()}; "the {w}" '
             f"and a computer {w}.\n- {w.capitalize()}: “{w}” {w}" for w in listed]
    assert len(spelt) > 130
    changed = 0
    for text in (*spelt, *texts()):
        assert to_british(text) == t.british.to_british(text)
        changed += to_british(text) != text
    assert changed > 150


def test_spelling_across_segments_gives_what_the_sites_gives(site):
    t = theirs(site)
    for blocks, sources in briefings(COUNT):
        mine, their = site.verifier.verify(blocks, sources).segments, t.verify.verify(blocks, sources).segments
        assert outside_quotes(mine) == t.british.outside_quotes(their)
        britishise_segments(mine)
        t.british.britishise_segments(their)
        assert [s.text for s in mine] == [s.text for s in their]


def test_curly_quotes_give_what_where_countries_stands_gives():
    site = COUNTRIES  # the one site with a typography module
    t = theirs(site)
    for text in texts():
        assert curl_quotes(text) == t.typography.curl_quotes(text)
    for blocks, sources in briefings(COUNT):
        answer = site.verifier.verify(blocks, sources).to_dict()
        assert curl_answer(answer) == t.typography.curl_answer(answer)
        events = [{"type": "plan", "plan": {"interpretation": blocks[0]["text"]}}, {"type": "sources", "sources": []},
                  {"type": "text", "text": answer["markdown"]}, {"type": "final", "answer": answer, "usage": None}]
        assert curl_events(events) == t.typography.curl_events(events)


# ---- the three functions the rankings share ---------------------------------------------------------------------

TODAY = date(2026, 10, 1)


def candidates(rng: random.Random, t: Any, site: SiteChecks) -> list[Any]:
    """Candidates as the site's engine makes them, with scores that tie and data its grouping and caps read."""
    out = []
    kinds = rng.choice(("both", "both", "words", "meaning", "neither"))
    for i in range(rng.randint(0, 60)):
        council, meeting = rng.choice(("E06000001", "E06000002", "E07000003", "")), rng.randint(1, 6)
        data: dict[str, Any] = {
            "gss": council, "control": rng.choice(("LAB", "CON", "NOC", None)), "region": rng.choice(("NE", "NW", None)),
            "council_type": rng.choice(("county", "unitary", None)),
            "country_code": rng.choice(("FRA", "KEN", "FJI", "USA", None)), "country_name": rng.choice(("France", None)),
            "speaker_name": rng.choice(("A", "B", "C", None)), "on_behalf_of": rng.choice((None, None, None, "EU")),
            "group_statement": rng.random() < 0.05, "entity_kind": rng.choice(("state", "state", "un", None)),
            "groups": rng.sample(("p5", "council_elected", "eu", "nato", "g77", "region:africa", "region:europe"),
                                 rng.randint(0, 3))}
        out.append(t.composite.Candidate(
            record_id=f"{council or 'X'}:{meeting}:{i:03d}" if site.name == "councils" else f"r{i:03d}",
            date=TODAY - timedelta(days=rng.randint(-30, 6000)),
            bm25=rng.choice((None, 0.0, round(rng.uniform(0, 12), 1))) if kinds in ("both", "words") else None,
            cosine=rng.choice((None, round(rng.uniform(0.3, 0.95), 2))) if kinds in ("both", "meaning") else None,
            data=data))
    return out


def profiles(rng: random.Random, found: list[Any]) -> dict[str, Any]:
    """Where MPs Stand's speaker profiles, by record."""
    out = {}
    for c in found:
        if rng.random() < 0.9:
            out[c.record_id] = {
                "person_id": rng.choice((None, "p1", "p2", "p3", "p4", "p5", "p6")),
                "offices": rng.choice(([], [], [{"kind": "gov"}], [{"kind": "shadow"}], [{"kind": "chair"}])),
                "house": rng.choice(("commons", "commons", "lords", None)),
                "settlement": rng.choice(("city", "town", "rural", None)), "gender": rng.choice(("f", "m", None)),
                "first_term": rng.choice((True, False, None)), "majority_band": rng.choice(("safe", "marginal", None)),
                "runner_up": rng.choice(("con", "lab", None)), "age_band": rng.choice(("40s", "50s", None)),
                "party_groups": rng.choice(([], [{"id": "g1"}], [{"id": "g2"}, {"id": "g1"}]))}
    return out


def ranked(rng: random.Random, t: Any, site: SiteChecks) -> tuple[list[Any], Any]:
    params = t.composite.RankParams(today=TODAY, recency=rng.choice((0.0, 0.25, 0.4, 1.0, round(rng.random(), 2))),
                                    bm25_weight=rng.choice((0.5, 0.3, 1.0, 0.0)),
                                    semantic_floor=rng.choice((0.5, 0.0, 0.85)),
                                    semantic_ceiling=rng.choice((0.85, 0.8, 0.5)))
    found = candidates(rng, t, site)
    return (t.composite.rank(found, set(), params) if site.name == "mps" else t.composite.rank(found, params)), params


def test_the_blend_and_the_recency_factor_give_the_sites_numbers_exactly(site):
    t = theirs(site)
    rng = random.Random(7)
    compared = 0
    for _ in range(COUNT):
        scored, p = ranked(rng, t, site)
        found = [s.candidate for s in scored]
        mine = blend([c.bm25 for c in found], [c.cosine for c in found], word_weight=p.bm25_weight,
                     meaning_floor=p.semantic_floor, meaning_ceiling=p.semantic_ceiling)
        assert mine == [s.relevance for s in scored]  # the same floats, not nearly the same
        for s in scored:
            factor = recency_factor(s.candidate.date, p.today, recency=p.recency, floor=p.recency_floor,
                                    min_half_life_years=p.min_half_life_years)
            assert factor == s.recency == t.composite.recency_factor(s.candidate.date, p)
        compared += len(scored)
    assert compared > 5000


def select_with_the_package(site: SiteChecks, t: Any, scored: list[Any], k: int, known: dict[str, Any],
                            options: dict[str, Any]) -> list[Any]:
    """Each site's ``select_evidence`` as it will be written on the package's ``round_robin``: its own relevance
    floor, grouping, caps and (Where MPs Stand) seeds, and nothing else."""
    if not scored:
        return []

    def record(s: Any) -> str:
        return s.candidate.record_id

    def relevance(s: Any) -> float:
        base = getattr(s, "base_relevance", None)  # Where MPs Stand: search relevance before re-ranking
        return s.relevance if base is None else base

    best = max(relevance(s) for s in scored)
    pool = [s for s in scored if relevance(s) >= best * options["min_relevance_ratio"]]
    by, ev = options["group_by"], t.evidence
    if site.name == "countries":
        def who(s: Any) -> str:
            d = s.candidate.data
            return f"{d.get('country_code') or d.get('country_name')}|{d.get('speaker_name')}"

        def country(s: Any) -> str:
            d = s.candidate.data
            return d.get("on_behalf_of") or d.get("country_code") or d.get("country_name") or record(s)

        return round_robin(pool, k, group_of=lambda s: ev.evidence_group(s.candidate.data, by), key_of=record,
                           score_of=lambda s: s.score,
                           caps=[(who, options["max_per_speaker"]), (country, options["max_per_country"])])
    if site.name == "councils":
        return round_robin(pool, k, group_of=lambda s: ev.evidence_group(s.candidate.data, by), key_of=record,
                           score_of=lambda s: s.score,
                           caps=[(lambda s: s.candidate.data.get("gss") or "", options["max_per_council"]),
                                 (lambda s: record(s).rsplit(":", 1)[0], options["max_per_meeting"])])

    def speaker(s: Any) -> str:
        return ev._person(known.get(record(s))) or record(s)

    def group(s: Any) -> str:
        prof = known.get(record(s))
        return ev.speaker_group(prof) if by == "role" else ev.demographic_group(prof, by, options["only_groups"])

    # members who keep raising the subject (the site's own: who they are follows its record)
    days: dict[str, set[Any]] = defaultdict(set)
    first: dict[str, Any] = {}
    for s in pool:
        prof = known.get(record(s))
        pid = ev._person(prof)
        if pid and ev.speaker_group(prof) != "gov":
            days[pid].add(s.candidate.date)
            first.setdefault(pid, s)
    persistent = sorted((pid for pid, d in days.items() if len(d) >= options["min_occasions"]),
                        key=lambda pid: (-len(days[pid]), -first[pid].score, pid))[:options["max_persistent"]]
    return round_robin(pool, k, group_of=group, key_of=record, score_of=lambda s: s.score,
                       caps=[(speaker, options["max_per_speaker"])], seeds=[first[pid] for pid in persistent])


def test_the_round_robin_selects_what_each_sites_select_evidence_selects(site):
    t = theirs(site)
    rng = random.Random(8)
    selected = short = 0
    for _ in range(COUNT * 2):
        scored, _ = ranked(rng, t, site)
        k = rng.choice((0, 1, 3, 8, 12, 20, 100))
        options: dict[str, Any] = {"min_relevance_ratio": rng.choice((0.25, 0.0, 0.6, 1.0))}
        known: dict[str, Any] = {}
        if site.name == "mps":
            known = profiles(rng, [s.candidate for s in scored])
            for s in scored:
                if rng.random() < 0.2:
                    s.base_relevance = round(rng.random(), 2)
            options |= {"max_per_speaker": rng.choice((1, 2, 3)), "min_occasions": rng.choice((1, 2, 3)),
                        "max_persistent": rng.choice((0, 1, 4)), "only_groups": rng.choice((None, ["g1"])),
                        "group_by": rng.choice(("role", "gender", "age", "tenure", "majority", "runner_up", "group"))}
            their = t.evidence.select_evidence(scored, known, k, **options)
        elif site.name == "countries":
            options |= {"max_per_speaker": rng.choice((1, 2, 3)), "max_per_country": rng.choice((1, 2, 5)),
                        "group_by": rng.choice(t.evidence.GROUP_BY)}
            their = t.evidence.select_evidence(scored, k, **options)
        else:
            options |= {"max_per_council": rng.choice((1, 2, 3)), "max_per_meeting": rng.choice((1, 2)),
                        "group_by": rng.choice(t.evidence.GROUP_BY)}
            their = t.evidence.select_evidence(scored, k, **options)
        mine = select_with_the_package(site, t, scored, k, known, options)
        assert len(mine) == len(their) and all(a is b for a, b in zip(mine, their, strict=True)), (k, options)
        selected, short = selected + len(mine), short + (0 < len(mine) < min(k, len(scored)))
    assert selected > 2000 and short > 50  # and the caps did bite
