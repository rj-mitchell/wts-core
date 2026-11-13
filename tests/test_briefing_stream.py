"""Briefings are streamed with a comment line during long silences, so a proxy does not close the connection, and the
work stops once the reader has gone. From Where MPs Stand's and Where Councils Stand's ``tests/test_sse.py`` and
Where Countries Stand's ``tests/test_api.py``: the streamer was the same code in all three, and is theirs here."""

from __future__ import annotations

import contextvars
import threading
import time
from datetime import date
from pathlib import Path

import pytest

from test_usage_sites import SITES, checkout_of
from wts_core.briefing import KEEP_ALIVE_SECONDS, sse


def test_a_silence_is_filled_with_comment_lines_and_events_arrive_in_order():
    def events():
        yield {"type": "plan", "n": 1}
        time.sleep(0.35)  # the model thinking
        yield {"type": "final", "n": 2}

    out = list(sse(events(), keep_alive=0.1))
    assert out[0].startswith(b"event: plan\ndata: ")
    assert out[-1].startswith(b"event: final\ndata: ")
    assert out[1:-1] and all(c == b": still working\n\n" for c in out[1:-1])


def test_an_error_is_raised_where_the_response_is_sent():
    def events():
        yield {"type": "plan"}
        raise RuntimeError("boom")

    stream = sse(events(), keep_alive=1)
    next(stream)
    with pytest.raises(RuntimeError):
        next(stream)


def test_the_work_stops_once_the_reader_has_gone():
    closed = threading.Event()

    def events():
        try:
            for i in range(1000):
                yield {"type": "text", "text": str(i)}
                time.sleep(0.01)
        finally:
            closed.set()

    stream = sse(events(), keep_alive=1)
    next(stream)
    stream.close()  # the reader left
    assert closed.wait(2)


def test_stream_stops_when_the_reader_leaves():
    """A briefing nobody is reading any more must stop being written: its events are closed, which closes the
    model's stream (found on Where Countries Stand's live site: a reader who left kept the briefing running, and
    paid for)."""
    closed = threading.Event()
    made = []

    def briefing():
        try:
            while True:
                made.append(1)
                yield {"type": "text", "text": "word "}
                time.sleep(0.01)
        finally:
            closed.set()

    events = briefing()  # held here, so only an explicit close (not the garbage collector) can stop it
    out = sse(events, keep_alive=1)
    assert next(out).startswith(b"event: text")
    out.close()  # the reader has gone: the server closes the response
    assert closed.wait(2)
    n = len(made)
    time.sleep(0.1)
    assert len(made) == n  # nothing more is written


def test_dates_are_written_as_text():
    out = list(sse(iter([{"type": "sources", "date": date(2025, 2, 26)}]), keep_alive=1))
    assert out == [b'event: sources\ndata: {"type": "sources", "date": "2025-02-26"}\n\n']


def test_every_event_is_written_as_the_sites_write_it_byte_for_byte():
    events = [{"type": "plan", "plan": {"question": "café “quoted”", "filters": {}}, "usage": None},
              {"type": "text", "text": "line one\nline two"},
              {"type": "final", "answer": None, "note": "Sources only: no briefing was written."}]
    assert list(sse(iter(events), keep_alive=1)) == [
        b'event: plan\ndata: {"type": "plan", "plan": {"question": "caf\\u00e9 \\u201cquoted\\u201d", '
        b'"filters": {}}, "usage": null}\n\n',
        b'event: text\ndata: {"type": "text", "text": "line one\\nline two"}\n\n',
        b'event: final\ndata: {"type": "final", "answer": null, "note": "Sources only: no briefing was written."}\n\n']


def test_the_events_are_closed_in_the_thread_that_ran_them():
    """The model's stream belongs to the thread that opened it: it is closed there, not where the response is."""
    seen: dict[str, str] = {}
    done = threading.Event()

    def events():
        try:
            seen["ran"] = threading.current_thread().name
            yield {"type": "text", "text": "a"}
            yield {"type": "text", "text": "b"}
        finally:
            seen["closed"] = threading.current_thread().name
            done.set()

    stream = sse(events(), keep_alive=1)
    next(stream)
    stream.close()
    assert done.wait(2) and seen == {"ran": "sse", "closed": "sse"}


def test_what_the_caller_set_in_its_context_reaches_the_thread_that_works_the_events_out():
    """A new thread starts with an empty context: the streamer gives its own a copy of the caller's, so a context
    variable set where the response is made (the desk's stage timings, a site's own) is there for the pipeline."""
    variable: contextvars.ContextVar[str] = contextvars.ContextVar("set_by_the_route", default="nothing")
    variable.set("the route's")

    def events():
        yield {"type": "plan", "seen": variable.get(), "thread": threading.current_thread().name}

    out = list(sse(events(), keep_alive=1))
    assert out == [b'event: plan\ndata: {"type": "plan", "seen": "the route\'s", "thread": "sse"}\n\n']


def _function(path: Path, name: str) -> str:
    """The source of one top-level function in a site's file, without its docstring and comments."""
    import ast

    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    if ast.get_docstring(node):
        node.body = node.body[1:]
    return ast.dump(node, include_attributes=False)


@pytest.mark.parametrize("facts", SITES, ids=str)
def test_each_sites_streamer_is_still_the_code_this_one_was_taken_from(facts):
    """If a site's ``sse`` changes, this streamer must follow it (or the site adopt this one): the three are
    compared with each other, and each waits the same fifteen seconds before a comment line."""
    app = checkout_of(facts) / "src" / facts.package / "api" / "app.py"
    reference = checkout_of(SITES[0]) / "src" / SITES[0].package / "api" / "app.py"
    assert _function(app, "sse") == _function(reference, "sse")
    assert f"KEEP_ALIVE_SECONDS = {KEEP_ALIVE_SECONDS}\n" in app.read_text()
