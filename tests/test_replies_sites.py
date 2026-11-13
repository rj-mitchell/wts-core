"""The four sites, as ``wts_core.replies`` sees them: each one's limits, its words and where its statements sit.

Every other ``test_replies_*`` file runs over these. Each site's ``ReplyRules`` are its limits of 12 November 2026;
its ``ReplyMessages`` are its own words wherever it has them (docs/study/reports-statements.md, section 4), and its
``Items`` is a small copy of its own item addresses, with its own refusals. Where a site has no words today for a
refusal it gains with the package (marked "new" below), the test uses its sister's, in the same family of wording:
the words a site really shows are the owner's to give when the site adopts the package.

This file's own tests are the sites' tests of their addresses, and of the two classes every site fills in.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse, urlsplit

import pytest

from wts_core.replies import Item, Items, Refused, Replies, ReplyMessages, ReplyRules, migrations
from wts_core.state import StateDB
from wts_core.testing import FixedClock

NOW = "2026-11-13T12:00:00+00:00"  # a Friday
HEADING = "Statement from {name}, {date}"  # the family glossary's words, the same on every site
DISCLAIMER = "In their own words. Not checked or endorsed by {site}."
LAPSED = "No decision was made in time; please send it again"  # ADR 0008, question 2


# ---- Where MPs Stand ---------------------------------------------------------------------------------------------

class MpsItems:
    """hansard.api.statements.item_path and app.item_missing: eleven kinds of page, a member's page kept as
    /people/<number>, and a briefing or member that must be there."""

    HOSTS = ("wherempsstand.com", "www.wherempsstand.com")
    ITEM = re.compile(r"^/(people/\d+|b/[a-km-z2-9]{10}|topics/[\w-]+|debates/\d{4}-\d{2}-\d{2}/[\w-]+/[\w-]+|"
                      r"bills/[\w-]+|groups/[\w-]+/[\w-]+|edms/\d+|committees/\d+|inquiries/\d+|evidence/\d+|"
                      r"devolved/[\w-]+/[\w.-]+)$")

    def __init__(self) -> None:
        self.briefings: dict[str, bool] = {"abcdefghjk": False}  # id -> withdrawn
        self.people = {10669, 10777}

    def resolve(self, pasted: str) -> Item:
        address = (pasted or "").strip()
        if "://" not in address:  # "wherempsstand.com/people/…", or a path
            address = ("https://" if address.split("/")[0] in self.HOSTS else "https://wherempsstand.com/") \
                + address.lstrip("/")
        parsed = urlparse(address)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in self.HOSTS:
            raise Refused("Please give the address of the page on wherempsstand.com that the statement is about.")
        path = re.sub(r"/+$", "", parsed.path) or "/"
        person = re.match(r"^/people/(\d+)(?:/[\w-]*)?$", path)
        if person:
            path = f"/people/{person.group(1)}"
        if not self.ITEM.match(path):
            raise Refused("That address isn't a page a statement can sit beside: please give the address of a "
                          "member's page, a briefing or another page that names them.")
        return Item(path, person.group(1) if person else None)

    def shown(self, item: Item) -> bool:
        if item.address.startswith("/b/"):
            bid = item.address.removeprefix("/b/")
            if bid not in self.briefings:
                raise Refused("There is no briefing at that address: please check the address of the briefing the "
                              "statement is about.")
            if self.briefings[bid]:
                raise Refused("That briefing has been withdrawn, so a statement can't sit beside it.")
        if item.address.startswith("/people/") and int(item.address.removeprefix("/people/")) not in self.people:
            raise Refused("There is no member's page at that address: please check the address of the page the "
                          "statement is about.")
        return True  # the other kinds of page are not looked up: the owner sees the address before publishing


MPS_RULES = ReplyRules(
    min_words=5, max_chars=2000, name_max=120, role_max=200, link_max=500, email_max=200,
    daily_statements=5, daily_reports=10, about_required=False,
    report_kinds={"correction": "correction", "complaint": "complaint", "takedown": "takedown", "general": "general"},
    report_kind_required=True, report_min=10, report_max=4000, page_max=200, contact_max=200)
MPS_MESSAGES = ReplyMessages(
    too_few_words="Please write the statement: a sentence or more.",
    too_many_words="A statement can be up to {max} words. This one is {n}.",
    too_many_chars="A statement can be up to {max:,} characters. This one is {n:,}.",  # new: Landlords' words
    name_missing="Please give the name the statement is from.",
    name_too_long="Your name can be up to {max:,} characters. This one is {n:,}.",  # new
    role_missing="Please give their role, for example \"MP for Leeds Central\" or \"Chief of staff to …\".",
    role_too_long="Your role can be up to {max:,} characters. This one is {n:,}.",  # new
    bad_link="The link to the record should be a full web address, starting https://.",
    link_too_long="The link to the record can be up to {max:,} characters. This one is {n:,}.",  # new
    bad_email="Please give an email address, so we can confirm who the statement is from.",
    item_not_shown="There is no page at that address just now: please check the address of the page the statement "
                   "is about.",  # new: the site's own Items says which, for a briefing or a member
    daily_statements="Thank you, we have your statements. Please email us if there is more to add.",
    daily_reports="Thank you, we have your reports. Please email us if there is more to add.",
    report_kind="Please say what kind of problem it is.",  # new: the form's own list stops it today
    report_too_short="Please describe the problem in a sentence or two.",
    report_too_long="A report can be up to {max:,} characters. This one is {n:,}.",  # new
    contact_too_long="Your contact details can be up to {max:,} characters.",  # new
    lapsed=LAPSED, heading=HEADING, disclaimer=DISCLAIMER, record_link="The record they point to",
    site="Where MPs Stand")
MPS_STATEMENT = {"name": "Hilary Benn", "role": "MP for Leeds South",
                 "item": "https://wherempsstand.com/people/10669/hilary-benn",
                 "text": "I have always supported the right to trial by jury, as my speech of 2008 makes clear.",
                 "link": "https://hansard.parliament.uk/commons/2008-06-11", "email": "hilary.benn.mp@parliament.uk"}
MPS_REFUSALS = (  # tests/test_statements.py, test_statements_are_checked
    ({"text": " ".join(["word"] * 151)}, "up to 150 words"),
    ({"text": "Too short."}, "a sentence or more"),
    ({"item": "https://example.org/b/abcdefghjk"}, "address of the page"),
    ({"item": "/about"}, "isn't a page a statement can sit beside"),
    ({"link": "javascript:alert(1)"}, "full web address"),
    ({"email": "not an email"}, "email address"),
    ({"role": " x "}, "their role"),
)


# ---- Where Countries Stand ---------------------------------------------------------------------------------------

class CountriesItems:
    """wcs.api.statements.item_address: only a saved briefing, on the site's hosts or one the app adds (its
    configured address, the request's own host), and it must exist and not be withdrawn."""

    HOSTS = ("wherecountriesstand.com", "www.wherecountriesstand.com")
    ITEM = re.compile(r"^/b/([A-Za-z0-9_-]{6,20})$")

    def __init__(self, extra_hosts: tuple[str, ...] = ()) -> None:
        self.hosts = (*self.HOSTS, *extra_hosts)
        self.briefings: dict[str, bool] = {"AbC123xy": False}

    def resolve(self, pasted: str) -> Item:
        a = (pasted or "").strip()
        if not a:
            raise Refused("Give the address of the briefing the statement is about.")
        parts = urlsplit(a if "://" in a or a.startswith("/") else "https://" + a)
        if parts.scheme not in ("http", "https", "") or (parts.hostname and parts.hostname.lower() not in self.hosts):
            raise Refused("The address must be a briefing on wherecountriesstand.com.")
        m = self.ITEM.match(unquote(parts.path).rstrip("/"))
        if not m:
            raise Refused("The address must be a briefing on this site, such as "
                          "https://wherecountriesstand.com/b/…")
        return Item(f"/b/{m[1]}")

    def shown(self, item: Item) -> bool:
        return self.briefings.get(item.address.removeprefix("/b/")) is False


