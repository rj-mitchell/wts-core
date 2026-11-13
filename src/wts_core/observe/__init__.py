"""The record of each briefing, and what is made of it: structured logs, statistics, the weekly report and alerts
(ADR 0012).

New on every site: nothing here replaces a site's code. The briefing desk writes one ``ports.BriefingRecord`` a
question through ``SqliteBriefingLog``; ``stats`` turns the records into the figures the owner asked for, each
beside the weeks before; ``weekly_report`` saves them; ``tripped`` says what got worse than the owner allows.

**Nothing about a reader is stored or logged.** The record has no visitor code, no address and nothing from a
request's headers; a later question is never linked to an earlier one; the structured log cannot write a question
or any text of a briefing. How long things are kept is the owner's decision of 13 November 2026
(``OWNER_ACCEPTED``): a row for 13 months, the question of a failed briefing for 90 days.

Nothing here imports an outside library, or anything from ``wts_core.replies`` or ``wts_core.adapters``.
"""

from wts_core.observe.config import config_id
from wts_core.observe.log import (
    OWNER_ACCEPTED,
    Retention,
    SqliteBriefingLog,
    Tidied,
    count,
    counts,
    migrations,
    save_week,
    weeks,
)
from wts_core.observe.logging import FIELDS, LOGGER, json_logging, log_event
from wts_core.observe.report import ALERTS, MARGIN, proposed_thresholds, tidy_reports, tripped, weekly_report
from wts_core.observe.stats import (
    PROPORTIONS,
    ArmComparison,
    BriefingHistory,
    Figures,
    Headline,
    Stats,
    stats,
    two_proportion_test,
)

__all__ = [
    "ALERTS",
    "FIELDS",
    "LOGGER",
    "MARGIN",
    "OWNER_ACCEPTED",
    "PROPORTIONS",
    "ArmComparison",
    "BriefingHistory",
    "Figures",
    "Headline",
    "Retention",
    "SqliteBriefingLog",
    "Stats",
    "Tidied",
    "config_id",
    "count",
    "counts",
    "json_logging",
    "log_event",
    "migrations",
    "proposed_thresholds",
    "save_week",
    "stats",
    "tidy_reports",
    "tripped",
    "two_proportion_test",
    "weekly_report",
    "weeks",
]
