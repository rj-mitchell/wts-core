"""The display rule for quotations beside their citation (wts_core.checks.display)."""

from __future__ import annotations

import random
from typing import Any

from wts_core.checks import Verifier, quotes_beside
from wts_core.checks.verify import COMMON_HONORIFICS, EVIDENCE_NOTES_WIDE


def seg(text: str, status: str = "connective", sources: list[int] | None = None, **more: Any) -> dict[str, Any]:
    return {"text": text, "sources": sources or [], "cited": [], "status": status, "loaded": [], "misquotes": [],
            **more}


def answer(*segments: dict[str, Any], unsupported: int = 1) -> dict[str, Any]:
    return {"segments": list(segments), "markdown": "", "no_records": False, "citations_total": 1,
            "citations_invalid": 0, "grounded_ratio": 0.5, "unsupported_segments": unsupported, "loaded_words": 0,
            "quotes_total": 1, "quotes_unverified": 0, "rules": 2}


# Where Countries Stand's saved briefing kGfKBI3cRLw (18 November 2026), its first two passages as saved
ITALY = answer(
    seg("Several European States, speaking nationally and for groups, backed limits on the veto and fuller use of "
        "Article 27, paragraph 3, as when Italy said it “supports all initiatives that seek to impose "
        "self-limitations on the use of veto” ", "unsupported"),
    seg("in November 2025", "cited", [1]),
    seg(". Countries from other regions went further"),
)


def test_a_quotation_found_in_the_source_cited_beside_it_is_shown_as_that_sources():
    shown = quotes_beside(ITALY)
    assert shown is not ITALY
    texts = [(s["text"], s["status"], s["sources"]) for s in shown["segments"]]
    assert texts[0][1] == "unsupported" and texts[0][0].endswith("as when Italy said it ")
    assert texts[1] == ("“supports all initiatives that seek to impose self-limitations on the use of veto”",
                        "cited", [1])
    assert shown["segments"][1]["beside"] is True
    assert texts[2] == (" ", "connective", [])
    assert texts[3] == ("in November 2025", "cited", [1])


def test_the_counts_and_the_text_are_the_verifiers_unchanged():
    shown = quotes_beside(ITALY)
    assert {k: v for k, v in shown.items() if k != "segments"} == {k: v for k, v in ITALY.items() if k != "segments"}
    assert "".join(s["text"] for s in shown["segments"]) == "".join(s["text"] for s in ITALY["segments"])
    assert ITALY["segments"][0]["status"] == "unsupported"  # the saved answer itself is left alone


def test_nothing_moves_without_a_cited_passage_straight_after():
    lone = answer(seg('Italy said it "supports all initiatives that seek limits" ', "unsupported"),
                  seg("in November 2025 and much later besides, as recorded", "connective"))
    assert quotes_beside(lone) is lone
    far = answer(seg('Italy said it "supports all initiatives that seek limits" and much more besides ',
                     "unsupported"), seg("in 2025", "cited", [1]))
    assert quotes_beside(far) is far


def test_a_misquoted_or_short_quotation_is_never_moved():
    bad = answer(seg('Italy said it "supports every initiative going" ', "unsupported",
                     misquotes=[{"start": 14, "end": 48, "text": "supports every initiative going"}]),
                 seg("in 2025", "cited", [1]))
    assert quotes_beside(bad) is bad
    term = answer(seg('It backed the "veto initiative" ', "unsupported"), seg("in 2025", "cited", [1]))
    assert quotes_beside(term) is term


def test_loaded_words_stay_on_the_words_they_mark():
    text = 'Ministers were attacked, and Italy said it "supports all initiatives that seek limits" '
    a = text.index("attacked")
    shown = quotes_beside(answer(seg(text, "unsupported", loaded=[{"start": a, "end": a + 8, "word": "attacked"}]),
                                 seg("in 2025", "cited", [1])))
    first = shown["segments"][0]
    assert first["loaded"] == [{"start": a, "end": a + 8, "word": "attacked"}]
    assert first["text"][a:a + 8] == "attacked"


