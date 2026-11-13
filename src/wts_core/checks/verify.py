"""The citation verifier: what is and is not supported in a cited briefing.

The model's citations give, for each cited span, the exact ``cited_text`` and the number of the source it came from.
The verifier checks every citation again against the site's own copy of the source text and classifies every uncited
span, so the page can show the reader exactly what is and is not supported. Unsupported text is never silently
passed off as sourced.

This is Where MPs Stand's copy (``hansard/rag/verify.py``), which is now the fullest: it has everything Where
Countries Stand's has, and both of phase 1's fixes to the recheck of saved briefings. The three sites' copies differ
in three inputs, and a site passes each to ``Verifier``:

* the opening words of a "no records" answer (each site's ``NO_RECORDS``);
* the honorifics whose full stop ends no sentence (Where Councils Stand adds ``Cllr``, ``Rev``, ``Revd``, ``Hon``);
* its form of the "note about the evidence" rule: ``EVIDENCE_NOTES_WIDE`` is what Where MPs Stand and Where
  Countries Stand have today, ``EVIDENCE_NOTES_STRICT`` what Where Councils Stand has. The package has no default
  for it. (The strict form plus a narrow one is a change of its own, made at each site's adoption: MIGRATION.md
  1.4.)

One thing is new. Every report is stamped with the version of the checking rules that wrote it (``rules``), and
``Verifier.recheck`` leaves alone an answer written under the current rules: a saved briefing keeps its segments but
not the blocks the model wrote, so judging it again can never repeat exactly what ``verify`` did the first time, and
only a briefing saved under older rules needs it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast, final

from wts_core.events import Answer

__all__ = [
    "COMMON_HONORIFICS",
    "EVIDENCE_NOTES_STRICT",
    "EVIDENCE_NOTES_WIDE",
    "RULES_VERSION",
    "Segment",
    "SourceText",
    "Status",
    "TitledSource",
    "Verification",
    "Verifier",
]

# The version of the checking rules: stamped on every report as ``rules``. It goes up by one whenever a rule here
# changes what is flagged or cleared, so that briefings saved before the change are judged again when shown.
RULES_VERSION = 1

# an honorific's full stop ("Mr. Smith") ends no sentence; the part every site shares
COMMON_HONORIFICS: tuple[str, ...] = ("Mr", "Mrs", "Ms", "Dr", "Prof", "Sr", "Jr", "St")

# statements about the evidence itself (what was or was not retrieved), not about what anyone said
_NOTES_BEFORE = (r"\b(records? (retrieved|supplied|shown)|(retrieved|supplied) (records|results|sources)|"
                 r"in the records|")
_NOTES_AFTER = (
    r"(were|was) not relevant|been excluded|the records (are|were|contain|include|cover)|little (was|is) (found|said)|"
    r"nothing (was|is) found|no stated position|written questions only|"
    r"decides? (many|most|some)? ?(of )?(these |the |such )?(subjects|matters|areas|policies) for ((its|their) own "
    r"nations?|wales|scotland|northern ireland)|(is|are) (a )?separate (parliament|legislature)s?\b|"
    r"decides? (different|separate|their own) (matters|subjects|policies)\b|"
    r"^\W*(about the evidence|notes?)\b\W*:)")
# The wide form, as Where MPs Stand and Where Countries Stand have it: it also takes for a note anything said to be
# (or not to be) "supplied" or "retrieved", and notes that vote data was missing. It clears real notes ("The votes
# on the second reading were not supplied") and, with them, ordinary claims ("Gas was supplied to two million
# homes").
EVIDENCE_NOTES_WIDE: re.Pattern[str] = re.compile(
    _NOTES_BEFORE
    + r"no (division|voting) records|no (recorded[- ]vote|vote|voting) (data|records|tables)|"
    r"(votes?|data) (were|was) (not )?supplied|\b(are|were|is|was) (not )?(supplied|retrieved)\b|"
    r"evidence (base|is|set)|gaps?\b|caveats?\b|cannot be (reported|attributed)|"
    + _NOTES_AFTER, re.I)
# The strict form, as Where Councils Stand has it: without those alternatives, so both of the sentences above are
# points to check.
EVIDENCE_NOTES_STRICT: re.Pattern[str] = re.compile(
    _NOTES_BEFORE
    + r"no (division|voting) records|evidence (base|is|set)|gaps?\b|caveats?\b|cannot be (reported|attributed)|"
    + _NOTES_AFTER, re.I)

type Status = Literal["cited", "connective", "unsupported", "invalid"]

_WS = re.compile(r"\s+")
_CONNECTIVE_MAX = 60


class SourceText(Protocol):
    """What the verifier needs of a site's source: its number and its text. Each site's ``Source`` already fits."""

    @property
    def n(self) -> int: ...  # its number, from 1, shown as [Source n]

    @property
    def blocks(self) -> Sequence[str]: ...  # its citable text, in passages, word for word from the record


class TitledSource(Protocol):
    """What the quotation check needs of a site's source: the two fields above, and its title line and its ``meta``
    (whose ``heading``, where there is one, is the debate's heading), since headings are quoted too."""

    @property
    def n(self) -> int: ...

    @property
    def blocks(self) -> Sequence[str]: ...

    @property
    def title(self) -> str: ...

    @property
    def meta(self) -> Mapping[str, Any]: ...


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return _WS.sub(" ", text).strip().lower()


def _compact(text: str) -> str:
    """For checking a citation: the characters without any spacing. A citation that runs across two paragraphs of
    a source comes back with them joined directly ("and(b) implementation"), not with the space between them."""
    return _WS.sub("", _norm(text))


@dataclass
class Segment:
    text: str
    sources: list[int] = field(default_factory=list)       # 1-based source numbers
    cited: list[dict[str, Any]] = field(default_factory=list)
    status: Status = "cited"
    loaded: list[dict[str, Any]] = field(default_factory=list)  # judgemental words outside quotes (neutral.py)
    misquotes: list[dict[str, Any]] = field(default_factory=list)  # quotations not found in their sources

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "sources": self.sources, "cited": self.cited, "status": self.status,
                "loaded": self.loaded, "misquotes": self.misquotes}


