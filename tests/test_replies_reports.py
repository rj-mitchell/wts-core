"""Readers' reports, the corrections log, hiding an item while a concern is decided, and what is waiting.

Where MPs Stand's tests of reports and its corrections log, Where Landlords Stand's of takedown requests first, its
aliases and its trap, and Where Countries Stand's and Where Councils Stand's of their kinds, run over every site.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from test_replies_sites import Open, one_site, site_fixture
from wts_core.replies import REPORT_OUTCOMES, TAKEDOWN, NotDone, Refused, Waiting, working_days_between

site = site_fixture()
mps, countries, councils, landlords = one_site("mps"), one_site("countries"), one_site("councils"), \
    one_site("landlords")

WITHDRAWN = {"date": "2026-11-13T12:05:00+00:00", "briefing_id": "abcdefghjk",
             "question": "What has been said about trial by jury?", "note": "Misquoted a minister."}


def report(site: Open, **over) -> int | None:
    return site.replies.report(**{**site.case.report, **over})


def refused(site: Open, **over) -> Refused:
    with pytest.raises(Refused) as caught:
        report(site, **over)
    return caught.value


def not_done(what, *args, **kw) -> str:
    with pytest.raises(NotDone) as caught:
        what(*args, **kw)
    return str(caught.value)


def kinds_kept(site: Open) -> list[str | None]:
    return [r["kind"] for r in site.replies.reports()]


# ---- reports -------------------------------------------------------------------------------------------------------

def test_reports_are_private_until_closed_with_a_public_note(site):
    rid = report(site, contact="reader@example.org", briefing_id="abcdefghjk")
    [waiting] = site.replies.reports()
    assert (waiting["id"], waiting["briefing_id"], waiting["contact"]) == (rid, "abcdefghjk", "reader@example.org")
    assert (waiting["status"], waiting["closed_at"], waiting["message"]) == ("open", None, site.case.report["message"])
    assert site.replies.corrections() == []

    site.replies.close(rid, outcome="resolved", note="Checked; quote was wrong.",
                       public_note=" A quotation in a briefing on jury trials was corrected. ")
    assert site.replies.reports() == []
    [after] = site.replies.reports(open_only=False)
    assert after["status"] == "resolved" and after["contact"] is None  # contact details deleted on closing
    assert after["resolution"] == "Checked; quote was wrong."

    # the site joins in its withdrawn briefings, which are its own to keep: as a list, or something that gives one
    log = site.replies.corrections(withdrawn=[WITHDRAWN])
    assert log == site.replies.corrections(withdrawn=lambda: [WITHDRAWN])
    assert log == [
        {"date": "2026-11-13", "kind": "withdrawn", "page": None, "briefing_id": "abcdefghjk",
         "question": "What has been said about trial by jury?", "note": "Misquoted a minister."},
        {"date": "2026-11-13", "kind": site.case.report["kind"], "page": site.case.report["page"],
         "briefing_id": "abcdefghjk", "question": None,
         "note": "A quotation in a briefing on jury trials was corrected."}]
    assert "Checked" not in json.dumps(log)  # the private note never appears publicly
    assert site.case.report["message"] not in json.dumps(log) and "reader@" not in json.dumps(log)


def test_a_report_closed_without_a_public_note_is_not_in_the_corrections_log(site):
    for public_note in (None, "", "   "):
        site.replies.close(report(site), outcome="dismissed", note="Not a mistake.", public_note=public_note)
    assert site.replies.corrections() == []
    assert [r["status"] for r in site.replies.reports(open_only=False)] == ["dismissed"] * 3


def test_open_takedown_requests_are_listed_first(site):
    """Policy 7.1: they are the ones that cannot wait. Where Landlords Stand's rule, in Where MPs Stand's order."""
    others = sorted({k for k in site.rules.report_kinds.values() if k != TAKEDOWN})[:2]
    site.clock.set("2026-11-01T09:00:00+00:00")
    for kind in (TAKEDOWN, others[0], TAKEDOWN, others[1], TAKEDOWN):
        report(site, kind=kind, message="Please look at this.")
        site.clock.advance(days=1)
    newest = site.replies.reports()[0]["id"]
    site.replies.close(newest, outcome="resolved", note="Name removed.")  # the fifth: a closed takedown request
    assert [(r["kind"], r["at"][8:10]) for r in site.replies.reports()] == [
        (TAKEDOWN, "03"), (TAKEDOWN, "01"), (others[1], "04"), (others[0], "02")]
    # with closed reports too: the open requests first, then everything else newest first
    assert [r["at"][8:10] for r in site.replies.reports(open_only=False)] == ["03", "01", "05", "04", "02"]
    site.replies.close(site.replies.reports()[0]["id"], outcome="resolved", note="Name removed.")
    assert [r["at"][8:10] for r in site.replies.reports(open_only=False)] == ["01", "05", "04", "03", "02"]


def test_reports_are_limited_per_visitor(site):
    limit = site.rules.daily_reports
    for _ in range(limit):
        assert report(site, visitor="v1")
    eleventh = refused(site, visitor="v1")
    assert limit == 10 and (eleventh.why, str(eleventh)) == ("daily_reports", site.messages.daily_reports)
    assert report(site, visitor="v2") and report(site)  # someone else, and a call that gives no visitor
    assert site.replies.submit(**site.body(), visitor="v1")  # statements are counted on their own
    assert len(site.replies.reports()) == limit + 2
    site.clock.advance(days=1)
    assert report(site, visitor="v1")  # a new day


def test_the_hidden_field_robots_fill_in_keeps_no_report(site):
    assert report(site, contact="robot@spam.example", visitor="v1", trap="https://spam.example") is None
    assert site.replies.reports() == [] and site.rows("SELECT * FROM wts_reply_counts") == []
    assert report(site, trap=" ")  # left empty, as people leave it: kept
    assert len(site.replies.reports()) == 1


def test_a_report_must_say_something_and_what_is_sent_is_tidied(site):
    r, m = site.rules, site.messages
    for nothing in ("", "   ", None, "x" * (r.report_min - 1)):
        short = refused(site, message=nothing)
        assert (short.why, str(short)) == ("report_too_short", m.report_too_short)
    long = refused(site, message="x" * (r.report_max + 1))
    assert (long.why, str(long)) == ("report_too_long", m.report_too_long.format(max=r.report_max, n=r.report_max + 1))
    far = refused(site, contact="a" * r.contact_max + "@example.org")
    assert far.why == "contact_too_long"
    assert site.replies.reports() == []
    rid = report(site, message="  " + "x" * r.report_max + "\n", contact="  ", page=" /" + "p" * 600 + " ",
                 briefing_id=" ")
    [kept] = site.replies.reports()
    assert kept["id"] == rid and kept["message"] == "x" * r.report_max
    assert kept["contact"] is None and kept["briefing_id"] is None  # the contact is optional
    assert kept["page"] == ("/" + "p" * 600)[:r.page_max]  # the page is the browser's, not the sender's words
    assert site.replies.reports()[0]["page"] is not None and report(site, page=None)


def test_mps_reports_keep_the_kinds_old_links_use(mps):
    for kind in ("correction", "complaint", "takedown", "general"):
        report(mps, kind=kind)
    assert kinds_kept(mps) == ["takedown", "general", "complaint", "correction"]
    for unknown in ("wrong", "statement", "", None):
        assert refused(mps, kind=unknown).why == "report_kind"
    assert refused(mps, kind="general", message="too short").why == "report_too_short"  # ten characters at least


def test_countries_reports_take_the_routes_and_the_old_kind(countries):
    for kind in ("error", "unfair", "problem", "takedown", "other", None):  # no kind given: "error"
        report(countries, kind=kind, message="A group label is wrong.")
    assert kinds_kept(countries) == ["takedown", "error", "other", "problem", "unfair", "error"]
    assert str(refused(countries, kind="statement")) == countries.messages.report_kind  # it has its own form


def test_councils_report_form_takes_the_policys_routes(councils):
    for kind in ("error", "unfair", "takedown", "other"):
        report(councils, kind=kind, message="Something to say")
    assert kinds_kept(councils) == ["takedown", "other", "unfair", "error"]
    assert refused(councils, kind="dispute").why == "report_kind"
    assert len(councils.replies.reports()) == 4


def test_landlords_reports_take_the_sisters_words_and_keep_one_with_no_kind(landlords):
    for sent, stored in (("unfair", "unfair"), ("takedown", "takedown"), ("complaint", "unfair"),
                         ("correction", "wrong"), ("error", "wrong"), ("mistake", "wrong"), ("general", "other"),
                         ("Takedown", "takedown"), (" wrong ", "wrong"), ("nonsense", None), ("", None), (None, None)):
        rid = report(landlords, kind=sent, message="a loaded word")  # an older form sends no kind: kept all the same
        assert landlords.rows("SELECT kind FROM wts_reports WHERE id = ?", rid) == [{"kind": stored}], sent
    assert kinds_kept(landlords)[:2] == ["takedown", "takedown"]  # first
    assert str(refused(landlords, message="")) == "please say what is wrong"


def test_closing_a_report_records_how_it_ended(site):
    rid = report(site)
    assert REPORT_OUTCOMES == ("resolved", "dismissed")
    for unsaid in ("", "closed", "fixed"):
        assert "say how it ended" in not_done(site.replies.close, rid, outcome=unsaid)
    assert len(site.replies.reports()) == 1
    site.replies.close(rid, outcome="dismissed")  # a private note is the owner's to give or not
    assert not_done(site.replies.close, rid, outcome="resolved") == f"no open report {rid}"  # already closed
    assert not_done(site.replies.close, 999, outcome="resolved") == "no open report 999"
    [closed] = site.replies.reports(open_only=False)
    assert (closed["status"], closed["resolution"], closed["public_note"]) == ("dismissed", None, None)
    assert closed["closed_at"] == "2026-11-13T12:00:00+00:00"


# ---- the corrections log -------------------------------------------------------------------------------------------

def test_the_corrections_log_is_newest_first_and_as_long_as_asked(site):
    site.clock.set("2026-11-01T09:00:00+00:00")
    for day in range(1, 6):
        site.replies.close(report(site), outcome="resolved", public_note=f"Correction {day}.")
        site.clock.advance(days=1)
    old = {"date": "2026-10-20", "question": "An older question?", "note": "It misread a statement."}
    same_day = {"date": "2026-11-05T08:00:00+00:00", "question": "A newer one?", "note": "Wrong."}
    log = site.replies.corrections(withdrawn=[old, same_day])
    assert [(c["date"], c["note"]) for c in log] == [
        ("2026-11-05", "Wrong."), ("2026-11-05", "Correction 5."), ("2026-11-04", "Correction 4."),
        ("2026-11-03", "Correction 3."), ("2026-11-02", "Correction 2."), ("2026-11-01", "Correction 1."),
        ("2026-10-20", "It misread a statement.")]
    assert all(set(c) == {"date", "kind", "page", "briefing_id", "question", "note"} for c in log)
    assert [c["note"] for c in site.replies.corrections(2)] == ["Correction 5.", "Correction 4."]
    assert site.replies.corrections(0) == []


def test_a_removed_statements_reason_is_in_the_log_only_when_the_site_asks(site):
    removed, withdrawn, declined = site.send(), site.send(), site.send()
    for sid in (removed, withdrawn):
        site.show(sid)
    site.replies.remove(removed, "It appeals for votes.")
    site.replies.withdraw(withdrawn, "Withdrawn by its author.")
    site.replies.decline(declined, "It is about another person's conduct.")
    assert site.replies.corrections() == []
    assert site.replies.corrections(removed=True) == [
        {"date": "2026-11-13", "kind": "removed", "page": site.case.address, "briefing_id": None, "question": None,
         "note": "It appeals for votes."}]  # never who wrote it, and never one withdrawn or declined


# ---- hiding an item while a concern is decided ----------------------------------------------------------------------

@pytest.mark.parametrize("address", ["/topics/onshore-wind", "/b/AbC123xy", "landlords/example-housing/",
                                     "label:majority:10669"])
def test_any_item_can_be_hidden_with_a_note_and_shown_again(site, address):
    """Policy 7.3: "the item can be hidden meanwhile, with a note". All four "If you're named" pages promised it
    and none had built it. Any address a site files things by, not only what a statement can sit beside."""
    note = "Hidden while we look into a concern about it."
    assert site.replies.hidden(address) is None
    for unsaid in ("", "  ", None):
        assert "give the note" in not_done(site.replies.hide, address, unsaid)
    assert "say which item" in not_done(site.replies.hide, " ", note)
    site.replies.hide(f" {address} ", f" {note} ")
    assert site.replies.hidden(address) == {"item": address, "note": note, "at": "2026-11-13T12:00:00+00:00"}
    assert site.replies.hidden(address + "/other") is None
    assert "already hidden" in not_done(site.replies.hide, address, "Another note.")
    site.clock.advance(days=2)
    site.replies.unhide(address)
    assert site.replies.hidden(address) is None
    assert not_done(site.replies.unhide, address) == f"{address} is not hidden"
    site.replies.hide(address, "Hidden again, while the trustees take advice.")
    assert site.replies.hidden(address)["note"] == "Hidden again, while the trustees take advice."
    # both times are kept on record: the decision and its reasons are logged (policy 7.4)
    assert site.rows("SELECT at, shown_at FROM wts_hidden ORDER BY id") == [
        {"at": "2026-11-13T12:00:00+00:00", "shown_at": "2026-11-15T12:00:00+00:00"},
        {"at": "2026-11-15T12:00:00+00:00", "shown_at": None}]


# ---- what is waiting ------------------------------------------------------------------------------------------------

def test_what_is_waiting_is_counted_with_the_age_of_the_oldest_in_working_days(site):
    assert site.replies.waiting() == Waiting(reports=0, statements=0, oldest_working_days=None)
    rid = report(site)  # Friday 13 November 2026
    assert site.replies.waiting() == Waiting(1, 0, 0)
    site.clock.advance(days=3)  # Monday
    first, second = site.send(), site.send()
    assert site.replies.waiting() == Waiting(reports=1, statements=2, oldest_working_days=1)
    site.clock.advance(days=3)  # Thursday: the nightly check fails once anything has waited four working days
    assert site.replies.waiting().oldest_working_days == 4
    site.replies.close(rid, outcome="resolved")
    assert site.replies.waiting() == Waiting(0, 2, 3)  # the statements came on the Monday
    site.show(first, about="someone")
    site.replies.decline(second, "It appeals for votes.")
    assert site.replies.waiting() == Waiting(0, 0, None)


def test_working_days_are_monday_to_friday():
    friday = date(2026, 11, 13)
    assert friday.weekday() == 4
    assert [working_days_between(friday, friday + timedelta(days=n)) for n in range(8)] == [0, 0, 0, 1, 2, 3, 4, 5]
    saturday = friday + timedelta(days=1)
    assert [working_days_between(saturday, saturday + timedelta(days=n)) for n in range(4)] == [0, 0, 1, 2]
    assert working_days_between(friday, friday - timedelta(days=3)) == 0  # never less than nothing
    assert working_days_between(date(2026, 11, 2), date(2026, 11, 30)) == 20  # four weeks
    # bank holidays are not taken out: Christmas week counts in full, which errs towards alerting early
    assert working_days_between(date(2026, 12, 24), date(2026, 12, 29)) == 3
    for start in (friday + timedelta(days=n) for n in range(7)):
        for length in range(40):
            end = start + timedelta(days=length)
            by_hand = sum(1 for n in range(1, length + 1) if (start + timedelta(days=n)).weekday() < 5)
            assert working_days_between(start, end) == by_hand, (start, end)


def test_the_owner_is_shown_everything_hidden_now_so_nothing_stays_hidden_by_oversight(site):
    """Hiding is for while a concern is decided. What is hidden now is listed, longest hidden first, and counted in
    what is waiting for the owner, so the update report and the nightly check both remind them."""
    assert site.replies.all_hidden() == []
    assert site.replies.waiting().hidden == 0
    site.replies.hide("/b/first", "Hidden while we look into a concern about it.")
    site.clock.advance(days=1)
    site.replies.hide("/b/second", "Hidden while the trustees take advice.")
    assert [h["item"] for h in site.replies.all_hidden()] == ["/b/first", "/b/second"]
    assert set(site.replies.all_hidden()[0]) == {"item", "note", "at"}
    assert site.replies.waiting().hidden == 2
    site.replies.unhide("/b/first")
    assert [h["item"] for h in site.replies.all_hidden()] == ["/b/second"]
    assert site.replies.waiting().hidden == 1