def test_a_verified_briefing_keeps_the_verifiers_reading_of_the_quotation():
    """End to end with the verifier: the quotation it counted as found is the one shown as cited."""
    class Source:
        def __init__(self, n: int, text: str) -> None:
            self.n, self.title, self.blocks, self.meta = n, f"Source {n}", [text], {}

    verifier = Verifier(no_records="No records found", honorifics=COMMON_HONORIFICS,
                        evidence_notes=EVIDENCE_NOTES_WIDE)
    src = Source(1, "For this reason, Italy supports all initiatives that seek to impose self-limitations on the "
                    "use of veto, such as the French-Mexican initiative.")
    blocks = [{"type": "text", "text": "Several European States backed limits on the veto, as when Italy said it "
                                       "“supports all initiatives that seek to impose self-limitations on the "
                                       "use of veto” "},
              {"type": "text", "text": "in November 2025",
               "citations": [{"search_result_index": 0, "cited_text": src.blocks[0], "start_block_index": 0,
                              "end_block_index": 0, "type": "search_result_location"}]},
              {"type": "text", "text": "."}]
    report = verifier.verify(blocks, [src])
    verifier.check_quotes(report, [src])
    assert report.quotes_total == 1 and report.quotes_unverified == 0
    before = report.to_dict()
    shown = quotes_beside(before)
    # the quotation the verifier found is never shown inside a passage marked as having no source
    assert not any(s["status"] == "unsupported" and "\u201csupports" in s["text"] for s in shown["segments"])
    assert shown["unsupported_segments"] == before["unsupported_segments"]


def test_property_the_rule_never_marks_or_cites_anything_new():
    """Over many made-up briefings: the text is the same, no passage is newly unsupported, the counts are the same,
    and every passage newly cited is a whole quotation of at least three words whose citation is the very next
    passage's."""
    rng = random.Random(20261121)
    words = ["the", "veto", "council", "reform", "must", "be", "abolished", "restraint", "atrocities", "members", "initiative"]
    for _ in range(3000):
        segs = []
        for _ in range(rng.randint(1, 7)):
            kind = rng.choice(["connective", "unsupported", "cited", "invalid"])
            body = " ".join(rng.choice(words) for _ in range(rng.randint(1, 8)))
            if rng.random() < 0.5:
                q = " ".join(rng.choice(words) for _ in range(rng.randint(1, 6)))
                body += rng.choice([' "', " “"]) + q + rng.choice(['"', "”"]) + rng.choice(["", " ", ". ", "    "])
            segs.append(seg(body, kind, [rng.randint(1, 4)] if kind == "cited" else [],
                            misquotes=[{"start": 0, "end": 1, "text": "x"}] if rng.random() < 0.1 else []))
        before = answer(*segs, unsupported=sum(s["status"] == "unsupported" for s in segs))
        shown = quotes_beside(before)
        assert "".join(s["text"] for s in shown["segments"]) == "".join(s["text"] for s in segs)
        assert {k: v for k, v in shown.items() if k != "segments"} == {k: v for k, v in before.items() if k != "segments"}
        unsupported_before = sum(len(s["text"]) for s in segs if s["status"] == "unsupported")
        unsupported_after = sum(len(s["text"]) for s in shown["segments"] if s["status"] == "unsupported")
        assert unsupported_after <= unsupported_before
        out = shown["segments"]
        for j, s in enumerate(out):
            if s.get("beside"):
                assert s["text"][0] in '"“' and s["text"][-1] in '"”'
                assert len(s["text"].strip('"“”').split()) >= 3
                nxt = next(t for t in out[j + 1:] if t["text"].strip(" .,;:!?"))
                assert nxt["status"] == "cited" and nxt["sources"] == s["sources"]