@dataclass
class Verification:
    segments: list[Segment]
    no_records: bool
    citations_total: int
    citations_invalid: int
    unsupported_chars: int
    cited_chars: int
    quotes_total: int = 0
    quotes_unverified: int = 0
    rules: int = RULES_VERSION  # the version of the checking rules that wrote this report

    @property
    def grounded_ratio(self) -> float:
        total = self.cited_chars + self.unsupported_chars
        return 1.0 if total == 0 else self.cited_chars / total

    def markdown(self) -> str:
        """Answer text with [Source n] markers after each cited span."""
        out = []
        for s in self.segments:
            out.append(s.text)
            if s.sources:
                out.append(" " + "".join(f"[Source {n}]" for n in s.sources))
        return "".join(out)

    def to_dict(self) -> Answer:
        """The report as every site sends and saves it: today's keys, exactly, and ``rules``."""
        return {
            "segments": [s.to_dict() for s in self.segments],
            "markdown": self.markdown(),
            "no_records": self.no_records,
            "citations_total": self.citations_total,
            "citations_invalid": self.citations_invalid,
            "grounded_ratio": round(self.grounded_ratio, 3),
            "unsupported_segments": sum(1 for s in self.segments if s.status == "unsupported"),
            "loaded_words": sum(len(s.loaded) for s in self.segments),
            "quotes_total": self.quotes_total,
            "quotes_unverified": self.quotes_unverified,
            "rules": self.rules,
        }


# the date of the contribution just cited, after its citation: "[Source 2] (16 September 2025).",
# "on 12 November 2025.", "(written answer, 12 October 2026)."
_DATE_ONLY = re.compile(r"^\W*(?:on\s+)?\(?\s*(?:(?:written|oral)\s+(?:answer|question|statement)s?,?\s*)?"
                        r"(?:\d{1,2}\s+)?(?:[A-Z][a-z]+\s+)?\d{4}\s*\)?\W*$")


