"""Structured logs: one JSON object a line, the same shape on every site (ADR 0012).

A line says what the site did and how long it took ("briefing 4f2a… spent 310 ms ranking"): a note about the
site's work, not a log of a reader's request. So that the sites' notices can go on saying "requests are not
logged", the formatter here is unable to write anything but eight named fields, and each of those only in a shape
that a sentence does not fit:

- ``at``, ``level`` and ``site`` are the formatter's own;
- ``event`` and ``stage`` are short names in lower case with no spaces (``briefing.stage``, ``rank``);
- ``briefing`` is the record's id; ``ms`` is a number;
- ``error_type`` is an exception's class name, never its message.

Anything else is left out: the message of an ordinary ``log.info("… %s", question)`` call is never written, nor an
exception's text or traceback, nor an extra field with another name, nor a named field of the wrong shape. A
careless call leaves a line with empty fields, and nothing of the reader's.

The files are kept for a stated time and size (ADR 0012: 14 days or 50 MB a site, whichever is less). The handler
is the standard library's ``RotatingFileHandler`` with one addition: it also starts a new file each day, and at
each new file deletes the old ones last written more than ``days`` ago, so the limit in days holds on a quiet site
whose files never fill. The most a site's logs can take is ``max_bytes × (keep + 1)``.
"""

from __future__ import annotations

import json
import logging
import math
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from wts_core.ports import SYSTEM_CLOCK, Clock
from wts_core.settings import Site
from wts_core.state import iso, today

__all__ = ["FIELDS", "LOGGER", "json_logging", "log_event"]

FIELDS = ("at", "level", "site", "event", "briefing", "stage", "ms", "error_type")
LOGGER = "wts.briefings"  # the logger ``log_event`` writes to: a site adds the handler to it

_NAME = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,63}")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,99}")
_SHAPES = {"event": _NAME, "stage": _NAME, "briefing": _ID, "error_type": _CLASS}
_MESSAGE = "briefing event"  # all that any other handler on the same logger is given to print


def _shaped(name: str, value: Any) -> str | None:
    return value if isinstance(value, str) and _SHAPES[name].fullmatch(value) else None


class _JsonLines(logging.Formatter):
    """Writes the eight fields and nothing else. It never calls ``record.getMessage()`` and never formats an
    exception: there is no path from a log call's message or arguments to the line."""

    def __init__(self, site: str, clock: Clock) -> None:
        super().__init__()
        self._site = site
        self._clock = clock

    def format(self, record: logging.LogRecord) -> str:
        given = record.__dict__
        ms = given.get("ms")
        error_type = _shaped("error_type", given.get("error_type"))
        if error_type is None and record.exc_info and record.exc_info[0] is not None:
            error_type = _shaped("error_type", record.exc_info[0].__name__)
        return json.dumps({
            "at": iso(self._clock),
            "level": logging.getLevelName(record.levelno),
            "site": self._site,
            "event": _shaped("event", given.get("event")),
            "briefing": _shaped("briefing", given.get("briefing")),
            "stage": _shaped("stage", given.get("stage")),
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


def json_logging(path: Path, *, site: Site, max_bytes: int, keep: int, days: int,
                 clock: Clock = SYSTEM_CLOCK) -> logging.Handler:
    """A handler that writes the structured log to ``path`` (``data/logs/briefings.jsonl`` on the sites), one JSON
    object a line with the fields in ``FIELDS``; ``site`` is written as the site's package name.

    A new file is started when the current one reaches ``max_bytes`` or the day changes; ``keep`` old files are
    kept, and none last written more than ``days`` ago. The limits are the site's to state (ADR 0012 gives 14
    days and 50 MB), so none has a default. The site adds the handler to the logger named ``LOGGER``::

        log = logging.getLogger(observe.LOGGER)
        log.addHandler(observe.json_logging(path, site=SITE, max_bytes=3_000_000, keep=15, days=14))
        log.setLevel(logging.INFO)
        log.propagate = False
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = _DailyRotatingFile(path, max_bytes=max_bytes, keep=keep, days=days, clock=clock)
    handler.setFormatter(_JsonLines(site.package, clock))
    return handler


def log_event(event: str, *, briefing: str | None = None, stage: str | None = None, ms: int | None = None,
              error_type: str | None = None, level: int = logging.INFO) -> None:
    """Note one thing the site did: ``event`` is a short name (``briefing.stage``), ``briefing`` the record's id,
    ``stage`` the stage's name, ``ms`` how long it took, ``error_type`` an exception's class name. Never pass a
    question, any text of a briefing or a source, a visitor code, an address or a header: there is no field for
    them, and a value of the wrong shape is left out of the line."""
    logging.getLogger(LOGGER).log(level, _MESSAGE, extra={"event": event, "briefing": briefing, "stage": stage,
                                                         "ms": ms, "error_type": error_type})