COUNTRIES_RULES = ReplyRules(
    min_words=1, max_chars=1500, name_max=200, role_max=200, link_max=500, email_max=200,
    daily_statements=5, daily_reports=10, about_required=False,  # the limits are gained with the package
    report_kinds={"": "error", "error": "error", "unfair": "unfair", "problem": "problem", "takedown": "takedown",
                  "other": "other"},
    report_kind_required=True, report_min=5, report_max=4000, page_max=300, contact_max=200)
COUNTRIES_MESSAGES = ReplyMessages(
    too_few_words="Write the statement.",
    too_many_words="A statement can be up to {max} words; this one is {n}.",
    too_many_chars="A statement can be up to {words} words ({max:,} characters).",
    name_missing="Give your name, as it should be shown.",
    name_too_long="Your name can be up to {max} characters.",
    role_missing="Give your role, such as Permanent Representative of Kenya to the United Nations.",
    role_too_long="Your role can be up to {max} characters.",
    bad_link="The link to the record must be a web address starting https:// (or leave it empty).",
    link_too_long="The link to the record can be up to {max} characters.",  # new
    bad_email="Give an email address we can use to confirm who you are.",
    item_not_shown="There is no briefing at that address. Check the address of the briefing the statement is about.",
    daily_statements="Thank you: we have your statements. Please email us if there is more to add.",  # new
    daily_reports="Thank you: we have your reports. Please email us if there is more to add.",  # new
    report_kind="Say what kind of problem it is.",  # new
    report_too_short="Say what is wrong.",  # new
    report_too_long="A report can be up to {max:,} characters.",  # new
    contact_too_long="Your contact details can be up to {max} characters.",  # new
    lapsed=LAPSED, heading=HEADING, disclaimer=DISCLAIMER, record_link="The record it points to: {link}",
    site="Where Countries Stand")