def _is_connective(text: str, short: bool = True) -> bool:
    """A date, a heading, a line ending in a colon or, with ``short``, a join or short transition."""
    t = text.strip()
    if not t or _DATE_ONLY.match(t):
        return True
    if t.startswith("#") or t.endswith(":"):
        return True
    # bullet markers, joins between cited spans, short transitions
    stripped = re.sub(r"^[\s\-*•\d.)]+", "", t)
    return short and len(stripped) <= _CONNECTIVE_MAX and not re.search(r"\d{4}|£|%", stripped)


_LABEL = re.compile(r"^\s*(#+ .*|\*\*[^*]+\*\*:?)\s*$")
# a note about the evidence that reports what someone said ("Smith said", "he argued") is a claim, not a note;
# "what was said" or "nothing said by Benn" is not
_SOMEONE_SAID = re.compile(r"\b(?:[A-Z][\w'-]+|[Hh]e|[Ss]he|[Tt]hey)\s+(?:also\s+)?"
                           r"(?:said|argued|claimed|stated|told|described|called)\b")
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s+\S")
_CLOSED = re.compile(r"[.!?][\"')\]]*$")  # the text ends where a sentence does
_ATTRIBUTION_MAX = 220

# "Across the records retrieved, ..." and the like: an opener about the records rather than the substance
_PREAMBLE = re.compile(
    r"(^|\n|[.!?] )([-*•]\s+)?(?:across|in|from|based on|on the basis of|according to|within)\s+"
    r"(?:all\s+)?(?:the\s+|these\s+)?(?:retrieved\s+|supplied\s+)?(?:records?|evidence|search results|results|"
    r"sources|contributions)(?:\s+(?:retrieved|supplied|provided|shown|available|here|above))?\s*[,:]\s*"
    r"([a-z]?)", re.I)

# ---- quotations ------------------------------------------------------------------------------------------------
# Words the briefing puts in quotation marks must appear, word for word, in the record it attributes them to.
# A citation proves its own cited passage exists; this also checks the quotation written around it.

_QUOTE = re.compile(r'["\u201c]([^"\u201c\u201d\n]{6,}?)["\u201d]|\u2018([^\u2018\u2019\n]{6,}?)\u2019(?![a-z])')
# gaps a quotation may contain: an ellipsis, or an editorial insertion in square brackets ("welcome[d]")
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|\u2026|\[[^\]]{0,40}\])\s*")
_WORDS = re.compile(r"[^a-z0-9]+")
_REPEATED = re.compile(r"\b(\w+)(?: \1\b)+")


def _words(text: str) -> str:
    """Lower-case words only: punctuation, quote marks and spacing are not what a quotation is checked on, nor a
    word printed twice in a row in the record ("the positioning of of that company")."""
    words = _WORDS.sub(" ", text.lower().replace("\u2019", "'").replace("'", "")).strip()
    return " " + _REPEATED.sub(r"\1", words) + " "


def _found(quote: str, haystack: str) -> bool:
    parts = [p for p in _ELLIPSIS.split(quote) if len(_words(p).split()) >= 2]
    # the last word may run on in the record ("Gentleman" quoted from "Gentleman's")
    return all(_words(p).rstrip() in haystack for p in parts) if parts else True


# a briefing shown with curly quotes is judged again on the text as the checks first read it
_STRAIGHT = str.maketrans("“”‘’", "\"\"''")


