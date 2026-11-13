"""What answers the nightly family check: ``GET /api/check`` (ADR 0010).

``check_route`` returns a plain function: given what the request presented as its token, it returns the status and
the body to send. The site's own route calls it, so the package imports no web framework::

    check = check_route(SITE, token=SITE.env("CHECK_TOKEN"), replies=replies, backups=lambda: backup_ages(...))

    @app.get("/api/check")
    def api_check(authorization: str | None = Header(None)) -> JSONResponse:
        status, body = check(authorization)
        return JSONResponse(body, status_code=status)

The family's check token is one random value the owner sets in the charity repository's secrets and in each site's
``deploy/.env`` (``<PREFIX>_CHECK_TOKEN``). With none set, the answer is the 404 any missing address gets, so a site
without the token shows nothing, not even that the address exists. With a wrong one, or none presented, it is 401
and an empty body. The comparison takes the same time whatever was presented.

The answer holds counts, ages and versions, and nothing else: no question, no word of a report or a statement, no
name, no address. What a site's own ``backups`` and ``figures`` give is passed through a sieve that lets only
numbers through, so that a mistake there cannot put a reader's words in the answer either.
"""

from __future__ import annotations

import hmac
import json
import math
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wts_core import __version__
from wts_core.events import EVENTS_VERSION
from wts_core.ops import BackupSpec
from wts_core.ops.offsite import _STATUS_FILE
from wts_core.ports import SYSTEM_CLOCK, Clock
from wts_core.replies import Replies
from wts_core.settings import Site
from wts_core.state import iso

__all__ = ["backup_ages", "check_route"]

# what a missing address answers on every site (FastAPI's own words), so that a site with no token set answers
# this address exactly as it answers one that was never there
_NOT_THERE: tuple[int, dict[str, Any]] = (404, {"detail": "Not Found"})
# A key that may leave in the answer is the plain name of a figure, as written in code: lower-case words joined by
# underscores ("briefings", "p95_seconds", "by_outcome"). A visitor's code, an address, a question or a person's
# name used as a key is not one, and is left out with whatever it counted.
_KEY = re.compile(r"(?=.{1,40}$)[a-z]+[0-9]{0,3}(_[a-z0-9]+)*")


def check_route(site: Site, *, token: str | None, replies: Replies | Callable[[], Replies] | None = None,
                backups: Callable[[], Mapping[str, Any]] | None = None,
                figures: Callable[[], Mapping[str, Any]] | None = None,
                clock: Clock = SYSTEM_CLOCK) -> Callable[[str | None], tuple[int, dict[str, Any]]]:
    """The function behind a site's ``GET /api/check``. It takes what the request presented (the ``Authorization``
    header as sent, ``Bearer …``, or the token alone) and returns the status and the body.

    ``token`` is the site's own copy of the check token; None or blank means the check is not set up. ``replies``
    (or something that returns it) gives what is waiting: how many reports and statements, how many items are
    hidden, and how long the oldest has waited in working days. ``backups`` gives the ages of the newest backup and
    off-site copy (``backup_ages``); ``figures`` the briefing record's latest figures. Only the numbers in what
    those two return are passed on.

    The answer, when the token is right::

        {"site": "councils", "at": "2026-11-13T02:10:00+00:00",
         "versions": {"package": "0.1.0", "site": "1.4.2", "events": 1},
         "waiting": {"reports": 2, "statements": 1, "hidden": 0, "oldest_working_days": 3},
         "backups": {"newest_hours": 21.7, "offsite_hours": 21.7, "offsite_ok": true},
         "figures": {…}}
    """
    wanted = (token or "").strip().encode()

    def check(presented: str | None) -> tuple[int, dict[str, Any]]:
        if not wanted:
            return _NOT_THERE
        if not hmac.compare_digest(_token(presented).encode(), wanted):
            return 401, {}
        body: dict[str, Any] = {
            "site": site.package, "at": iso(clock),
            "versions": {"package": __version__, "site": site.version, "events": EVENTS_VERSION}}
        if replies is not None:
            waiting = (replies() if callable(replies) else replies).waiting()
            body["waiting"] = {"reports": waiting.reports, "statements": waiting.statements,
                               "hidden": waiting.hidden, "oldest_working_days": waiting.oldest_working_days}
        if backups is not None:
            body["backups"] = _numbers_only(backups())
        if figures is not None:
            body["figures"] = _numbers_only(figures())
        return 200, body

    return check


def backup_ages(folder: Path, spec: BackupSpec, *, clock: Clock = SYSTEM_CLOCK) -> dict[str, float | bool | None]:
    """How old the newest backup in ``folder`` and the last off-site copy are, in hours, for the check's
    ``backups``: ``newest_hours`` (None when there is no backup), ``offsite_hours`` and ``offsite_ok`` (None when no
    copy has been tried, or its record cannot be read). As ``ops.backup_alerts`` reads them: the newest backup is
    the last by name, and its age is its file's."""
    folder, now = Path(folder), clock.now()
    local = spec.archives(folder) if folder.is_dir() else []
    newest = _hours(now, datetime.fromtimestamp(local[-1].stat().st_mtime, UTC)) if local else None
    try:
        status = json.loads((folder / _STATUS_FILE).read_text())
        sent = _hours(now, datetime.fromisoformat(status["when"]))
        ok: bool | None = bool(status.get("ok"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        sent, ok = None, None
    return {"newest_hours": newest, "offsite_hours": sent, "offsite_ok": ok}


def _hours(now: datetime, then: datetime) -> float:
    return round((now - then).total_seconds() / 3600, 1)


def _token(presented: str | None) -> str:
    """The token in what a request presented: the header's value after ``Bearer``, or the value itself."""
    text = (presented or "").strip()
    scheme, _, rest = text.partition(" ")
    return rest.strip() if scheme.lower() == "bearer" else text


def _numbers_only(value: Any) -> Any:
    """What may leave in the check's answer: numbers, yes or no, nothing, and lists and tables of those under the
    plain names of figures. Any text is left out, with its key: counts and ages only."""
    if isinstance(value, Mapping):
        kept = {str(k): _numbers_only(v) for k, v in value.items()
                if isinstance(k, str) and _KEY.fullmatch(k) and _passes(v)}
        return kept
    if isinstance(value, (list, tuple)):
        return [_numbers_only(v) for v in value if _passes(v)]
    if isinstance(value, float) and not math.isfinite(value):
        return None  # not a number JSON can carry
    return value if _passes(value) else None


def _passes(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, Mapping, list, tuple))
