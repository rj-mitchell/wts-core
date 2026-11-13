"""The one piece of markup the package offers for a statement: the glossary's heading and disclaimer, set apart
from the site's own words, kept out of what a search engine quotes, and safe whatever was sent.

Where Landlords Stand's test of its rendered markup, Where Councils Stand's of the text it sends to readers without
scripts, and Where MPs Stand's browser tests (text never as HTML, a ``javascript:`` link not made a link).
"""

from __future__ import annotations

import dataclasses
import re
from datetime import date
from html.parser import HTMLParser

import pytest

from test_replies_sites import SITES, site_fixture
from wts_core.replies import long_date, safe_link, statement_html

site = site_fixture()



class Seen(HTMLParser):
    """The elements, attributes and text a browser would find in a piece of markup."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str | None]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attrs += attrs

    def handle_data(self, data: str) -> None:
        self.text.append(data)


WORDS = "Our survey was carried out after a big change to our repairs service, and we have published newer results."


def shown(**over) -> dict:
    return {"id": 7, "item": "landlords/example-housing/", "part": "", "about": "example-housing",
            "name": "Jane Example", "role": "Chief executive, Example Housing", "text": WORDS, "link": None,
            "date": "2026-11-12"} | over


def test_a_statement_is_headed_and_marked_as_the_glossary_says(site):
    html = statement_html(shown(text="Line one <b>bold</b>\nline two\n\npara two", link="https://example.org/r?a=1&b=2"),
                          site.messages)
    link_words = {"countries": "The record it points to: https://example.org/r?a=1&amp;b=2"}.get(
        site.key, "The record they point to")
    assert html == (
        '<div class="statement" role="note" id="statement-7" aria-labelledby="statement-7-h" data-nosnippet>'
        '<h2 class="statement-head" id="statement-7-h">Statement from Jane Example, 12 November 2026</h2>'
        '<p class="statement-role">Chief executive, Example Housing</p>'
        '<blockquote class="statement-text"><p>Line one &lt;b&gt;bold&lt;/b&gt;<br>line two</p><p>para two</p>'
        "</blockquote>"
        '<p class="statement-link"><a href="https://example.org/r?a=1&amp;b=2" '
        f'rel="nofollow ugc noopener noreferrer">{link_words}</a></p>'
        f'<p class="statement-note">In their own words. Not checked or endorsed by {site.messages.site}.</p></div>')
    assert "updated" not in html and "Right of reply" not in html and "Response" not in html


def test_the_whole_statement_is_kept_out_of_what_a_search_engine_quotes(site):
    """ADR 0008, question 1: shown to every reader beside the item, never quoted as the site's own words. Search
    engines honour ``data-nosnippet`` on a div, a span or a section."""
    html = statement_html(shown(link="https://example.org/r"), site.messages)
    opening = re.match(r"<div [^>]*>", html)
    assert opening and "data-nosnippet" in opening.group(0)
    assert html.count("<div") == 1 and html.endswith("</p></div>")  # everything is inside it
    assert html.rindex(site.messages.site) > html.index("example.org/r")  # the disclaimer comes last


@pytest.mark.parametrize("field, hostile", [
    ("name", "<script>alert(1)</script>"),
    ("name", '"><img src=x onerror=alert(1)>'),
    ("name", "Steve <Houghton> & {site} {0} {name}"),
    ("role", "Leader</p></div><script>alert(2)</script>"),
    ("text", "</blockquote><script>alert(3)</script>\n\n<a href='javascript:alert(4)'>read this</a>"),
    ("text", "one & two < three > four \"five\" 'six'"),
    ("link", "javascript:alert(1)"),
    ("link", "data:text/html,<script>alert(1)</script>"),
    ("link", "https://example.org/\"onmouseover=\"alert(1)"),
    ("link", "https://example.org/'><script>alert(1)</script>"),
    ("link", "https://example.org/a b"),
    ("link", "//example.org/x"),
    ("link", "ftp://example.org/minutes"),
    ("id", '7" onclick="alert(1)'),
])
def test_a_hostile_name_text_or_link_is_escaped(site, field, hostile):
    """A row that reached the database some other way than the form can never become markup or a link that runs a
    script: every value is escaped, and the link's scheme is checked again when it is shown."""
    html = statement_html(shown(link="https://example.org/r") | {field: hostile}, site.messages)
    page = Seen()
    page.feed(html)
    assert set(page.tags) <= {"div", "h2", "p", "blockquote", "br", "a"}  # no element but the statement's own
    assert {name for name, _ in page.attrs} <= {"class", "role", "id", "aria-labelledby", "data-nosnippet", "href",
                                                "rel"}  # and no attribute smuggled into one of them
    if field == "link":  # not an ordinary web address: no link at all, and nothing of it on the page
        assert "a" not in page.tags and "statement-link" not in html and "alert" not in html
    else:  # what was sent is read as it was written, and the only link is the one to the record
        assert dict(page.attrs)["href"] == "https://example.org/r" and page.tags.count("a") == 1
        assert dict(page.attrs)["rel"] == "nofollow ugc noopener noreferrer"
    if field in ("name", "role"):
        assert hostile in "".join(page.text)


