"""Replay: the checks run again over recorded briefings, free and offline (docs/ARCHITECTURE.md, section 6).

A fixture is a recorded briefing: the question, the documents the model was given, the blocks it returned, and the
report the checks made of them at the time. ``replay`` makes the report again with the verifier, the word list and
the spelling rules as they are now, and names every difference: which check, which sentence, what it was and what it
is. Each difference is ``stricter`` (something is flagged that was not), ``weaker`` (something is no longer flagged)
or ``other``. ``assert_never_weaker`` is for CI: it is how "the checks on briefings never weaken" is guarded when a
rule changes, on any machine, with no key and no site's data.

``checked`` is the one place the package turns a model's blocks and its documents into a checked report, in the
order all three sites' pipelines run the checks today (``rag/pipeline.py`` in each)::

    report = verify(blocks, sources); drop_preambles; britishise_segments; flag loaded words; check_quotes

then ``to_dict()``, and curled quotes for a site that shows them (Where Countries Stand).

A fixture is kept as a recording in the format of ``wts_core.testing.models`` (so it can also be replayed to a
pipeline through ``ScriptedModel``), with the question and any headings in its header, and the report in a file
beside it: ``<name>.jsonl`` and ``<name>.report.json``. Fixtures are recorded by a site's evaluation run, from its
own test questions: never from a reader's briefing.

How two reports are compared. The briefing's text is laid out character by character, each with its status (cited,
connective, unsupported, invalid), the sources cited for it, and whether it is marked as a loaded word or as part of
a quotation that was not found. Where the two texts are the same, the marks are compared in place, so a sentence
that the verifier now splits or joins differently is not mistaken for a change. Where the text itself differs (a
spelling rule, a dropped opener), the stretch that differs is named as a difference of its own and its marks are
compared as a whole. The report's counts are compared too. Its ``rules`` stamp and its ``markdown`` are not: the
first changes with every change of rule, the second is the text and the sources again.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal, cast

from wts_core.checks import LoadedWords, Verifier, britishise_segments, curl_answer
from wts_core.events import Answer, Block, Completed, blocks_as_today
from wts_core.ports import Document, Usage
from wts_core.testing.models import load_documents, load_header, load_stream, record_stream

__all__ = ["Difference", "Fixture", "Kind", "assert_never_weaker", "checked", "load_fixture", "replay",
           "save_fixture"]

type Kind = Literal["stricter", "weaker", "other"]


@dataclass(frozen=True)
class Fixture:
    """A recorded briefing. ``headings`` are the documents' headings, one for each, where the site's sources have
    one apart from the title (Where MPs Stand's debate headings): a quotation is looked for there too."""

    name: str
    question: str
    documents: tuple[Document, ...]
    blocks: tuple[Block, ...]
    report: Answer | None = None  # what the checks made of it when it was recorded
    headings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Difference:
    """One thing the checks say now that they did not say when the fixture was recorded."""

    fixture: str
    check: str  # "status", "citations", "loaded_words", "quotations", "text", or one of the report's counts
    sentence: str | None  # the words concerned; None for a count
    before: Any
    after: Any
    kind: Kind

    def __str__(self) -> str:
        where = f" in {self.sentence!r}" if self.sentence else ""
        return f"{self.fixture}: {self.check}{where} was {self.before!r} and is now {self.after!r} ({self.kind})"


# ---- a checked report ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Source:
    """A document as the checks read a site's source (``checks.TitledSource``)."""

    n: int
    title: str
    blocks: tuple[str, ...]
    meta: Mapping[str, Any] = field(default_factory=dict)


def checked(blocks: Sequence[Block], documents: Sequence[Document], verifier: Verifier, loaded_words: LoadedWords,
            *, headings: Sequence[str] = (), curled: bool = False) -> Answer:
    """The model's blocks through every check, in the order every site's pipeline runs them: the report as it is
    sent to a reader and saved. ``documents`` are those the model was given, numbered from 1; ``headings``, where
    given, one for each document; ``curled`` for a site that shows its briefings with curly quotes."""
    if headings and len(headings) != len(documents):
        raise ValueError(f"{len(headings)} headings for {len(documents)} documents: there must be one for each")
    sources = [_Source(d.number, d.title, d.passages, {"heading": headings[i]} if headings else {})
               for i, d in enumerate(documents)]
    as_today = blocks_as_today(Completed(tuple(blocks), "", None, Usage()))
    report = verifier.verify(as_today, sources)
    verifier.drop_preambles(report.segments)  # "Across the records retrieved, ..." openers
    britishise_segments(report.segments)  # the model's own words only; quotations stay verbatim
    loaded_words.flag(report.segments)  # judgemental words in its own voice are highlighted, not hidden
    verifier.check_quotes(report, sources)  # quotations not found word for word in their sources are marked
    answer = report.to_dict()
    return cast(Answer, curl_answer(answer)) if curled else answer


# ---- fixtures on disk ------------------------------------------------------------------------------------------


def _report_path(path: Path) -> Path:
    return path.with_name(path.stem + ".report.json")


def load_fixture(path: Path, *, report: Path | None = None) -> Fixture:
    """A fixture from a recording. Its report is read from ``report``, or from ``<name>.report.json`` beside the
    recording where there is one; a fixture without a report can be checked but not replayed."""
    path = Path(path)
    done = [e for e in load_stream(path) if isinstance(e, Completed)]
    if not done:
        raise ValueError(f"{path} has no finished message: a stream that ended in an error is no fixture")
    header = load_header(path)
    beside = report if report is not None else _report_path(path)
    recorded = cast(Answer, json.loads(beside.read_text(encoding="utf-8"))) if beside.exists() else None
    if report is not None and recorded is None:
        raise FileNotFoundError(f"no report at {report}")
    return Fixture(name=path.stem, question=str(header.get("question") or ""), documents=load_documents(path),
                   blocks=done[-1].blocks, report=recorded, headings=tuple(header.get("headings") or ()))


def save_fixture(fixture: Fixture, folder: Path) -> Path:
    """Write a fixture as ``<folder>/<name>.jsonl`` and, when it has a report, ``<name>.report.json`` beside it.
    Only for briefings written from a site's own test questions."""
    about: dict[str, Any] = {"question": fixture.question}
    if fixture.headings:
        about["headings"] = list(fixture.headings)
    path = record_stream(Path(folder) / f"{fixture.name}.jsonl", [Completed(fixture.blocks, "", None, Usage())],
                         documents=fixture.documents, **about)
    if fixture.report is not None:
        _write_report(_report_path(path), fixture.report)
    return path


def _write_report(path: Path, report: Answer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# ---- comparing two reports -------------------------------------------------------------------------------------

_FLAGGED = ("unsupported", "invalid")
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*\s+")
# a short capitalised word before a full stop is taken for a title ("Cllr. Shah"), which ends no sentence: only for
# naming the sentence a difference is in, so "in May. The" merely names two sentences where one would do
_TITLE = re.compile(r"\b[A-Z][a-z]{1,4}$")
# the report's counts, and whether a rise means more is flagged (None: neither stricter nor weaker in itself)
_COUNTS: tuple[tuple[str, bool | None], ...] = (
    ("citations_total", None), ("citations_invalid", True), ("loaded_words", True), ("quotes_total", None),
    ("quotes_unverified", True))


@dataclass
class _Marks:
    """A report's text, and what the checks say of each character of it."""

    text: str
    status: list[str]
    sources: list[tuple[int, ...]]
    loaded: list[str]  # the loaded word a character is part of, or ""
    misquoted: list[bool]

    def flagged(self, a: int, b: int) -> str:
        """The status of a stretch: a flagged one if any of it is flagged."""
        found = self.status[a:b]
        return next((s for s in found if s in _FLAGGED), found[0] if found else "")

    def cited(self, a: int, b: int) -> tuple[int, ...]:
        return tuple(sorted({n for group in self.sources[a:b] for n in group}))

    def word(self, a: int, b: int) -> str:
        return next((w for w in self.loaded[a:b] if w), "")

    def misquote(self, a: int, b: int) -> bool:
        return any(self.misquoted[a:b])


def _marks(answer: Answer) -> _Marks:
    marks = _Marks("", [], [], [], [])
    for seg in answer.get("segments") or []:
        text = seg.get("text") or ""
        n = len(text)
        loaded, misquoted = [""] * n, [False] * n
        for mark in seg.get("loaded") or []:
            a, b = max(0, int(mark["start"])), min(n, int(mark["end"]))
            loaded[a:b] = [str(mark.get("word") or text[a:b])] * (b - a)
        for mark in seg.get("misquotes") or []:
            a, b = max(0, int(mark["start"])), min(n, int(mark["end"]))
            misquoted[a:b] = [True] * (b - a)
        marks.text += text
        marks.status += [str(seg.get("status") or "")] * n
        marks.sources += [tuple(seg.get("sources") or ())] * n
        marks.loaded += loaded
        marks.misquoted += misquoted
    return marks


def _sentence(text: str, a: int, b: int) -> str:
    """The sentence of ``text`` that holds the stretch from ``a`` to ``b`` (its line, where it has no full stop)."""
    start = text.rfind("\n", 0, a) + 1
    end = text.find("\n", b)
    line = text[start:len(text) if end < 0 else end]
    a, b = a - start, b - start
    bounds = [0, *(m.end() for m in _SENTENCE_END.finditer(line) if not _TITLE.search(line, 0, m.start())),
              len(line)]
    return line[max(x for x in bounds if x <= a):min(x for x in bounds if x >= b)].strip()


def _widen(text: str, a: int, b: int) -> tuple[int, int]:
    """A stretch widened to whole words: "colo(u)r" is shown as "color" and "colour", not as a "u"."""
    while a > 0 and not text[a - 1].isspace():
        a -= 1
    while b < len(text) and not text[b].isspace():
        b += 1
    return a, b


def _status_kind(before: str, after: str) -> Kind:
    was, now = before in _FLAGGED, after in _FLAGGED
    return "weaker" if was and not now else "stricter" if now and not was else "other"


def _differences(name: str, before: Answer, after: Answer) -> list[Difference]:
    """Every difference between two reports on one briefing."""
    old, new = _marks(before), _marks(after)
    found: list[Difference] = []
    # stretches of the two texts side by side: the same text (compared character by character) or text that differs
    stretches: Sequence[tuple[str, int, int, int, int]] = [("equal", 0, len(old.text), 0, len(new.text))]
    if old.text != new.text:
        stretches = SequenceMatcher(None, old.text, new.text, autojunk=False).get_opcodes()
    text_seen: set[tuple[int, int, int, int]] = set()
    # a run of characters whose marks changed in the same way: [check, start, end, before, after], in the new text
    runs: list[list[Any]] = []

    def note(check: str, a: int, b: int, was: Any, now: Any, joins: bool) -> None:
        if was == now:
            return
        last = next((r for r in reversed(runs) if r[0] == check), None)
        if joins and last is not None and last[2] == a and last[3:] == [was, now]:
            last[2] = b
        else:
            runs.append([check, a, b, was, now])

    for tag, i1, i2, j1, j2 in stretches:
        if tag == "equal":
            for k in range(i2 - i1):
                i, j = i1 + k, j1 + k
                note("status", j, j + 1, old.status[i], new.status[j], True)
                note("citations", j, j + 1, tuple(sorted(old.sources[i])), tuple(sorted(new.sources[j])), True)
                note("loaded_words", j, j + 1, old.loaded[i], new.loaded[j], True)
                note("quotations", j, j + 1, old.misquoted[i], new.misquoted[j], True)
            continue
        (a1, a2), (b1, b2) = _widen(old.text, i1, i2), _widen(new.text, j1, j2)
        if (a1, a2, b1, b2) not in text_seen:
            text_seen.add((a1, a2, b1, b2))
            found.append(Difference(name, "text", _sentence(new.text, b1, b2) or None, old.text[a1:a2],
                                    new.text[b1:b2], "other"))
        if tag == "replace":  # words that changed: their marks are compared as a whole
            note("status", j1, j2, old.flagged(i1, i2), new.flagged(j1, j2), False)
            note("citations", j1, j2, old.cited(i1, i2), new.cited(j1, j2), False)
            note("loaded_words", j1, j2, old.word(i1, i2), new.word(j1, j2), False)
            note("quotations", j1, j2, old.misquote(i1, i2), new.misquote(j1, j2), False)

    status_kinds: set[Kind] = set()
    for check, a, b, was, now in runs:
        words = new.text[a:b].strip()
        if not words:  # a line break that moved from one passage to its neighbour
            continue
        kind: Kind
        if check == "status":
            kind = _status_kind(was, now)
            status_kinds.add(kind)
            found.append(Difference(name, check, words, was, now, kind))
        elif check == "citations":
            lost, gained = set(was) - set(now), set(now) - set(was)
            kind = "stricter" if lost and not gained else "weaker" if gained and not lost else "other"
            found.append(Difference(name, check, words, list(was), list(now), kind))
        elif check == "loaded_words":
            kind = "stricter" if not was else "weaker" if not now else "other"
            found.append(Difference(name, check, _sentence(new.text, a, b), was or None, now or None, kind))
        else:
            found.append(Difference(name, check, _sentence(new.text, a, b), "not found" if was else "found",
                                    "not found" if now else "found", "stricter" if now else "weaker"))

    for key, rise_is_stricter in _COUNTS:
        was, now = int(cast(Any, before.get(key)) or 0), int(cast(Any, after.get(key)) or 0)
        if was != now:
            kind = "other" if rise_is_stricter is None else "stricter" if now > was else "weaker"
            found.append(Difference(name, key, None, was, now, kind))
    # how much is unsupported follows from the statuses above, not from the direction of the figure: the number of
    # passages changes when one is split, and the ratio when a spelling changes a word's length
    overall: Kind = "weaker" if "weaker" in status_kinds else "stricter" if "stricter" in status_kinds else "other"
    for key in ("unsupported_segments", "grounded_ratio", "no_records"):
        was, now = before.get(key), after.get(key)
        if was is not None and now is not None and was != now:
            found.append(Difference(name, key, None, was, now, "other" if key == "no_records" else overall))
    return found


def replay(fixtures: Iterable[Fixture], verifier: Verifier, loaded_words: LoadedWords, *,
           curled: bool = False) -> list[Difference]:
    """Run the checks over each recorded briefing and compare with the report recorded with it. Nothing in the
    list means the checks say today exactly what they said then."""
    found: list[Difference] = []
    for fixture in fixtures:
        if fixture.report is None:
            raise ValueError(f"the fixture {fixture.name!r} has no recorded report to compare with: record one "
                             "(save_fixture) with the checks as they stand before the change")
        now = checked(fixture.blocks, fixture.documents, verifier, loaded_words, headings=fixture.headings,
                      curled=curled)
        found += _differences(fixture.name, fixture.report, now)
    return found


def assert_never_weaker(differences: Iterable[Difference]) -> None:
    """For CI: fail if anything that was flagged is no longer flagged. What is stricter, or merely different,
    passes: it is for a person to read."""
    weaker = [d for d in differences if d.kind == "weaker"]
    if weaker:
        raise AssertionError(f"the checks on briefings have weakened in {len(weaker)} "
                             f"place{'' if len(weaker) == 1 else 's'}:\n" + "\n".join(f"  {d}" for d in weaker))
