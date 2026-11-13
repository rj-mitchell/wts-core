"""The module's tables: numbered 30 to 39, only ever adding, and able to hold every site's existing rows.

Each site brings its own rows across with an import it declares in its own repository (ADR 0005); the imports here
are drafts that show the package's columns can take them. ``OLD`` holds each site's tables as its code makes them
on 12 November 2026, copied word for word (``test_replies_parity.py`` checks the copies against the sites' code
where their checkouts are present).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from test_replies_sites import NOW, SITES
from wts_core.replies import Replies, migrations
from wts_core.state import Import, StateDB
from wts_core.testing import FixedClock


@dataclass(frozen=True)
class Old:
    """A site's own tables for reports and statements, rows of every kind in them, and a draft of its import."""

    source: str  # the file in the site's repository that makes the tables
    schema: tuple[str, ...]
    rows: tuple[str, ...]
    imports: tuple[str, ...]
    statuses: tuple[str, ...]  # of statements 1, 2, 3…, once imported
    shown: tuple[tuple[int, str, str | None, str], ...]  # the published: id, item, about, date
    log_of_the_shown: tuple[tuple[str, str | None], ...]


OLD: dict[str, Old] = {
    "mps": Old(
        "src/hansard/store/state.py",
        ("""CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    at           TEXT NOT NULL,
    kind         TEXT NOT NULL,
    briefing_id  TEXT,
    page         TEXT,
    message      TEXT NOT NULL,
    contact      TEXT,
    visitor      TEXT,
    status       TEXT NOT NULL DEFAULT 'open',
    closed_at    TEXT,
    resolution   TEXT,
    public_note  TEXT
)""", """CREATE TABLE IF NOT EXISTS statements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    at           TEXT NOT NULL,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL,
    item_path    TEXT NOT NULL,
    person       INTEGER,
    text         TEXT NOT NULL,
    link         TEXT,
    email        TEXT,
    visitor      TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    published_at TEXT,
    updated_at   TEXT,
    closed_at    TEXT,
    reason       TEXT,
    checked      TEXT
)"""),
        ("INSERT INTO reports (at, kind, briefing_id, page, message, contact, visitor, status, closed_at, resolution, "
         "public_note) VALUES "
         "('2026-11-10T09:00:00+00:00', 'correction', 'abcdefghjk', NULL, 'The second point misquotes the minister.', "
         "'reader@example.org', 'v1', 'open', NULL, NULL, NULL), "
         "('2026-11-01T09:00:00+00:00', 'takedown', NULL, '/people/10669', 'Please remove my name.', NULL, NULL, "
         "'resolved', '2026-11-02T09:00:00+00:00', 'Name removed.', 'A name was removed from a page.')",
         "INSERT INTO statements (at, name, role, item_path, person, text, link, email, visitor, status, published_at, "
         "updated_at, closed_at, reason, checked) VALUES "
         "('2026-11-09T09:00:00+00:00', 'A Group', 'Secretary', '/groups/commons/a-group', NULL, 'Waiting words here.', "
         "NULL, 'sender@example.org', 'v2', 'pending', NULL, NULL, NULL, NULL, NULL), "
         "('2026-11-03T09:00:00+00:00', 'Hilary Benn', 'MP for Leeds South', '/people/10669', 10669, 'Shown words.', "
         "'https://hansard.parliament.uk/commons/2008-06-11', 'sender@example.org', NULL, 'published', "
         "'2026-11-06T10:00:00+00:00', '2026-11-06T10:00:00+00:00', NULL, NULL, 'Replied from his parliament.uk address'), "
         "('2026-11-03T09:00:00+00:00', 'X', 'Y', '/people/10777', 10777, 'Never shown.', NULL, 'sender@example.org', "
         "NULL, 'declined', NULL, NULL, '2026-11-04T09:00:00+00:00', 'It is about another member.', NULL), "
         "('2026-10-01T09:00:00+00:00', 'X', 'Y', '/people/10777', 10777, 'Shown, then taken down.', NULL, "
         "'sender@example.org', NULL, 'declined', '2026-10-02T09:00:00+00:00', NULL, '2026-10-20T09:00:00+00:00', "
         "'It appealed for votes.', 'Phoned the office'), "
         "('2026-03-01T09:00:00+00:00', 'X', 'Y', '/b/abcdefghjk', NULL, 'Withdrawn long ago.', NULL, NULL, NULL, "
         "'withdrawn', '2026-03-02T09:00:00+00:00', NULL, '2026-04-01T09:00:00+00:00', 'Withdrawn by the author.', 'ok')"),
        ("INSERT INTO wts_reports (id, at, kind, page, message, contact, briefing_id, status, closed_at, resolution, "
         "public_note) SELECT id, at, kind, page, message, contact, briefing_id, status, closed_at, resolution, "
         "public_note FROM reports",
         # "declined" after it was shown is what the package calls removed; the visitor code is left behind
         "INSERT INTO wts_statements (id, at, item, about, name, role, text, link, email, status, published_at, "
         "updated_at, closed_at, reason) SELECT id, at, item_path, CAST(person AS TEXT), name, role, text, link, email, "
         "CASE WHEN status = 'declined' AND published_at IS NOT NULL THEN 'removed' ELSE status END, published_at, "
         "updated_at, closed_at, reason FROM statements",
         # it kept no log: one entry each, holding the note of how the sender was confirmed
         "INSERT INTO wts_statement_log (statement, at, action, note) SELECT id, at, 'imported', checked FROM statements"),
        ("pending", "published", "declined", "removed", "withdrawn"),
        ((2, "/people/10669", "10669", "2026-11-06"),),
        (("imported", "Replied from his parliament.uk address"),)),
    "countries": Old(
        "src/wcs/api/usage.py",
        ("""CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL,
    page TEXT, message TEXT NOT NULL, contact TEXT, closed_at TEXT)""",
         """CREATE TABLE IF NOT EXISTS statements (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, page TEXT NOT NULL,
    country TEXT, name TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, link TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', shown_on TEXT, ended_at TEXT, reason TEXT,
    log TEXT NOT NULL DEFAULT '[]')"""),
        ("INSERT INTO reports (at, kind, page, message, contact, closed_at) VALUES "
         "('2026-11-10T09:00:00+00:00', 'error', '/b/AbC123xy', 'A date is wrong.', 'reader@example.org', NULL), "
         "('2026-11-01T09:00:00+00:00', 'takedown', '', 'Please remove my name.', '', '2026-11-02T09:00:00+00:00')",
         "INSERT INTO statements (at, page, country, name, role, text, link, email, status, shown_on, ended_at, reason, "
         "log) VALUES "
         "('2026-11-09T09:00:00+00:00', '/b/AbC123xy', NULL, 'A', 'Role', 'Waiting words.', '', 'sender@example.org', "
         "'pending', NULL, NULL, NULL, '[{\"at\": \"2026-11-09T09:00:00+00:00\", \"action\": \"received\"}]'), "
         "('2026-11-03T09:00:00+00:00', '/b/AbC123xy', 'KEN', 'Ms. Amina Odhiambo', 'Role', 'Shown words.', "
         "'https://undocs.org/en/A/79/123', 'sender@example.org', 'published', '2026-11-06', NULL, NULL, "
         "'[{\"at\": \"2026-11-03T09:00:00+00:00\", \"action\": \"received\"}, {\"at\": \"2026-11-06T10:00:00+00:00\", "
         "\"action\": \"published\", \"note\": \"Reply from the mission''s published address.\"}]'), "
         "('2026-11-03T09:00:00+00:00', '/b/AbC123xy', NULL, 'X', 'Y', 'Never shown.', '', 'sender@example.org', "
         "'declined', NULL, '2026-11-04T09:00:00+00:00', 'Off the subject.', '[{\"at\": \"2026-11-03T09:00:00+00:00\", "
         "\"action\": \"received\"}, {\"at\": \"2026-11-04T09:00:00+00:00\", \"action\": \"declined\", \"note\": "
         "\"Off the subject.\"}]'), "
         "('2026-03-01T09:00:00+00:00', '/b/AbC123xy', NULL, 'X', 'Y', 'Withdrawn long ago.', '', '', 'withdrawn', "
         "'2026-03-02', '2026-04-01T09:00:00+00:00', 'Withdrawn by its author.', "
         "'[{\"at\": \"2026-03-01T09:00:00+00:00\", \"action\": \"received\"}]')"),
        ("INSERT INTO wts_reports (id, at, kind, page, message, contact, status, closed_at) SELECT id, at, kind, "
         "NULLIF(page, ''), message, NULLIF(contact, ''), CASE WHEN closed_at IS NULL THEN 'open' ELSE 'resolved' END, "
         "closed_at FROM reports",
         "INSERT INTO wts_statements (id, at, item, about, name, role, text, link, email, status, published_at, "
         "closed_at, reason) SELECT id, at, page, country, name, role, text, NULLIF(link, ''), NULLIF(email, ''), status, "
         "shown_on, ended_at, reason FROM statements",
         "INSERT INTO wts_statement_log (statement, at, action, note) SELECT s.id, json_extract(e.value, '$.at'), "
         "json_extract(e.value, '$.action'), json_extract(e.value, '$.note') FROM statements s, json_each(s.log) e "
         "ORDER BY s.id, e.key"),
        ("pending", "published", "declined", "withdrawn"),
        ((2, "/b/AbC123xy", "KEN", "2026-11-06"),),
        (("received", None), ("published", "Reply from the mission's published address."))),
    "landlords": Old(
        "src/landlords/api.py",
        ("""create table if not exists reports (id integer primary key, at text not null, page text, message text not null,
  email text, closed_at text, outcome text)""",
         """create table if not exists statements (id integer primary key, at text not null, name text not null, role text not null,
  page text not null, part text not null default '', text text not null, link text, email text,
  status text not null default 'pending', landlord text, checked text, reason text, published_at text,
  updated_at text, closed_at text)""",
         """create table if not exists statement_log (id integer primary key, statement integer not null, at text not null,
  action text not null, note text)""",
         "alter table reports add column kind text"),
        ("insert into reports (at, page, message, email, closed_at, outcome, kind) values "
         "('2026-11-10T09:00:00+00:00', 'landlords/x/', 'Wrong grade', 'reader@example.org', NULL, NULL, NULL), "
         "('2026-11-01T09:00:00+00:00', 'landlords/y/', 'Please remove my name.', NULL, '2026-11-02T09:00:00+00:00', "
         "'fixed', 'takedown')",
         "insert into statements (at, name, role, page, part, text, link, email, status, landlord, checked, reason, "
         "published_at, updated_at, closed_at) values "
         "('2026-11-09T09:00:00+00:00', 'Sam Officer', 'Head of housing', 'areas/leeds/', '', 'Waiting words here.', "
         "NULL, 'sender@example.org', 'pending', NULL, NULL, NULL, NULL, NULL, NULL), "
         "('2026-11-03T09:00:00+00:00', 'Jane Example', 'Chief executive', 'landlords/example-housing/', 'bands', "
         "'Shown words here.', 'https://example.org/results', 'sender@example.org', 'published', 'example-housing', "
         "'replied from the landlord''s own address', NULL, '2026-11-04T10:00:00+00:00', '2026-11-06T10:00:00+00:00', "
         "NULL), "
         "('2026-11-03T09:00:00+00:00', 'X', 'Y', 'landlords/example-housing/', '', 'Never shown at all.', NULL, "
         "'sender@example.org', 'declined', 'example-housing', NULL, 'it is about a tenant', NULL, NULL, "
         "'2026-11-04T09:00:00+00:00'), "
         "('2026-03-01T09:00:00+00:00', 'X', 'Y', 'landlords/example-housing/', '', 'Withdrawn long ago.', NULL, NULL, "
         "'withdrawn', 'example-housing', 'phoned', 'withdrawn by the author', '2026-03-02T09:00:00+00:00', NULL, "
         "'2026-04-01T09:00:00+00:00')",
         "insert into statement_log (statement, at, action, note) values "
         "(1, '2026-11-09T09:00:00+00:00', 'received', NULL), (2, '2026-11-03T09:00:00+00:00', 'received', NULL), "
         "(2, '2026-11-04T10:00:00+00:00', 'published', 'replied from the landlord''s own address'), "
         "(2, '2026-11-06T10:00:00+00:00', 'updated', 'the author''s new version'), "
         "(3, '2026-11-03T09:00:00+00:00', 'received', NULL), (3, '2026-11-04T09:00:00+00:00', 'declined', "
         "'it is about a tenant'), (4, '2026-03-01T09:00:00+00:00', 'received', NULL)"),
        ("INSERT INTO wts_reports (id, at, kind, page, message, contact, status, closed_at, resolution) SELECT id, at, "
         "kind, page, message, email, CASE WHEN closed_at IS NULL THEN 'open' ELSE 'resolved' END, closed_at, outcome "
         "FROM reports",
         "INSERT INTO wts_statements (id, at, item, part, about, name, role, text, link, email, status, published_at, "
         "updated_at, closed_at, reason) SELECT id, at, page, part, landlord, name, role, text, link, email, status, "
         "published_at, updated_at, closed_at, reason FROM statements",
         "INSERT INTO wts_statement_log (id, statement, at, action, note) SELECT id, statement, at, action, note "
         "FROM statement_log"),
        ("pending", "published", "declined", "withdrawn"),
        ((2, "landlords/example-housing/", "example-housing", "2026-11-06"),),
        (("received", None), ("published", "replied from the landlord's own address"),
         ("updated", "the author's new version"))),
}
# Where Councils Stand's tables are Where Countries Stand's, with the council where the country is
_countries = OLD["countries"]
OLD["councils"] = Old(
    "src/councils/api/state.py",
    ("""CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, page TEXT, message TEXT NOT NULL,
    contact TEXT, closed_at TEXT)""",
     """CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, page TEXT NOT NULL, council TEXT, name TEXT NOT NULL,
    role TEXT NOT NULL, text TEXT NOT NULL, link TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending', shown_on TEXT, ended_at TEXT, reason TEXT, log TEXT NOT NULL DEFAULT '[]')"""),
    tuple(row.replace("country", "council").replace("'KEN'", "'E08000038'").replace("/b/AbC123xy", "/votes/E08000038:1:10:0")
          for row in _countries.rows),
    tuple(statement.replace("country", "council") for statement in _countries.imports),
    _countries.statuses, ((2, "/votes/E08000038:1:10:0", "E08000038", "2026-11-06"),), _countries.log_of_the_shown)

