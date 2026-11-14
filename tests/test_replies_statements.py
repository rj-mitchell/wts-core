"""Statements under the right of reply: what is accepted, the owner's decisions, and what is shown.

The four sites' own tests of this (docs/study/reports-statements.md, section 5), brought to the package's interface
and run over every site's rules and words. What a site tested through its routes or its commands is tested here at
the method the route or command will call; the HTTP status, the page and the command's printed line stay each
site's to test.
"""

from __future__ import annotations

import json
import re

import pytest

from test_replies_sites import (
    BARNSLEY,
    SITES,
    VOTE,
    CountriesItems,
    Open,
    one_site,
    site_fixture,
)
from wts_core.replies import PUBLIC_FIELDS, Item, NotDone, Refused

site = site_fixture()
mps, countries, councils, landlords = one_site("mps"), one_site("countries"), one_site("councils"), \
    one_site("landlords")

WORDS_150 = " ".join(["word"] * 150)
NEW = "Having read the debate again, I stand by every word of what I said about juries then."
REFUSALS = [pytest.param(key, over, says, id=f"{key}-{'-'.join(over)}-{n}")
            for key, case in SITES.items() for n, (over, says) in enumerate(case.refusals)]


def refusal(site: Open, **over) -> Refused:
    with pytest.raises(Refused) as caught:
        site.replies.submit(**site.body(**over))
    return caught.value


def not_done(what, *args, **kw) -> str:
    with pytest.raises(NotDone) as caught:
        what(*args, **kw)
    return str(caught.value)


def shown(site: Open, **kw) -> list[dict]:
    return site.replies.published(**(kw or {"items": [site.case.address]}))


# ---- what is accepted --------------------------------------------------------------------------------------------

def test_a_statement_is_received_as_waiting_and_not_shown(site):
    sid = site.send()
    s = site.replies.statement(sid)
    assert s["status"] == "pending" and s["item"] == site.case.address and s["about"] == site.case.about
    sent = site.case.statement
    assert (s["name"], s["role"], s["text"], s["link"], s["email"]) == \
        (sent["name"], sent["role"], sent["text"], sent["link"], sent["email"])
    assert s["at"] == site.clock.now().isoformat(timespec="seconds") and s["published_at"] is None
    assert [e["action"] for e in site.replies.log(sid)] == ["received"]
    assert shown(site) == [] and shown(site, everywhere=True) == []  # not until published
    assert site.replies.statements("pending") == [s] and site.replies.statements("published") == []


@pytest.mark.parametrize("key, over, says", REFUSALS)
def test_a_statement_that_breaks_the_rules_is_refused_in_the_sites_words(tmp_path, key, over, says):
    site = Open(SITES[key], tmp_path)
    assert says in str(refusal(site, **over))
    assert site.replies.statements() == []
    assert site.rows("SELECT * FROM wts_statement_log") == [] and site.rows("SELECT * FROM wts_reply_counts") == []


@pytest.mark.parametrize("missing", ["name", "role", "item", "text", "email"])
def test_every_required_field_is_required(site, missing):
    for nothing in ("", " ", None):
        refusal(site, **{missing: nothing})
    assert site.replies.statements() == []


def test_exactly_150_words_and_no_link_are_accepted(site):
    with_link = site.send(text=WORDS_150)
    assert site.replies.statement(with_link)["text"] == WORDS_150
    for no_link in (None, "", "  "):
        assert site.replies.statement(site.send(link=no_link))["link"] is None  # the link is optional
    assert "151" in str(refusal(site, text=WORDS_150 + " word"))
    assert refusal(site, text=WORDS_150 + " word").why == "too_many_words"
    assert len(site.replies.statements()) == 4


