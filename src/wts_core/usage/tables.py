"""The tables this module keeps in a site's state database (ADR 0005), as numbered migrations (10 to 19).

One shape for what the sites' own tables hold in three:

- ``wts_spending``: one row a model call. Token counts as the sites store them today (input includes the cache
  writes). ``account`` is Where MPs Stand's ``user_id``. The visitor's code, the account and the time of day are
  kept on a row for its own day only (``spending.forget_earlier_days``): each account's totals are kept by the
  calendar month in ``wts_account_months``.
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
        # how many different visitors, kept when their codes are forgotten (``forget_earlier_days``): for each
        # past day under ``who`` "*"; and the public's for each month, under ``who`` "" with the month
        # (``YYYY-MM``) where the day would be
        Migration(14, "visitor_days", (
            "CREATE TABLE IF NOT EXISTS wts_visitor_days (day TEXT NOT NULL, who TEXT NOT NULL, "
            "visitors INTEGER NOT NULL, PRIMARY KEY (day, who))",
        )),
        # What each signed-in account's model calls came to in each calendar month: how many, their cost to the
        # cent, and how many visitors' codes it was seen with. Kept when the account is taken off the spending
        # rows themselves, and all that is kept about an account and a time gone by: nothing by the day.
        # The last three statements are for a database that 0.2.x has written to, which counted the public's and
        # each account's visitors by the day: they are gathered into months, and the days' own rows deleted.
        Migration(15, "account_months", (
            "CREATE TABLE IF NOT EXISTS wts_account_months (month TEXT NOT NULL, account INTEGER NOT NULL, "
            "cost_usd REAL NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0, "
            "visitors INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (month, account))",
            "INSERT INTO wts_account_months (month, account, visitors) SELECT substr(day, 1, 7), "
            "CAST(who AS INTEGER), sum(visitors) FROM wts_visitor_days WHERE who NOT IN ('*', '') "
            "AND length(day) = 10 GROUP BY 1, 2 ON CONFLICT(month, account) DO UPDATE SET "
            "visitors = visitors + excluded.visitors",
            "INSERT INTO wts_visitor_days (day, who, visitors) SELECT substr(day, 1, 7), '', sum(visitors) "
            "FROM wts_visitor_days WHERE who = '' AND length(day) = 10 GROUP BY 1 "
            "ON CONFLICT(day, who) DO UPDATE SET visitors = visitors + excluded.visitors",
            "DELETE FROM wts_visitor_days WHERE who != '*' AND length(day) = 10",
        )),
        # Cuts the time of day from model calls of past days in an older database; after this,
        # ``forget_earlier_days`` does it when each day is over. A migration has no clock but SQLite's own
        # (the real date, in UTC): the package's ``Clock`` is not asked. On a server the two are the same day.
        # They differ only where a test stands another clock in: with a clock set to a day before the real
        # one, this cuts rows that are "today's" by the test's clock (their day, visitor and account are
        # untouched, and the daily limits and caps count as before: only a period that begins part-way through
        # that day is affected); with a clock set after the real day, it leaves rows the first forgetting then
        # cuts. It runs once.
        Migration(16, "spending_to_the_day", (
            "UPDATE wts_spending SET at = substr(at, 1, 10) || 'T00:00:00+00:00' WHERE at < date('now') "
            "AND at != substr(at, 1, 10) || 'T00:00:00+00:00' "
            "AND at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]?*'",
        )),
    )