COUNTRIES_STATEMENT = {"name": "Ms. Amina Odhiambo",
                       "role": "Deputy Permanent Representative of Kenya to the United Nations",
                       "item": "https://wherecountriesstand.com/b/AbC123xy",
                       "text": "Our delegation's position on adaptation finance is set out in full in document "
                               "A/79/123, paragraph 4.",
                       "link": "https://undocs.org/en/A/79/123", "email": "press@kenyamission.example"}
COUNTRIES_REFUSALS = (  # tests/test_statements.py: the checks, and what is refused with words for the reader
    ({"text": " ".join(["word"] * 151)}, "A statement can be up to 150 words; this one is 151."),
    ({"text": "x" * 1501}, "1,500 characters"),
    ({"text": "   "}, "Write the statement"),
    ({"email": "nobody"}, "confirm who you are"),
    ({"email": "press@mission"}, "confirm who you are"),
    ({"email": "a b@c.d"}, "confirm who you are"),
    ({"link": "javascript:alert(1)"}, "web address"),
    ({"link": "undocs.org/x"}, "web address"),
    ({"link": "https://"}, "web address"),
    ({"link": "https://un.org/a b"}, "web address"),
    ({"link": 'https://undocs.org/en/A/79/123"><b>'}, "web address"),
    ({"link": "https://un.org/a'b"}, "web address"),
    ({"link": "https://un.org/<script>"}, "web address"),
    ({"item": "https://example.org/b/AbC123xy"}, "wherecountriesstand.com"),
    ({"item": "https://wherecountriesstand.com/about.html"}, "a briefing on this site"),
    ({"item": "/b/nosuchbriefing"}, "no briefing at that address"),
    ({"name": " x "}, "Give your name, as it should be shown."),
    ({"name": "x" * 201}, "Your name can be up to 200 characters."),
    ({"role": "x" * 201}, "Your role can be up to 200 characters."),
)


# ---- Where Councils Stand ----------------------------------------------------------------------------------------

BARNSLEY = "E08000038"
VOTE = f"{BARNSLEY}:1:10:0"


