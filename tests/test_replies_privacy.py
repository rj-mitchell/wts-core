"""What the public can see of a statement, and how long a sender's address is kept.

The sites' own tests of the three months (each to the minute or the hour, and 31 May back to 28 February), run over
every site, with the cases none of them had: a leap year, a statement nobody decided, a report nobody closed, and
the address written into a note.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_replies_sites import Open, site_fixture

import wts_core.replies
from wts_core.replies import PUBLIC_FIELDS, Refused, months_before, statement_html

site = site_fixture()

CHECKED = "Reply from the mission's published address, 14 November."
NOTE = "Hidden while we look into a concern about it."


def emails(site: Open) -> dict[int, str | None]:
    return {r["id"]: r["email"] for r in site.rows("SELECT id, email FROM wts_statements")}


def everything_kept(site: Open) -> str:
    with site.db.connect() as con:
        return "\n".join(con.iterdump())


# ---- what the public may see ---------------------------------------------------------------------------------------

def test_the_public_fields_are_exactly_these():
    assert PUBLIC_FIELDS == ("id", "item", "part", "about", "name", "role", "text", "link", "date")


def test_what_is_shown_is_the_public_fields_and_nothing_else(site):
    sid = site.send()
    site.replies.publish(sid, checked=CHECKED, about=site.case.about or "someone")
    site.replies.update(sid, role="Leader of the council", note="the author's new version, by email")
    for asked in ({"items": [site.case.address]}, {"about": site.case.about or "someone"}, {"everywhere": True}):
        [public] = site.replies.published(**asked)
        assert tuple(public) == PUBLIC_FIELDS, asked  # never the address, the notes or the log
        said = json.dumps(public)
        assert site.case.statement["email"] not in said and "published address" not in said
        assert "new version" not in said and "log" not in public and "email" not in public
    assert site.replies.log(sid)[1]["note"] == CHECKED  # the owner can read it back; no one else


def test_nothing_public_ever_gives_a_senders_address(site, caplog, capsys):
    """Through a statement's whole life and a report's, with everything a page could ask for gathered up. And the
    module writes nothing down but its own tables: no log line, nothing printed."""
    caplog.set_level(logging.DEBUG)
    email, contact = site.case.statement["email"], "reader@example.org"
    public: list[object] = []
    refusals: list[str] = []
    for bad in ({"email": "nobody at all"}, {"text": ""}, {"link": "javascript:alert(1)"}, {"item": "/nowhere/at/all"}):
        with pytest.raises(Refused) as refused:
            site.replies.submit(**site.body(**bad))
        refusals.append(str(refused.value))
    shown, removed, declined = site.send(), site.send(), site.send()
    rid = site.replies.report(**site.case.report, contact=contact, visitor="v1")
    for sid in (shown, removed):
        site.replies.publish(sid, checked=CHECKED, about=site.case.about or "someone")
        public += [statement_html(s, site.messages) for s in site.replies.published(everywhere=True)]
    site.replies.decline(declined, "It is about another person's conduct.")
    site.replies.remove(removed, "It appeals for votes.")
    site.replies.close(rid, outcome="resolved", note=f"Wrote back to {contact}.", public_note="A date was put right.")
    site.replies.hide(site.case.address, NOTE)
    public += [site.replies.published(everywhere=True), site.replies.hidden(site.case.address),
               site.replies.corrections(removed=True), site.replies.waiting()]
    site.replies.unhide(site.case.address)
    public += [site.replies.published(items=[site.case.address]), site.replies.published(about=site.case.about or "x")]
    said = repr(public) + repr(refusals)
    assert email not in said and contact not in said and "nobody at all" not in said
    assert "published address" not in said and "Wrote back" not in said  # nor the owner's private notes
    assert "A date was put right." in said and "It appeals for votes." in said
    assert caplog.records == [] and capsys.readouterr() == ("", "")
    assert email in everything_kept(site)  # it is kept, for the owner: only never given out


def test_the_module_has_nothing_to_log_with():
    for path in Path(wts_core.replies.__file__).parent.glob("*.py"):
        code = path.read_text(encoding="utf-8")
        assert not re.search(r"\bimport logging\b|\bprint\(|\bwarnings\b|sys\.std(out|err)", code), path.name


# ---- three calendar months after a statement ends ------------------------------------------------------------------

@pytest.mark.parametrize("ended, not_yet, by_now", [
    ("2026-08-12T09:00", "2026-11-12T08:59", "2026-11-12T09:01"),  # Where MPs Stand's test: to the minute
    ("2026-08-13T12:00", "2026-11-13T11:00", "2026-11-13T13:00"),  # Where Councils Stand's: to the hour
    ("2026-08-12T10:00", "2026-11-12T09:00", "2026-11-12T11:00"),  # Where Landlords Stand's
    ("2026-11-13T12:00", "2027-02-01T12:00", "2027-02-14T12:00"),  # Where Countries Stand's: 80 days, and 93
    ("2026-08-12T09:00", "2026-11-11T09:01", "2026-11-12T09:00:01"),  # not a day before; a second after
    ("2026-02-28T12:00", "2026-05-27T23:59", "2026-05-28T12:01"),  # the end of February counts from the 28th
    ("2025-11-30T12:00", "2026-02-28T23:59", "2026-03-01T00:00"),  # there is no 30 February: the day after the 28th
    ("2027-11-29T12:00", "2028-02-29T11:59", "2028-02-29T12:01"),  # a leap year has its 29th
    ("2027-11-30T12:00", "2028-02-29T23:59", "2028-03-01T00:00"),
])
def test_the_address_is_deleted_three_months_after_a_statement_ends_and_not_before(site, ended, not_yet, by_now):
    site.clock.set(ended + "+00:00")
    kept, declined, withdrawn, removed = (site.send() for _ in range(4))
    for sid in (kept, withdrawn, removed):
        site.show(sid)  # shown: kept
    site.replies.decline(declined, "It names a member of the public.")
    site.replies.withdraw(withdrawn, "Withdrawn by its author.")
    site.replies.remove(removed, "It appeals for votes.")
    address = site.case.statement["email"]
    site.clock.set(not_yet + "+00:00")
    assert site.replies.forget_old_emails() == 0  # not quite three months
    assert emails(site) == dict.fromkeys((kept, declined, withdrawn, removed), address)
    site.clock.set(by_now + "+00:00")
    assert site.replies.forget_old_emails() == 3
    assert emails(site) == {kept: address, declined: None, withdrawn: None, removed: None}
    assert site.replies.forget_old_emails() == 0  # and only once
    assert site.replies.statement(kept)["email"] == address  # kept while it is shown, however long


def test_three_months_back_from_the_end_of_a_month():
    assert months_before(datetime(2026, 5, 31, tzinfo=UTC), 3) == datetime(2026, 2, 28, tzinfo=UTC)
    assert months_before(datetime(2028, 5, 31, tzinfo=UTC), 3) == datetime(2028, 2, 29, tzinfo=UTC)  # a leap year
    assert months_before(datetime(2026, 2, 10, tzinfo=UTC), 3) == datetime(2025, 11, 10, tzinfo=UTC)
    assert months_before(datetime(2026, 11, 13, 9, 30, 15, tzinfo=UTC), 3) == datetime(2026, 8, 13, 9, 30, 15, tzinfo=UTC)
    assert months_before(datetime(2026, 12, 31, tzinfo=UTC), 1) == datetime(2026, 11, 30, tzinfo=UTC)
    assert months_before(datetime(2026, 1, 15, tzinfo=UTC), 12) == datetime(2025, 1, 15, tzinfo=UTC)


def test_the_addresses_that_are_due_go_with_every_write_and_every_listing(site):
    """So the promise does not wait on a timer: Where Landlords Stand's only scheduled run was weekly."""
    def one_due() -> int:
        site.clock.set("2026-07-01T09:00:00+00:00")
        sid = site.send()
        site.replies.decline(sid, "Off the subject.")
        site.clock.set("2026-11-13T12:00:00+00:00")
        assert emails(site)[sid]
        return sid

    r = site.replies
    writes = (lambda: site.send(), lambda: r.report(**site.case.report), lambda: r.statements(),
              lambda: r.reports(), lambda: r.publish(site.send(), checked=CHECKED, about="someone"),
              lambda: r.withdraw(site.send()), lambda: r.update(site.send(), role="Leader of the council"))
    for write in writes:
        sid = one_due()
        write()
        assert emails(site)[sid] is None


