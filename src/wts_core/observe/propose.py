"""Test questions proposed from real use, for the maintainer to approve.

``proposed_questions`` picks candidates from the record of briefings for a period; ``proposals_toml`` writes them as
a fragment in the shape of the sites' ``eval/questions.toml``. Nothing here adds a question to a test set. The
fragment is a file for the owner to read: a person approves each question, removes anything personal from it,
says what a careful reader would expect, and only then puts it into ``eval/questions.toml`` by hand.

Three kinds of question are proposed, because each points at something to fix:

* ``no-records``: it found no records, which points to a gap in coverage or in how the question was read;
* ``not-useful``: a reader said the briefing was not useful;
* ``worst-checked``: the checks found the most problems in its briefing.

Which questions may be proposed. Only those the record is allowed to hold (ADR 0012): of a briefing that was
written and saved, or of a question that found no records. And of saved briefings, only those not since withdrawn
or corrected, not reported by a reader, and not among those the site says to leave out (``leave_out``: a
briefing hidden while a concern about it is decided, above all). A question someone has raised a concern about
is not copied into another file while the concern stands. Never the question of a briefing
that failed (it is removed from the record after 90 days, and must not outlive that in a file), nor of a request
for the sources only, one a limit or a cap stopped, or one the reader left, whose records hold no question at
all. The rule is applied here by outcome, not by trusting a row's question to be empty.

Nothing about a reader is in a proposal: the record holds none. A reader may still have typed something personal
into a question, so an email address, a web address and a long run of digits are replaced with ``[removed]``, and
the file says that a name can only be spotted by the person approving it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from wts_core.dates import long_date
from wts_core.observe.figures import _normal, _problems
from wts_core.ports import SYSTEM_CLOCK, BriefingLog, BriefingRecord, Clock
from wts_core.settings import Site

__all__ = ["REASONS", "Proposed", "proposals_toml", "proposed_questions"]

# why a question is proposed, in the order they are listed
REASONS = ("no-records", "not-useful", "worst-checked")
REMOVED = "[removed]"

_PERSONAL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"  # an email address
                       r"|(?:https?://|www\.)\S+"  # a web address
                       r"|\+?\d[\d\s().-]{7,}\d")  # a telephone number, or any long run of digits


@dataclass(frozen=True)
class Proposed:
    """One question proposed as a test question: its words (with anything that looks personal taken out), why it
    is proposed, how many times it was asked in the period, the saved briefing it belongs to (None for a question
    that found no records) and what the checks found, added up."""

    question: str
    reason: str
    times: int = 1
    briefing_id: str | None = None
    problems: int = 0


def _may_be_proposed(record: BriefingRecord, leave_out: Callable[[str], bool] | None = None) -> bool:
    """The rule above: a question that found no records; or the question of a briefing that was written, is
    saved, has not been withdrawn, corrected or reported since, and is not one the site says to leave out."""
    if record.kind != "reader" or not record.question.strip():
        return False
    if record.outcome == "no_records":
        return True
    if record.outcome != "completed" or not record.briefing_id or record.corrected or record.reported:
        return False
    return leave_out is None or not leave_out(record.briefing_id)


def _clean(question: str) -> str:
    return _PERSONAL.sub(REMOVED, " ".join(question.split()))


def proposed_questions(log: BriefingLog, *, since: datetime | timedelta, until: datetime | None = None,
                       limit: int = 10, clock: Clock = SYSTEM_CLOCK,
                       leave_out: Callable[[str], bool] | None = None) -> tuple[Proposed, ...]:
    """The questions of the period from ``since`` (a time, or how long before ``until``) up to ``until`` (now, if
    not given) that are worth proposing: up to ``limit`` of each kind, a question once (under the first kind it
    is proposed for, in the order of ``REASONS``), whatever its case, punctuation and spacing.

    ``leave_out`` is the site's: given a saved briefing's id, whether its question is to be left out. A site
    with the right of reply says there which briefings are hidden while a concern about them is decided (and
    which it shows as hidden because of what they cite): this module does not read the right of reply's tables,
    and must not (ADR 0008). A briefing a reader has reported, or that has been withdrawn or corrected, is left
    out without being asked about."""
    if limit < 1:
        raise ValueError("limit must be at least 1: how many questions of each kind to propose")
    end = until or clock.now()
    start = end - since if isinstance(since, timedelta) else since
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("a period's times must say their timezone")
    if start >= end:
        raise ValueError("the period must begin before it ends")
    rows = sorted((r for r in log.since(start, end) if _may_be_proposed(r, leave_out)), key=lambda r: (r.at, r.id))

    def wordings(chosen: Sequence[BriefingRecord]) -> list[tuple[BriefingRecord, int]]:
        """Each wording once, with how many times it was asked, the most asked first."""
        first: dict[str, BriefingRecord] = {}
        times: dict[str, int] = {}
        for r in chosen:
            key = _normal(r.question)
            first.setdefault(key, r)
            times[key] = times.get(key, 0) + 1
        return sorted(((first[k], times[k]) for k in first), key=lambda rt: (-rt[1], rt[0].at, rt[0].id))

    kinds: dict[str, list[tuple[BriefingRecord, int]]] = {
        "no-records": wordings([r for r in rows if r.outcome == "no_records"]),
        "not-useful": wordings([r for r in rows if r.outcome == "completed" and r.useful is False]),
        "worst-checked": sorted(wordings([r for r in rows if r.outcome == "completed" and _problems(r) > 0]),
                                key=lambda rt: (-_problems(rt[0]), rt[0].at, rt[0].id)),
    }
    seen: set[str] = set()
    found: list[Proposed] = []
    for reason in REASONS:
        taken = 0
        for record, times in kinds[reason]:
            key = _normal(record.question)
            if key in seen or taken >= limit:
                continue
            seen.add(key)
            taken += 1
            found.append(Proposed(question=_clean(record.question), reason=reason, times=times,
                                  briefing_id=record.briefing_id or None, problems=_problems(record)))
    return tuple(found)


def _toml(text: str) -> str:
    """A text as a TOML basic string, on one line."""
    out = ['"']
    for ch in text:
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif ch < " " or ch == "\x7f":
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join([*out, '"'])


_WHY = {
    "no-records": "it found no records",
    "not-useful": "a reader said its briefing was not useful",
    "worst-checked": "the checks found {problems} problem{s} in its briefing",
}


def proposals_toml(proposed: Sequence[Proposed], site: Site, *, since: datetime, until: datetime) -> str:
    """The proposals as a fragment in the shape of a site's ``eval/questions.toml``: one ``[[q]]`` table each,
    with an id, the question and, as its category, why it is proposed. It is valid TOML, and it is not a test
    set: the comments at its head say what the owner does with it."""
    day = until.astimezone(UTC).strftime("%Y-%m-%d")
    lines = [
        f"# Proposed test questions for {site.name}, from readers' questions between {long_date(since)} and "
        f"{long_date(until)}.",
        "#",
        "# NOTHING HERE IS IN THE TEST SET. This file is a list for the owner to read. For each question worth",
        "# keeping:",
        "#   1. read it for anything personal. Email addresses, web addresses and long numbers have been replaced",
        f"#      with {REMOVED}; a name can only be spotted by a person. Reword or drop a question that names a",
        "#      private individual;",
        "#   2. say what a careful reader would expect: the filters under [q.expect], or `no_records = true` where",
        "#      finding nothing is the right answer, or `include = [...]` for sources that must be among the",
        "#      evidence, as the site's eval/questions.toml does for its other questions;",
        "#   3. give it an id and a category of the site's own, and copy it into eval/questions.toml by hand;",
        "#   4. make an evaluation run, so that the thresholds are checked with the new questions in the set.",
        "#",
        "# Only questions the site already keeps are here: of saved briefings that have not been withdrawn,",
        "# corrected or reported and are not hidden while a concern is decided, and of questions that found no",
        "# records. Delete this file when you have finished with it: the nightly tidy deletes it in any case once",
        "# the oldest question it could hold is older than the record of briefings is kept.",
        "",
    ]
    if not proposed:
        lines += ["# No question of this period is proposed: none found no records, was rated not useful or was "
                  "flagged by the checks.", ""]
    for number, item in enumerate(proposed, start=1):
        why = _WHY[item.reason].format(problems=item.problems, s="" if item.problems == 1 else "s")
        asked = "" if item.times == 1 else f"; asked {item.times} times"
        where = f"; saved as {item.briefing_id}" if item.briefing_id else ""
        lines += [f"# Proposed because {why}{asked}{where}.",
                  "[[q]]",
                  f"id = {_toml(f'proposed-{day}-{number:02d}')}",
                  f"question = {_toml(item.question)}",
                  f"category = {_toml(f'proposed-{item.reason}')}",
                  ""]
    return "\n".join(lines).rstrip("\n") + "\n"