class CouncilsItems:
    """councils.api.statements.item_address and app.item_exists: a council's page, a named vote or a briefing."""

    HOSTS = ("wherecouncilsstand.com", "www.wherecouncilsstand.com")
    ITEM = re.compile(r"^/(councils|votes|b)/([^/\s]+)$")

    def __init__(self, extra_hosts: tuple[str, ...] = ()) -> None:
        self.hosts = (*self.HOSTS, *extra_hosts)
        self.councils = {BARNSLEY}
        self.votes = {VOTE}
        self.briefings: dict[str, bool] = {"abc123": False}

    def resolve(self, pasted: str) -> Item:
        a = (pasted or "").strip()
        if not a:
            raise Refused("Give the address of the page the statement is about.")
        parts = urlsplit(a if "://" in a or a.startswith("/") else "https://" + a)
        if parts.scheme not in ("http", "https", "") or (parts.hostname and parts.hostname.lower() not in self.hosts):
            raise Refused("The address must be a page on wherecouncilsstand.com.")
        m = self.ITEM.match(unquote(parts.path).rstrip("/"))
        if not m:
            raise Refused("The address must be a council's page, a named vote or a briefing on this site, such as "
                          "https://wherecouncilsstand.com/votes/…")
        kind, key = m.groups()
        if kind == "councils":
            return Item(f"/councils/{key.upper()}", key.upper())
        if kind == "votes":
            gss, _, rest = key.partition(":")
            return Item(f"/votes/{gss.upper()}:{rest}" if rest else f"/votes/{gss.upper()}", gss.upper())
        return Item(f"/b/{key}")  # a briefing belongs to no one council until the owner gives one

    def shown(self, item: Item) -> bool:
        kind, key = item.address.split("/")[1:3]
        if kind == "councils":
            return key in self.councils
        if kind == "votes":
            return key in self.votes
        return self.briefings.get(key) is False  # a withdrawn briefing has no page to stand beside


COUNCILS_RULES = ReplyRules(
    min_words=1, max_chars=1500, name_max=200, role_max=200, link_max=500, email_max=300,
    daily_statements=5, daily_reports=10, about_required=False,  # the limits are gained with the package
    report_kinds={"": "error", "error": "error", "unfair": "unfair", "takedown": "takedown", "other": "other"},
    report_kind_required=True, report_min=5, report_max=5000, page_max=500, contact_max=300)
COUNCILS_MESSAGES = dataclasses.replace(
    COUNTRIES_MESSAGES,
    role_missing="Give your role, such as Councillor, Barnsley Metropolitan Borough Council.",
    item_not_shown="There's no page at that address on this site. Copy the address from the page the statement is "
                   "about.",
    record_link="The record they point to", site="Where Councils Stand")
COUNCILS_STATEMENT = {"name": "Steve Houghton", "role": "Councillor, Barnsley Metropolitan Borough Council",
                      "item": f"https://wherecouncilsstand.com/votes/{VOTE}",
                      "text": "I voted against this motion because the council had already agreed a review of "
                              "collections, and the minutes of that meeting set it out. Zanzibarquokka.",
                      "link": "https://barnsley.moderngov.co.uk/ieListDocuments.aspx?MId=1",
                      "email": "cllr@barnsley.gov.uk"}
COUNCILS_REFUSALS = (  # tests/test_statements.py: every case but the box to tick, which is the site's own form's
    ({"text": " ".join(["word"] * 151)}, "up to 150 words; this one is 151"),
    ({"text": "   "}, "Write the statement"),
    ({"text": "x" * 1550}, "up to 150 words"),
    ({"email": "not an address"}, "email address"),
    ({"email": ""}, "email address"),
    ({"item": "https://example.org/votes/x"}, "a page on wherecouncilsstand.com"),
    ({"item": "/about"}, "a council's page, a named vote or a briefing"),
    ({"item": ""}, "Give the address"),
    ({"item": f"/votes/{BARNSLEY}:9:9:9"}, "no page at that address"),
    ({"item": "/b/nosuchbriefing"}, "no page at that address"),
    ({"item": "ftp://wherecouncilsstand.com/votes/x"}, "a page on wherecouncilsstand.com"),
    ({"link": "javascript:alert(1)"}, "web address"),
    ({"link": "https://example.org/a\"onmouseover=\"alert(1)"}, "web address"),
    ({"link": "https://example.org/<script>"}, "web address"),
    ({"link": "https://example.org/it's"}, "web address"),
    ({"name": "    "}, "Give your name"),
    ({"name": " \n\tX "}, "Give your name"),
    ({"role": "   "}, "Give your role"),
)


