"""The tables reports and statements are kept in (ADR 0005: the package's own, beside each site's).

One shape that can hold every site's rows, so each site's import is a plain ``INSERT … SELECT`` (the study's
section 1 lists each site's columns):

* ``wts_statements``: ``item`` is the address of what the statement sits beside (Where MPs Stand's ``item_path``,
  the others' ``page``), ``part`` a part of that page (Where Landlords Stand's), and ``about`` the member, country,
  council or landlord it speaks for, as text (``person``, ``country``, ``council``, ``landlord``). Both dates are
  kept: ``published_at`` (Where Countries Stand's and Where Councils Stand's ``shown_on``) and ``updated_at``.
  ``closed_at`` is when it was declined, withdrawn or removed (``ended_at``), and ``reason`` why. An address
  already deleted is NULL.
* ``wts_statement_log``: a row for each thing done to a statement, with its time and note (Where Landlords Stand's
  ``statement_log``; the JSON ``log`` column of Where Countries Stand and Where Councils Stand, one row for each
  entry). ``previous`` holds the old words when a statement is updated, as a JSON object of the fields that changed.
  The note of how a sender was confirmed lives here and nowhere else.
* ``wts_reports``: Where MPs Stand's columns, which the others' fit inside: ``status`` ("open", then the outcome),
  ``resolution`` (the private note: Where Landlords Stand's ``outcome``), ``public_note``, ``briefing_id``.
  ``contact`` is Where Landlords Stand's ``email``. ``kind`` may be NULL (a report from an older form).
* ``wts_hidden``: an item hidden while a concern is decided, with the note shown in its place; ``shown_at`` is set
  when it is shown again, so the record of having hidden it stays.
* ``wts_reply_counts``: how many reports and statements each of the day's visitor codes has sent. It is emptied of
  earlier days whenever it is written, and it is the only place a visitor code is kept: no report or statement
  carries one, so nothing is tied to its sender.
"""

from __future__ import annotations

from wts_core.state import Migration

__all__ = ["migrations"]


def migrations() -> tuple[Migration, ...]:
    """Numbers 30 to 39 are this module's (CONTRIBUTING.md, rule 6). They only add."""
    return (
        Migration(30, "reports", (
            "CREATE TABLE IF NOT EXISTS wts_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, "
            "kind TEXT, page TEXT, message TEXT NOT NULL, contact TEXT, briefing_id TEXT, "
            "status TEXT NOT NULL DEFAULT 'open', closed_at TEXT, resolution TEXT, public_note TEXT)",
            "CREATE INDEX IF NOT EXISTS wts_reports_open ON wts_reports (closed_at, at)",
        )),
        Migration(31, "statements", (
            "CREATE TABLE IF NOT EXISTS wts_statements (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, "
            "item TEXT NOT NULL, part TEXT NOT NULL DEFAULT '', about TEXT, name TEXT NOT NULL, role TEXT NOT NULL, "
            "text TEXT NOT NULL, link TEXT, email TEXT, status TEXT NOT NULL DEFAULT 'pending', published_at TEXT, "
            "updated_at TEXT, closed_at TEXT, reason TEXT)",
            "CREATE INDEX IF NOT EXISTS wts_statements_item ON wts_statements (status, item)",
            "CREATE INDEX IF NOT EXISTS wts_statements_about ON wts_statements (status, about)",
        )),
        Migration(32, "statement_log", (
            "CREATE TABLE IF NOT EXISTS wts_statement_log (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "statement INTEGER NOT NULL, at TEXT NOT NULL, action TEXT NOT NULL, note TEXT, previous TEXT)",
            "CREATE INDEX IF NOT EXISTS wts_statement_log_statement ON wts_statement_log (statement, id)",
        )),
        Migration(33, "hidden", (
            "CREATE TABLE IF NOT EXISTS wts_hidden (id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT NOT NULL, "
            "at TEXT NOT NULL, note TEXT NOT NULL, shown_at TEXT)",
            "CREATE INDEX IF NOT EXISTS wts_hidden_item ON wts_hidden (item, shown_at)",
        )),
        Migration(34, "reply_counts", (
            "CREATE TABLE IF NOT EXISTS wts_reply_counts (day TEXT NOT NULL, visitor TEXT NOT NULL, "
            "what TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (day, visitor, what))",
        )),
    )
