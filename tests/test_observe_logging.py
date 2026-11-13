"""The structured log: one JSON object a line, eight named fields, and no way for a reader's words to reach it."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from test_observe_log import SITE
from wts_core.observe import FIELDS, LOGGER, json_logging, log_event
from wts_core.testing import FixedClock

# a string that must never be found in a log file: a question, with an address and a visitor code in it
MARKER = "CANARY what did Cllr Example of 12 Acacia Avenue say 203.0.113.9 v_5f2a9c"


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock("2026-11-13T12:00:00+00:00")


@pytest.fixture
def path(tmp_path) -> Path:
    return tmp_path / "logs" / "briefings.jsonl"


@pytest.fixture
def log(path, clock):
    """The briefings' logger with the handler on it, as a site sets it up; put back as it was afterwards."""
    logger = logging.getLogger(LOGGER)
    handler = json_logging(path, site=SITE, max_bytes=1_000_000, keep=3, days=14, clock=clock)
    before = (logger.level, logger.propagate)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield logger
    logger.removeHandler(handler)
    handler.close()
    logger.setLevel(before[0])
    logger.propagate = before[1]


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def everything_written(path: Path) -> str:
    return "".join(p.read_text() for p in sorted(path.parent.iterdir()))


def test_an_event_is_one_json_object_with_the_named_fields_in_order(log, path):
    log_event("briefing.stage", briefing="4f2a9c01", stage="rank", ms=310)
    [text] = path.read_text().splitlines()
    assert text == ('{"at": "2026-11-13T12:00:00+00:00", "level": "INFO", "site": "councils", '
                    '"event": "briefing.stage", "briefing": "4f2a9c01", "stage": "rank", "ms": 310, '
                    '"error_type": null}')
    assert tuple(json.loads(text)) == FIELDS == ("at", "level", "site", "event", "briefing", "stage", "ms",
                                                 "error_type")


def test_an_error_is_noted_by_its_type_and_level(log, path):
    log_event("briefing.failed", briefing="4f2a9c01", stage="write", ms=9400, error_type="APITimeoutError",
              level=logging.ERROR)
    assert lines(path) == [{"at": "2026-11-13T12:00:00+00:00", "level": "ERROR", "site": "councils",
                            "event": "briefing.failed", "briefing": "4f2a9c01", "stage": "write", "ms": 9400,
                            "error_type": "APITimeoutError"}]


def test_an_event_with_nothing_but_its_name_leaves_the_rest_empty(log, path):
    log_event("update.finished")
    assert lines(path) == [{"at": "2026-11-13T12:00:00+00:00", "level": "INFO", "site": "councils",
                            "event": "update.finished", "briefing": None, "stage": None, "ms": None,
                            "error_type": None}]


def test_a_careless_log_call_cannot_put_a_readers_words_in_the_log(log, path):
    """Every way a question, a briefing's text, a visitor code or an address might reach a line, tried with a
    marker string: the message, its arguments, an exception's text and traceback, extra fields, and each named
    field itself."""
    log.info(MARKER)
    log.info("a question was asked: %s", MARKER)
    log.warning("question=%(q)s", {"q": MARKER})
    log.error(MARKER, extra={"question": MARKER, "visitor": MARKER, "text": MARKER, "headers": {"x": MARKER}})
    try:
        raise RuntimeError(MARKER)
    except RuntimeError:
        log.exception("it failed for %s", MARKER)
        log.error("again", exc_info=True, stack_info=True)
    log.info("named fields of the wrong shape", extra={
        "event": MARKER, "briefing": MARKER, "stage": MARKER, "ms": MARKER, "error_type": MARKER})
    log.info("named fields of other kinds", extra={
        "event": [MARKER], "briefing": {"id": MARKER}, "stage": (MARKER,), "ms": [MARKER],
        "error_type": RuntimeError(MARKER)})
    log_event(MARKER, briefing=MARKER, stage=MARKER, ms=MARKER, error_type=MARKER)  # type: ignore[arg-type]
    log_event("briefing.failed", error_type=f"RuntimeError: {MARKER}")
    log_event("Why did the council close the library?")  # a sentence is not an event's name

    written = everything_written(path)
    assert "CANARY" not in written and "Acacia" not in written and "203.0.113.9" not in written
    assert "v_5f2a9c" not in written and "library" not in written and "Traceback" not in written
    found = lines(path)
    assert len(found) == 11
    for line in found:
        assert tuple(line) == FIELDS
        assert (line["at"], line["site"]) == ("2026-11-13T12:00:00+00:00", "councils")
        assert line["briefing"] is None and line["stage"] is None and line["ms"] is None
    # what is left is what cannot hold a reader's words: the level, a known event's name, an exception's class
    assert [line["level"] for line in found] == ["INFO", "INFO", "WARNING", "ERROR", "ERROR", "ERROR"] + ["INFO"] * 5
    assert [line["event"] for line in found] == [None] * 9 + ["briefing.failed", None]
    assert [line["error_type"] for line in found] == [None] * 4 + ["RuntimeError", "RuntimeError"] + [None] * 5