# ---- Where Landlords Stand ---------------------------------------------------------------------------------------

class LandlordsItems:
    """landlords.statements.item: a landlord's page or an area's page, with no leading slash and a trailing one,
    and a part of a landlord's page from the address's #fragment (or the form's own field: ``with_part``)."""

    HOSTS = ("wherelandlordsstand.com", "www.wherelandlordsstand.com")
    PAGE = re.compile(r"^(landlords|areas)/([a-z0-9][a-z0-9-]*)/?(?:index\.html)?$")
    PARTS = ("grade", "bands", "ombudsman", "safety")

    def __init__(self) -> None:
        self.pages = {"landlords/example-housing/", "landlords/example-council/", "areas/leeds/"}

    def resolve(self, pasted: str) -> Item:
        return self.with_part(pasted)

    def with_part(self, pasted: str, part: str = "") -> Item:
        address = (pasted or "").strip()
        if "://" not in address:  # "wherelandlordsstand.com/landlords/…", or a path
            host = address.split("/")[0]
            address = "https://" + (address if host in self.HOSTS else "wherelandlordsstand.com/" + address.lstrip("/"))
        parsed = urlparse(address)
        found = self.PAGE.match(parsed.path.lstrip("/")) if parsed.hostname in self.HOSTS else None
        if not found:
            raise Refused("Please give the address of a page on wherelandlordsstand.com that names your landlord: "
                          "its own page (with /landlords/ in it), or a council area's page (with /areas/ in it).")
        kind, slug = found.groups()
        part = (part or parsed.fragment or "").strip().lower()
        return Item(f"{kind}/{slug}/", slug if kind == "landlords" else None,
                    part if kind == "landlords" and part in self.PARTS else "")

    def shown(self, item: Item) -> bool:
        return item.address in self.pages


LANDLORDS_RULES = ReplyRules(
    min_words=3, max_chars=2000, name_max=120, role_max=200, link_max=300, email_max=200,
    daily_statements=5, daily_reports=10, about_required=True,  # the daily limits are gained with the package
    report_kinds={"wrong": "wrong", "unfair": "unfair", "takedown": "takedown", "other": "other",
                  "correction": "wrong", "error": "wrong", "mistake": "wrong", "complaint": "unfair",
                  "general": "other"},
    report_kind_required=False, report_min=1, report_max=4000, page_max=300, contact_max=200)
LANDLORDS_MESSAGES = ReplyMessages(
    too_few_words="Please write the statement: a sentence or more.",
    too_many_words="A statement can be up to {max} words. This one is {n}.",
    too_many_chars="A statement can be up to {max:,} characters. This one is {n:,}.",
    name_missing="Please give the name the statement is from.",
    name_too_long="Your name can be up to {max:,} characters. This one is {n:,}.",
    role_missing="Please give your role and the landlord you speak for, for example \"Chief executive, Example "
                 "Housing\".",
    role_too_long="Your role can be up to {max:,} characters. This one is {n:,}.",
    bad_link="The link to the record should be a full web address, starting https://.",
    link_too_long="The link to the record can be up to {max:,} characters. This one is {n:,}.",
    bad_email="Please give an email address, so we can confirm who the statement is from.",
    item_not_shown="We couldn't find that page on the site. Please copy its address from your browser.",
    daily_statements="Thank you, we have your statements. Please email us if there is more to add.",  # new
    daily_reports="Thank you, we have your reports. Please email us if there is more to add.",  # new
    report_kind="Please say what kind of problem it is.",  # never shown: a report with no kind is kept
    report_too_short="please say what is wrong",
    report_too_long="A report can be up to {max:,} characters. This one is {n:,}.",  # new: it was cut to fit
    contact_too_long="Your email address can be up to {max:,} characters.",  # new: it was cut to fit
    lapsed=LAPSED, heading=HEADING, disclaimer=DISCLAIMER, record_link="The record they point to",
    site="Where Landlords Stand")
