"""How a checked briefing is shown: the display rule for quotations beside their citation.

A quotation that the verifier found word for word in a source is never shown as text with no source. The model
sometimes attaches its citation to the words just after a quotation ("… said it “supports all initiatives that
seek to impose self-limitations on the use of veto” in November 2025 [Source 1]") rather than to the quotation. The
verifier then finds the quotation in source 1 (``Verifier.check_quotes`` reads the citation straight after a
quotation as its citation) but marks the sentence before it, quotation and all, as unsupported, and the page showed
the record's own words as if nothing supported them.

``quotes_beside`` changes only what is shown. A sentence marked unsupported that ends in a quotation, with no
misquote recorded against it, and is followed within three characters by a cited passage, is split: the quotation
becomes a passage cited to the same sources (marked ``"beside": True``), and the words before it keep their
"unsupported" mark. Nothing else is touched: no passage is newly marked, no citation is added that the verifier did
not itself read as the quotation's, and the briefing's counts are the verifier's, unchanged. The family's account of
how a briefing is shown is ``family/BRIEFINGS.md`` in the charity's repository.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from wts_core.events import Answer

__all__ = ["CheckCounts", "check_counts", "quotes_beside"]

# a quotation at the end of a passage: straight or curly double quotes, as the verifier reads them
_LAST_QUOTE = re.compile(r'["“]([^"“”\n]{6,}?)["”]\W{0,3}$')
_WORD = re.compile(r"[A-Za-z0-9À-ɏ']+")


def _shift(marks: Sequence[Mapping[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    """The marks (with ``start`` and ``end`` offsets) that fall within [start, end), moved to the piece's own
    offsets."""
    out = []
    for m in marks:
        a, b = m.get("start"), m.get("end")
        if isinstance(a, int) and isinstance(b, int) and start <= a and b <= end:
            out.append({**m, "start": a - start, "end": b - start})
    return out


def _split(seg: Mapping[str, Any], following: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    if seg.get("status") != "unsupported" or seg.get("misquotes"):
        return None
    if following.get("status") != "cited" or not following.get("sources"):
        return None
    text = str(seg.get("text") or "")
    body = text.rstrip()
    m = _LAST_QUOTE.search(body)
    if not m or len(_WORD.findall(m.group(1))) < 3:  # a word or two in quotes is a term, not a quotation
        return None
    # the quotation ends within three characters of the cited passage, as Verifier.check_quotes reads it
    quote_end = m.start() + len(m.group(0).rstrip(",.;:!? )"))
    if len(text) - quote_end > 3:
        return None
    start = m.start()
    pieces: list[dict[str, Any]] = []
    loaded = seg.get("loaded") or []
    if text[:start].strip():
        pieces.append({**seg, "text": text[:start], "loaded": _shift(loaded, 0, start), "misquotes": []})
    elif text[:start]:
        pieces.append({"text": text[:start], "sources": [], "cited": [], "status": "connective", "loaded": [],
                       "misquotes": []})
    pieces.append({"text": text[start:quote_end], "sources": list(following["sources"]), "cited": [],
                   "status": "cited", "loaded": _shift(loaded, start, quote_end), "misquotes": [], "beside": True})
    if text[quote_end:]:
        pieces.append({"text": text[quote_end:], "sources": [], "cited": [], "status": "connective",
                       "loaded": _shift(loaded, quote_end, len(text)), "misquotes": []})
    return pieces


def quotes_beside(answer: Answer | None) -> Answer | None:
    """The answer as it is shown: each quotation found in the source cited straight after it is shown as that
    source's passage, and nothing else changes (see the module's docstring). Returns a new answer; the counts
    (``unsupported_segments`` and the rest) are the verifier's, as they were."""
    if not answer or not answer.get("segments"):
        return answer
    segments = list(answer["segments"])
    out: list[Any] = []
    for i, seg in enumerate(segments):
        pieces = _split(seg, segments[i + 1]) if i + 1 < len(segments) else None
        out.extend(pieces if pieces is not None else [seg])
    if len(out) == len(segments):
        return answer
    shown = dict(answer)
    shown["segments"] = out
    return shown  # type: ignore[return-value]  # the same keys as the answer it was made from


@dataclass(frozen=True)
class CheckCounts:
    """The three counts a reader is shown at the top of a briefing (the family's check strip), and on its share
    card: citations matched of those made, quotations found word for word of those checked, and sentences shown
    as having no source."""

    citations_matched: int
    citations_total: int
    quotes_found: int
    quotes_total: int
    no_source: int

    @property
    def all_clear(self) -> bool:
        return (self.citations_matched == self.citations_total and self.quotes_found == self.quotes_total
                and self.no_source == 0)


def check_counts(shown: Answer) -> CheckCounts:
    """The strip's counts for an answer as it is shown (after ``quotes_beside``): the verifier's counts of
    citations and quotations, and the passages shown as having no source, those with no citation and those whose
    every citation failed and was removed."""
    segments = shown.get("segments") or []
    total = int(shown.get("citations_total") or 0)
    quotes = int(shown.get("quotes_total") or 0)
    return CheckCounts(
        citations_matched=total - int(shown.get("citations_invalid") or 0), citations_total=total,
        quotes_found=quotes - int(shown.get("quotes_unverified") or 0), quotes_total=quotes,
        no_source=sum(1 for s in segments if s.get("status") in ("unsupported", "invalid")))
