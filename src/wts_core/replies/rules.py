"""What a statement or a report may be: the limits a site sets, the words it refuses with, and the checks.

The checks are the best copy's of each rule (docs/study/reports-statements.md, section 3): the text is cleaned as
Where MPs Stand does (line endings and runs of blank lines, nothing else), words are counted as every site counts
them (``len(text.split())``), a name and a role are checked as Where Countries Stand's ``check_line`` does (on one
line, never blank), a link by Where MPs Stand's rule (a full web address with no quotes, angle brackets or spaces),
and the email address by the pattern all four share. What is too long is refused, never cut to fit: a statement is
published as written or declined (the impartiality policy, 7.2).

Everything that differs between the sites today is a field of ``ReplyRules`` with no default, and every word a
sender can be shown is a field of ``ReplyMessages``: the package has no wording of its own for a sender.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Literal, Protocol
from urllib.parse import urlsplit

__all__ = [
    "PUBLIC_FIELDS",
    "REPORT_OUTCOMES",
    "STATUSES",
    "TAKEDOWN",
    "Item",
    "Items",
    "NotDone",
    "Refused",
    "ReplyMessages",
    "ReplyRules",
    "StatementStatus",
    "check_email",
    "check_line",
    "check_link",
    "check_text",
    "clean_text",
    "safe_link",
    "word_count",
]

type StatementStatus = Literal["pending", "published", "declined", "withdrawn", "removed"]
# received -> published, or declined (never shown); published -> withdrawn (its author asked) or removed (the site
# took it down for breaking the rules). Five, so the log always says what happened (ADR 0008).
STATUSES: tuple[str, ...] = ("pending", "published", "declined", "withdrawn", "removed")
# how a report is closed, as Where MPs Stand records it: put right, or looked at and nothing to do
REPORT_OUTCOMES: tuple[str, ...] = ("resolved", "dismissed")
# the kind every site stores for a request to remove a person's name or details: dealt with first (policy 7.1)
TAKEDOWN = "takedown"
# What the public may see of a statement. Never the address used to confirm the sender, the reason it ended, the
# owner's notes or the log. ``date`` is the date of the words shown: the later of publishing and the last update.
PUBLIC_FIELDS: tuple[str, ...] = ("id", "item", "part", "about", "name", "role", "text", "link", "date")

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SAFE_LINK = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


class Refused(ValueError):
    """What was sent can't be accepted. The message is the site's, for the sender; the site turns it into its own
    HTTP status and shape. ``why`` names the rule that was broken (the field of ``ReplyMessages`` the words came
    from, such as ``too_many_words`` or ``daily_statements``), so a site can answer a daily limit differently from
    a mistake in the form."""

    def __init__(self, message: str, why: str = "") -> None:
        super().__init__(message)
        self.why = why


class NotDone(ValueError):
    """Something the owner asked for can't be done: no such statement, the wrong status for the action, a reason
    or note that is missing. The message is for the owner, never for a reader, and the commands print it and exit 1."""


@dataclass(frozen=True)
class Item:
    """Something on a site that a statement can sit beside. ``address`` is the item's address as the site files it
    (``/people/10669``, ``/b/AbC123xy``, ``/votes/E08000016:1:10:0``, ``landlords/example-housing/``); ``about`` is
    the member, country, council or landlord it concerns, as text, when the address says so; ``part`` is a part of
    the page (Where Landlords Stand's "grade", "bands", "ombudsman" or "safety"), or empty."""

    address: str
    about: str | None = None
    part: str = ""


class Items(Protocol):
    """Where a statement may sit: the one thing about statements that is wholly a site's own."""

    def resolve(self, pasted: str) -> Item:
        """The item at what someone pasted (a full address or a path). Raises ``Refused``, with the site's words
        for the sender, when it isn't the address of something a statement can sit beside."""
        ...

    def shown(self, item: Item) -> bool:
        """Whether the item exists and has not been withdrawn. A site with more exact words for one case (no such
        briefing, a withdrawn one) may raise ``Refused`` with them instead of answering False. Whether the item
        is hidden while a concern is decided is the package's own record, and is checked as well."""
        ...


@dataclass(frozen=True, kw_only=True)
class ReplyRules:
    """A site's limits. Only what is the same on all four sites today has a default."""

    min_words: int  # 5 on Where MPs Stand, 3 on Where Landlords Stand, 1 elsewhere
    max_chars: int  # of a statement's text, however few its words: 1,500 or 2,000
    name_max: int
    role_max: int
    link_max: int
    email_max: int
    daily_statements: int  # per visitor code, per day
    daily_reports: int
    about_required: bool  # can a statement be published before it is known whom it speaks for? (Landlords: no)
    report_kinds: Mapping[str, str]  # the words a form or link may send -> the kind that is stored
    report_kind_required: bool  # a word not in report_kinds: refused, or (Landlords) kept with no kind
    report_min: int  # characters of a report's message
    report_max: int
    page_max: int  # the address a report is about is the browser's, not the sender's words: cut to this
    contact_max: int
    max_words: int = 150  # the policy's figure, the same everywhere; the trustees may change it
    email_kept_months: int = 3  # after a statement ends, or while nothing is decided (the privacy notices)


@dataclass(frozen=True, kw_only=True)
class ReplyMessages:
    """Every word of this feature that a sender or reader can be shown: one field for each refusal, then the words
    a statement is shown with. A site supplies all of them. A template's placeholders are filled with
    ``str.format``: ``{max}`` is the limit that was passed, ``{n}`` what was sent, ``{words}`` the word limit.
    A template that asks for anything else stops the site when it starts, naming the field."""

    too_few_words: str
    too_many_words: str  # {max}, {n}
    too_many_chars: str  # {words}, {max}, {n}
    name_missing: str
    name_too_long: str  # {max}, {n}
    role_missing: str
    role_too_long: str  # {max}, {n}
    bad_link: str
    link_too_long: str  # {max}, {n}
    bad_email: str
    item_not_shown: str  # nothing at that address, or it has been withdrawn or is hidden
    daily_statements: str
    daily_reports: str
    report_kind: str
    report_too_short: str
    report_too_long: str  # {max}, {n}
    contact_too_long: str  # {max}, {n}
    lapsed: str  # the reason recorded for a statement nobody decided in time; its sender is told if they ask
    heading: str  # the glossary's "Statement from {name}, {date}"
    disclaimer: str  # the glossary's "In their own words. Not checked or endorsed by {site}."
    record_link: str  # the words of the link to the record; {link} is the address, if a site shows it
    site: str  # the site's name, for the disclaimer

    def __post_init__(self) -> None:
        sample: dict[str, object] = {"max": 1, "n": 2, "words": 3, "name": "", "date": "", "site": "", "link": ""}
        for field in fields(self):
            try:
                getattr(self, field.name).format(**sample)
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError(f"ReplyMessages.{field.name} can't be filled in: {exc!r}. Its placeholders are "
                                 "{max}, {n}, {words}, {name}, {date}, {site} and {link}; write a brace that is "
                                 "meant as one twice.") from None


# ---- the checks ------------------------------------------------------------------------------------------------


def word_count(text: str) -> int:
    return len(text.split())


def clean_text(text: str | None) -> str:
    """Line endings made plain and runs of blank lines closed up; the words themselves are never changed."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def check_text(text: str | None, rules: ReplyRules, messages: ReplyMessages) -> str:
    """A statement's words, as written, or ``Refused`` if there are too few or too many. Never cut."""
    cleaned = clean_text(text)
    words = word_count(cleaned)
    if words < max(rules.min_words, 1):
        raise Refused(messages.too_few_words, "too_few_words")
    if words > rules.max_words:
        raise Refused(messages.too_many_words.format(max=rules.max_words, n=words), "too_many_words")
    if len(cleaned) > rules.max_chars:  # so a wall of text without spaces is refused too
        raise Refused(messages.too_many_chars.format(words=rules.max_words, max=rules.max_chars, n=len(cleaned)),
                      "too_many_chars")
    return cleaned


def check_line(value: str | None, longest: int, missing: str, too_long: str, why: str) -> str:
    """A name or role, on one line: spaces around and within are tidied, and it is never blank or only spaces."""
    line = " ".join((value or "").split())
    if len(line) < 2:
        raise Refused(missing, f"{why}_missing")
    if len(line) > longest:
        raise Refused(too_long.format(max=longest, n=len(line)), f"{why}_too_long")
    return line


def check_link(link: str | None, rules: ReplyRules, messages: ReplyMessages) -> str | None:
    """A link to the record, or None when none was given: a full web address, with nothing in it that could break
    out of a link's markup (quotes, angle brackets, spaces)."""
    link = (link or "").strip()
    if not link:
        return None
    if len(link) > rules.link_max:
        raise Refused(messages.link_too_long.format(max=rules.link_max, n=len(link)), "link_too_long")
    try:
        parts = urlsplit(link)
        sound = parts.scheme in ("http", "https") and bool(parts.hostname)
    except ValueError:  # brackets that aren't an address
        sound = False
    if not sound or re.search(r"[\s\"'<>]", link):
        raise Refused(messages.bad_link, "bad_link")
    return link


def safe_link(link: str | None) -> str | None:
    """A stored link as it may be shown: checked again (as Where MPs Stand's pages do), so a row that reached the
    database some other way than the form can never become a link that runs a script."""
    return link if link and _SAFE_LINK.fullmatch(link) else None


def check_email(email: str | None, rules: ReplyRules, messages: ReplyMessages) -> str:
    email = (email or "").strip()
    if not _EMAIL.match(email) or len(email) > rules.email_max:
        raise Refused(messages.bad_email, "bad_email")
    return email
