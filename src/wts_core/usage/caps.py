"""The limits on new briefings: each visitor's (or account's) for the day, and the site's spending for the day and
the month.

A refusal is never an error to the reader: the site shows the sources it found, with the refusal's message as a
note. The order is today's on every site: the account's or the visitor's daily limit, then today's spending, then
the month's. Every comparison is ``>=``: a visitor with a limit of 40 gets 40 briefings, spending equal to a cap
stops briefings, and a cap of 0 stops them all.

The package has no limits and no wording of its own: the limits come from the site's ``[usage]`` settings and
every message from its ``Messages``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from wts_core.ports import SYSTEM_CLOCK, Busy, Clock, SpendingRecord
from wts_core.settings import Messages, SettingsError

__all__ = ["Caps", "Limits", "Refusal", "busy_refusal"]


@dataclass(frozen=True)
class Refusal:
    """Why a briefing won't be written now, and the site's words for it."""

    kind: Literal["visitor_limit", "account_limit", "daily_cap", "monthly_cap", "busy_visitor", "busy_site"]
    message: str


def busy_refusal(busy: Busy, messages: Messages) -> Refusal:
    """The refusal for too many briefings in progress (``BriefingsInProgress.start``), in the site's words."""
    if busy.reason == "visitor":
        return Refusal("busy_visitor", messages.busy_visitor)
    return Refusal("busy_site", messages.busy_site)


@dataclass(frozen=True)
class Limits:
    """A site's limits on new briefings. ``per_account_daily`` is for a site with signed-in accounts (only Where
    MPs Stand today); the others give ``None``."""

    per_visitor_daily: int
    per_account_daily: int | None
    daily_cap_usd: float
    monthly_cap_usd: float

    @classmethod
    def from_settings(cls, usage: Mapping[str, Any], *, section: str = "usage") -> Limits:
        """Read the limits from a site's ``[usage]`` section, under today's keys. Each site's copy fell back to a
        figure in its code when a key was missing; here a missing one stops the site, naming it."""
        keys = ("per_visitor_daily_questions", "daily_spend_cap_usd", "monthly_spend_cap_usd")
        missing = [k for k in keys if k not in usage]
        if missing:
            raise SettingsError(f"[{section}] needs " + ", ".join(missing) + ": the package has no limits of its own")
        try:
            per_account = usage.get("per_user_daily_questions")
            return cls(per_visitor_daily=int(usage["per_visitor_daily_questions"]),
                       per_account_daily=None if per_account is None else int(per_account),
                       daily_cap_usd=float(usage["daily_spend_cap_usd"]),
                       monthly_cap_usd=float(usage["monthly_spend_cap_usd"]))
        except (TypeError, ValueError) as exc:
            raise SettingsError(f"[{section}] has a limit that is not a number: {exc}") from None


class Caps:
    """Whether another briefing may be written now."""

    def __init__(self, spending: SpendingRecord, limits: Limits, messages: Messages,
                 clock: Clock = SYSTEM_CLOCK) -> None:
        if messages.account_daily_limit is not None and limits.per_account_daily is None:
            raise SettingsError("a site with signed-in accounts needs their daily limit: "
                                "[usage] per_user_daily_questions")
        if limits.per_account_daily is not None and messages.account_daily_limit is None:
            raise SettingsError("a daily limit for signed-in accounts needs its message: "
                                "Messages.account_daily_limit")
        self._spending = spending
        self._limits = limits
        self._messages = messages
        self._clock = clock

    def refusal(self, *, visitor: str | None, account: int | None = None,
                pending_usd: float = 0.0) -> Refusal | None:
        """Why this person may not have another briefing written now, or ``None``. ``pending_usd`` is the
        estimated cost of briefings being written at this moment, whose cost is not recorded yet. A signed-in
        account is counted by its own limit and not as a visitor; with neither, only the site's spending is
        checked."""
        limits, messages = self._limits, self._messages
        if account is not None:
            if limits.per_account_daily is None or messages.account_daily_limit is None:
                raise ValueError("this site has no daily limit for signed-in accounts")
            if self._spending.briefings_today(account=account) >= limits.per_account_daily:
                return Refusal("account_limit", messages.account_daily_limit)
        elif visitor is not None and self._spending.briefings_today(visitor=visitor) >= limits.per_visitor_daily:
            return Refusal("visitor_limit", messages.visitor_daily_limit)
        return self.site_paused(pending_usd)

    def site_paused(self, pending_usd: float = 0.0) -> Refusal | None:
        """Why new briefings are paused for everyone (a spending cap reached), or ``None``: for the status page."""
        now = self._clock.now()
        if self._spending.spent_since(now.strftime("%Y-%m-%d")) + pending_usd >= self._limits.daily_cap_usd:
            return Refusal("daily_cap", self._messages.daily_cap)
        if self._spending.spent_since(now.strftime("%Y-%m")) + pending_usd >= self._limits.monthly_cap_usd:
            return Refusal("monthly_cap", self._messages.monthly_cap)
        return None