def test_a_statement_is_kept_as_written(site):
    """Never edited (policy 7.2): only the line endings are made plain and runs of blank lines closed up, as Where
    MPs Stand and Where Landlords Stand do. A browser sends each line break as two characters."""
    as_written = "First paragraph.\n\nSecond   paragraph, as written."
    assert site.replies.statement(site.send(text=as_written))["text"] == as_written
    assert site.replies.statement(site.send(text="  " + WORDS_150 + "\n"))["text"] == WORDS_150
    tidied = site.replies.statement(site.send(text="One line here.\r\nThe next.\r\rA new paragraph.\n\n\n\nThe last."))
    assert tidied["text"] == "One line here.\nThe next.\n\nA new paragraph.\n\nThe last."


def test_a_name_and_role_are_kept_on_one_line(site):
    """A name or role is never blank or only spaces (Where Countries Stand's check_line); spaces around and within
    are tidied."""
    s = site.replies.statement(site.send(name="  Steve   Houghton ", role=" Leader of\n the  council "))
    assert (s["name"], s["role"]) == ("Steve Houghton", "Leader of the council")
    for bad in ("", " ", "X", "  \t ", " \n\tX ", "   ", None):
        assert refusal(site, name=bad).why == "name_missing"
        assert str(refusal(site, role=bad)) == site.messages.role_missing


