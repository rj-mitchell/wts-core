"""Judging a briefing again, done properly (MIGRATION.md 1.4): the property the design asks for.

A saved briefing keeps its segments but not the blocks the model wrote, so judging it again can never repeat exactly
what verify() did the first time. Every answer is therefore stamped with the version of the rules that wrote it, and
rechecking what today's verifier has just written changes nothing. With the stamp taken off (an answer saved before
the package), the recheck may clear a flag and can never add one.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from checks_sites import SITES, SiteChecks, as_saved, briefings

COUNT = 3000  # generated briefings for each site, the same every time


@pytest.fixture(params=SITES, ids=lambda s: s.name)
def site(request: pytest.FixtureRequest) -> SiteChecks:
    return request.param


def flags(answer: dict[str, Any]) -> list[bool]:
    return [s["status"] in ("unsupported", "invalid") for s in answer["segments"]]


def ratio(answer: dict[str, Any]) -> float:
    cited = sum(len(s["text"]) for s in answer["segments"] if s["status"] == "cited")
    flagged = sum(len(s["text"]) for s in answer["segments"] if s["status"] in ("unsupported", "invalid"))
    return round(1.0 if not cited + flagged else cited / (cited + flagged), 3)


def assert_nothing_is_newly_flagged(before: dict[str, Any], after: dict[str, Any]) -> None:
    assert [s["text"] for s in after["segments"]] == [s["text"] for s in before["segments"]]
    for was, now in zip(before["segments"], after["segments"], strict=True):
        if now["status"] != was["status"]:  # the one change there may be: a point to check is cleared
            assert (was["status"], now["status"]) == ("unsupported", "connective")
        assert len(now.get("loaded") or []) <= len(was.get("loaded") or [])
        assert now.get("misquotes") == was.get("misquotes") and now.get("sources") == was.get("sources")
    assert after["unsupported_segments"] <= before["unsupported_segments"]
    # the ratio is kept, or, when a flag is cleared, worked out again from the saved text (which the later checks
    # may have changed by a character or two since verify() counted it): never below what that text and its flags give
    assert after["grounded_ratio"] >= min(before["grounded_ratio"], ratio(before))
    assert after["loaded_words"] <= before["loaded_words"]
    assert {k: v for k, v in after.items() if k not in ("segments", "unsupported_segments", "grounded_ratio",
                                                         "loaded_words")} == {
        k: v for k, v in before.items() if k not in ("segments", "unsupported_segments", "grounded_ratio",
                                                      "loaded_words")}


def test_rechecking_what_verify_has_just_written_changes_nothing(site):
    v = site.verifier
    flagged = 0
    for blocks, sources in briefings(COUNT):
        report = v.verify(blocks, sources)
        answer = report.to_dict()  # as verify() leaves it
        assert answer["rules"] == v.rules_version
        assert v.recheck(answer) is answer and v.recheck(answer, curled=True) is answer
        sent = site.check(blocks, sources)  # and as it is sent and saved, after every other check
        assert v.recheck(sent, curled=site.curled) is sent
        assert site.shown_again(sent) == sent
        flagged += sent["unsupported_segments"]
    assert flagged > COUNT  # there were flags to lose


def test_with_the_stamp_removed_the_recheck_never_adds_a_flag(site):
    v = site.verifier
    rng = random.Random(9)
    cleared_fresh = cleared_saved = 0
    for blocks, sources in briefings(COUNT):
        sent = site.check(blocks, sources)
        fresh = {k: x for k, x in sent.items() if k != "rules"}
        for saved in (fresh, as_saved(fresh, rng)):
            for curled in (False, True):
                out = v.recheck(saved, curled=curled)
                assert_nothing_is_newly_flagged(saved, out)
                assert out is saved or flags(out) != flags(saved)  # changed only to clear something
            shown = site.shown_again(saved)
            assert_nothing_is_newly_flagged(saved, shown)
        cleared_fresh += flags(v.recheck(fresh, curled=site.curled)) != flags(fresh)
        cleared_saved += flags(site.shown_again(saved)) != flags(saved)
    assert cleared_saved > COUNT // 4  # flags that older rules made and today's clear are cleared
    # without the stamp, the recheck would clear a little of what verify() has just flagged: that is why the stamp
    # is there, and it must stay a little (phase 1's fixes: never for shortness, nor for standing before a lead-in)
    assert cleared_fresh <= COUNT // 100, cleared_fresh
