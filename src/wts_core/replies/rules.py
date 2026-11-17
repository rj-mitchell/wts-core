"""What a statement or a report may be: the limits a site sets, the words it refuses with, and the checks.

The checks are the best copy's of each rule: the text is cleaned as
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
from dataclasses import dataclass, field, fields
from typing import Literal, Protocol
from urllib.parse import urlsplit

__all__ = [
    "FORM_FIELDS",
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
    "too_long",
    "unreachable",
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

# The fields a site's own form may already hold to a length, each with the limit of ``ReplyRules`` it is checked
# against and the message of ``ReplyMessages`` said when it is too long (``ReplyRules.form_max``).
FORM_FIELDS: Mapping[str, tuple[str, str]] = {
    "text": ("max_chars", "too_many_chars"), "name": ("name_max", "name_too_long"),
    "role": ("role_max", "role_too_long"), "link": ("link_max", "link_too_long"),
    "report": ("report_max", "report_too_long"), "contact": ("contact_max", "contact_too_long"),
}

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
    # The most characters the site's own form (its request body) lets through for a field, where it has a limit
    # of its own: any of "text", "name", "role", "link", "report", "contact" (``FORM_FIELDS``). Where the form's
    # limit is no more than the rule's, the rule's "too long" message can never be said, and the site may leave
    # it out of its ``ReplyMessages``: see there.
    form_max: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = sorted(set(self.form_max) - set(FORM_FIELDS))
        if unknown:
            raise ValueError(f"ReplyRules.form_max names {', '.join(unknown)}: the fields a form may limit are "
                             + ", ".join(FORM_FIELDS))


@dataclass(frozen=True, kw_only=True)
class ReplyMessages:
    """Every word of this feature that a sender or reader can be shown: one field for each refusal, then the words
    a statement is shown with. A site supplies all of them. A template's placeholders are filled with
    ``str.format``: ``{max}`` is the limit that was passed, ``{n}`` what was sent, ``{words}`` the word limit.
    A template that asks for anything else stops the site when it starts, naming the field.

    Six messages may be left out, and only where they can never be said. A site whose own form already holds
    a field to a length no greater than the rule's (its request body refuses a name of more than 120 characters
    before the package sees it) would otherwise write a sentence for a refusal no sender can meet. It says what
    its form allows in ``ReplyRules.form_max``, and may then leave that field's "too long" message as None.
    ``Replies`` checks the two against each other when the site starts: a message left out for a field the form
    does not hold to the rule's limit stops the site, naming the message. The package still has no words of its
    own for a sender: where a message is missing there is, by the site's own account, nothing to say. (Should
    the account be wrong and the rule be reached all the same, that is a fault in the site, raised as
    ``RuntimeError`` and answered by its route as any fault is; it is never put to a sender in words the site
    did not choose.)

    ``item_hidden`` may be left out too: it is what a sender is told when the item is hidden while a concern
    about it is decided, where a site wants other words for that than for an item that is not there. Without it
    ``item_not_shown`` serves for both."""

    too_few_words: str
    too_many_words: str  # {max}, {n}
    name_missing: str
    role_missing: str
    bad_link: str
    bad_email: str
    item_not_shown: str  # nothing at that address, or it has been withdrawn (or is hidden, with no item_hidden)
    daily_statements: str
    daily_reports: str
    report_kind: str
    report_too_short: str
    lapsed: str  # the reason recorded for a statement nobody decided in time; its sender is told if they ask
    heading: str  # the glossary's "Statement from {name}, {date}"
    disclaimer: str  # the glossary's "In their own words. Not checked or endorsed by {site}."
    record_link: str  # the words of the link to the record; {link} is the address, if a site shows it
    site: str  # the site's name, for the disclaimer
    # the six that a site's own form limits may make unreachable (see above), each None only then
    too_many_chars: str | None = None  # {words}, {max}, {n}
    name_too_long: str | None = None  # {max}, {n}
    role_too_long: str | None = None  # {max}, {n}
    link_too_long: str | None = None  # {max}, {n}
    report_too_long: str | None = None  # {max}, {n}
    contact_too_long: str | None = None  # {max}, {n}
    item_hidden: str | None = None  # the item is hidden while a concern about it is decided

    def __post_init__(self) -> None:
        sample: dict[str, object] = {"max": 1, "n": 2, "words": 3, "name": "", "date": "", "site": "", "link": ""}
        for field in fields(self):  # noqa: F402 (the dataclass's own name for one of its fields)
            if getattr(self, field.name) is None:
                continue
            try:
                getattr(self, field.name).format(**sample)
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError(f"ReplyMessages.{field.name} can't be filled in: {exc!r}. Its placeholders are "
                                 "{max}, {n}, {words}, {name}, {date}, {site} and {link}; write a brace that is "
                                 "meant as one twice.") from None


# The checks


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
        raise Refused(too_long(messages, "too_many_chars").format(words=rules.max_words, max=rules.max_chars,
                                                                 n=len(cleaned)), "too_many_chars")
    return cleaned


class LeftOut(RuntimeError):
    """A "too long" message the site left out as unreachable has been reached. From a sender's form it is a
    fault in the site (the form let through more than the site said it would), and is raised as one: never a
    refusal in words the site did not choose. From the owner's own command it is no fault at all, since the
    owner's words come through no form: ``Replies.update`` turns it into ``NotDone``, in words for the owner."""

    def __init__(self, name: str) -> None:
        super().__init__(f"ReplyMessages.{name} was left out as a refusal no sender could meet, and one has met "
                         "it: the site's form lets through more than its ReplyRules.form_max says. Give the "
                         "message, or mend the form's limit")
        self.name = name


