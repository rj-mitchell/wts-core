"""Structured logs: one JSON object a line, the same shape on every site (ADR 0012).

A line says what the site did and how long it took ("briefing 4f2a… spent 310 ms ranking"): a note about the
site's work, not a log of a reader's request. So that the sites' notices can go on saying "requests are not
logged", the formatter here is unable to write anything but eight named fields, and each of those only from a
fixed list or in one fixed shape:

- ``at``, ``level`` and ``site`` are the formatter's own;
- ``event`` is one of ``EVENTS`` (or a name the site listed in its code when it made the handler), and ``stage``
  one of ``STAGE_NAMES``: a word that is not on the list is left out, however short;
- ``briefing`` is the record's id, in exactly the shape the briefing desk makes (eleven characters), so an
  address or a visitor's code does not fit; ``ms`` is a number;
- ``error_type`` is an exception's class name (one word, no dots), never its message.

Anything else is left out: the message of an ordinary ``log.info("… %s", question)`` call is never written, nor an
exception's text or traceback, nor an extra field with another name, nor a named field of the wrong shape. A
careless call leaves a line with empty fields, and nothing of the reader's. The same holds when a line cannot be
written at all: the handler reports the failure by the error's class, not by printing the call as the standard
library would.

The files are kept for a stated time and size (ADR 0012: 14 days or 50 MB a site, whichever is less). The handler
is the standard library's ``RotatingFileHandler`` with one addition: it also starts a new file each day, and at
each new file deletes the old ones last written more than ``days`` ago, so the limit in days holds on a quiet site
whose files never fill. The most a site's logs can take is ``max_bytes × (keep + 1)``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import re
import sys
from collections.abc import Collection
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from wts_core.observe.log import OUTCOMES
from wts_core.ports import SYSTEM_CLOCK, Clock
from wts_core.settings import Site
from wts_core.state import iso, today

__all__ = ["EVENTS", "FIELDS", "LOGGER", "STAGE_NAMES", "json_logging", "log_event"]

FIELDS = ("at", "level", "site", "event", "briefing", "stage", "ms", "error_type")
LOGGER = "wts.briefings"  # the logger ``log_event`` writes to: a site adds the handler to it

# what a line may say happened: a stage of a briefing reached, or a briefing ended in one of its outcomes
EVENTS = ("briefing.stage", *(f"briefing.{outcome}" for outcome in OUTCOMES))
# the stages a briefing passes (``briefing.STAGES``; a test keeps the two alike), and "start" for before the first
STAGE_NAMES = ("start", "parsed", "searched", "ranked", "sources_sent", "first_token", "written", "checked")

_NAME = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*")  # a site's own event names: words joined by dots
_ID = re.compile(r"[A-Za-z0-9_-]{11}")  # the desk's ``random.token(8)``; a visitor's code is 24 characters
_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,99}")
_MESSAGE = "briefing event"  # all that any other handler on the same logger is given to print


def _shaped(shape: re.Pattern[str], value: Any) -> str | None:
    return value if isinstance(value, str) and shape.fullmatch(value) else None


def _listed(names: Collection[str], value: Any) -> str | None:
    return value if isinstance(value, str) and value in names else None


class _JsonLines(logging.Formatter):
    """Writes the eight fields and nothing else. It never calls ``record.getMessage()`` and never formats an
    exception: there is no path from a log call's message or arguments to the line."""

    def __init__(self, site: str, clock: Clock, events: frozenset[str]) -> None:
        super().__init__()
        self._site = site
        self._clock = clock
        self._events = events

    def format(self, record: logging.LogRecord) -> str:
        given = record.__dict__
        ms = given.get("ms")
        error_type = _shaped(_CLASS, given.get("error_type"))
        if error_type is None and record.exc_info and record.exc_info[0] is not None:
            error_type = _shaped(_CLASS, record.exc_info[0].__name__)
        return json.dumps({
            "at": iso(self._clock),
            "level": logging.getLevelName(record.levelno),
            "site": self._site,
            "event": _listed(self._events, given.get("event")),
            "briefing": _shaped(_ID, given.get("briefing")),
            "stage": _listed(STAGE_NAMES, given.get("stage")),
            "ms": ms if isinstance(ms, (int, float)) and not isinstance(ms, bool) and math.isfinite(ms) else None,
            "error_type": error_type,
        })