def within(site: Open) -> dict[str, str]:
    """A statement with every part exactly as long as the site allows."""
    r = site.rules
    return {"name": "N" * r.name_max, "role": "R" * r.role_max,
            "text": " ".join(["a" * 20] + ["b" * 19] * (r.max_chars // 20 - 1)),
            "link": "https://example.org/" + "a" * (r.link_max - 20), "email": "a" * (r.email_max - 12) + "@example.org"}


def test_what_is_just_within_the_limits_is_kept_as_written(site):
    exact = within(site)
    r = site.rules
    assert [len(v) for v in exact.values()] == [r.name_max, r.role_max, r.max_chars, r.link_max, r.email_max]
    kept = site.replies.statement(site.send(**exact))
    assert {k: kept[k] for k in exact} == exact
    # a browser sends each line break as two characters: they are counted as one, as its own limit counts them
    lines = site.replies.statement(site.send(text=exact["text"].replace(" ", "\r\n")))
    assert lines["text"] == exact["text"].replace(" ", "\n") and len(lines["text"]) == r.max_chars


def test_what_is_too_long_is_refused_never_cut_to_fit(site):
    """A statement is published as written or declined, never edited: so one longer than a limit is refused, with
    words for the sender, where Where Landlords Stand used to cut it at the limit and keep it."""
    exact, r, m = within(site), site.rules, site.messages
    over = {"text": (exact["text"] + "b", "too_many_chars",
                     m.too_many_chars.format(words=150, max=r.max_chars, n=r.max_chars + 1)),
            "name": (exact["name"] + "N", "name_too_long", m.name_too_long.format(max=r.name_max, n=r.name_max + 1)),
            "role": (exact["role"] + "R", "role_too_long", m.role_too_long.format(max=r.role_max, n=r.role_max + 1)),
            "link": (exact["link"] + "a", "link_too_long", m.link_too_long.format(max=r.link_max, n=r.link_max + 1)),
            "email": ("a" + exact["email"], "bad_email", m.bad_email)}
    for part, (value, why, says) in over.items():
        refused = refusal(site, **{part: value})
        assert (refused.why, str(refused)) == (why, says), part
    assert site.replies.statements() == []


def test_mps_a_statement_is_only_accepted_beside_an_item_that_exists(mps):
    assert "There is no briefing at that address" in str(refusal(mps, item="/b/zzzzzzzzzz"))  # well formed; none
    nobody = refusal(mps, item="https://wherempsstand.com/people/99999999/no-one")
    assert "There is no member's page at that address" in str(nobody)
    assert mps.replies.statements() == []
    for there in ("/b/abcdefghjk", "/people/10669", "/groups/commons/no-such-group"):
        mps.send(item=there)  # the other kinds of page are not looked up: the owner sees the address first
    assert {s["item"] for s in mps.replies.statements()} == {"/b/abcdefghjk", "/people/10669",
                                                             "/groups/commons/no-such-group"}
    mps.items.briefings["abcdefghjk"] = True  # a withdrawn briefing takes no new statements
    assert "has been withdrawn" in str(refusal(mps, item="/b/abcdefghjk"))
    assert len(mps.replies.statements()) == 3
    # the other checks still come first
    assert "a sentence or more" in str(refusal(mps, item="/b/zzzzzzzzzz", text="Too short."))


def test_countries_a_statement_is_not_accepted_beside_a_missing_or_withdrawn_briefing(countries):
    assert "no briefing at that address" in str(refusal(countries, item="/b/nosuchbriefing"))
    countries.send()
    countries.items.briefings["AbC123xy"] = True
    gone = refusal(countries)
    assert gone.why == "item_not_shown" and str(gone) == countries.messages.item_not_shown
    assert len(countries.replies.statements()) == 1


def test_countries_the_test_servers_own_address_is_this_site(countries):
    """The app adds its configured address and the request's own host to the site's. A site that knows more than
    its ``Items`` does resolves the address itself and hands the package the item."""
    assert "wherecountriesstand.com" in str(refusal(countries, item="http://testserver/b/AbC123xy"))
    here = CountriesItems(("countries.example", "testserver"))
    for address in ("https://countries.example/b/AbC123xy", "http://testserver/b/AbC123xy"):
        sid = countries.send(item=here.resolve(address))
        assert countries.replies.statement(sid)["item"] == "/b/AbC123xy"
    # and so keeps its own order: the address is read before the words are counted
    with pytest.raises(Refused, match="a briefing on this site"):
        countries.replies.submit(**countries.body(item=here.resolve("/about.html"), text=""))
    assert refusal(countries, item="/about.html", text="").why == "too_few_words"


def test_councils_a_statement_beside_a_withdrawn_briefing_is_refused(councils):
    councils.send(item="/b/abc123")
    councils.items.briefings["abc123"] = True
    assert "no page at that address" in str(refusal(councils, item="/b/abc123"))
    assert len(councils.replies.statements()) == 1
    beside_the_council = councils.replies.statement(councils.send(item=f"/councils/{BARNSLEY.lower()}"))
    assert (beside_the_council["item"], beside_the_council["about"]) == (f"/councils/{BARNSLEY}", BARNSLEY)


def test_landlords_a_statement_can_sit_beside_a_part_of_a_landlords_page(landlords):
    from_fragment = landlords.send(item="https://wherelandlordsstand.com/landlords/example-housing/#bands")
    from_the_form = landlords.send(item=landlords.items.with_part("landlords/example-housing/", "safety"))
    on_an_area = landlords.send(item=landlords.items.with_part("areas/leeds/", "grade"))
    rows = {s["id"]: (s["item"], s["part"], s["about"]) for s in landlords.replies.statements()}
    assert rows == {from_fragment: ("landlords/example-housing/", "bands", "example-housing"),
                    from_the_form: ("landlords/example-housing/", "safety", "example-housing"),
                    on_an_area: ("areas/leeds/", "", None)}
    landlords.show(from_fragment)
    assert [(s["item"], s["part"]) for s in shown(landlords, everywhere=True)] == \
        [("landlords/example-housing/", "bands")]


def test_no_statement_is_taken_beside_an_item_hidden_while_a_concern_is_decided(site):
    site.replies.hide(site.case.address, "Hidden while we look into a concern about it.")
    hidden = refusal(site)
    assert (hidden.why, str(hidden)) == ("item_not_shown", site.messages.item_not_shown)
    site.replies.unhide(site.case.address)
    assert site.send()


# ---- the item is looked at again when a statement is published -------------------------------------------------------


def _whom(site: Open) -> dict:
    return {"about": "example-housing"} if site.key == "landlords" else {}


def test_a_statement_is_not_published_beside_an_item_that_has_gone_since_it_was_sent(site):
    """Weeks can pass between a statement arriving and the owner deciding. Where Landlords Stand's own command
    refused a landlord whose page had gone ("no landlord's page … on the site"); every site now refuses."""
    sid = site.send()
    stored = site.replies.statement(sid)
    asked: list[Item] = []

    def gone(item: Item) -> bool:
        asked.append(item)
        return False

    was, site.items.shown = site.items.shown, gone
    with pytest.raises(NotDone) as refused:
        site.show(sid, **_whom(site))
    assert str(refused.value) == (f"statement {sid} is beside {stored['item']}, which is no longer shown on the "
                                  "site: decline the statement, saying why, or put the item back first")
    # the site was asked about the item as stored, with whom the statement would speak for
    assert asked == [Item(address=stored["item"], about=_whom(site).get("about") or stored["about"],
                          part=stored["part"] or "")]
    # nothing was changed, and nothing is shown
    assert site.replies.statement(sid) == stored and site.replies.published(everywhere=True) == []
    assert [e["action"] for e in site.replies.log(sid)] == ["received"]
    site.items.shown = was  # the item is back: now it is published
    site.show(sid, **_whom(site))
    assert site.replies.statement(sid)["status"] == "published"


def test_the_sites_own_words_for_why_an_item_is_not_shown_reach_the_owner(site):
    sid = site.send()

    def withdrawn(item: Item) -> bool:
        raise Refused("That briefing has been withdrawn, so a statement can't be shown beside it.", "item_not_shown")

    site.items.shown = withdrawn
    with pytest.raises(NotDone, match=r"which cannot be shown: That briefing has been withdrawn, so a statement "
                                      r"can't be shown beside it\.$"):
        site.show(sid, **_whom(site))
    assert site.replies.statement(sid)["status"] == "pending"


def test_a_statement_is_not_published_beside_an_item_hidden_while_a_concern_is_decided(site):
    sid = site.send()
    address = site.replies.statement(sid)["item"]
    site.replies.hide(address, "Hidden while we look into a concern about it.")
    with pytest.raises(NotDone, match=rf"statement {sid} is beside {re.escape(address)}, which is hidden while a "
                                      "concern is decided: show the item again"):
        site.show(sid, **_whom(site))
    assert site.replies.statement(sid)["status"] == "pending"
    site.replies.unhide(address)
    site.show(sid, **_whom(site))
    assert [s["id"] for s in site.replies.published(everywhere=True)] == [sid]


def test_landlords_a_statement_is_not_published_once_its_landlords_page_has_gone(landlords):
    sid = landlords.send()  # beside landlords/example-housing/, which says whom it speaks for
    landlords.items.pages.discard("landlords/example-housing/")  # the landlord has left the register since
    with pytest.raises(NotDone, match="is beside landlords/example-housing/, which is no longer shown on the site"):
        landlords.show(sid)
    landlords.items.pages.add("landlords/example-housing/")
    landlords.show(sid)
    assert landlords.replies.statement(sid)["about"] == "example-housing"


# ---- the trap, and the daily limit --------------------------------------------------------------------------------

def test_the_trap_field_keeps_nothing_and_there_is_a_daily_limit(site):
    assert site.replies.submit(**site.body(), visitor="v1", trap="http://spam.example") is None  # thanked like anyone
    assert site.replies.statements() == [] and site.rows("SELECT * FROM wts_reply_counts") == []
    assert site.replies.submit(**site.body(), visitor="v1", trap=" ")  # left empty, as people leave it: kept
    limit = site.rules.daily_statements
    for _ in range(limit - 1):
        assert site.replies.submit(**site.body(), visitor="v1")
    with pytest.raises(Refused) as sixth:
        site.replies.submit(**site.body(), visitor="v1")
    assert (sixth.value.why, str(sixth.value)) == ("daily_statements", site.messages.daily_statements)
    assert limit == 5 and len(site.replies.statements()) == 5
    assert site.replies.submit(**site.body(), visitor="v2")  # someone else is not held up
    assert site.replies.submit(**site.body())  # nor the owner's own tools, which give no visitor
    # one that was refused did not count against its sender
    for _ in range(3):
        refusal(site, text="", visitor="v2")
    assert site.rows("SELECT visitor, what, n FROM wts_reply_counts ORDER BY visitor") == [
        {"visitor": "v1", "what": "statement", "n": 5}, {"visitor": "v2", "what": "statement", "n": 1}]


def test_the_days_counts_are_emptied_and_nothing_else_holds_a_visitor_code(site):
    for _ in range(site.rules.daily_statements):
        site.replies.submit(**site.body(), visitor="code-of-12-november")
    site.clock.advance(days=1)  # the codes change at midnight; a new day starts the count again
    assert site.replies.submit(**site.body(), visitor="code-of-13-november")
    assert site.rows("SELECT * FROM wts_reply_counts") == [
        {"day": "2026-11-14", "visitor": "code-of-13-november", "what": "statement", "n": 1}]
    site.clock.advance(days=1)
    assert site.replies.submit(**site.body())  # a write with no code still empties the earlier days
    assert site.rows("SELECT * FROM wts_reply_counts") == []
    # the count is the only place a code is ever kept: no statement, report or log entry carries one
    with site.db.connect() as con:
        everything = "\n".join(con.iterdump())
    assert "code-of-" not in everything
    for table in ("wts_statements", "wts_statement_log", "wts_reports", "wts_hidden"):
        assert "visitor" not in {r["name"] for r in site.rows(f"PRAGMA table_info({table})")}, table


# ---- the owner's decisions -----------------------------------------------------------------------------------------

def test_publishing_needs_a_note_of_how_the_sender_was_confirmed(site):
    sid = site.send()
    for unsaid in ("", "   ", None):
        assert "how you confirmed who sent it" in not_done(site.replies.publish, sid, checked=unsaid)
    assert site.replies.statement(sid)["status"] == "pending" and shown(site) == []
    note = "Replied from the address on the council's website, 12 November."
    site.replies.publish(sid, checked=f"  {note}\n")
    assert site.replies.statement(sid)["status"] == "published"
    assert [(e["action"], e["note"]) for e in site.replies.log(sid)] == [("received", None), ("published", note)]
    assert [s["id"] for s in shown(site)] == [sid]
    # the note is kept in the log, which only the owner reads: never beside the statement
    assert "council's website" not in json.dumps(shown(site)) + json.dumps(site.replies.statement(sid))
    assert not_done(site.replies.publish, sid, checked="again") == f"statement {sid} is published, not pending"
    assert not_done(site.replies.publish, 999, checked="x") == "no statement 999"


def test_the_note_cannot_hold_the_senders_address(site):
    """The note is kept for good; the address is promised to be deleted. Where Landlords Stand's guide once showed
    the address in the note (the study's privacy finding 1)."""
    sid = site.send()
    email = site.case.statement["email"]
    assert "leave their email address out" in not_done(site.replies.publish, sid,
                                                       checked=f"reply from {email.upper()}, 14 Nov")
    assert site.replies.statement(sid)["status"] == "pending"
    site.replies.publish(sid, checked="reply from the landlord's own address, 14 Nov")


def test_mps_a_statement_about_another_page_is_given_its_member_when_published(mps):
    benn = mps.send()
    group = mps.send(item="/groups/commons/socialist-campaign-group")
    assert mps.replies.statement(group)["about"] is None
    mps.show(benn)
    assert [s["item"] for s in shown(mps, about="10669")] == ["/people/10669"]
    mps.clock.advance(60)
    mps.show(group, about="10669")
    both = shown(mps, about="10669")
    assert [s["item"] for s in both] == ["/people/10669", "/groups/commons/socialist-campaign-group"]
    assert set(both[0]) == set(PUBLIC_FIELDS)  # never the email
    assert "parliament.uk" not in json.dumps(both).replace("hansard.parliament.uk", "")
    beside = shown(mps, items=["https://wherempsstand.com/groups/commons/socialist-campaign-group"])
    assert [s["id"] for s in beside] == [group]
    assert shown(mps, items=[]) == [] and mps.replies.published() == []  # nothing asked for, nothing given
    assert shown(mps, items=["/about", "javascript:alert(1)", "/people/10669"]) == [both[0]]  # bad ones passed over


def test_countries_a_statement_can_be_given_the_country_it_speaks_for(countries):
    sid = countries.send(text="First paragraph.\n\nSecond paragraph.")
    countries.show(sid, about="KEN")
    [public] = shown(countries)
    assert public == {"id": sid, "item": "/b/AbC123xy", "part": "", "about": "KEN", "name": "Ms. Amina Odhiambo",
                      "role": "Deputy Permanent Representative of Kenya to the United Nations",
                      "text": "First paragraph.\n\nSecond paragraph.", "link": "https://undocs.org/en/A/79/123",
                      "date": "2026-11-13"}
    assert shown(countries, about="KEN") == [public] and shown(countries, about="UGA") == []
    assert shown(countries, items=["/b/otherbriefing"]) == []
    # whom it speaks for can be put right after publishing too, and that does not change its date
    countries.clock.advance(days=3)
    countries.replies.update(sid, about="UGA")
    assert shown(countries, about="UGA") == [{**public, "about": "UGA"}]
    assert countries.replies.log(sid)[-1]["previous"] == {"about": "KEN"}


def test_councils_a_statement_about_a_briefing_is_put_on_its_councils_page_by_the_owner(councils):
    first = councils.send()
    second = councils.send(item="/b/abc123", name="Barnsley Council", role="Democratic services", text="Our view.")
    assert councils.replies.statement(second)["about"] is None
    councils.show(first)
    councils.clock.advance(60)
    councils.show(second, about=BARNSLEY)
    on_page = shown(councils, about=BARNSLEY)
    assert [s["id"] for s in on_page] == [first, second] and "email" not in on_page[0]
    assert [s["item"] for s in on_page] == [f"/votes/{VOTE}", "/b/abc123"]
    assert [s["id"] for s in shown(councils, items=[f"https://wherecouncilsstand.com/votes/{VOTE}"])] == [first]


def test_landlords_a_statement_about_an_areas_page_needs_its_landlord(landlords):
    own = landlords.send()
    area = landlords.send(item="https://wherelandlordsstand.com/areas/leeds/", name="Sam Officer",
                          role="Head of housing, Example Council")
    landlords.show(own)  # its own page says which landlord
    assert not_done(landlords.replies.publish, area, checked="phoned the council") == \
        f"statement {area} is beside areas/leeds/: say whom it speaks for (about)"
    landlords.replies.publish(area, checked="phoned the council", about="example-council")
    assert [(s["item"], s["about"]) for s in shown(landlords, everywhere=True)] == [
        ("landlords/example-housing/", "example-housing"), ("areas/leeds/", "example-council")]
    assert [s["name"] for s in shown(landlords, about="example-council")] == ["Sam Officer"]


def test_the_authors_new_words_are_shown_as_written_with_the_new_date(site):
    sid = site.send()
    site.show(sid)
    old = site.case.statement
    assert shown(site)[0]["date"] == "2026-11-13"
    site.clock.advance(days=1)
    site.replies.update(sid, text=NEW + "\r\n")
    [s] = shown(site)
    assert s["text"] == NEW and s["date"] == "2026-11-14" and s["link"] == old["link"]
    row = site.replies.statement(sid)
    assert row["published_at"].startswith("2026-11-13") and row["updated_at"].startswith("2026-11-14")  # both kept
    # the words it replaced are kept in the log (policy 7.4), which no site did before
    last = site.replies.log(sid)[-1]
    assert (last["action"], last["note"], last["previous"]) == ("updated", "text", {"text": old["text"]})

    # an update keeps to the rules too, and is never cut to fit either
    with pytest.raises(Refused, match="150 words"):
        site.replies.update(sid, text=" ".join(["w"] * 151))
    exact = within(site)
    for part, why in (("text", "too_many_chars"), ("name", "name_too_long"), ("role", "role_too_long"),
                      ("link", "link_too_long")):
        with pytest.raises(Refused) as too_long:
            site.replies.update(sid, **{part: exact[part] + "x"})
        assert too_long.value.why == why
    for part in ("name", "role"):  # a name or role can't be changed to nothing
        with pytest.raises(Refused) as blank:
            site.replies.update(sid, **{part: "   "})
        assert blank.value.why == f"{part}_missing"
    with pytest.raises(Refused, match="web address"):
        site.replies.update(sid, link="javascript:alert(1)")
    assert shown(site) == [s] and len(site.replies.log(sid)) == 3

    site.replies.update(sid, link="")  # an empty link removes it
    assert shown(site)[0]["link"] is None
    site.replies.update(sid, link="https://example.org/record", role="  Leader of  the council ",
                        note="the author's new version")
    assert (shown(site)[0]["link"], shown(site)[0]["role"]) == ("https://example.org/record", "Leader of the council")
    assert site.replies.log(sid)[-1] == {"at": "2026-11-14T12:00:00+00:00", "action": "updated",
                                         "note": "the author's new version",
                                         "previous": {"link": None, "role": old["role"]}}
    site.replies.update(sid, clear_link=True)
    assert shown(site)[0]["link"] is None and site.replies.log(sid)[-1]["note"] == "link"
    assert "nothing to change" in not_done(site.replies.update, sid)
    assert "nothing to change" in not_done(site.replies.update, sid, about="  ")
    assert not_done(site.replies.update, 999, text=NEW) == "no statement 999"


def test_a_waiting_statement_updated_is_dated_when_it_is_published(site):
    sid = site.send()
    site.clock.advance(days=1)
    site.replies.update(sid, text=NEW)
    assert site.replies.statement(sid)["status"] == "pending" and shown(site) == []
    site.clock.advance(days=4)
    site.show(sid)
    assert [(s["text"], s["date"]) for s in shown(site)] == [(NEW, "2026-11-18")]


def test_declined_withdrawn_and_removed_each_say_what_happened(site):
    """Five statuses, so the log always says what happened (ADR 0008). "Declined" always means never shown: Where
    MPs Stand declined a published statement to take it down, and the others withdrew it with a reason."""
    declined, withdrawn, removed, waiting = (site.send() for _ in range(4))
    for no_reason in ("", "     ", None):
        assert "give the reason" in not_done(site.replies.decline, declined, no_reason)
    site.replies.decline(declined, " It is about another member's conduct. ")
    row = site.replies.statement(declined)
    assert (row["status"], row["reason"], row["closed_at"]) == \
        ("declined", "It is about another member's conduct.", "2026-11-13T12:00:00+00:00")

    for sid in (withdrawn, removed):
        site.show(sid)
    assert not_done(site.replies.decline, removed, "Too late.") == f"statement {removed} is published, not pending"
    assert "give the reason" in not_done(site.replies.remove, removed, " ")
    assert not_done(site.replies.remove, waiting, "It appeals for votes.") == \
        f"statement {waiting} is pending, not published"
    site.replies.remove(removed, "It appeals for votes.")
    site.replies.withdraw(withdrawn)  # at its author's request: a note is recorded if one is given
    site.replies.withdraw(waiting, "Withdrawn by its author.")
    rows = {s["id"]: (s["status"], s["reason"]) for s in site.replies.statements()}
    assert rows == {declined: ("declined", "It is about another member's conduct."), withdrawn: ("withdrawn", None),
                    removed: ("removed", "It appeals for votes."), waiting: ("withdrawn", "Withdrawn by its author.")}
    assert shown(site, everywhere=True) == []
    assert [(e["action"], e["note"]) for e in site.replies.log(removed)][-1] == ("removed", "It appeals for votes.")
    assert [e["action"] for e in site.replies.log(waiting)] == ["received", "withdrawn"]

    # a declined, withdrawn or removed statement can't be published or changed again
    for sid, status in ((declined, "declined"), (withdrawn, "withdrawn"), (removed, "removed")):
        assert not_done(site.replies.publish, sid, checked="again") == f"statement {sid} is {status}, not pending"
        assert not_done(site.replies.update, sid, text=NEW) == f"statement {sid} is {status}, not pending or published"
        assert not_done(site.replies.withdraw, sid) == f"statement {sid} is {status}, not pending or published"
        assert not_done(site.replies.decline, sid, "again") == f"statement {sid} is {status}, not pending"
        assert not_done(site.replies.remove, sid, "again") == f"statement {sid} is {status}, not published"
    assert not_done(site.replies.withdraw, 999) == "no statement 999"
    assert {s["id"]: s["status"] for s in site.replies.statements()} == {
        declined: "declined", withdrawn: "withdrawn", removed: "removed", waiting: "withdrawn"}


def test_the_log_gives_every_action_in_order(site):
    sid = site.send()
    site.show(sid)
    site.clock.advance(3600)
    site.replies.update(sid, text=NEW)
    site.clock.advance(3600)
    site.replies.withdraw(sid, "withdrawn by the author")
    log = site.replies.log(sid)
    assert [e["action"] for e in log] == ["received", "published", "updated", "withdrawn"]
    assert [e["at"][11:16] for e in log] == ["12:00", "12:00", "13:00", "14:00"]
    assert log[-1]["note"] == "withdrawn by the author" and site.replies.log(999) == []


def test_the_owner_lists_statements_newest_first_with_what_only_the_owner_sees(site):
    first, second, third = (site.send(name=name) for name in ("First Sender", "Second Sender", "Third Sender"))
    site.show(second)
    site.replies.decline(third, "It appeals for votes.")
    assert [s["id"] for s in site.replies.statements()] == [third, second, first]
    assert all(s["email"] == site.case.statement["email"] for s in site.replies.statements())
    assert [s["id"] for s in site.replies.statements("pending")] == [first]
    assert [s["id"] for s in site.replies.statements("published")] == [second]
    assert [(s["id"], s["reason"]) for s in site.replies.statements("declined")] == [(third, "It appeals for votes.")]
    assert site.replies.statements("removed") == [] and site.replies.statement(999) is None
    assert "no such status" in not_done(site.replies.statements, "shown")


# ---- what is shown -------------------------------------------------------------------------------------------------

def test_published_statements_are_given_oldest_first_by_the_date_of_the_words_shown(site):
    first, second, third = (site.send() for _ in range(3))
    for sid in (first, second, third):
        site.show(sid)
        site.clock.advance(3600)
    assert [s["id"] for s in shown(site)] == [first, second, third]
    site.replies.update(first, text=NEW)  # its words are now the newest
    assert [s["id"] for s in shown(site)] == [second, third, first]
    site.replies.withdraw(second)
    assert [s["id"] for s in shown(site, everywhere=True)] == [third, first]
    assert shown(site, items=[Item(site.case.address)]) == shown(site)  # an item already resolved is taken as it is


def test_a_statement_is_hidden_with_the_item_it_sits_beside(site):
    sid = site.send()
    site.show(sid)
    site.replies.hide(site.case.address, "Hidden while we look into a concern about it.")
    assert shown(site) == [] and shown(site, everywhere=True) == []
    if site.case.about:
        assert shown(site, about=site.case.about) == []
    assert site.replies.statement(sid)["status"] == "published"  # hidden, not withdrawn
    site.replies.unhide(site.case.address)
    assert [s["id"] for s in shown(site)] == [sid]
