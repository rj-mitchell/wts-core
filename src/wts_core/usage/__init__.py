"""Limits, cost and caps: what stands between a question and a briefing that costs money.

The per-minute limiter, the visitor's code, prices and cost, the spending record, the daily and monthly caps, the
briefings in progress, the answer cache, saved briefings and notes of failures. Each was written out by hand in
Where MPs Stand, Where Countries Stand and Where Councils Stand, alike but for their limits, messages and table
shapes (``docs/study/usage-state-stream.md``, sections 1 and 2): here the shared rules are written once, and every
limit, price and message is the site's own, passed in.

Nothing here imports an outside library; everything stored is in the ``wts_`` tables that ``migrations()`` makes.
"""

from wts_core.usage.briefings import BriefingArchive, alphabet_id, token_id
from wts_core.usage.cache import SqliteAnswerCache, cache_key
from wts_core.usage.caps import Caps, Limits, Refusal, busy_refusal
from wts_core.usage.failures import Failures
from wts_core.usage.inprogress import BriefingsInProgress
from wts_core.usage.interfaces import (
    AccountSpending,
    BriefingListing,
    DaySpending,
    FailureLog,
    SavedBriefing,
    SavedBriefings,
    SpendingFigures,
    SpendingTotals,
)
from wts_core.usage.limiter import RateLimiter
from wts_core.usage.pricing import PriceTable
from wts_core.usage.spending import Spending
from wts_core.usage.tables import migrations
from wts_core.usage.visitor import client_address, network_of, visitor_code

__all__ = [
    "AccountSpending",
    "BriefingArchive",
    "BriefingListing",
    "BriefingsInProgress",
    "Caps",
    "DaySpending",
    "FailureLog",
    "Failures",
    "Limits",
    "PriceTable",
    "RateLimiter",
    "Refusal",
    "SavedBriefing",
    "SavedBriefings",
    "SpendingFigures",
    "SpendingTotals",
    "Spending",
    "SqliteAnswerCache",
    "alphabet_id",
    "busy_refusal",
    "cache_key",
    "client_address",
    "migrations",
    "network_of",
    "token_id",
    "visitor_code",
]
