"""Dates as the family's pages write them: "12 November 2026".

One small function, in a module that imports nothing else from the package, so that anything may use it: a site's
pipeline for the title of a source, a page, and the right of reply for a statement's heading (which is where it
first lived, as ``replies.long_date``; it is still exported from there).
"""

from __future__ import annotations

from datetime import date

__all__ = ["long_date"]

# written out, so a date never depends on the server's language settings
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


def long_date(iso: str | date | None) -> str:
    """A date as every site writes it for a reader: "12 November 2026". Given as a date, or as text that begins
    with one (``2026-11-12``, or a time such as ``2026-11-12T10:00:00+00:00``); nothing gives nothing."""
    if not iso:
        return ""
    d = iso if isinstance(iso, date) else date.fromisoformat(str(iso)[:10])
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"
