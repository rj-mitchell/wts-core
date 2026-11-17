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

import wts_core.replies
from test_replies_sites import Open, site_fixture
from wts_core.replies import PUBLIC_FIELDS, Lapsing, Refused, WouldLapse, months_before, statement_html

site = site_fixture()

CHECKED = "Reply from the mission's published address, 14 November."
NOTE = "Hidden while we look into a concern about it."


def emails(site: Open) -> dict[int, str | None]:
    return {r["id"]: r["email"] for r in site.rows("SELECT id, email FROM wts_statements")}


def everything_kept(site: Open) -> str:
    with site.db.connect() as con:
        return "\n".join(con.iterdump())


# What the public may see

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


# Three calendar months after a statement ends

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


# What nobody decided (ADR 0008, question 2)

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


def test_what_would_lapse_is_read_before_anything_lapses(site):
    """Every write and every owner's listing tidies first, so after a site's import the first of them lapses what
    has already waited three months. ``would_lapse`` shows the owner beforehand, and changes nothing."""
    assert site.replies.would_lapse() == WouldLapse((), (), before="2026-08-13T12:00:00+00:00")
    old = site.send()
    old_report = site.replies.report(**site.case.report, contact="reader@example.org")
    no_contact = site.replies.report(**site.case.report)  # nothing of it to delete
    closed = site.replies.report(**site.case.report, contact="closed@example.org")
    decided = site.send()
    site.clock.advance(days=30)
    newer = site.send()
    site.replies.report(**site.case.report, contact="another@example.org")
    site.replies.decline(decided, "It is about another person's conduct.")
    site.replies.close(closed, outcome="dismissed")
    site.clock.set("2027-02-13T11:59:00+00:00")  # three months less a minute after the first
    assert site.replies.would_lapse() == WouldLapse((), (), before="2026-11-13T11:59:00+00:00")
    site.clock.set("2027-02-13T12:01:00+00:00")
    before = everything_kept(site)
    lapsing = site.replies.would_lapse()
    assert lapsing == WouldLapse(statements=(Lapsing(id=old, at="2026-11-13T12:00:00+00:00", days=92),),
                                 reports=(Lapsing(id=old_report, at="2026-11-13T12:00:00+00:00", days=92),),
                                 before="2026-11-13T12:01:00+00:00")
    assert everything_kept(site) == before  # read, and nothing done: asked twice, the answer is the same
    assert site.replies.would_lapse() == lapsing
    said = repr(lapsing)  # ids, dates and ages: never an address, a name or a word of what was sent
    for private in ("example.org", site.case.statement["email"], site.case.statement["name"],
                    site.case.report["message"]):
        assert private not in said
    # and it is exactly what the tidy then does
    assert site.replies.lapse_undecided() == (len(lapsing.statements), len(lapsing.reports))
    assert site.replies.statement(old)["status"] == "declined" and site.replies.statement(newer)["status"] == "pending"
    assert {r["id"]: r["contact"] for r in site.rows("SELECT id, contact FROM wts_reports")}[no_contact] is None
    assert site.replies.would_lapse() == WouldLapse((), (), before="2026-11-13T12:01:00+00:00")


def test_what_would_lapse_counts_the_days_of_a_row_an_import_brought_across(site):
    """An imported row's time may be written another way (a date alone, or with no zone): it is aged by its date."""
    sid = site.send()
    rid = site.replies.report(**site.case.report, contact="reader@example.org")
    with site.db.connect() as con:
        con.execute("UPDATE wts_statements SET at = '2025-12-25' WHERE id = ?", (sid,))
        con.execute("UPDATE wts_reports SET at = '2026-01-02 09:30:00' WHERE id = ?", (rid,))
    lapsing = site.replies.would_lapse()
    assert lapsing.statements == (Lapsing(sid, "2025-12-25", 323),)
    assert lapsing.reports == (Lapsing(rid, "2026-01-02 09:30:00", 315),)


def test_a_report_contact_is_deleted_when_the_report_is_closed(site):
    rid = site.replies.report(**site.case.report, contact=" reader@example.org ")
    assert site.replies.reports()[0]["contact"] == "reader@example.org"
    site.replies.close(rid, outcome="resolved", note="Checked; the date was wrong.")
    [closed] = site.replies.reports(open_only=False)
    assert closed["contact"] is None and closed["status"] == "resolved" and closed["closed_at"]
    assert "reader@example.org" not in everything_kept(site)