class _DailyRotatingFile(RotatingFileHandler):
    """``RotatingFileHandler`` that also starts a new file each day (UTC) and forgets files older than ``days``."""

    def __init__(self, path: Path, *, max_bytes: int, keep: int, days: int, clock: Clock) -> None:
        super().__init__(path, maxBytes=max_bytes, backupCount=keep, encoding="utf-8")
        self._days = days
        self._clock = clock
        self._day = self._day_begun()

    def _day_begun(self) -> str | None:
        """The day of the file's first line, or None for a file with nothing in it yet."""
        try:
            with open(self.baseFilename, encoding="utf-8") as f:
                first = f.readline()
            return str(json.loads(first)["at"])[:10] if first.strip() else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def shouldRollover(self, record: logging.LogRecord) -> bool:  # noqa: N802  (the standard library's name)
        return bool((self._day is not None and self._day != today(self._clock)) or super().shouldRollover(record))

    def doRollover(self) -> None:  # noqa: N802  (the standard library's name)
        super().doRollover()
        self._day = None
        too_old = self._clock.now().timestamp() - self._days * 86400
        for n in range(1, self.backupCount + 1):
            old = Path(f"{self.baseFilename}.{n}")
            if old.exists() and old.stat().st_mtime < too_old:
                old.unlink()

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        if self._day is None:
            self._day = today(self._clock)

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802  (the standard library's name)
        """Say that a line could not be written (a full disk, say) and why, by the error's class alone. The
        standard library's version prints the log call's message and arguments to the error stream, where a
        careless call's question would land in the server's journal."""
        failed = sys.exc_info()[0]
        if logging.raiseExceptions and sys.stderr is not None:
            with contextlib.suppress(OSError):
                sys.stderr.write("wts-core: a line of the structured log could not be written "
                                 f"({failed.__name__ if failed else 'no reason given'})\n")


def json_logging(path: Path, *, site: Site, max_bytes: int, keep: int, days: int,
                 events: Collection[str] = (), clock: Clock = SYSTEM_CLOCK) -> logging.Handler:
    """A handler that writes the structured log to ``path`` (``data/logs/briefings.jsonl`` on the sites), one JSON
    object a line with the fields in ``FIELDS``; ``site`` is written as the site's package name.

    A new file is started when the current one reaches ``max_bytes`` or the day changes; ``keep`` old files are
    kept, and none last written more than ``days`` ago. The limits are the site's to state (ADR 0012 gives 14
    days and 50 MB), so none has a default. ``events`` are the site's own event names beside ``EVENTS``, written
    in its code (never taken from a request): lower-case words joined by dots. The site adds the handler to the
    logger named ``LOGGER``::

        log = logging.getLogger(observe.LOGGER)
        log.addHandler(observe.json_logging(path, site=SITE, max_bytes=3_000_000, keep=15, days=14))
        log.setLevel(logging.INFO)
        log.propagate = False
    """
    wrong = [e for e in events if not isinstance(e, str) or not _NAME.fullmatch(e)]
    if wrong:
        raise ValueError(f"an event's name is lower-case words joined by dots, which {wrong[0]!r} is not")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _DailyRotatingFile(path, max_bytes=max_bytes, keep=keep, days=days, clock=clock)
    handler.setFormatter(_JsonLines(site.package, clock, frozenset((*EVENTS, *events))))
    return handler


def log_event(event: str, *, briefing: str | None = None, stage: str | None = None, ms: int | None = None,
              error_type: str | None = None, level: int = logging.INFO) -> None:
    """Note one thing the site did: ``event`` is one of ``EVENTS`` or of the site's own listed names, ``briefing``
    the record's id, ``stage`` one of ``STAGE_NAMES``, ``ms`` how long it took, ``error_type`` an exception's class
    name. Never pass a question, any text of a briefing or a source, a visitor code, an address or a header: there
    is no field for them, and a value that is not on its list or of its shape is left out of the line."""
    logging.getLogger(LOGGER).log(level, _MESSAGE, extra={"event": event, "briefing": briefing, "stage": stage,
                                                         "ms": ms, "error_type": error_type})
