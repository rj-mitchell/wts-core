"""Readers' reports, statements under the right of reply, the corrections log, and hiding an item while a concern
is decided: the charity's impartiality policy, section 7, for all four sites (ADR 0008).

The package owns the rules and the data; a site owns addresses, pages and wording. A site passes in:

* ``Items``: where a statement may sit. Given what someone pasted it returns the ``Item`` (its address, whom it is
  about), or refuses in the site's words; and it says whether the item exists and is still shown.
* ``ReplyRules``: its limits, where the sites differ today (the least words, the most characters, the daily
  limits, the report kinds its forms send and what each is stored as).
* ``ReplyMessages``: every word a sender or reader can be shown.

and gets ``Replies``: ``submit``, ``published``, ``publish``, ``decline``, ``update``, ``withdraw``, ``remove``,
``statements``, ``log``; ``report``, ``reports``, ``close``; ``corrections``; ``hide``, ``unhide``, ``hidden``;
``waiting``; ``forget_old_emails`` and ``lapse_undecided``. A refusal for a sender is ``Refused`` (the site's
words; the site chooses the HTTP status and shape); something the owner asked for that can't be done is
``NotDone``.

Where the four sites' builds of 12 November 2026 differed by accident, the best copy's behaviour is taken
(docs/study/reports-statements.md, section 3):

* statuses and what may follow what: Where Countries Stand's (declined only while waiting), with a fifth status,
  ``removed``, for a statement the site takes down, which no site had;
* the log of every action, and the required note of how the sender was confirmed: Where Landlords Stand's. The
  old words are kept when a statement is updated, which no site did;
* text cleaned, and the link's rule: Where MPs Stand's. Name and role: Where Countries Stand's ``check_line``.
  Too long is refused, never cut: Where Countries Stand's and Where Councils Stand's;
* the item must exist and still be shown: Where Countries Stand's;
* the trap field and the daily limit per visitor: Where MPs Stand's, with the count kept apart from the report
  or statement, in a table emptied each day, so that nothing is tied to a sender;
* both dates kept and the later shown: Where Landlords Stand's;
* the sum for three months, Where Countries Stand's; deleted with whatever else names the sender, as Where MPs
  Stand cleared its visitor code;
* a report's outcome, private note and public note, and the corrections log: Where MPs Stand's. Takedown
  requests listed first: Where Landlords Stand's, in Where MPs Stand's newest-first order;
* the link's ``rel`` and its scheme checked again when shown: Where MPs Stand's.

A statement is never part of the record. This module imports nothing from ``wts_core.checks``, ``briefing``,
``observe``, ``eval`` or ``adapters``, and they import nothing from it (tests/test_walls.py): there is no path
from a statement to a model request, the index or a briefing.
"""

from __future__ import annotations

from wts_core.replies.days import months_before, working_days_between
from wts_core.replies.desk import Replies, Waiting
from wts_core.replies.markup import long_date, statement_html
from wts_core.replies.rules import (
    PUBLIC_FIELDS,
    REPORT_OUTCOMES,
    STATUSES,
    TAKEDOWN,
    Item,
    Items,
    NotDone,
    Refused,
    ReplyMessages,
    ReplyRules,
    StatementStatus,
    safe_link,
    word_count,
)
from wts_core.replies.tables import migrations

__all__ = [
    "PUBLIC_FIELDS",
    "REPORT_OUTCOMES",
    "STATUSES",
    "TAKEDOWN",
    "Item",
    "Items",
    "NotDone",
    "Refused",
    "Replies",
    "ReplyMessages",
    "ReplyRules",
    "StatementStatus",
    "Waiting",
    "long_date",
    "migrations",
    "months_before",
    "safe_link",
    "statement_html",
    "word_count",
    "working_days_between",
]