@final
class Verifier:
    """The checks on a cited briefing, with what is a site's own passed in. Not for subclassing.

    ``no_records``: the words a "no records" answer opens with (the site's instructions tell the model to use them).
    ``honorifics``: the abbreviations whose full stop ends no sentence, as written, capital letter and all.
    ``evidence_notes``: what makes a sentence a note about the evidence rather than a claim; ``EVIDENCE_NOTES_WIDE``
    or ``EVIDENCE_NOTES_STRICT`` is what each site has today.
    """

    # stamped on every report as ``rules``; ``recheck`` leaves alone an answer that carries it
    rules_version: int = RULES_VERSION

    def __init__(self, *, no_records: str, evidence_notes: re.Pattern[str],
                 honorifics: Sequence[str] = COMMON_HONORIFICS) -> None:
        if not no_records.strip():
            # with no words to look for, every briefing would open with them: each would be "no records"
            raise ValueError("no_records must be the words a \"no records\" answer opens with")
        if not isinstance(evidence_notes, re.Pattern):
            raise TypeError("evidence_notes must be a compiled pattern: EVIDENCE_NOTES_WIDE or EVIDENCE_NOTES_STRICT")
        named = [h for h in honorifics if h.strip()]
        self._no_records = no_records
        self._evidence_note = evidence_notes
        # with no honorifics the pattern must match nothing: an empty alternative would match the full stop after
        # any word, and so hide where sentences end
        self._honorific_dot = re.compile(r"\b(" + "|".join(re.escape(h) for h in named) + r")\." if named else r"(?!)")

    # ---- a new briefing ----------------------------------------------------------------------------------------

    def verify(self, blocks: Sequence[Mapping[str, Any]], sources: Sequence[SourceText]) -> Verification:
        """``blocks``: text blocks as returned by the model (``text`` and optional ``citations``)."""
        by_index = {s.n - 1: s for s in sources}
        segments: list[Segment] = []
        total = invalid = 0
        for i, b in enumerate(blocks):
            text = b.get("text") or ""
            cites = b.get("citations") or []
            if not cites:
                # a lead-in can come in pieces ("..., as when France's Mr. " + "Delattre said " + the quotation):
                # short uncited pieces in between do not stop it leading in to the citation after them
                j = i + 1
                while j < len(blocks) and not blocks[j].get("citations") and \
                        self._is_lead_in_piece(blocks[j].get("text") or ""):
                    j += 1
                next_is_cited = j < len(blocks) and bool(blocks[j].get("citations"))
                segments.extend(self._classify_uncited(text, next_is_cited))
                continue
            nums: list[int] = []
            kept: list[dict[str, Any]] = []
            for c in cites:
                total += 1
                idx = c.get("search_result_index", c.get("document_index"))
                src = by_index.get(idx)
                cited_text = c.get("cited_text") or ""
                if src is None or _compact(cited_text) not in _compact("\n\n".join(src.blocks)):
                    invalid += 1
                    continue
                if src.n not in nums:
                    nums.append(src.n)
                kept.append({"source": src.n, "cited_text": cited_text})
            segments.append(Segment(text, nums, kept, "cited" if nums else "invalid"))
        full = "".join(s.text for s in segments).strip()
        unsupported = sum(len(s.text) for s in segments if s.status in ("unsupported", "invalid"))
        cited = sum(len(s.text) for s in segments if s.status == "cited")
        return Verification(segments, full.startswith(self._no_records), total, invalid, unsupported, cited,
                            rules=self.rules_version)

    def drop_preambles(self, segments: list[Segment]) -> int:
        """Remove openers that talk about the records instead of the substance ("Across the records retrieved, most
        ..." becomes "Most ..."); returns how many were removed."""
        removed = 0
        for seg in segments:
            new, n = _PREAMBLE.subn(lambda m: m.group(1) + (m.group(2) or "") + m.group(3).upper(), seg.text)
            if n:
                seg.text, removed = new, removed + n
        return removed

    def check_quotes(self, report: Verification, sources: Sequence[TitledSource]) -> int:
        """Mark quotations that cannot be found in the sources cited for them; returns how many were not found."""
        # the speech and its title line (debate headings are quoted too)
        texts = {s.n: _words("\n\n".join([s.title, str(s.meta.get("heading") or ""), *s.blocks])) for s in sources}
        everything = " ".join(texts.values())
        starts, pos = [], 0
        for seg in report.segments:
            starts.append(pos)
            pos += len(seg.text)
        full = "".join(seg.text for seg in report.segments)
        total = bad = 0
        for m in _QUOTE.finditer(full):
            quote = m.group(1) or m.group(2)
            if len(_words(quote).split()) < 3:  # a word or two in quotes is a term, not a quotation
                continue
            total += 1
            a, b = m.span()
            # the sources cited for the quotation: segments it overlaps, or the citation straight after it
            cited: set[int] = set()
            for i, seg in enumerate(report.segments):
                s0, s1 = starts[i], starts[i] + len(seg.text)
                if s0 < b and a < s1 or (s0 >= b and s0 - b <= 3 and seg.sources):
                    cited.update(seg.sources)
            haystack = " ".join(texts[n] for n in cited if n in texts) or everything
            if _found(quote, haystack):
                continue
            bad += 1
            for i, seg in enumerate(report.segments):
                s0, s1 = starts[i], starts[i] + len(seg.text)
                if s0 < b and a < s1:
                    seg.misquotes.append({"start": max(a, s0) - s0, "end": min(b, s1) - s0, "text": quote})
        report.quotes_total, report.quotes_unverified = total, bad
        return bad

    # ---- a saved briefing, shown again -------------------------------------------------------------------------

    def recheck(self, answer: Answer | None, *, curled: bool = False) -> Answer | None:
        """A saved briefing's points to check, judged again by the current rules: a passage since recognised as a
        date, a label, a lead-in or a note about the evidence is no longer one. Being short is never reason enough:
        a flagged sentence may be a claim that verify() split off a lead-in. Nor is standing before a lead-in: a
        passage is judged here without the block it was written in, so a whole line, or a sentence that closed, is
        not taken for the opening of the quotation after it. Nothing is ever newly flagged.

        Only a briefing written under older rules is judged: one stamped with the current ``rules_version`` (or a
        later one) comes back as it is, the same object. One with no stamp was written before the package.

        ``curled``: for a site that shows its briefings with curly quotes (``typography``). The text is read with
        straight quotes, as the checks first read it: a briefing saved since quotes were curled would otherwise not
        show a sentence ending in a closing quote (He said “no.” Smith said …) and could lose a point to check.
        Only the statuses come back; the saved text is kept.
        """
        if not answer:
            return answer
        stamp = answer.get("rules")
        if isinstance(stamp, int) and not isinstance(stamp, bool) and stamp >= self.rules_version:
            return answer
        if not curled:
            return self._recheck_flags(answer)
        segs = answer.get("segments")
        if not segs:
            return answer
        straight = cast(Answer, {**answer, "segments": [{**s, "text": s["text"].translate(_STRAIGHT)}
                                                         if isinstance(s.get("text"), str) else s for s in segs]})
        out = self._recheck_flags(straight)
        if out is straight:
            return answer
        return cast(Answer, {**out, "segments": [{**o, "text": s["text"]} if "text" in s else o
                                                 for o, s in zip(out["segments"], segs, strict=True)]})

    def _recheck_flags(self, answer: Answer) -> Answer:
        """The sites' ``recheck_flags``, whatever rules the answer was written under."""
        found = answer.get("segments")
        if not found:
            return answer
        segs: list[dict[str, Any]] = found

        def cleared(i: int) -> bool:
            # as in verify(): short uncited pieces of a lead-in do not stop it leading in to the citation after them
            j = i + 1
            while j < len(segs) and segs[j].get("status") != "cited" and \
                    self._is_lead_in_piece(segs[j].get("text") or ""):
                j += 1
            nxt = j < len(segs) and segs[j].get("status") == "cited"
            # flagged=True: verify() marks a whole sentence split off a lead-in as a claim however short it is, and
            # that is not known here, so a point to check is never cleared only for being short
            return all(x.status == "connective" for x in self._classify_uncited(segs[i]["text"], nxt, flagged=True))

        fixed = {i for i, x in enumerate(segs) if x.get("status") == "unsupported" and cleared(i)}
        if not fixed:
            return answer
        segs = [{**x, "status": "connective"} if i in fixed else x for i, x in enumerate(segs)]
        cited = sum(len(x["text"]) for x in segs if x.get("status") == "cited")
        unsupported = sum(len(x["text"]) for x in segs if x.get("status") in ("unsupported", "invalid"))
        return cast(Answer, {
            **answer, "segments": segs,
            "unsupported_segments": sum(1 for x in segs if x.get("status") == "unsupported"),
            "grounded_ratio": round(1.0 if not cited + unsupported else cited / (cited + unsupported), 3)})

    # ---- what is uncited ---------------------------------------------------------------------------------------

    def _is_lead_in_piece(self, text: str) -> bool:
        """A short piece of a lead-in ("Delattre said "): no sentence ends in it."""
        t = self._honorific_dot.sub(lambda m: m.group(1), text).strip()
        return bool(t) and len(t) <= 80 and "\n" not in t and not re.search(r"[.!?][\"')\]]*$", t) and \
            not _SENTENCE_END.search(t)

    def _classify_uncited(self, text: str, next_is_cited: bool, flagged: bool = False) -> list[Segment]:
        """Split an uncited block into lines and label each one.

        * headings, bold group labels, bullets and joins are ``connective``;
        * the lead-in to a cited quotation ("- Keir Mather (Selby), 10 August 2026, said ") is ``connective``
          when the very next span is cited and the lead-in states nothing on its own;
        * notes about the evidence itself ("No division records were supplied") are ``connective``;
        * anything else (a claim with no citation) is ``unsupported``.

        ``flagged`` is for judging again a passage already marked as a point to check (``recheck``): there, being
        short does not make it a join, and a line that ended or a sentence that closed is no lead-in.
        """
        # an honorific's full stop ("Mr. Delattre") ends no sentence: the checks read a copy with it masked (the
        # same length, so positions carry over), and the text kept is the original
        masked = self._honorific_dot.sub(lambda m: m.group(1) + "\u2024", text)
        lines = text.splitlines(keepends=True)
        mlines = masked.splitlines(keepends=True)
        claims: set[int] = set()  # whole sentences split off a lead-in: never a mere transition, however short
        if next_is_cited and lines:
            # "Some answers said the data was not held. Stephen Kinnock said on 24 March that " + quotation: the
            # last sentence leads in to the citation that follows; only the sentence before it is a claim
            ends = list(_SENTENCE_END.finditer(mlines[-1]))
            if ends:
                cut = ends[-1].end() - 1
                tail = mlines[-1][cut:]
                if len(tail.strip()) <= _ATTRIBUTION_MAX and not tail.rstrip().endswith("."):
                    lines[-1:] = [lines[-1][:cut], lines[-1][cut:]]
                    mlines[-1:] = [mlines[-1][:cut], tail]
                    if re.search(r"\w", lines[-2]):  # a bare full stop closing the citation before is no claim
                        claims.add(len(lines) - 2)
        out: list[Segment] = []
        for i, line in enumerate(lines):
            last = i == len(lines) - 1
            body = re.sub(r"^[\s\-*•\d.)]+", "", mlines[i]).strip()
            lead_in = (last and next_is_cited and len(body) <= _ATTRIBUTION_MAX
                       and not _SENTENCE_END.search(body.rstrip()) and not body.endswith("."))
            if flagged and (line.endswith("\n") or _CLOSED.search(body)):
                # judged again on its own, a flagged passage is the last line of nothing: a line that ended, or a
                # sentence that closed ("... in real terms?"), led in to no quotation when verify() read it
                lead_in = False
            # judged again, a passage that does not end its line may be a sentence verify() split off a lead-in,
            # which it counts as a claim whatever it looks like (a date, a heading, something short)
            claim = i in claims or (flagged and not line.endswith("\n"))
            status: Status
            if ((_is_connective(line, short=not flagged) and not claim) or _LABEL.match(line) or lead_in
                    or (self._evidence_note.search(body) and not _SOMEONE_SAID.search(body))):
                status = "connective"
            else:
                status = "unsupported"
            if out and out[-1].status == status:
                out[-1].text += line
            else:
                out.append(Segment(line, status=status))
        return out or [Segment(text, status="connective")]
