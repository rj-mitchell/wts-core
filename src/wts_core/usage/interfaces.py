"""The storage interfaces of this module that ``wts_core.ports`` does not have yet, and the values they pass.

One small interface per need (ADR 0002): saved briefings, notes of failures, and the figures the owner's reports
are made from. The SQLite versions are beside this file; another database means writing these few methods again.
Like ``ports``, this file imports nothing from the rest of the package, so it can be moved there whole.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "AccountSpending",
    "BriefingListing",
    "DaySpending",
    "FailureLog",
    "SavedBriefing",
    "SavedBriefings",
    "SpendingFigures",
    "SpendingTotals",
]

# ---- saved briefings -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SavedBriefing:
    """A briefing kept at its own address: the record of what the site published.

    ``options`` is what the reader chose (Where MPs Stand calls it ``settings``); ``events`` is the site's own
    list of reader events, exactly as it was given; ``extra`` holds what only one site keeps (Where MPs Stand's
    ``records_up_to`` and ``model``).
    """

    id: str
    created_at: str
    question: str
    options: dict[str, Any]
    events: list[dict[str, Any]]
    extra: dict[str, Any] = field(default_factory=dict)
    withdrawn_at: str | None = None
    withdrawn_reason: str | None = None


@dataclass(frozen=True)
class BriefingListing:
    """A saved briefing without its contents: for the corrections page and the owner's list."""

    id: str
    created_at: str
    question: str
    withdrawn_at: str | None
    withdrawn_reason: str | None


class SavedBriefings(Protocol):
    def new_id(self) -> str: ...

    def save(self, question: str, options: Mapping[str, Any], events: Sequence[Mapping[str, Any]], *,
             id: str | None = None, extra: Mapping[str, Any] | None = None) -> SavedBriefing:
        """Keep a briefing and return it as kept: under ``id``, or under another if that one is taken."""
        ...

    def get(self, id: str) -> SavedBriefing | None: ...

    def withdraw(self, id: str, reason: str) -> bool: ...

    def withdrawn(self) -> list[BriefingListing]: ...

    def recent(self, limit: int = 50) -> list[BriefingListing]: ...


# ---- notes of failures -----------------------------------------------------------------------------------------


class FailureLog(Protocol):
    def note(self, kind: str, question: str | None, error: str) -> None: ...

    def recent(self, limit: int | None = 20, *, since: str | None = None) -> list[dict[str, Any]]:
        """The newest first, each with ``at``, ``kind``, ``question`` and ``error``."""
        ...


# ---- the figures the owner's reports are made from -------------------------------------------------------------


@dataclass(frozen=True)
class SpendingTotals:
    """What was spent since a time: the cost, every model call, the briefings among them (rows of kind ``answer``)
    and how many different visitors' codes they carry. Nothing is rounded: the site rounds what it shows."""

    spent_usd: float
    calls: int
    briefings: int
    visitors: int


@dataclass(frozen=True)
class DaySpending:
    day: str  # YYYY-MM-DD, UTC
    spent_usd: float
    calls: int
    briefings: int


@dataclass(frozen=True)
class AccountSpending:
    """One line of the owner's report of who the spending was for: a signed-in account; or, with no account, the
    public (``public``: the rows carry a visitor's code) or the site's own work (neither an account nor a code)."""

    account: int | None
    public: bool
    spent_usd: float
    calls: int
    visitors: int


class SpendingFigures(Protocol):
    def totals(self, since: str) -> SpendingTotals: ...

    def by_day(self, since: str) -> list[DaySpending]: ...

    def by_account(self, since: str) -> list[AccountSpending]: ...
