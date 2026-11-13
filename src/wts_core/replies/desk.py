"""The desk reports and statements pass over: received, decided, shown, logged, and their senders forgotten in time.

``Replies`` is everything a site's routes, pages and owner's commands need. A site builds one from its state
database, its ``Items``, its ``ReplyRules`` and its ``ReplyMessages``::

    replies = Replies(state, items=MyItems(), rules=RULES, messages=MESSAGES)
    sid = replies.submit(name=…, role=…, item=pasted, text=…, link=…, email=…, visitor=code, trap=body.website)
    replies.published(items=[path], about=member)

A statement's life (ADR 0008): received as ``pending``; then ``published``, or ``declined`` (never shown); a
published one is ``withdrawn`` (its author asked) or ``removed`` (the site took it down for breaking the rules);
its words can be replaced while it is waiting or shown. Every step is logged with its time and note, and an update
keeps the words it replaced. Nothing leaves declined, withdrawn or removed.

What a sender gave to be reached by is kept only as long as it is needed. A report's contact is deleted when the
report is closed. A statement's address is kept while it is waiting or shown and deleted three calendar months
after it ends; and nothing waits for ever: after three months without a decision a statement lapses and a report's
contact is deleted (ADR 0008, question 2). Every write and every owner's listing does this tidying first, so it
does not depend on a timer; a site's daily job calls ``forget_old_emails`` and ``lapse_undecided`` as well.

Nothing here logs: a sender's address is never written anywhere but its own column.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from wts_core.ports import SYSTEM_CLOCK, Clock
from wts_core.replies.days import months_before, working_days_between
from wts_core.replies.rules import (
    REPORT_OUTCOMES,
    STATUSES,
    TAKEDOWN,
    Item,
    Items,
    NotDone,
    Refused,
    ReplyMessages,
    ReplyRules,
    StatementStatus,
    check_email,
    check_line,
    check_link,
    check_text,
)
from wts_core.state import StateDB, iso, today

__all__ = ["Replies", "Waiting"]

# what the owner sees of a statement: everything but the log, which ``Replies.log`` reads
_STATEMENT = ("id", "at", "item", "part", "about", "name", "role", "text", "link", "email", "status",
              "published_at", "updated_at", "closed_at", "reason")
_REPORT = ("id", "at", "kind", "page", "message", "contact", "briefing_id", "status", "closed_at", "resolution",
           "public_note")
_ENDED = ("declined", "withdrawn", "removed")
# put where a sender's address stood in a note or reason, when the address itself is deleted
_GONE = "[address deleted]"


@dataclass(frozen=True)
class Waiting:
    """What is waiting for the owner: open reports, statements not yet decided, and how long the oldest of them
    has waited, in working days (None when nothing is waiting). The sites promise a reply within five. ``hidden``
    is how many items are hidden now: hiding is for while a concern is decided, so each one is waiting too."""

    reports: int
    statements: int
    oldest_working_days: int | None
    hidden: int = 0


class Replies:
    def __init__(self, db: StateDB, *, items: Items, rules: ReplyRules, messages: ReplyMessages,
                 clock: Clock = SYSTEM_CLOCK) -> None:
        self.db = db
        self.items = items
        self.rules = rules
        self.messages = messages
        self.clock = clock

    # ---- statements: what is sent -------------------------------------------------------------------------------

    def submit(self, *, name: str, role: str, item: str | Item, text: str, link: str | None, email: str,
               visitor: str | None = None, trap: str | None = "") -> int | None:
        """Keep a statement as pending and return its number, or raise ``Refused`` with the site's words.

        ``trap`` is the form's hidden field, which people leave empty: when it is filled the sender is a robot, and
        None is returned as if all were well, with nothing kept. ``visitor`` is the day's visitor code, used only to
        count against the daily limit. ``item`` is what the sender pasted, or an ``Item`` the site has already
        resolved (with the request's own host, say).

        Checked in this order, stopping at the first fault: the daily limit; the words (too few, too many, too
        long); the name; the role; the link; the email address; the item's address; that the item is there and
        still shown. Where MPs Stand and Where Landlords Stand check the name and role before the words, and Where
        Countries Stand and Where Councils Stand the address first: a site that resolves the item itself keeps the
        address first."""
        if (trap or "").strip():
            return None
        self._tidy()
        self._within_limit("statement", visitor)
        rules, messages = self.rules, self.messages
        words = check_text(text, rules, messages)
        name = check_line(name, rules.name_max, messages.name_missing, messages.name_too_long, "name")
        role = check_line(role, rules.role_max, messages.role_missing, messages.role_too_long, "role")
        link = check_link(link, rules, messages)
        email = check_email(email, rules, messages)
        beside = item if isinstance(item, Item) else self.items.resolve(item)
        if self.hidden(beside.address) or not self.items.shown(beside):
            raise Refused(messages.item_not_shown, "item_not_shown")
        now = iso(self.clock)
        with self.db.connect() as con:
            cur = con.execute("INSERT INTO wts_statements (at, item, part, about, name, role, text, link, email) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (now, beside.address, beside.part, beside.about, name, role, words, link, email))
            sid = int(cur.lastrowid or 0)
            self._log(con, sid, "received")
            self._count(con, "statement", visitor)
        return sid

    # ---- statements: what is shown ------------------------------------------------------------------------------

    def published(self, *, items: Sequence[str | Item] = (), about: str | None = None,
                  everywhere: bool = False) -> list[dict[str, Any]]:
        """What the public sees: the published statements beside any of ``items`` or speaking for ``about``, oldest
        first, with ``PUBLIC_FIELDS`` and nothing else. An address that isn't an item's is passed over; with nothing
        asked for, nothing is returned. ``everywhere`` gives every published statement, for a site whose pages are
        built rather than asked (Where Landlords Stand). A statement beside an item that is hidden while a concern
        is decided is hidden with it."""
        where: list[str] = []
        args: list[str] = []
        for pasted in items:
            try:
                address = pasted.address if isinstance(pasted, Item) else self.items.resolve(pasted).address
            except Refused:
                continue
            where.append("item = ?")
            args.append(address)
        if about:
            where.append("about = ?")
            args.append(about)
        if not where and not everywhere:
            return []
        # the columns are named one by one, so the address can never leak through a SELECT *
        sql = ("SELECT id, item, part, about, name, role, text, link, published_at, updated_at FROM wts_statements "
               "WHERE status = 'published' AND item NOT IN (SELECT item FROM wts_hidden WHERE shown_at IS NULL)")
        if not everywhere:
            sql += f" AND ({' OR '.join(where)})"
        with self.db.connect() as con:
            rows = con.execute(sql, args).fetchall()
        rows.sort(key=lambda r: (_words_dated(r), r["id"]))
        return [{"id": r["id"], "item": r["item"], "part": r["part"], "about": r["about"], "name": r["name"],
                 "role": r["role"], "text": r["text"], "link": r["link"], "date": _words_dated(r)[:10]} for r in rows]

    # ---- statements: the owner's decisions ----------------------------------------------------------------------

    def publish(self, sid: int, *, checked: str, about: str | None = None) -> None:
        """Show a waiting statement, as written, once the owner has confirmed who sent it. ``checked`` says how
        (policy 7.2, "Who is checked") and is required: it is kept in the log, which only the owner reads, for
        good. So it must not hold the sender's address, which the privacy notice promises to delete: a note that
        does is refused. ``about`` is whom the statement speaks for, when its item's address doesn't say."""
        note = " ".join((checked or "").split())
        if not note:
            raise NotDone("say how you confirmed who sent it (checked), for the log")
        self._tidy()
        with self.db.connect() as con:
            s = self._get(con, sid, "pending")
            if s["email"] and s["email"].lower() in note.lower():
                raise NotDone("the note of how the sender was confirmed is kept for good, so leave their email "
                              "address out of it: say where their reply came from, not the address itself")
            whom = (about or "").strip() or s["about"]
            if self.rules.about_required and not whom:
                raise NotDone(f"statement {sid} is beside {s['item']}: say whom it speaks for (about)")
            con.execute("UPDATE wts_statements SET status = 'published', published_at = ?, about = ? WHERE id = ?",
                        (iso(self.clock), whom, sid))
            self._log(con, sid, "published", note)

    def decline(self, sid: int, reason: str) -> None:
        """Decline a waiting statement, with the reason its sender is told (never shown on the site). Only a
        waiting one: "declined" always means it was never shown; a published one is withdrawn or removed."""
        self._end(sid, "declined", _needed(reason, "give the reason: the sender is told why"), "pending")

    def withdraw(self, sid: int, note: str | None = None) -> None:
        """Take a statement down, or stop one waiting, because its author asked. The note is recorded."""
        self._end(sid, "withdrawn", (note or "").strip() or None, "pending", "published")

    def remove(self, sid: int, reason: str) -> None:
        """Take a published statement down because it breaks the rules: the charity says why (policy 7.2)."""
        self._end(sid, "removed", _needed(reason, "give the reason: the rule it broke, which its author is told"),
                  "published")

    def update(self, sid: int, *, text: str | None = None, name: str | None = None, role: str | None = None,
               link: str | None = None, clear_link: bool = False, about: str | None = None,
               note: str | None = None) -> None:
        """The author's new words, name, role or link, as they sent them, for a statement that is waiting or shown;
        or whom it speaks for. The new version keeps to the same rules as the first (``Refused`` says which it
        breaks, in the site's words). The words it replaces are kept in the log. A published statement is then
        shown with the date of the new version; saying whom it speaks for does not change its date. An empty
        ``link``, or ``clear_link``, takes the link away."""
        rules, messages = self.rules, self.messages
        new: dict[str, str | None] = {}
        if text is not None:
            new["text"] = check_text(text, rules, messages)
        if name is not None:
            new["name"] = check_line(name, rules.name_max, messages.name_missing, messages.name_too_long, "name")
        if role is not None:
            new["role"] = check_line(role, rules.role_max, messages.role_missing, messages.role_too_long, "role")
        if clear_link:
            new["link"] = None
        elif link is not None:
            new["link"] = check_link(link, rules, messages)
        reworded = bool(new)
        if about is not None and about.strip():
            new["about"] = about.strip()
        if not new:
            raise NotDone("nothing to change: give new words, a name, a role, a link or whom it speaks for")
        self._tidy()
        with self.db.connect() as con:
            s = self._get(con, sid, "pending", "published")
            previous = {k: s[k] for k in new if s[k] != new[k]}
            if reworded:
                new["updated_at"] = iso(self.clock)
            con.execute(f"UPDATE wts_statements SET {', '.join(f'{k} = ?' for k in new)} WHERE id = ?",
                        (*new.values(), sid))
            self._log(con, sid, "updated", (note or "").strip() or ", ".join(sorted(k for k in new if k != "updated_at")),
                      previous or None)

    # ---- statements: the owner's reading ------------------------------------------------------------------------

    def statements(self, status: StatementStatus | None = None) -> list[dict[str, Any]]:
        """Every statement, or those with one status, newest first, with the sender's address and the reason it
        ended: for the owner only."""
        if status is not None and status not in STATUSES:
            raise NotDone(f"no such status {status!r}: one of {', '.join(STATUSES)}")
        self._tidy()
        sql = f"SELECT {', '.join(_STATEMENT)} FROM wts_statements"
        with self.db.connect() as con:
            rows = (con.execute(sql + " WHERE status = ? ORDER BY id DESC", (status,)) if status
                    else con.execute(sql + " ORDER BY id DESC")).fetchall()
        return [dict(r) for r in rows]

    def statement(self, sid: int) -> dict[str, Any] | None:
        """One statement as the owner sees it, or None."""
        with self.db.connect() as con:
            row = con.execute(f"SELECT {', '.join(_STATEMENT)} FROM wts_statements WHERE id = ?", (sid,)).fetchone()
        return dict(row) if row else None

    def log(self, sid: int) -> list[dict[str, Any]]:
        """Everything done to a statement, oldest first: ``at``, ``action``, ``note`` and, for an update,
        ``previous`` (what the changed fields said before). For the owner only: the note of a publishing says how
        the sender was confirmed."""
        with self.db.connect() as con:
            rows = con.execute("SELECT at, action, note, previous FROM wts_statement_log WHERE statement = ? "
                               "ORDER BY id", (sid,)).fetchall()
        return [{"at": r["at"], "action": r["action"], "note": r["note"],
                 "previous": json.loads(r["previous"]) if r["previous"] else None} for r in rows]

    # ---- forgetting senders -------------------------------------------------------------------------------------

    def forget_old_emails(self) -> int:
        """Delete the confirming address of every statement declined, withdrawn or removed more than three calendar
        months ago (the privacy notices), and anything else that would tie the statement to its sender: the address
        is taken out of the log's notes and the recorded reason too, should the owner have written it there.
        Returns how many addresses were deleted."""
        cutoff = months_before(self.clock.now(), self.rules.email_kept_months).isoformat(timespec="seconds")
        with self.db.connect() as con:
            due = con.execute("SELECT id, email FROM wts_statements WHERE email IS NOT NULL AND email != '' AND "
                              f"status IN ({', '.join('?' * len(_ENDED))}) AND closed_at < ?",
                              (*_ENDED, cutoff)).fetchall()
            for row in due:
                self._forget(con, row["id"], row["email"])
        return len(due)

    def lapse_undecided(self) -> tuple[int, int]:
        """What nobody decided in three calendar months (ADR 0008, question 2; the nightly check should have
        alerted the owner long before). A statement still waiting lapses: it is declined with the site's words for
        that, which its sender is told if they ask, and its address is deleted at once. A report still open keeps
        its place in the list, but its contact is deleted, exactly as if it had been closed. Returns how many
        statements lapsed and how many reports' contacts were deleted."""
        now = iso(self.clock)
        cutoff = months_before(self.clock.now(), self.rules.email_kept_months).isoformat(timespec="seconds")
        with self.db.connect() as con:
            waiting = con.execute("SELECT id, email FROM wts_statements WHERE status = 'pending' AND at < ?",
                                  (cutoff,)).fetchall()
            for row in waiting:
                con.execute("UPDATE wts_statements SET status = 'declined', closed_at = ?, reason = ? WHERE id = ?",
                            (now, self.messages.lapsed, row["id"]))
                self._log(con, row["id"], "lapsed", self.messages.lapsed)
                self._forget(con, row["id"], row["email"])
            reports = con.execute("UPDATE wts_reports SET contact = NULL WHERE closed_at IS NULL AND "
                                  "contact IS NOT NULL AND at < ?", (cutoff,)).rowcount
        return len(waiting), reports

    # ---- reports ------------------------------------------------------------------------------------------------

    def report(self, *, kind: str | None, page: str | None, message: str, contact: str | None = None,
               briefing_id: str | None = None, visitor: str | None = None, trap: str | None = "") -> int | None:
        """Keep a reader's report as open and return its number, or raise ``Refused`` with the site's words. A
        filled ``trap`` returns None and keeps nothing, as for a statement. ``kind`` is the word the form or a link
        sent, stored as the site's ``report_kinds`` says. The contact is optional, used only to reply, and deleted
        when the report is closed."""
        if (trap or "").strip():
            return None
        self._tidy()
        self._within_limit("report", visitor)
        rules, messages = self.rules, self.messages
        stored = rules.report_kinds.get((kind or "").strip().lower())
        if stored is None and rules.report_kind_required:
            raise Refused(messages.report_kind, "report_kind")
        said = (message or "").strip()
        if len(said) < max(rules.report_min, 1):
            raise Refused(messages.report_too_short, "report_too_short")
        if len(said) > rules.report_max:
            raise Refused(messages.report_too_long.format(max=rules.report_max, n=len(said)), "report_too_long")
        reply_to = (contact or "").strip()
        if len(reply_to) > rules.contact_max:
            raise Refused(messages.contact_too_long.format(max=rules.contact_max, n=len(reply_to)), "contact_too_long")
        with self.db.connect() as con:
            cur = con.execute("INSERT INTO wts_reports (at, kind, page, message, contact, briefing_id) "
                              "VALUES (?, ?, ?, ?, ?, ?)",
                              (iso(self.clock), stored, (page or "").strip()[:rules.page_max] or None, said,
                               reply_to or None, (briefing_id or "").strip() or None))
            self._count(con, "report", visitor)
            return int(cur.lastrowid or 0)

    def reports(self, open_only: bool = True) -> list[dict[str, Any]]:
        """Reports for the owner, newest first, but open requests to remove a person's name or details before
        everything else (policy 7.1: they are the ones that cannot wait)."""
        self._tidy()
        with self.db.connect() as con:
            rows = con.execute(f"SELECT {', '.join(_REPORT)} FROM wts_reports" +
                               (" WHERE closed_at IS NULL" if open_only else "") +
                               " ORDER BY (closed_at IS NULL AND kind IS ?) DESC, at DESC, id DESC",
                               (TAKEDOWN,)).fetchall()
        return [dict(r) for r in rows]

    def close(self, rid: int, *, outcome: str, note: str | None = None, public_note: str | None = None) -> None:
        """Close an open report and delete its contact: it was only ever for replying. ``outcome`` is "resolved"
        or "dismissed"; ``note`` is private (what was found and done); ``public_note``, if given, appears in the
        corrections log, and must name no one who reported."""
        if outcome not in REPORT_OUTCOMES:
            raise NotDone(f"say how it ended (outcome): {' or '.join(REPORT_OUTCOMES)}")
        self._tidy()
        with self.db.connect() as con:
            done = con.execute("UPDATE wts_reports SET status = ?, closed_at = ?, resolution = ?, public_note = ?, "
                               "contact = NULL WHERE id = ? AND closed_at IS NULL",
                               (outcome, iso(self.clock), (note or "").strip() or None,
                                (public_note or "").strip() or None, rid)).rowcount
        if not done:
            raise NotDone(f"no open report {rid}")

    # ---- the corrections log ------------------------------------------------------------------------------------

    def corrections(self, limit: int = 100, *,
                    withdrawn: Iterable[Mapping[str, Any]] | Callable[[], Iterable[Mapping[str, Any]]] = (),
                    removed: bool = False) -> list[dict[str, Any]]:
        """The public log of what has been put right, newest first: every public note on a closed report and, when
        the site asks for them (``removed``), the reason each removed statement was taken down. Withdrawn
        briefings are the site's (it owns saved briefings): it passes them as ``withdrawn``, a list or something
        that returns one, each with a ``date`` and what it wants shown (``briefing_id``, ``question``, ``note``).

        Each entry has ``date``, ``kind`` ("withdrawn", the report's kind, or "removed"), ``page``,
        ``briefing_id``, ``question`` and ``note``. Never a report's private note, its message or its contact."""
        blank: dict[str, Any] = {"date": "", "kind": "withdrawn", "page": None, "briefing_id": None,
                                 "question": None, "note": None}
        out = [{**blank, **entry, "date": str(entry["date"])[:10]}
               for entry in (withdrawn() if callable(withdrawn) else withdrawn)]
        with self.db.connect() as con:
            out += [{**blank, "date": r["closed_at"][:10], "kind": r["kind"], "page": r["page"],
                     "briefing_id": r["briefing_id"], "note": r["public_note"]}
                    for r in con.execute("SELECT closed_at, kind, page, briefing_id, public_note FROM wts_reports "
                                         "WHERE closed_at IS NOT NULL AND public_note IS NOT NULL "
                                         "AND public_note != '' ORDER BY id")]
            if removed:
                out += [{**blank, "date": r["closed_at"][:10], "kind": "removed", "page": r["item"],
                         "note": r["reason"]}
                        for r in con.execute("SELECT closed_at, item, reason FROM wts_statements "
                                             "WHERE status = 'removed' AND closed_at IS NOT NULL ORDER BY id")]
        out.sort(key=lambda entry: entry["date"], reverse=True)
        return out[:limit]

    # ---- hiding an item while a concern is decided (policy 7.3) --------------------------------------------------

    def hide(self, item: str, note: str) -> None:
        """Hide the item at this address (as the site files it) from now, with the note its pages show in its
        place. Any kind of item, not only what a statement can sit beside. This is not withdrawal: it is undone
        with ``unhide``, and both are kept on record."""
        address, shown_instead = (item or "").strip(), (note or "").strip()
        if not address:
            raise NotDone("say which item to hide: its address on the site")
        if not shown_instead:
            raise NotDone("give the note that is shown in the item's place while it is hidden")
        with self.db.connect() as con:
            if con.execute("SELECT 1 FROM wts_hidden WHERE item = ? AND shown_at IS NULL", (address,)).fetchone():
                raise NotDone(f"{address} is already hidden: unhide it first to change the note")
            con.execute("INSERT INTO wts_hidden (item, at, note) VALUES (?, ?, ?)",
                        (address, iso(self.clock), shown_instead))

    def unhide(self, item: str) -> None:
        with self.db.connect() as con:
            done = con.execute("UPDATE wts_hidden SET shown_at = ? WHERE item = ? AND shown_at IS NULL",
                               (iso(self.clock), (item or "").strip())).rowcount
        if not done:
            raise NotDone(f"{item} is not hidden")

    def hidden(self, item: str) -> dict[str, Any] | None:
        """Whether the item at this address is hidden now: its ``item``, the ``note`` to show in its place and when
        it was hidden (``at``), or None. A site's page asks this before it shows the item."""
        with self.db.connect() as con:
            row = con.execute("SELECT item, note, at FROM wts_hidden WHERE item = ? AND shown_at IS NULL",
                              ((item or "").strip(),)).fetchone()
        return dict(row) if row else None

    def all_hidden(self) -> list[dict[str, Any]]:
        """Every item hidden now, longest hidden first (``item``, ``note``, ``at``): for the owner, so that an item
        hidden while a concern was decided is not left hidden by oversight."""
        with self.db.connect() as con:
            return [dict(r) for r in con.execute("SELECT item, note, at FROM wts_hidden WHERE shown_at IS NULL "
                                                 "ORDER BY at, id")]

    # ---- for the owner, the update report and the nightly check --------------------------------------------------

    def waiting(self) -> Waiting:
        with self.db.connect() as con:
            reports, first_report = con.execute("SELECT count(*), min(at) FROM wts_reports "
                                                "WHERE closed_at IS NULL").fetchone()
            statements, first_statement = con.execute("SELECT count(*), min(at) FROM wts_statements "
                                                      "WHERE status = 'pending'").fetchone()
            hidden = con.execute("SELECT count(*) FROM wts_hidden WHERE shown_at IS NULL").fetchone()[0]
        oldest = min((at for at in (first_report, first_statement) if at), default=None)
        days = working_days_between(date.fromisoformat(oldest[:10]), self.clock.now().date()) if oldest else None
        return Waiting(reports=reports, statements=statements, oldest_working_days=days, hidden=hidden)

    # ---- private ------------------------------------------------------------------------------------------------

    def _tidy(self) -> None:
        self.forget_old_emails()
        self.lapse_undecided()

    def _get(self, con: sqlite3.Connection, sid: int, *allowed: str) -> sqlite3.Row:
        row: sqlite3.Row | None = con.execute("SELECT * FROM wts_statements WHERE id = ?", (sid,)).fetchone()
        if row is None:
            raise NotDone(f"no statement {sid}")
        if row["status"] not in allowed:
            raise NotDone(f"statement {sid} is {row['status']}, not {' or '.join(allowed)}")
        return row

    def _end(self, sid: int, status: str, reason: str | None, *allowed: str) -> None:
        self._tidy()
        with self.db.connect() as con:
            self._get(con, sid, *allowed)
            con.execute("UPDATE wts_statements SET status = ?, closed_at = ?, reason = ? WHERE id = ?",
                        (status, iso(self.clock), reason, sid))
            self._log(con, sid, status, reason)

    def _log(self, con: sqlite3.Connection, sid: int, action: str, note: str | None = None,
             previous: Mapping[str, Any] | None = None) -> None:
        """What was done, when and why (policy 7.4: every decision and its reasons are logged)."""
        con.execute("INSERT INTO wts_statement_log (statement, at, action, note, previous) VALUES (?, ?, ?, ?, ?)",
                    (sid, iso(self.clock), action, note or None,
                     json.dumps(previous, ensure_ascii=False) if previous else None))

    def _forget(self, con: sqlite3.Connection, sid: int, email: str | None) -> None:
        """Delete a statement's confirming address, wherever it was written."""
        if email:
            address = re.compile(re.escape(email), re.IGNORECASE)
            for row in con.execute("SELECT id, note FROM wts_statement_log WHERE statement = ? AND note IS NOT NULL",
                                   (sid,)).fetchall():
                if address.search(row["note"]):
                    con.execute("UPDATE wts_statement_log SET note = ? WHERE id = ?",
                                (address.sub(_GONE, row["note"]), row["id"]))
            reason = con.execute("SELECT reason FROM wts_statements WHERE id = ?", (sid,)).fetchone()["reason"]
            if reason and address.search(reason):
                con.execute("UPDATE wts_statements SET reason = ? WHERE id = ?", (address.sub(_GONE, reason), sid))
        con.execute("UPDATE wts_statements SET email = NULL WHERE id = ?", (sid,))

    def _within_limit(self, what: str, visitor: str | None) -> None:
        if not visitor:
            return
        limit, words = ((self.rules.daily_statements, self.messages.daily_statements) if what == "statement"
                        else (self.rules.daily_reports, self.messages.daily_reports))
        with self.db.connect() as con:
            row = con.execute("SELECT n FROM wts_reply_counts WHERE day = ? AND visitor = ? AND what = ?",
                              (today(self.clock), visitor, what)).fetchone()
        if (row["n"] if row else 0) >= limit:
            raise Refused(words, f"daily_{what}s")

    def _count(self, con: sqlite3.Connection, what: str, visitor: str | None) -> None:
        """One more from this visitor code today. Earlier days are emptied first: the codes change at midnight,
        and yesterday's are of no use to anyone."""
        day = today(self.clock)
        con.execute("DELETE FROM wts_reply_counts WHERE day != ?", (day,))
        if visitor:
            con.execute("INSERT INTO wts_reply_counts (day, visitor, what, n) VALUES (?, ?, ?, 1) "
                        "ON CONFLICT(day, visitor, what) DO UPDATE SET n = n + 1", (day, visitor, what))


def _needed(reason: str | None, or_else: str) -> str:
    said = (reason or "").strip()
    if not said:
        raise NotDone(or_else)
    return said


def _words_dated(row: sqlite3.Row) -> str:
    """When the words now shown were first shown: the later of publishing and the last update."""
    return max(row["published_at"] or "", row["updated_at"] or "")