def test_yesterdays_visitor_codes_are_gone_without_anyone_sending_anything_more(site):
    """Found in review: the counts were emptied only when the next statement or report was accepted, so on a quiet
    site a visitor's code stayed for as long as nobody wrote in. The owner's listings and the nightly check's
    question now empty them too."""
    site.send(visitor="a" * 24)
    assert site.rows("SELECT visitor FROM wts_reply_counts") == [{"visitor": "a" * 24}]
    site.clock.advance(days=1)
    site.replies.waiting()  # what the nightly check asks
    assert site.rows("SELECT visitor FROM wts_reply_counts") == []
    site.send(visitor="b" * 24)
    site.clock.advance(days=40)
    site.replies.statements()  # the owner looking at the list
    assert site.rows("SELECT visitor FROM wts_reply_counts") == []
    site.send(visitor="c" * 24)
    site.clock.advance(days=1)
    assert site.replies.forget_old_counts() == 1 and site.rows("SELECT visitor FROM wts_reply_counts") == []


def test_an_ended_statement_brought_across_with_no_closing_time_still_loses_its_address(site):
    """Found in review: a declined statement whose closing time was empty (as a site's import might leave it) kept
    its sender's address for ever, because nothing is ever "before" an empty time. It is judged by when it was
    sent."""
    sid = site.send()
    with site.db.connect() as con:
        con.execute("UPDATE wts_statements SET status = 'declined', closed_at = NULL WHERE id = ?", (sid,))
    site.clock.advance(days=80)
    site.replies.forget_old_emails()
    assert emails(site)[sid]  # not yet three months
    site.clock.advance(days=20)
    assert site.replies.forget_old_emails() == 1 and not emails(site)[sid]


# The sum behind what lapses, on its own (0.3.0)


def test_the_sum_behind_what_lapses_agrees_with_the_desk_row_for_row(site):
    """Anything with no ``Replies`` to ask, such as a site's page or tests, must still say exactly what the tidy
    will lapse. These are that sum: the desk uses them, so anything else that uses them cannot disagree with it."""
    from datetime import datetime, timedelta

    from wts_core.replies import has_lapsed, lapse_cutoff, lapses_on

    sent: dict[int, str] = {}
    site.clock.set("2026-05-28T23:59:30+00:00")
    for _ in range(12):  # either side of every kind of month end
        sent[site.send(email="sender@example.org")] = site.clock.now().isoformat(timespec="seconds")
        site.clock.advance(hours=17, minutes=13)
    site.clock.set("2026-08-29T00:00:10+00:00")
    for _ in range(40):
        now = site.clock.now()
        would = {entry.id for entry in site.replies.would_lapse().statements}
        assert would == {sid for sid, at in sent.items() if has_lapsed(at, now)}
        assert site.replies.would_lapse().before == lapse_cutoff(now)
        site.clock.advance(hours=5, minutes=7)
    for at in sent.values():  # the day it lapses is the first day by whose end it has
        day = lapses_on(at)
        end = datetime.fromisoformat(f"{day.isoformat()}T23:59:59+00:00")
        assert has_lapsed(at, end) and not has_lapsed(at, end - timedelta(days=1))


def test_three_months_on_from_a_months_last_days_is_the_day_the_package_itself_would_lapse_it():
    from datetime import date

    from wts_core.replies import lapses_on

    assert lapses_on("2026-08-13T12:00:00+00:00") == date(2026, 11, 13)
    assert lapses_on("2026-08-13T00:00:00+00:00") == date(2026, 11, 13)
    # three months before 28 February is 28 November: what was sent on the 29th or 30th lapses on 1 March
    assert lapses_on("2026-11-28T09:00:00+00:00") == date(2027, 2, 28)
    assert lapses_on("2026-11-30T09:00:00+00:00") == date(2027, 3, 1)
    assert lapses_on("2026-11-30T09:00:00+00:00", months=1) == date(2026, 12, 30)
    assert lapses_on("2026-05-01T09:00:00") == date(2026, 8, 1)  # an old row whose time says no timezone
