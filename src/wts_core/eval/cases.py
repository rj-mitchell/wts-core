"""A site's test questions and its judgements, read as the sites keep them today.

Each site has ``eval/questions.toml``: a ``today`` (the date the questions are read as if it were) and a list of
``[[q]]`` tables. Every table has an ``id``, a ``question``, a ``category`` and an ``expect`` table of the filters a
careful reader would choose. Beside those, Where MPs Stand's follow-up questions have a ``history``; Where Countries
Stand's and Where Councils Stand's have ``no_records`` (finding nothing is the right answer) or ``include`` (codes
of the countries or councils the evidence must hold a source from), and one has a ``note``.

``load_cases`` reads any of the three as it stands and changes none of it. A ``Case`` has one place for all a site
expects of a question, so the keys of the ``expect`` table and the keys beside it are kept together under
``Case.expect``, each under its own name: ``case.expect["date_from"]``, ``case.expect["category"]``,
``case.expect.get("no_records")``, ``case.expect.get("history", [])``. No site uses one name in both places; a file
that did would be refused, naming the question.

Where MPs Stand also keeps ``eval/judgments.jsonl``: one line for each source graded for a question (0 not about
the topic, 1 related, 2 directly on it), so that a source is only ever graded once. ``load_judgements`` reads it.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

__all__ = ["Case", "Judgement", "load_cases", "load_judgements", "read_as_if"]


@dataclass(frozen=True)
class Case:
    """One test question, and everything the site's file says about it but its id and its words."""

    id: str
    question: str
    expect: Mapping[str, Any]


@dataclass(frozen=True)
class Judgement:
    """One source graded for one question: Where MPs Stand's ``{"id", "record_id", "grade", "judge"}``."""

    id: str  # the question's
    record_id: str
    grade: int
    judge: str = ""  # the model that graded it


def _read(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path} is not valid TOML: {exc}") from None


def load_cases(path: Path) -> list[Case]:
    """The questions of a site's ``eval/questions.toml``, in the file's order."""
    tables = _read(path).get("q")
    if not isinstance(tables, list) or not tables:
        raise ValueError(f"{path} has no questions: each is a [[q]] table with an id and a question")
    cases: list[Case] = []
    seen: set[str] = set()
    for number, table in enumerate(tables, start=1):
        if not isinstance(table.get("id"), str) or not isinstance(table.get("question"), str):
            raise ValueError(f"{path}: question {number} needs an id and a question")
        if table["id"] in seen:
            raise ValueError(f"{path}: two questions have the id {table['id']!r}: ids must be unique")
        seen.add(table["id"])
        filters = table.get("expect", {})
        if not isinstance(filters, Mapping):
            raise ValueError(f"{path}: question {table['id']!r}: expect must be a table")
        beside = {k: v for k, v in table.items() if k not in ("id", "question", "expect")}
        both = sorted(set(filters) & set(beside))
        if both:
            raise ValueError(f"{path}: question {table['id']!r} has {', '.join(both)} both inside expect and "
                             "beside it: rename one")
        cases.append(Case(table["id"], table["question"], MappingProxyType({**filters, **beside})))
    return cases


def read_as_if(path: Path) -> date | None:
    """The file's ``today``: the date its questions are read as if it were ("the last five years" depends on it).
    None when the file gives none."""
    today = _read(path).get("today")
    if today is None:
        return None
    try:
        return today if isinstance(today, date) else date.fromisoformat(str(today))
    except ValueError:
        raise ValueError(f"{path}: today must be a date such as 2026-10-11, not {today!r}") from None


def load_judgements(path: Path) -> list[Judgement]:
    """Where MPs Stand's ``eval/judgments.jsonl``, in the file's order; nothing when there is no file yet. A source
    graded twice for a question appears twice: the site's own reader keeps the later grade, which is
    ``{(j.id, j.record_id): j.grade for j in load_judgements(path)}``."""
    path = Path(path)
    if not path.exists():
        return []
    found: list[Judgement] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            found.append(Judgement(str(raw["id"]), str(raw["record_id"]), int(raw["grade"]), str(raw.get("judge", ""))))
        except (ValueError, KeyError, TypeError):
            raise ValueError(f"{path}, line {number}: not a judgement (an id, a record_id and a grade)") from None
    return found