def too_long(messages: ReplyMessages, name: str) -> str:
    """One of the six "too long" messages, which a site may have left out as unreachable. Reached all the same,
    ``LeftOut`` is raised (a ``RuntimeError``)."""
    said: str | None = getattr(messages, name)
    if said is None:
        raise LeftOut(name)
    return said


def unreachable(rules: ReplyRules, messages: ReplyMessages) -> list[str]:
    """What is wrong with the "too long" messages a site left out, each in a sentence for the owner: a message
    may be None only where the site's form holds its field to no more than the rule's limit."""
    problems: list[str] = []
    for part, (limit, message) in FORM_FIELDS.items():
        if getattr(messages, message) is not None:
            continue
        allowed, form = getattr(rules, limit), rules.form_max.get(part)
        if form is None:
            problems.append(f"ReplyMessages.{message} is not given: give it, or say in ReplyRules.form_max how "
                            f"many characters the site's own form lets through for \"{part}\" (no more than "
                            f"{limit}, {allowed}, and the message can never be needed)")
        elif form > allowed:
            problems.append(f"ReplyMessages.{message} is not given, and the site's form lets through {form} "
                            f"characters for \"{part}\" where ReplyRules.{limit} allows {allowed}: a sender can "
                            "meet the refusal, so it needs its words")
    return problems


def check_line(value: str | None, longest: int, missing: str, too_long: str | None, why: str) -> str:
    """A name or role, on one line: spaces around and within are tidied, and it is never blank or only spaces.
    ``too_long`` is None only where the site's form makes it unreachable (``ReplyMessages``)."""
    line = " ".join((value or "").split())
    if len(line) < 2:
        raise Refused(missing, f"{why}_missing")
    if len(line) > longest:
        if too_long is None:
            raise LeftOut(f"{why}_too_long")
        raise Refused(too_long.format(max=longest, n=len(line)), f"{why}_too_long")
    return line


def check_link(link: str | None, rules: ReplyRules, messages: ReplyMessages) -> str | None:
    """A link to the record, or None when none was given: a full web address, with nothing in it that could break
    out of a link's markup (quotes, angle brackets, spaces)."""
    link = (link or "").strip()
    if not link:
        return None
    if len(link) > rules.link_max:
        raise Refused(too_long(messages, "link_too_long").format(max=rules.link_max, n=len(link)), "link_too_long")
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