def test_the_words_are_text_never_markup(site):
    html = statement_html(shown(name="Steve <Houghton>", text="First para.\n\nSecond.\r\n \n  Third, <i>as written</i>."),
                          site.messages)
    assert ">Statement from Steve &lt;Houghton&gt;, 12 November 2026</h2>" in html
    assert "<p>First para.</p><p>Second.</p><p>Third, &lt;i&gt;as written&lt;/i&gt;.</p>" in html
    braces = statement_html(shown(name="{site}", role="{0}", text="{name} {date} {link}"), site.messages)
    assert "Statement from {site}, 12 November 2026" in braces and "<p>{name} {date} {link}</p>" in braces


def test_only_an_ordinary_web_address_is_ever_made_a_link():
    good = "https://barnsley.moderngov.co.uk/ieListDocuments.aspx?CId=137&MId=1"
    assert safe_link(good) == good and safe_link("HTTP://EXAMPLE.ORG/x") == "HTTP://EXAMPLE.ORG/x"
    for bad in ("javascript:alert(1)", "data:text/html,x", "https://example.org/a b", "//example.org", "", None,
                "https://example.org/\"x", "ftp://example.org/minutes", "https://example.org/<x>",
                " https://example.org/x", "https://example.org/x\n", "https://"):
        assert safe_link(bad) is None, bad
    messages = SITES["councils"].messages
    assert "The record they point to" in statement_html(shown(link=good), messages)
    without = statement_html(shown(link="javascript:alert(1)"), messages)
    assert "javascript" not in without and "The record they point to" not in without and WORDS in without


def test_the_heading_gives_the_date_of_the_words_shown(site):
    sid = site.send()
    site.show(sid, about="someone")
    [first] = site.replies.published(everywhere=True)
    assert f"Statement from {site.case.statement['name']}, 13 November 2026</h2>" in statement_html(first, site.messages)
    site.clock.advance(days=19)
    site.replies.update(sid, text="Our newer results are published every quarter on our website.")
    [newer] = site.replies.published(everywhere=True)
    html = statement_html(newer, site.messages)
    assert ", 2 December 2026</h2>" in html and "every quarter" in html and "13 November" not in html  # the newer version
    assert site.case.statement["email"] not in html


def test_dates_are_written_as_the_sites_write_them():
    assert long_date("2026-11-02") == "2 November 2026" and long_date("2026-11-12T10:00:00+00:00") == "12 November 2026"
    assert long_date(date(2028, 2, 29)) == "29 February 2028" and long_date(None) == "" and long_date("") == ""
    assert [long_date(f"2026-{m:02d}-01").split()[1] for m in range(1, 13)] == [
        "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
        "December"]


def test_the_heading_takes_the_level_its_place_on_the_page_needs():
    messages = SITES["landlords"].messages
    for level, tag in ((2, "h2"), (3, "h3"), (4, "h4"), (0, "h1"), (9, "h6")):
        html = statement_html(shown(), messages, level=level)
        assert f'<{tag} class="statement-head" id="statement-7-h">' in html and f"</{tag}>" in html
    assert '<h2 class="statement-head"' in statement_html(shown(), messages)


def test_the_words_shown_with_a_statement_are_the_sites_own():
    theirs = dataclasses.replace(SITES["mps"].messages, heading="Datganiad gan {name}, {date}",
                                 disclaimer="Yn eu geiriau eu hunain. Heb ei wirio gan {site}.", record_link="Y cofnod",
                                 site="Ble Mae ASau'n Sefyll")
    html = statement_html(shown(link="https://example.org/r"), theirs)
    assert ">Datganiad gan Jane Example, 12 November 2026</h2>" in html and ">Y cofnod</a>" in html
    assert html.endswith('<p class="statement-note">Yn eu geiriau eu hunain. Heb ei wirio gan Ble Mae ASau&#x27;n '
                         "Sefyll.</p></div>")