LANDLORDS_STATEMENT = {"name": "Jane Example", "role": "Chief executive, Example Housing",
                       "item": "landlords/example-housing/",
                       "text": "Our survey was carried out after a big change to our repairs service, and we have "
                               "published newer results.",
                       "link": "https://example.org/results", "email": "jane@example-housing.org.uk"}
LONG = " ".join(["extraordinarily"] * 140)  # within 150 words, but 2,239 characters
LANDLORDS_REFUSALS = (  # tests/test_statements.py: test_what_is_needed, and what is too long is never cut to fit
    ({"name": ""}, "the name"), ({"role": " "}, "your role"), ({"text": ""}, "write the statement"),
    ({"email": ""}, "email address"), ({"email": "not-an-address"}, "email address"),
    ({"item": ""}, "address of a page"),
    ({"item": "https://example.org/landlords/example-housing/"}, "address of a page"),
    ({"item": "/compare/"}, "address of a page"),
    ({"item": "landlords/nobody-at-all/"}, "couldn't find that page"),
    ({"link": "javascript:alert(1)"}, "full web address"), ({"link": "https://example.org/a b"}, "full web address"),
    ({"text": " ".join(["word"] * 151)}, "up to 150 words. This one is 151"),
    ({"text": LONG}, "A statement can be up to 2,000 characters. This one is 2,239."),
    ({"name": "N" * 121}, "Your name can be up to 120 characters. This one is 121."),
    ({"role": "R" * 201}, "Your role can be up to 200 characters. This one is 201."),
    ({"link": "https://example.org/" + "a" * 281}, "The link to the record can be up to 300 characters. This one "
                                                   "is 301."),
    ({"email": "a" * 189 + "@example.org"}, "Please give an email address, so we can confirm who the statement is "
                                            "from."),
)


# ---- the four, as the other tests use them ------------------------------------------------------------------------

@dataclass(frozen=True)
class Case:
    """A site as the package sees it, and its own tests' sample statement and table of refusals."""

    key: str
    rules: ReplyRules
    messages: ReplyMessages
    items: Callable[[], Any]
    statement: dict[str, Any]
    address: str  # where the sample statement is filed
    about: str | None  # and whom its address says it is about
    refusals: tuple[tuple[dict[str, Any], str], ...]
    report: dict[str, Any] = field(default_factory=dict)


SITES: dict[str, Case] = {c.key: c for c in (
    Case("mps", MPS_RULES, MPS_MESSAGES, MpsItems, MPS_STATEMENT, "/people/10669", "10669", MPS_REFUSALS,
         {"kind": "correction", "page": "/b/abcdefghjk", "message": "The second point misquotes the minister."}),
    Case("countries", COUNTRIES_RULES, COUNTRIES_MESSAGES, CountriesItems, COUNTRIES_STATEMENT, "/b/AbC123xy", None,
         COUNTRIES_REFUSALS, {"kind": "error", "page": "/b/AbC123xy", "message": "A date is wrong."}),
    Case("councils", COUNCILS_RULES, COUNCILS_MESSAGES, CouncilsItems, COUNCILS_STATEMENT, f"/votes/{VOTE}", BARNSLEY,
         COUNCILS_REFUSALS, {"kind": "error", "page": "/votes/x", "message": "Something is wrong here."}),
    Case("landlords", LANDLORDS_RULES, LANDLORDS_MESSAGES, LandlordsItems, LANDLORDS_STATEMENT,
         "landlords/example-housing/", "example-housing", LANDLORDS_REFUSALS,
         {"kind": "wrong", "page": "landlords/x/", "message": "Wrong grade"}),
)}