def test_log_event_gives_other_handlers_nothing_to_print_either(log):
    """A site's own handler on the same logger (its console, say) sees a fixed message, not the event's fields."""
    seen: list[str] = []

    class Console(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(self.format(record))

    console = Console()
    log.addHandler(console)
    try:
        log_event(MARKER, stage=MARKER)  # the wrong thing to pass, and still not printed
    finally:
        log.removeHandler(console)
    assert seen == ["briefing event"]


def test_a_line_that_cannot_be_written_is_reported_without_the_calls_words(path, clock, capsys):
    """The standard library reports a failed write by printing the call's message and arguments."""
    handler = json_logging(path, site=SITE, max_bytes=1_000_000, keep=1, days=14, clock=clock)
    logger = logging.getLogger("wts.test.full-disk")
    logger.addHandler(handler)
    logger.propagate = False

    class FullDisk:
        def write(self, text: str) -> None:
            raise OSError(28, "No space left on device")

        def tell(self) -> int:
            return 1

        def flush(self) -> None: ...

        def close(self) -> None: ...

    handler.stream.close()
    handler.stream = FullDisk()  # type: ignore[assignment]
    try:
        logger.error("a question was asked: %s", MARKER, extra={"event": "briefing.asked"})
    finally:
        logger.removeHandler(handler)
        handler.close()
    said = capsys.readouterr().err
    assert said == "wts-core: a line of the structured log could not be written (OSError)\n"
    assert "CANARY" not in said


def test_only_numbers_are_times(log, path):
    for ms in (310, 0, 12.5, True, float("nan"), float("inf"), "310"):
        log.info("x", extra={"event": "briefing.stage", "ms": ms})
    assert [line["ms"] for line in lines(path)] == [310, 0, 12.5, None, None, None, None]


def test_a_new_file_is_begun_when_the_file_is_full_and_only_so_many_are_kept(path, clock):
    handler = json_logging(path, site=SITE, max_bytes=400, keep=2, days=14, clock=clock)
    logger = logging.getLogger("wts.test.rotation")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        for n in range(40):  # each line is about 150 bytes: two fit in a file
            logger.info("x", extra={"event": "briefing.stage", "briefing": f"b{n:03d}", "ms": n})
    finally:
        logger.removeHandler(handler)
        handler.close()
    names = sorted(p.name for p in path.parent.iterdir())
    assert names == ["briefings.jsonl", "briefings.jsonl.1", "briefings.jsonl.2"]
    assert all(p.stat().st_size <= 400 for p in path.parent.iterdir())
    kept = [json.loads(line)["briefing"] for name in reversed(names)
            for line in (path.parent / name).read_text().splitlines()]
    assert kept == [f"b{n:03d}" for n in range(40 - len(kept), 40)]  # the newest lines, in order, none torn
    assert 3 <= len(kept) <= 6


def test_a_new_file_is_begun_each_day_and_files_older_than_the_limit_are_deleted(path, clock):
    handler = json_logging(path, site=SITE, max_bytes=1_000_000, keep=30, days=14, clock=clock)
    logger = logging.getLogger("wts.test.days")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    def a_day_of_events(day: int) -> None:
        logger.info("x", extra={"event": "briefing.stage", "briefing": f"day{day}"})
        logger.info("x", extra={"event": "briefing.stage", "briefing": f"day{day}"})
        for p in path.parent.iterdir():  # the files' own times follow the test's clock
            if p.stat().st_mtime > clock.now().timestamp() - 3600 or p == path:
                os.utime(p, (clock.now().timestamp(), clock.now().timestamp()))

    try:
        a_day_of_events(0)
        assert [p.name for p in path.parent.iterdir()] == ["briefings.jsonl"]  # the same day: the same file
        for day in range(1, 4):
            clock.advance(days=1)
            a_day_of_events(day)
        assert sorted(p.name for p in path.parent.iterdir()) == [
            "briefings.jsonl", "briefings.jsonl.1", "briefings.jsonl.2", "briefings.jsonl.3"]
        assert {line["briefing"] for line in lines(path.parent / "briefings.jsonl.1")} == {"day2"}
        clock.advance(days=20)  # a quiet three weeks: the next event starts a file, and the old ones have had
        a_day_of_events(23)     # their fourteen days
        assert sorted(p.name for p in path.parent.iterdir()) == ["briefings.jsonl"]
        assert {line["briefing"] for line in lines(path)} == {"day23"}
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_a_handler_opened_on_yesterdays_file_begins_a_new_one(path, clock):
    def write_one(name: str) -> None:
        handler = json_logging(path, site=SITE, max_bytes=1_000_000, keep=5, days=14, clock=clock)
        logger = logging.getLogger("wts.test.restart")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            logger.info("x", extra={"event": name})
        finally:
            logger.removeHandler(handler)
            handler.close()

    write_one("first")
    write_one("second")  # the site restarted the same day: the same file
    assert [line["event"] for line in lines(path)] == ["first", "second"]
    clock.advance(days=1)
    write_one("third")
    assert [line["event"] for line in lines(path)] == ["third"]
    assert [line["event"] for line in lines(path.parent / "briefings.jsonl.1")] == ["first", "second"]


def test_the_handler_makes_the_logs_folder(tmp_path, clock):
    handler = json_logging(tmp_path / "data" / "logs" / "briefings.jsonl", site=SITE, max_bytes=1000, keep=1,
                           days=14, clock=clock)
    handler.close()
    assert (tmp_path / "data" / "logs").is_dir()


def test_the_limits_have_no_defaults(path):
    with pytest.raises(TypeError):
        json_logging(path, site=SITE)  # type: ignore[call-arg]