def test_an_address_written_into_a_note_or_a_reason_goes_with_it(site):
    """The notices promise the address is deleted, without exception. If the owner wrote it into the reason, or a
    note in the log, it is taken out there too."""
    address = site.case.statement["email"]
    site.clock.set("2026-07-01T09:00:00+00:00")
    sid = site.send()
    site.show(sid)
    site.replies.update(sid, role="Leader of the council", note=f"asked by {address.upper()} on 2 July")
    site.replies.remove(sid, f"It appeals for votes. Told {address} why.")
    assert address in everything_kept(site)
    site.clock.set("2026-11-13T12:00:00+00:00")
    assert site.replies.forget_old_emails() == 1
    assert site.replies.statement(sid)["reason"] == "It appeals for votes. Told [address deleted] why."
    assert site.replies.log(sid)[2]["note"] == "asked by [address deleted] on 2 July"
    assert address.lower() not in everything_kept(site).lower()


# ---- what nobody decided (ADR 0008, question 2) --------------------------------------------------------------------

def test_a_statement_nobody_decided_lapses_after_three_months_and_its_address_is_deleted(site):
    old = site.send()
    site.clock.advance(days=30)
    newer = site.send()
    site.clock.set("2027-02-13T11:59:00+00:00")  # three months less a minute after the first
    assert site.replies.lapse_undecided() == (0, 0)
    site.clock.set("2027-02-13T12:01:00+00:00")
    assert site.replies.lapse_undecided() == (1, 0)
    lapsed = site.replies.statement(old)
    assert (lapsed["status"], lapsed["reason"], lapsed["email"]) == ("declined", site.messages.lapsed, None)
    assert lapsed["closed_at"] == "2027-02-13T12:01:00+00:00"
    assert [(e["action"], e["note"]) for e in site.replies.log(old)] == [("received", None),
                                                                       ("lapsed", site.messages.lapsed)]
    still = site.replies.statement(newer)
    assert still["status"] == "pending" and still["email"] == site.case.statement["email"]
    assert site.replies.lapse_undecided() == (0, 0)
    assert site.replies.published(everywhere=True) == []  # a lapsed statement was never shown
    assert site.messages.lapsed == "No decision was made in time; please send it again"