OLD_TABLES = ("reports", "statements", "statement_log")


def old_database(key: str, folder: Path) -> Path:
    """A state file as the site's code of today leaves it: its own tables, with rows of every kind."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "state.db"
    con = sqlite3.connect(path)
    for statement in (*OLD[key].schema, *OLD[key].rows):
        con.execute(statement)
    con.commit()
    con.close()
    return path


def dump(path: Path, tables: tuple[str, ...]) -> list[str]:
    con = sqlite3.connect(path)
    try:
        return [line for line in con.iterdump() if any(f'"{t}"' in line or f" {t} " in line or f" {t}(" in line
                                                       for t in tables)]
    finally:
        con.close()


def adopted(key: str, folder: Path) -> tuple[Replies, StateDB]:
    clock = FixedClock(NOW)
    db = StateDB(old_database(key, folder), migrations=migrations(), clock=clock,
                 imports=[Import(f"{key}-replies", OLD[key].imports, needs=("reports", "statements"))])
    case = SITES[key]
    return Replies(db, items=case.items(), rules=case.rules, messages=case.messages, clock=clock), db


# ---- the migrations ------------------------------------------------------------------------------------------------

def test_the_migrations_are_numbered_30_to_39_and_only_add():
    made = migrations()
    numbers = [m.number for m in made]
    assert numbers == sorted(set(numbers)) and all(30 <= n <= 39 for n in numbers)
    assert [m.name for m in made] == ["reports", "statements", "statement_log", "hidden", "reply_counts"]
    for statement in (s for m in made for s in m.statements):
        assert re.match(r"CREATE (TABLE|INDEX) IF NOT EXISTS wts_\w+ ", statement), statement  # the package's own
        assert not re.search(r"\b(DROP|DELETE|ALTER|UPDATE|RENAME)\b", statement), statement


def test_the_tables_are_made_once_and_named_as_the_packages(tmp_path):
    first = StateDB(tmp_path / "state.db", migrations=migrations())
    mine = {"wts_reports", "wts_statements", "wts_statement_log", "wts_hidden", "wts_reply_counts"}
    assert mine <= first.tables() and all(t.startswith(("wts_", "sqlite_")) for t in first.tables())
    again = StateDB(tmp_path / "state.db", migrations=migrations())  # the next start changes nothing
    assert again.tables() == first.tables()
    with again.connect() as con:
        applied = [r["name"] for r in con.execute("SELECT name FROM wts_schema ORDER BY name")]
    assert [n for n in applied if n.split(":")[1] >= "30"] == [
        "migration:30:reports", "migration:31:statements", "migration:32:statement_log", "migration:33:hidden",
        "migration:34:reply_counts"]


# ---- every site's rows ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(OLD))
def test_the_tables_hold_every_sites_rows(tmp_path, key):
    old = OLD[key]
    before = dump(old_database(key, tmp_path / "before"), OLD_TABLES)
    replies, db = adopted(key, tmp_path)
    assert dump(db.path, OLD_TABLES) == before and before  # the site's own tables are left exactly as they were

    everything = {s["id"]: s for s in replies.statements()}
    assert tuple(everything[n]["status"] for n in sorted(everything)) == old.statuses
    assert everything[1]["email"] == "sender@example.org" and everything[1]["published_at"] is None  # still waiting
    assert everything[len(everything)]["email"] is None  # an address deleted long ago stays deleted, as NULL
    assert [(s["id"], s["item"], s["about"], s["date"]) for s in replies.published(everywhere=True)] == list(old.shown)
    [(sid, item, about, _)] = old.shown
    assert replies.published(items=[item]) == replies.published(about=about) == replies.published(everywhere=True)
    assert [(e["action"], e["note"]) for e in replies.log(sid)] == list(old.log_of_the_shown)
    assert all(replies.log(n) for n in everything)  # every statement arrives with its history

    [waiting] = replies.reports()
    assert (waiting["contact"], waiting["status"], waiting["closed_at"]) == ("reader@example.org", "open", None)
    closed = replies.reports(open_only=False)[-1]
    assert closed["kind"] == "takedown" and closed["closed_at"] == "2026-11-02T09:00:00+00:00" and not closed["contact"]


@pytest.mark.parametrize("key", list(OLD))
def test_imported_statements_and_reports_carry_on_under_the_package(tmp_path, key):
    replies, _ = adopted(key, tmp_path)
    [(sid, item, _, _)] = OLD[key].shown
    replies.update(sid, text="The author's new words, sent after the site adopted the package.")
    assert replies.published(items=[item])[0]["date"] == "2026-11-13"
    replies.publish(1, checked="Reply from their published address.", about="someone")
    replies.withdraw(sid, "Withdrawn by its author.")
    assert [s["id"] for s in replies.published(everywhere=True)] == [1]
    replies.close(replies.reports()[0]["id"], outcome="resolved", public_note="A date was put right.")
    assert [c["note"] for c in replies.corrections()][0] == "A date was put right."
    # the next one sent takes the next number, after the imported ones
    case = SITES[key]
    assert replies.submit(**case.statement) == len(OLD[key].statuses) + 1
