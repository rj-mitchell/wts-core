"""Two promises every site makes, as checks a site's own tests call with its real pipeline.

``assert_no_reader_data``: after a question has been asked, nothing the package keeps or logs holds the reader's
address; the visitor's code is nowhere but the two places it is counted; and the question itself is only where the
sites' privacy notices say a question is kept (ADR 0012).

``assert_statements_stay_out``: a statement under the right of reply never reaches the model, the search index or
the record (ADR 0008). It publishes a statement that carries a marker found nowhere else, asks a question through
the site's own pipeline with the recording fakes of ``wts_core.testing``, and fails if the marker turns up anywhere
but the right of reply's own tables.

Both read every row of every ``wts_`` table in the state database. A site's own tables are its own to check.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from wts_core.ports import SYSTEM_RANDOM, Random
from wts_core.replies import Replies
from wts_core.replies import migrations as replies_migrations
from wts_core.state import StateDB
from wts_core.testing.index import MemoryIndex, RecordingEmbedder
from wts_core.testing.models import ScriptedModel

__all__ = ["assert_no_reader_data", "assert_statements_stay_out"]

# Where a reader's question may be kept (ADR 0012, "Check against the privacy notices"; ``usage/tables.py``): with
# the saved briefing, in the replay kept for answering the same question again, in the briefing record, and in the
# note of a briefing that failed.
_QUESTION_KEPT_IN: Mapping[str, tuple[str, ...]] = {
    "wts_briefings": ("question", "events"),
    "wts_answer_cache": ("events",),
    "wts_briefing_log": ("question",),
    "wts_failures": ("question",),
}
# Where the day's visitor code may be kept: the spending record, for the daily limit, and the day's count of
# reports and statements sent, which is emptied each day.
_VISITOR_KEPT_IN: Mapping[str, tuple[str, ...]] = {
    "wts_spending": ("visitor",),
    "wts_reply_counts": ("visitor",),
}


def assert_no_reader_data(state: StateDB, log_lines: Iterable[str], *, question: str, address: str,
                          visitor: str | None = None) -> None:
    """Fail if anything about the reader who asked ``question`` from ``address`` is kept where it should not be.

    Call it after the question has been asked through the site's pipeline, with the lines its logging wrote.

    * ``address`` (the reader's network address, as the request carried it) must be in no ``wts_`` table and no
      log line.
    * ``visitor`` (the day's visitor code for that address, if the site gives it) must be in no log line, and in no
      ``wts_`` table but ``wts_spending.visitor`` and ``wts_reply_counts.visitor``.
    * ``question`` must be in no log line, and in no ``wts_`` table but these, which are where the sites' privacy
      notices say a question is kept: ``wts_briefings.question`` and ``wts_briefings.events`` (the saved briefing),
      ``wts_answer_cache.events`` (the replay for the same question asked again), ``wts_briefing_log.question``
      (the record of each briefing) and ``wts_failures.question`` (the note of a briefing that failed).

    Give a question and an address that could be nothing else: a search for "a" proves nothing."""
    wanted = {"question": (question, _QUESTION_KEPT_IN), "address": (address, {}),
              **({"visitor": (visitor, _VISITOR_KEPT_IN)} if visitor else {})}
    for what, (needle, _) in wanted.items():
        if len((needle or "").strip()) < 6:
            raise ValueError(f"the {what} to look for is too short to prove anything: {needle!r}")
    lines = list(log_lines)
    found: list[str] = []
    for what, (needle, allowed) in wanted.items():
        found += [f"the {what} is in {table}.{column}" for table, column in _kept_in(state, needle)
                  if column not in allowed.get(table, ())]
        found += [f"the {what} is in a log line: {line.strip()[:200]}" for line in lines if _holds(line, needle)]
    if found:
        raise AssertionError("something about a reader is kept where it should not be:\n  " + "\n  ".join(found))


def assert_statements_stay_out(*, replies: Replies, ask: Callable[[str], Iterable[Any]], model: ScriptedModel,
                               embedder: RecordingEmbedder, index: MemoryIndex, state: StateDB,
                               log_lines: Callable[[], Iterable[str]] | Iterable[str], item: str, question: str,
                               about: str | None = None, random: Random = SYSTEM_RANDOM) -> None:
    """Fail if a published statement reaches the model, the embedder, the search index, the record or a log.

    The site builds its real pipeline over the fakes it passes here (``model``, ``embedder``, ``index``), with
    ``state`` as its state database and ``replies`` its ``Replies``; ``ask`` asks a question through that pipeline
    and gives the events a reader would be sent. ``item`` is the address of something a statement can sit beside,
    and ``question`` a question about it, so that the pipeline has every reason to meet the statement; ``about``
    is whom the statement speaks for, where the site must be told (Where Landlords Stand, for an area's page).

    A statement is sent and published whose name, role, words, link and confirming address all carry one marker
    that is nowhere else. Then the question is asked, and the marker must not be in: any request the model was
    given; anything given to the embedder; anything in, or ever written to, the index; any event the reader was
    sent; any ``wts_`` table but the right of reply's own (``wts_statements``, ``wts_statement_log`` and the
    others its migrations make); or any log line. ``log_lines`` is the lines the site's logging wrote, or
    something that returns them, read after the question has been asked.

    It also fails if the statement was not shown, or the question never reached the model: a check that passes
    because nothing happened proves nothing."""
    marker = "wtsmarker" + random.token_hex(6).lower()
    sid = replies.submit(
        name=f"Marker {marker}", role=f"Spokesperson for {marker}", item=item, link=f"https://example.org/{marker}",
        text=f"This statement is here to be found nowhere else: {marker}. It must never reach the model, the search "
             "index or the record.", email=f"{marker}@example.org")
    if sid is None:
        raise AssertionError("the statement was not taken: nothing was kept")
    replies.publish(sid, checked="Confirmed for the test that statements stay out.", about=about)
    if not any(shown["id"] == sid for shown in replies.published(everywhere=True)):
        raise AssertionError(f"the statement was published but is not shown (is {item} hidden?): nothing to keep out")

    events = list(ask(question))
    if not model.requests and not model.structured_requests:
        raise AssertionError("the question never reached the model, so this proves nothing: ask one the site "
                             "finds sources for, with nothing in the answer cache")
    lines = list(log_lines() if callable(log_lines) else log_lines)

    own = _tables_of_replies()
    found = [f"a request to the model ({n + 1} of {len(model.requests)})"
             for n, request in enumerate(model.requests) if _holds(repr(request), marker)]
    found += ["a question the model was asked to read" for request, _ in model.structured_requests
              if _holds(repr(request), marker)]
    found += ["a text given to the embedder" for text in embedder.texts if _holds(text, marker)]
    found += [f"the index ({where})" for where, rows in (("its rows", index.rows), ("its vectors' rows",
                                                                                   index.vector_rows),
                                                         ("a row written to it", index.added))
              if _holds(repr(rows), marker)]
    found += ["an event sent to the reader" for event in events if _holds(repr(event), marker)]
    found += [f"{table}.{column}" for table, column in _kept_in(state, marker) if table not in own]
    found += [f"a log line: {line.strip()[:200]}" for line in lines if _holds(line, marker)]
    if found:
        raise AssertionError("a statement under the right of reply reached where it must never be:\n  "
                             + "\n  ".join(dict.fromkeys(found)))


def _tables_of_replies() -> set[str]:
    made = re.compile(r"CREATE TABLE IF NOT EXISTS (wts_\w+)")
    return {m.group(1) for migration in replies_migrations() for statement in migration.statements
            for m in [made.match(statement)] if m}


def _holds(text: str, needle: str) -> bool:
    """Whether ``needle`` is in ``text``, as it is or as JSON writes it (quotes and letters outside ASCII escaped),
    whatever its case."""
    lowered = text.lower()
    forms = {needle, json.dumps(needle)[1:-1], json.dumps(needle, ensure_ascii=False)[1:-1]}
    return any(form.lower() in lowered for form in forms)


def _kept_in(state: StateDB, needle: str) -> list[tuple[str, str]]:
    """Every column of every ``wts_`` table that holds ``needle`` in some row."""
    found: dict[tuple[str, str], None] = {}
    with state.connect() as con:
        for table in sorted(t for t in state.tables() if t.startswith("wts_")):
            for row in con.execute(f"SELECT * FROM {table}"):
                for column in row.keys():  # noqa: SIM118 (a sqlite3.Row is not a mapping to iterate)
                    value = row[column]
                    if value is not None and _holds(value.decode("utf-8", "replace") if isinstance(value, bytes)
                                                    else str(value), needle):
                        found[(table, column)] = None
    return list(found)