class Open:
    """One site, opened on an empty state database, with the clock standing at NOW."""

    def __init__(self, case: Case, folder: Path) -> None:
        self.case = case
        self.key = case.key
        self.rules, self.messages = case.rules, case.messages
        self.clock = FixedClock(NOW)
        self.db = StateDB(folder / "state.db", migrations=migrations(), clock=self.clock)
        self.items = case.items()
        self.replies = Replies(self.db, items=self.items, rules=case.rules, messages=case.messages, clock=self.clock)

    def body(self, **over: Any) -> dict[str, Any]:
        """The site's sample statement, as ``Replies.submit`` takes it."""
        return {**self.case.statement, **over}

    def send(self, **over: Any) -> int:
        sid = self.replies.submit(**self.body(**over))
        assert sid is not None
        return sid

    def show(self, sid: int, **kw: Any) -> None:
        """Publish, saying whom it speaks for where the site must be told (Where Landlords Stand, an area's page)."""
        self.replies.publish(sid, checked="Reply from their published address, 12 November.", **kw)

    def rows(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        with self.db.connect() as con:
            return [dict(r) for r in con.execute(sql, args).fetchall()]


def site_fixture(*keys: str) -> Any:
    """A fixture that is each of the sites in turn (or only those named). Each test file makes its own from this,
    with ``site = site_fixture()``."""

    @pytest.fixture(params=keys or tuple(SITES))
    def site(request: pytest.FixtureRequest, tmp_path: Path) -> Open:
        return Open(SITES[request.param], tmp_path)

    return site


def one_site(key: str) -> Any:
    @pytest.fixture
    def opened(tmp_path: Path) -> Open:
        return Open(SITES[key], tmp_path)

    return opened


site = site_fixture()
mps, countries, councils, landlords = one_site("mps"), one_site("countries"), one_site("councils"), \
    one_site("landlords")


# ---- each site's addresses, as its own tests check them -----------------------------------------------------------

def test_mps_item_addresses_are_paths_on_the_site():
    resolve = MpsItems().resolve
    assert resolve("https://wherempsstand.com/people/10669/hilary-benn") == Item("/people/10669", "10669")
    assert resolve("/people/10669").address == "/people/10669"
    assert resolve("https://www.wherempsstand.com/b/abcdefghjk?x=1#s") == Item("/b/abcdefghjk")
    assert resolve("wherempsstand.com/groups/commons/socialist-campaign-group/").address == \
        "/groups/commons/socialist-campaign-group"
    assert resolve("/debates/2008-06-11/commons/counter-terrorism-bill").address == \
        "/debates/2008-06-11/commons/counter-terrorism-bill"
    for bad in ("https://example.org/people/10669", "/about", "/", "javascript:alert(1)", "/people/abc", ""):
        with pytest.raises(Refused):
            resolve(bad)


def test_countries_item_is_a_briefing_on_the_site():
    resolve = CountriesItems().resolve
    assert resolve("https://wherecountriesstand.com/b/AbC123xy") == Item("/b/AbC123xy")
    assert resolve("wherecountriesstand.com/b/AbC123xy/").address == "/b/AbC123xy"
    assert resolve("/b/AbC123xy").address == "/b/AbC123xy"
    assert CountriesItems(("localhost",)).resolve("http://localhost/b/AbC123xy").address == "/b/AbC123xy"
    for bad in ("", "https://example.org/b/AbC123xy", "https://wherecountriesstand.com/about.html",
                "https://wherecountriesstand.com/b/x", "javascript:alert(1)", "/b/AbC123xy/more"):
        with pytest.raises(Refused):
            resolve(bad)


def test_councils_address_is_read_as_the_item_it_names():
    resolve = CouncilsItems().resolve
    assert resolve(f"wherecouncilsstand.com/votes/{BARNSLEY.lower()}:1:10:0/") == Item(f"/votes/{VOTE}", BARNSLEY)
    assert resolve(f"https://www.wherecouncilsstand.com/councils/{BARNSLEY.lower()}?x=1#y") == \
        Item(f"/councils/{BARNSLEY}", BARNSLEY)
    assert resolve("/b/AbC_12") == Item("/b/AbC_12", None)
    with pytest.raises(Refused):
        resolve("ftp://wherecouncilsstand.com/votes/x")


def test_landlords_page_can_be_given_in_any_of_the_ways_people_copy_it():
    items = LandlordsItems()
    for address in ("https://wherelandlordsstand.com/landlords/example-housing/",
                    "https://www.wherelandlordsstand.com/landlords/example-housing/index.html",
                    "wherelandlordsstand.com/landlords/example-housing", "/landlords/example-housing/"):
        assert items.resolve(address) == Item("landlords/example-housing/", "example-housing", ""), address
    assert items.resolve("https://wherelandlordsstand.com/landlords/example-housing/#bands") == \
        Item("landlords/example-housing/", "example-housing", "bands")
    assert items.resolve("landlords/example-housing/#figures").part == ""  # not a part of the card: after it
    assert items.with_part("landlords/example-housing/", "safety").part == "safety"
    assert items.with_part("https://wherelandlordsstand.com/areas/leeds/", "grade") == Item("areas/leeds/", None, "")


def test_every_sites_items_is_what_the_package_asks_for(site):
    items: Items = site.items  # the protocol, as a type checker would see it
    beside = items.resolve(site.case.statement["item"])
    assert beside.address == site.case.address and beside.about == site.case.about
    assert items.resolve(beside.address).address == beside.address  # an address already filed reads as itself
    assert items.shown(beside) is True


# ---- the two classes every site fills in --------------------------------------------------------------------------

def test_nothing_that_differs_between_the_sites_has_a_default():
    """CONTRIBUTING.md, rule 1. Only the policy's 150 words and the notices' three months are the same everywhere."""
    with_default = {f.name for f in dataclasses.fields(ReplyRules) if f.default is not dataclasses.MISSING}
    assert with_default == {"max_words", "email_kept_months"}
    assert ReplyRules.__dataclass_fields__["max_words"].default == 150
    assert all(f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
               for f in dataclasses.fields(ReplyMessages))  # the package has no wording of its own
    with pytest.raises(TypeError):
        ReplyRules()
    with pytest.raises(TypeError):
        ReplyMessages(too_few_words="Write the statement.")
    with pytest.raises(dataclasses.FrozenInstanceError):
        MPS_RULES.min_words = 1


def test_the_rules_are_each_sites_own():
    least = {key: (c.rules.min_words, c.rules.max_chars) for key, c in SITES.items()}
    assert least == {"mps": (5, 2000), "countries": (1, 1500), "councils": (1, 1500), "landlords": (3, 2000)}
    assert {c.rules.max_words for c in SITES.values()} == {150}
    assert {c.rules.email_kept_months for c in SITES.values()} == {3}


def test_the_heading_and_disclaimer_are_the_glossarys_on_every_site(site):
    assert site.messages.heading == "Statement from {name}, {date}"
    assert site.messages.disclaimer == "In their own words. Not checked or endorsed by {site}."
    assert site.messages.site.startswith("Where ") and site.messages.site.endswith(" Stand")


def test_a_message_that_cannot_be_filled_in_stops_the_site_naming_the_field():
    with pytest.raises(ValueError, match=r"ReplyMessages\.too_many_words"):
        dataclasses.replace(MPS_MESSAGES, too_many_words="Up to {limit} words.")
    with pytest.raises(ValueError, match=r"ReplyMessages\.role_missing"):
        dataclasses.replace(MPS_MESSAGES, role_missing="Give your role {like this.")
    assert dataclasses.replace(MPS_MESSAGES, role_missing="Braces {{meant}} as braces.").role_missing


def test_a_refusal_carries_the_sites_words_and_the_rule_broken():
    refused = Refused("Write the statement.", "too_few_words")
    assert str(refused) == "Write the statement." and refused.why == "too_few_words"
    assert isinstance(refused, ValueError) and Refused("A site's own.").why == ""
