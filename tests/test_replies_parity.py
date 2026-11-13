"""The package against each site's own code of 12 November 2026, where the site's checkout is present.

The other ``test_replies_*`` files carry copies of what is the sites': their words, their item addresses, their
tables. These tests read the sites' code itself and check the copies, and that the package refuses what each site
refuses, in the same words. The checkouts are looked for beside this repository, or in the folder ``WTS_SITES_DIR``
names; a test whose site is not there is skipped, saying which.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from test_replies_sites import (
    DISCLAIMER,
    HEADING,
    SITES,
    CountriesItems,
    Open,
    one_site,
    site_fixture,
)
from test_replies_tables import OLD
from wts_core.replies import Refused, months_before, word_count
from wts_core.replies.rules import clean_text

site = site_fixture()
mps, countries, councils, landlords = one_site("mps"), one_site("countries"), one_site("councils"), \
    one_site("landlords")

REPOS = {"mps": ("wherempsstand", "hansard"), "countries": ("wherecountriesstand", "wcs"),
         "councils": ("wherecouncilsstand", "councils"), "landlords": ("wherelandlordsstand", "landlords")}
STATEMENTS = {"mps": "hansard.api.statements", "countries": "wcs.api.statements",
              "councils": "councils.api.statements", "landlords": "landlords.statements"}


def checkout(repo: str, holds: str = "src") -> Path:
    """A site's checkout (or the charity's), or the test is skipped, naming the one that is missing."""
    named = os.environ.get("WTS_SITES_DIR")
    places = [Path(named)] if named else list(Path(__file__).resolve().parents[1].parents)
    found = next((p / repo for p in places if (p / repo / holds).exists()), None)
    if found is None:
        where = f"in {named} (WTS_SITES_DIR)" if named else "beside this repository"
        pytest.skip(f"no checkout of {repo} {where}: set WTS_SITES_DIR to the folder that holds the sites' checkouts "
                    "to check the package against the site's own code")
    return found


def theirs(key: str, module: str | None = None) -> ModuleType:
    """A module of the site's own, from its checkout. The four packages' names are theirs alone, so their source
    folders can sit on the path together."""
    repo, _ = REPOS[key]
    source = str(checkout(repo) / "src")
    if source not in sys.path:
        sys.path.append(source)
    try:
        return importlib.import_module(module or STATEMENTS[key])
    except ImportError as exc:
        pytest.skip(f"{repo}'s {module or STATEMENTS[key]} can't be imported here ({exc}): its own tests check it")


def said(text: str) -> str:
    """Source code with its line breaks inside sentences taken out, so a sentence can be looked for whole."""
    joined = re.sub(r"""["']\s*\n\s*f?["']""", "", text)
    return " ".join(joined.replace('\\"', '"').split())


# ---- the copies in these tests are still the sites' -----------------------------------------------------------------

@pytest.mark.parametrize("key", list(OLD))
def test_the_copy_of_each_sites_tables_is_what_its_code_makes(key):
    source = " ".join((checkout(REPOS[key][0]) / OLD[key].source).read_text(encoding="utf-8").split())
    for statement in OLD[key].schema:
        assert " ".join(statement.split()) in source, statement.split("(")[0]


@pytest.mark.parametrize("key, where, sentences", [
    ("mps", "src/hansard/api/app.py", (
        SITES["mps"].messages.daily_statements, SITES["mps"].messages.daily_reports,
        "There is no briefing at that address: please check the address of the briefing the statement is about.",
        "That briefing has been withdrawn, so a statement can't sit beside it.",
        "There is no member's page at that address: please check the address of the page the statement is about.")),
    ("mps", "web/src/statements.ts", ("In their own words. Not checked or endorsed by Where MPs Stand.",
                                      "Statement from ${s.name}, ${fmtDate(s.date)}", "The record they point to",
                                      "nofollow ugc noopener noreferrer")),
    ("mps", "web/src/pages.ts", (SITES["mps"].messages.report_too_short,)),
    ("countries", "src/wcs/api/app.py", (SITES["countries"].messages.item_not_shown,
                                         "your name, as it should be shown",
                                         "your role, such as Permanent Representative of Kenya to the United Nations")),
    ("countries", "web/site/app.js", ("In their own words. Not checked or endorsed by Where Countries Stand.",
                                      "The record it points to: ")),
    ("councils", "src/councils/api/app.py", (SITES["councils"].messages.item_not_shown,
                                             "your role, such as Councillor, Barnsley Metropolitan Borough Council")),
    ("councils", "src/councils/api/plaintext.py", ("The record they point to", "Statement from ")),
    ("landlords", "src/landlords/statements.py", (SITES["landlords"].messages.item_not_shown,)),
    ("landlords", "src/landlords/api.py", (SITES["landlords"].messages.report_too_short,)),
    ("landlords", "config/wording.toml", (f'heading = "{HEADING}"', f'endorsed = "{DISCLAIMER}"',
                                          'record = "The record they point to"')),
])
def test_the_words_in_these_tests_are_the_sites_own(key, where, sentences):
    path = checkout(REPOS[key][0]) / where
    if not path.is_file():
        pytest.skip(f"{REPOS[key][0]} has no {where} in this checkout")
    source = said(path.read_text(encoding="utf-8"))
    for sentence in sentences:
        assert sentence in source, sentence


def test_the_heading_and_disclaimer_are_the_family_glossarys():
    glossary = (checkout("wheretheystand-charity", "family/GLOSSARY.md") / "family" / "GLOSSARY.md").read_text()
    assert f'"{HEADING.format(name="[name]", date="[date]")}"' in glossary
    assert f'"{DISCLAIMER.format(site="[site]")}"' in glossary


# ---- item addresses ------------------------------------------------------------------------------------------------

ADDRESSES = {
    "mps": ("https://wherempsstand.com/people/10669/hilary-benn", "/people/10669", "/people/10669/",
            "https://www.wherempsstand.com/b/abcdefghjk?x=1#s", "wherempsstand.com/groups/commons/socialist-campaign-group/",
            "/debates/2008-06-11/commons/counter-terrorism-bill", "/topics/onshore-wind", "/bills/a-bill", "/edms/12",
            "/committees/3", "/inquiries/4", "/evidence/5", "/devolved/senedd/2026-11-12.1",
            "HTTPS://WWW.WHEREMPSSTAND.COM/people/10669", "https://example.org/people/10669", "/about", "/",
            "javascript:alert(1)", "/people/abc", "", "/b/short", "ftp://wherempsstand.com/people/1"),
    "countries": ("https://wherecountriesstand.com/b/AbC123xy", "wherecountriesstand.com/b/AbC123xy/", "/b/AbC123xy",
                  "http://localhost/b/AbC123xy", "", "https://example.org/b/AbC123xy",
                  "https://wherecountriesstand.com/about.html", "https://wherecountriesstand.com/b/x",
                  "javascript:alert(1)", "/b/AbC123xy/more", "https://WWW.wherecountriesstand.com/b/AbC123xy?x=1#y"),
    "councils": ("wherecouncilsstand.com/votes/e08000038:1:10:0/", "/b/AbC_12",
                 "https://www.wherecouncilsstand.com/councils/e08000038?x=1#y", "/votes/e08000038",
                 "ftp://wherecouncilsstand.com/votes/x", "https://example.org/votes/x", "/about", "",
                 "/councils/a/b", "/b/abc123"),
    "landlords": ("https://wherelandlordsstand.com/landlords/example-housing/",
                  "https://www.wherelandlordsstand.com/landlords/example-housing/index.html",
                  "wherelandlordsstand.com/landlords/example-housing", "/landlords/example-housing/",
                  "https://wherelandlordsstand.com/landlords/example-housing/#bands", "landlords/example-housing/#figures",
                  "https://wherelandlordsstand.com/areas/leeds/", "areas/leeds/#grade", "",
                  "https://example.org/landlords/example-housing/", "/compare/", "landlords/Example/"),
}


def their_item(key: str, m: ModuleType, pasted: str) -> tuple[str, str | None, str]:
    """The item a site's own code reads from an address: its address, whom it is about, and the part."""
    if key == "mps":
        path = m.item_path(pasted)
        return path, None if m.person_of(path) is None else str(m.person_of(path)), ""
    if key == "countries":
        return m.item_address(pasted), None, ""
    if key == "councils":
        return (*m.item_address(pasted), "")
    page, part, landlord = m.item(pasted)
    return page, landlord, part


@pytest.mark.parametrize("key", list(ADDRESSES))
def test_each_sites_items_in_these_tests_reads_addresses_as_the_site_does(key):
    m = theirs(key)
    ours = SITES[key].items()
    for pasted in ADDRESSES[key]:
        try:
            expected: Any = their_item(key, m, pasted)
        except ValueError as exc:
            expected = str(exc)
        try:
            item = ours.resolve(pasted)
            got: Any = (item.address, item.about, item.part)
        except Refused as exc:
            got = str(exc)
        assert got == expected, pasted


def test_countries_extra_hosts_are_the_sites_own_argument():
    m = theirs("countries")
    hosts = (*m.SITE_HOSTS, "countries.example", "testserver")
    for pasted in ("https://countries.example/b/AbC123xy", "http://testserver/b/AbC123xy"):
        assert CountriesItems(("countries.example", "testserver")).resolve(pasted).address == \
            m.item_address(pasted, hosts)


# ---- what is refused, and in which words -----------------------------------------------------------------------------

def their_refusal(key: str, m: ModuleType, body: dict[str, Any]) -> str | None:
    """What the site's own checks say of a statement, called as its route calls them: None when it is accepted.
    Whether the item exists is asked by each site's app, not its checks, and is left out here."""
    try:
        if key == "mps":
            m.check(body["name"], body["role"], m.clean_text(body["text"]), body["email"])
            m.item_path(body["item"])
            m.clean_link(body["link"])
        elif key in ("countries", "councils"):
            role = {"countries": "your role, such as Permanent Representative of Kenya to the United Nations",
                    "councils": "your role, such as Councillor, Barnsley Metropolitan Borough Council"}[key]
            m.item_address(body["item"])
            m.check_line(body["name"], "your name, as it should be shown")
            m.check_line(body["role"], role)
            m.check_text(body["text"])
            m.check_link(body["link"])
            m.check_email(body["email"])
        else:
            f = {k: str(v or "").strip() for k, v in body.items()}
            m.check(f["name"], f["role"], m.clean_text(f["text"]), f["email"])
            m.item(f["item"])
            m.clean_link(f["link"])
    except ValueError as exc:
        return str(exc)
    return None


def our_refusal(site: Open, body: dict[str, Any]) -> str | None:
    try:
        site.replies.submit(**body)
    except Refused as exc:
        return str(exc)
    return None


PROBES: tuple[dict[str, Any], ...] = (
    {}, {"text": " ".join(["word"] * 150)}, {"text": " ".join(["word"] * 151)}, {"text": ""}, {"text": "   \n "},
    {"text": "Too short."}, {"text": "Three words here."}, {"text": "Four words are here."},
    {"text": "Five words are here now."}, {"text": "First paragraph.\r\n\r\n\r\nSecond   paragraph, as written."},
    {"name": " "}, {"name": "X"}, {"name": "  Steve   Houghton "}, {"role": " "}, {"role": "x"},
    {"email": "x"}, {"email": ""}, {"email": "a b@c.d"}, {"email": "press@mission"}, {"email": " press@mission.example "},
    {"link": ""}, {"link": " https://example.org/ok "}, {"link": "javascript:alert(1)"}, {"link": "example.org/x"},
    {"link": "https://"}, {"link": "https://example.org/a b"}, {"link": "https://example.org/\"x"},
    {"link": "https://example.org/<x>"}, {"link": "https://example.org/it's"}, {"link": "ftp://example.org/minutes"},
    {"item": ""}, {"item": "/about"}, {"item": "https://example.org/somewhere"},
)
ASKED_BY_THE_APP = ("no briefing at that address", "no page at that address", "couldn't find that page")


def test_the_package_refuses_what_each_site_refuses_in_the_same_words(site):
    """One fault at a time (the sites check in different orders, and the package in one). The site's own table of
    refusals, and the same probes on every site: its sample statement, the edges of its word limits, and every
    kind of link, name, role and address."""
    m = theirs(site.key)
    own = tuple(over for over, says in site.case.refusals if says not in ASKED_BY_THE_APP)
    assert len(own) >= len(site.case.refusals) - 2
    refused = 0
    for over in (*PROBES, *own):
        body = site.body(**over)
        expected = their_refusal(site.key, m, body)
        assert our_refusal(site, body) == expected, over
        refused += expected is not None
    assert refused >= 15 and site.replies.statements()  # most are refused; the sound ones were kept


def test_words_are_counted_and_text_is_cleaned_as_the_sites_do(site):
    m = theirs(site.key)
    samples = ("", "one", " two  words ", "line\none\r\ntwo\rthree", "a\n\n\n\nb", "tab\tseparated words here",
               "  First paragraph.\n\nSecond   paragraph, as written.  ", "x" * 50, "word " * 151)
    for text in samples:
        assert word_count(text) == m.word_count(text), text
        if hasattr(m, "clean_text"):  # Where MPs Stand's and Where Landlords Stand's: the copy the package takes
            assert clean_text(text) == m.clean_text(text), text
        else:  # Where Countries Stand and Where Councils Stand only strip: the same words, the same count
            assert clean_text(text).split() == text.split()


# ---- three months --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key, module, name", [
    ("mps", "hansard.api.statements", "months_ago"), ("countries", "wcs.api.statements", "months_before"),
    ("councils", "councils.api.state", "months_before"), ("landlords", "landlords.statements", "months_ago")])
def test_three_months_back_is_each_sites_own_sum(key, module, name):
    their_sum = getattr(theirs(key, module), name)
    day = datetime(2026, 1, 1, 12, 34, 56, tzinfo=UTC)
    while day.year < 2029:  # every day of three years, one of them a leap year
        assert months_before(day, 3) == their_sum(day, 3), day
        day += timedelta(days=1)
    assert months_before(datetime(2026, 5, 31, tzinfo=UTC), 3) == their_sum(datetime(2026, 5, 31, tzinfo=UTC), 3) == \
        datetime(2026, 2, 28, tzinfo=UTC)