def test_a_report_nobody_closed_loses_its_contact_after_three_months(site):
    old = site.replies.report(**site.case.report, contact="reader@example.org")
    site.clock.advance(days=30)
    newer = site.replies.report(**site.case.report, contact="another@example.org")
    site.clock.set("2027-02-13T12:01:00+00:00")
    assert site.replies.lapse_undecided() == (0, 1)
    rows = {r["id"]: r for r in site.rows("SELECT * FROM wts_reports")}
    assert rows[old]["contact"] is None and rows[old]["closed_at"] is None  # still open, and still to be dealt with
    assert rows[newer]["contact"] == "another@example.org"
    assert "reader@example.org" not in everything_kept(site)


def test_nothing_keeps_an_address_for_more_than_three_months_without_a_decision(site):
    """Nor does it wait for the daily job: the next thing anyone does tidies what is due."""
    sid = site.send()
    rid = site.replies.report(**site.case.report, contact="reader@example.org")
    site.clock.set((datetime(2027, 2, 13, 12, 0, tzinfo=UTC) + timedelta(minutes=1)).isoformat())
    assert [s["id"] for s in site.replies.statements("pending")] == []  # the owner's listing is such a thing
    assert site.replies.statement(sid)["status"] == "declined" and emails(site)[sid] is None
    assert [(r["id"], r["contact"]) for r in site.replies.reports()] == [(rid, None)]


def test_a_report_contact_is_deleted_when_the_report_is_closed(site):
    rid = site.replies.report(**site.case.report, contact=" reader@example.org ")
    assert site.replies.reports()[0]["contact"] == "reader@example.org"
    site.replies.close(rid, outcome="resolved", note="Checked; the date was wrong.")
    [closed] = site.replies.reports(open_only=False)
    assert closed["contact"] is None and closed["status"] == "resolved" and closed["closed_at"]
    assert "reader@example.org" not in everything_kept(site)
