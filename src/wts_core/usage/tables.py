"""The tables this module keeps in a site's state database (ADR 0005), as numbered migrations (10 to 19).

One shape for what the sites' own tables hold in three:

- ``wts_spending``: one row a model call. Token counts as the sites store them today (input includes the cache
  writes). ``account`` is Where MPs Stand's ``user_id``.
- ``wts_answer_cache``: the replay of a briefing under the key of its question (Where Councils Stand's ``at`` is
  ``created_at`` here).
- ``wts_briefings``: every briefing kept at its own address. ``options`` is Where MPs Stand's ``settings``;
  ``extra`` is a JSON object for the columns only one site has (its ``records_up_to`` and ``model``).
- ``wts_failures``: notes of briefings that failed, for the owner.

A site's import must give every ``NOT NULL`` column a value (``coalesce(…)`` where its old column allowed none).
"""

from __future__ import annotations

from wts_core.state import Migration

__all__ = ["migrations"]


def migrations() -> tuple[Migration, ...]:
    """This module's tables, to pass to ``StateDB(path, migrations=…)`` with the other modules'."""
    return (
        Migration(10, "spending", (
            "CREATE TABLE IF NOT EXISTS wts_spending (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, "
            "kind TEXT NOT NULL, model TEXT, visitor TEXT, account INTEGER, "
            "input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, "
            "cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0, "
            "cost_usd REAL NOT NULL DEFAULT 0)",
            "CREATE INDEX IF NOT EXISTS wts_spending_at ON wts_spending (at)",
            "CREATE INDEX IF NOT EXISTS wts_spending_visitor_at ON wts_spending (visitor, at)",
            "CREATE INDEX IF NOT EXISTS wts_spending_account_at ON wts_spending (account, at)",
        )),
        Migration(11, "answer_cache", (
            "CREATE TABLE IF NOT EXISTS wts_answer_cache (key TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
            "events TEXT NOT NULL)",
        )),
        Migration(12, "briefings", (
            "CREATE TABLE IF NOT EXISTS wts_briefings (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
            "question TEXT NOT NULL, options TEXT NOT NULL, events TEXT NOT NULL, extra TEXT NOT NULL DEFAULT '{}', "
            "withdrawn_at TEXT, withdrawn_reason TEXT)",
            "CREATE INDEX IF NOT EXISTS wts_briefings_created ON wts_briefings (created_at)",
        )),
        Migration(13, "failures", (
            "CREATE TABLE IF NOT EXISTS wts_failures (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, "
            "kind TEXT NOT NULL, question TEXT, error TEXT NOT NULL)",
        )),
    )
