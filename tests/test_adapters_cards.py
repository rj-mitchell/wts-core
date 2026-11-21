"""Share cards for saved briefings (wts_core.adapters.cards)."""

from __future__ import annotations

import io

import pytest

from wts_core.checks import CheckCounts, check_counts, quotes_beside

PIL = pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from wts_core.adapters.cards import CardStyle, briefing_card, card_count_lines  # noqa: E402

STYLE = CardStyle(site_name="Where MPs Stand", domain="wherempsstand.com", cloth=(29, 69, 53), record="Hansard")


def test_a_card_is_a_1200_by_630_png_in_the_sites_cloth():
    png = briefing_card(STYLE, title="Briefing from Hansard, 17 November 2026",
                        counts=CheckCounts(19, 19, 19, 19, 0), prepared="17 November 2026")
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.size == (1200, 630)
    assert img.convert("RGB").getpixel((5, 5)) == (29, 69, 53)


def test_the_same_briefing_draws_the_same_card():
    args = dict(title="The cost of living", counts=CheckCounts(16, 16, 15, 15, 2), prepared="18 November 2026")
    assert briefing_card(STYLE, **args) == briefing_card(STYLE, **args)  # type: ignore[arg-type]


def test_the_counts_say_in_words_what_needs_checking():
    lines = card_count_lines(CheckCounts(15, 16, 14, 15, 1))
    assert lines == [("15 of 16", "citations matched to the record", True),
                     ("14 of 15", "quotations found word for word", True),
                     ("1", "sentence without a source", True)]
    assert [p for _, _, p in card_count_lines(CheckCounts(19, 19, 19, 19, 0))] == [False, False, False]


def test_the_strips_counts_follow_what_is_shown():
    answer = {"segments": [
        {"text": 'Italy said it “supports all initiatives that seek limits” ', "sources": [], "cited": [],
         "status": "unsupported", "loaded": [], "misquotes": []},
        {"text": "in 2025", "sources": [1], "cited": [], "status": "cited", "loaded": [], "misquotes": []},
        {"text": " Another claim.", "sources": [], "cited": [], "status": "invalid", "loaded": [], "misquotes": []}],
        "citations_total": 3, "citations_invalid": 1, "quotes_total": 1, "quotes_unverified": 0,
        "unsupported_segments": 1}
    counts = check_counts(quotes_beside(answer))  # type: ignore[arg-type]
    assert counts == CheckCounts(2, 3, 1, 1, 2)  # "Italy said it" stays marked, and the removed citation's claim
    assert not counts.all_clear and CheckCounts(1, 1, 0, 0, 0).all_clear
