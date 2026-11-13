"""The owner's commands on reports and statements, beside each site's own.

For each of the four sites, the same statements and reports are put into the site's own tables (by its own
functions, from its checkout) and into the package's ``wts_`` tables (by ``Replies``), in two temporary state
databases with their clocks stood at the same time. Then the site's own commands and the package's
(``replies_commands`` with that site's names and words, added to an app as a site adds it) are run step by step,
and what each prints, and how it ends, compared line for line.

What may differ is what docs/AS-BUILT.md lists for ``wts_core.replies``, and each difference is asserted where it
shows, never passed over:

* what cannot be done is said in the package's own words for the owner (``NotDone``: no such statement, the wrong
  status), where each site had one line of its own for it; the exit status is 1 on both;
* Where MPs Stand's "decline" of a published statement is refused: ``remove`` is the word for it;
* closing a closed report is refused (Where Landlords Stand said ``{"closed": false}`` and exited 0);
* statements are listed newest first (Where Landlords Stand listed oldest first); requests to remove a person's
  details are listed before other reports (as Where Landlords Stand's were);
* Where Landlords Stand's one command with an option for each action is commands like the other sites', and
  ``--checked`` is asked for by Typer (exit 2) before the site's own code can ask (exit 1).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cli_sites import (  # noqa: F401
    REPLIES,
    Said,
    logging_left_as_it_was,
    mounted,
    options,
    run,
    stop_their_clock,
    their_modules,
)
from test_ops_sites import COUNCILS, COUNTRIES, LANDLORDS, MPS
from test_replies_sites import BARNSLEY, SITES, Open, site_fixture
from wts_core.cli import RepliesCommands, replies_commands
from wts_core.replies import NotDone

pytestmark = pytest.mark.usefixtures("logging_left_as_it_was")
site = site_fixture()

FACTS = {"mps": MPS, "countries": COUNTRIES, "councils": COUNCILS, "landlords": LANDLORDS}
THEIRS = {"mps": ("cli", "store.state", "api.statements"), "countries": ("cli", "api.usage", "api.statements"),
          "councils": ("cli", "api.state", "api.statements", "registry"), "landlords": ("cli", "api", "statements")}
DAY = datetime(2026, 11, 9, 9, 30, tzinfo=UTC)  # a Monday
CHECKED = "Reply from their published address, 12 November."
LANDLORD_PAGES = ("example-housing", "example-council")


def landlord(slug: str) -> str:
    """Where Landlords Stand's own check of the landlord a statement speaks for, in its own words."""
    if slug not in LANDLORD_PAGES:
        raise ValueError(f"no landlord's page landlords/{slug}/ on the site")
    return slug


class Desk:
    """A site's own commands over its own tables, and the package's over ``wts_`` tables: the same statements and
    reports in both, the same time on both clocks."""

    def __init__(self, key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                 request: pytest.FixtureRequest) -> None:
        self.key, self.monkeypatch, facts = key, monkeypatch, FACTS[key]
        self.cli, *self.modules = their_modules(facts, request, *THEIRS[key])
        self.roots = {"theirs": tmp_path / "theirs", "ours": tmp_path / "ours"}
        self.data = self.roots["theirs"] / "data"
        monkeypatch.setenv(f"{facts.env_prefix}_DATA_DIR", str(self.data))
        self.open = Open(SITES[key], self.roots["ours"])
        self.replies = self.open.replies
        self.changes: list[int] = []
        commands, wording = REPLIES[key]
        about: Any = {"countries": lambda typed: self.modules[1].check_country(typed),
                      "councils": lambda typed: self.modules[2].get(typed).gss, "landlords": landlord}.get(key)
        self.app = mounted(replies_commands(lambda: self.replies, commands, wording, about=about,
                                            changed=self.changed if key == "landlords" else None))
        if key == "landlords":  # its own publish asks whether the landlord's page is on the site
            for slug in LANDLORD_PAGES:
                (self.data / "site" / "landlords" / slug).mkdir(parents=True)
                (self.data / "site" / "landlords" / slug / "index.html").write_text("<h1>A landlord</h1>")
        self.at(DAY)

    def changed(self, statement: Mapping[str, Any]) -> dict[str, int]:
        """What Where Landlords Stand does after each change: it writes its pages again, and says how many changed
        and how many statements are shown. No pages are built here, so none change."""
        self.changes.append(statement["id"])
        return {"pages_changed": 0, "shown": len(self.replies.published(everywhere=True))}

    def at(self, when: datetime) -> None:
        self.now = when
        stop_their_clock(self.monkeypatch, when, *(m for m in self.modules if hasattr(m, "datetime")))
        self.open.clock.set(when)

    def next_day(self) -> None:
        self.at(self.now + timedelta(days=1))

    def their_state(self) -> Any:
        state = self.modules[0]
        if self.key == "mps":
            return state.StateDB(self.data / "state.sqlite")
        return (state.State if self.key == "landlords" else state.StateDB)(self.data / "state.db")

    def send(self, **over: Any) -> int:
        """The same statement into both, by each one's own way in. Returns its number, the same in both."""
        body = self.open.body(**over)
        ours = self.open.send(**over)
        item = self.open.items.resolve(body["item"])
        state, st = self.their_state(), self.modules[-1]
        name, role, text, link, email = (body[k] for k in ("name", "role", "text", "link", "email"))
        if self.key == "mps":
            theirs = st.add_statement(state, name=name, role=role, item=body["item"], text=text, link=link, email=email)
        elif self.key == "countries":
            theirs = st.add_statement(state, item.address, name, role, text, link or "", email)
        elif self.key == "councils":
            theirs = state.add_statement(item.address, item.about, name, role, text, link or "", email)
        else:
            theirs = state.add_statement(name, role, item.address, item.part, text, link, email, item.about)
        assert theirs == ours
        return ours

    def report(self, **over: Any) -> int:
        body = {**self.open.case.report, "contact": "reader@example.org", **over}
        ours = self.replies.report(**body)
        kind = next(r["kind"] for r in self.replies.reports() if r["id"] == ours)  # as each site's route stores it
        state = self.their_state()
        if self.key == "countries":
            theirs = self.modules[0].add_report(state, kind, body["page"], body["message"], body["contact"])
        elif self.key == "councils":
            theirs = state.add_report(kind, body["page"], body["message"], body["contact"])
        else:
            theirs = state.add_report(body["page"], body["message"], body["contact"], kind)
        assert theirs == ours
        return ours

    def both(self, theirs: list[Any], ours: list[Any] | None = None) -> tuple[Said, Said]:
        return (run(self.cli.app, theirs, self.roots["theirs"]),
                run(self.app, theirs if ours is None else ours, self.roots["ours"]))

    def same(self, theirs: list[Any], ours: list[Any] | None = None) -> Said:
        """Run the site's command and the package's (under the same name unless another is given): they must have
        said the same and ended the same."""
        a, b = self.both(theirs, ours)
        assert b == a, f"\ntheirs: {a}\nours: {b}"
        return b

    def not_done(self, theirs: list[Any], ours: list[Any] | None = None) -> tuple[str, str]:
        """Something neither will do. Both end with status 1; each says why in its own words, which are returned
        (the site's, then the package's), from wherever each says them."""
        a, b = self.both(theirs, ours)
        assert a.exit_code == b.exit_code == 1 and a.error is None and b.error is None, f"\ntheirs: {a}\nours: {b}"
        return (a.stdout + a.stderr).strip(), (b.stdout + b.stderr).strip()


def desk_for(key: str) -> Any:
    @pytest.fixture
    def desk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Desk:
        return Desk(key, tmp_path, monkeypatch, request)

    return desk


mps, countries, councils, landlords = (desk_for(key) for key in FACTS)


# ---- Where MPs Stand: hansard statements list | publish | decline | update | withdraw ------------------------------


def test_where_mps_stands_commands(mps, tmp_path):
    d = mps
    d.send()
    d.next_day()
    d.send(name="Rachel Maskell", role="MP for York Central", item="/b/abcdefghjk", link=None,
           text="The briefing leaves out my amendment.\n\nIt was tabled on 4 November and is on the order paper.",
           email="rachel.maskell.mp@parliament.uk")
    listed = d.same(["statements", "list"])
    assert listed.stdout.startswith("#2  pending  received 2026-11-10\n  From: Rachel Maskell, MP for York Central  "
                                    "<rachel.maskell.mp@parliament.uk>\n  About: /b/abcdefghjk  (no member set)\n")
    assert "\n#1  pending  received 2026-11-09\n" in listed.stdout and "(member 10669)" in listed.stdout
    assert "  The briefing leaves out my amendment.\n  \n  It was tabled on 4 November" in listed.stdout

    # how the sender was confirmed must be said
    assert [said.exit_code for said in d.both(["statements", "publish", "1"])] == [2, 2]
    assert d.not_done(["statements", "publish", "1", "--checked", " "]) == (
        "Please say how you confirmed who sent it: it is kept privately.",
        "say how you confirmed who sent it (checked), for the log")
    d.next_day()
    assert d.same(["statements", "publish", "1", "--checked", CHECKED]) == Said(0, "published #1\n", "", None)
    assert d.same(["statements", "publish", "2", "--checked", "Phoned her office.", "--person", "10777"]).exit_code == 0
    assert d.not_done(["statements", "publish", "1", "--checked", CHECKED]) == (
        "No such statement, or it can't be changed in that way now (see `hansard statements list`).",
        "statement 1 is published, not pending")
    assert d.same(["statements", "list"]) == Said(0, "", "", None)  # none waiting now
    shown = d.same(["statements", "list", "--status", "published"])
    assert f"  Checked: {CHECKED}\n" in shown.stdout and "(member 10777)" in shown.stdout
    assert "#1  published  received 2026-11-09  published 2026-11-11\n" in shown.stdout

    # new words from the author, from a file; a published statement is then dated afresh
    words = tmp_path / "new.txt"
    words.write_text("These are the author's new words, sent by email, exactly as written.\n", encoding="utf-8")
    d.next_day()
    assert d.same(["statements", "update", "1", "--text-file", words]) == Said(0, "updated #1\n", "", None)
    assert "#1  published  received 2026-11-09  published 2026-11-12\n" in d.same(
        ["statements", "list", "--status", "published"]).stdout
    words.write_text(" ".join(["word"] * 151), encoding="utf-8")
    assert d.same(["statements", "update", "1", "--text-file", words]) == Said(
        1, "", "A statement can be up to 150 words. This one is 151.\n", None)
    assert d.same(["statements", "update", "1", "--link", ""]).exit_code == 0  # "" takes the link away
    assert "  Link: " not in d.same(["statements", "list", "--status", "published"]).stdout.split("#1  ")[1]

    third = d.send(name="A. Member", text="Vote for me at the next election, whatever this page says.")
    assert d.not_done(["statements", "decline", third, "--reason", " "]) == (
        "Please give the reason: it is sent to the author.", "give the reason: the sender is told why")
    d.next_day()
    assert d.same(["statements", "decline", third, "--reason", "It appeals for votes."]) == Said(
        0, f"declined #{third}: tell the author why; their email address is deleted in three months\n", "", None)
    assert d.same(["statements", "withdraw", "1"]) == Said(
        0, "withdrawn #1; the email address is deleted in three months\n", "", None)
    assert d.not_done(["statements", "withdraw", "1", "--note", "Asked again."])[1] == \
        "statement 1 is withdrawn, not pending or published"
    everything = d.same(["statements", "list", "--status", "all"])
    assert "  Reason: Withdrawn by the author.\n" in everything.stdout
    assert "  Reason: It appeals for votes.\n" in everything.stdout and "closed 2026-11-13" in everything.stdout
    assert d.same(["statements", "list", "--status", "declined"]).stdout.startswith(f"#{third}  declined")

    # docs/AS-BUILT.md: "decline" of a published statement was how Where MPs Stand took one down. It is refused
    # now: a statement that was shown is removed, and the list says so
    theirs, ours = d.both(["statements", "decline", "2", "--reason", "It names another member's family."])
    assert theirs == Said(0, "declined #2: tell the author why; their email address is deleted in three months\n",
                          "", None)
    assert ours == Said(1, "", "statement 2 is published, not pending\n", None)
    removed = run(d.app, ["statements", "remove", "2", "--reason", "It names another member's family."], tmp_path)
    assert removed == Said(0, "removed #2: tell the author why; their email address is deleted in three months\n",
                           "", None)
    their_list, our_list = d.both(["statements", "list", "--status", "all"])
    assert our_list.stdout == their_list.stdout.replace("#2  declined", "#2  removed")


# ---- Where Countries Stand and Where Councils Stand: one command for each action -----------------------------------


def plain_commands(d: Desk, tmp_path: Path, *, lists: str, reports: str, about: tuple[str, str], stored: str) -> None:
    """The steps the two sites share: they have the same commands, but for what the two lists are called and the
    option that says whom a statement speaks for."""
    first = d.send()
    d.next_day()
    second = d.send(name="A Second Sender", item=d.open.case.address if d.key == "countries" else "/b/abc123",
                    text="Our view.\nIn two lines.", link=None, email="second@example.org")
    listed = d.same([lists])
    assert listed.stdout.startswith(f"#{second}  2026-11-10T09:30:00+00:00  pending  ")
    assert f"    confirm with: {d.open.case.statement['email']}\n" in listed.stdout
    assert "    Our view.\n    In two lines.\n    (5 words)\n" in listed.stdout

    assert [said.exit_code for said in d.both(["publish-statement", first])] == [2, 2]  # --checked is required
    assert d.not_done(["publish-statement", first, "--checked", "  "])[1] == \
        "error: say how you confirmed who sent it (checked), for the log"
    d.next_day()
    assert d.same(["publish-statement", first, "--checked", CHECKED]) == Said(0, "published\n", "", None)
    assert d.same(["publish-statement", second, "--checked", CHECKED, *about]) == Said(0, "published\n", "", None)
    assert d.not_done(["publish-statement", first, "--checked", CHECKED]) == (
        "no waiting statement with that number", f"error: statement {first} is published, not pending")
    assert d.not_done(["decline-statement", first, "--reason", "Too late."]) == (
        "no waiting statement with that number", f"error: statement {first} is published, not pending")
    shown = d.same([lists])
    assert "; shown from 2026-11-11)" in shown.stdout and stored in shown.stdout
    assert (f"    sender confirmed: {CHECKED}\n" in shown.stdout) == (d.key == "countries")

    # new words: the site's own refusal for too many, word for word; then dated afresh
    assert d.same(["update-statement", first, "--text", " ".join(["word"] * 151)]) == Said(
        1, "", "error: " + d.open.messages.too_many_words.format(max=150, n=151) + "\n", None)
    words = tmp_path / "new.txt"
    words.write_text("New words, as the author sent them.", encoding="utf-8")
    d.next_day()
    assert d.same(["update-statement", first, "--text-file", words, "--role", "Leader"]) == Said(
        0, "updated\n", "", None)
    assert "; shown from 2026-11-12)" in d.same([lists]).stdout
    assert d.not_done(["update-statement", first]) == (
        "nothing changed: no waiting or published statement with that number, or no change",
        "error: nothing to change: give new words, a name, a role, a link or whom it speaks for")
    assert d.not_done(["update-statement", first, "--name", "   "])[1] == "error: " + d.open.messages.name_missing

    third = d.send(name="X. Candidate", text="Vote for me.", email="x@example.org")
    assert [said.exit_code for said in d.both(["decline-statement", third])] == [2, 2]  # a reason is required
    assert d.same(["decline-statement", third, "--reason", "It appeals for votes."]) == Said(0, "declined\n", "", None)
    assert d.same(["withdraw-statement", first]) == Said(0, "withdrawn\n", "", None)
    assert d.not_done(["withdraw-statement", first]) == (
        "no waiting or published statement with that number",
        f"error: statement {first} is withdrawn, not pending or published")
    assert d.not_done(["decline-statement", "999", "--reason", "x"])[1] == "error: no statement 999"
    still = d.same([lists])
    assert f"#{third}" not in still.stdout and f"#{first} " not in still.stdout and f"#{second} " in still.stdout
    everything = d.same([lists, "--all"])
    assert "; declined: It appeals for votes.)" in everything.stdout
    assert "; withdrawn: Withdrawn by its author.)" in everything.stdout

    # reports: listed, closed (the contact is deleted), and a closed one is not closed twice
    rid = d.report()
    listed = d.same([reports])
    assert listed.stdout.startswith(f"#{rid}  2026-11-12T09:30:00+00:00  ")
    assert "    reply to: reader@example.org\n" in listed.stdout
    d.next_day()
    assert d.same(["close-report", rid]) == Said(0, "closed\n", "", None)
    assert d.same([reports]) == Said(0, "", "", None)
    closed = d.same([reports, "--all"])
    assert "(closed)" in closed.stdout and "reader@example.org" not in closed.stdout
    assert d.not_done(["close-report", rid]) == ("no open report with that number", f"error: no open report {rid}")
    assert d.not_done(["close-report", "999"]) == ("no open report with that number", "error: no open report 999")


def test_where_countries_stands_commands(countries, tmp_path):
    d = countries
    plain_commands(d, tmp_path, lists="statements", reports="reports", about=("--country", "ken"),
                   stored="  (speaks for KEN)")
    # the same list under Where Councils Stand's name for it, as the site keeps it
    assert d.same(["list-statements", "--all"]) == d.same(["statements", "--all"])
    assert "list-statements" not in run(d.app, ["--help"], tmp_path).stdout
    # the site's own check of a country, in its own words
    fourth = d.send(name="Another Sender", email="another@example.org")
    assert d.same(["publish-statement", fourth, "--checked", CHECKED, "--country", "Kenya"]) == Said(
        1, "", "error: A country is given by its three-letter code, such as KEN.\n", None)
    assert d.same(["update-statement", fourth, "--country", "tza"]) == Said(0, "updated\n", "", None)
    assert "  (speaks for TZA)" in d.same(["statements"]).stdout

    # a request to remove a person's details is listed before other reports, however old (docs/AS-BUILT.md: Where
    # Landlords Stand's order): Where Countries Stand listed newest first and nothing else
    takedown = d.report(kind="takedown", message="Please remove my name from this briefing.")
    d.next_day()
    other = d.report(message="The year is wrong.")
    theirs, ours = d.both(["reports"])
    assert theirs.stdout.index(f"#{other} ") < theirs.stdout.index(f"#{takedown} ")
    assert ours.stdout.index(f"#{takedown} ") < ours.stdout.index(f"#{other} ")
    assert sorted(ours.stdout.splitlines()) == sorted(theirs.stdout.splitlines())


def test_where_councils_stands_commands(councils, tmp_path):
    d = councils
    plain_commands(d, tmp_path, lists="list-statements", reports="list-reports", about=("--council", "barnsley"),
                   stored=f"  (on {BARNSLEY}'s page)")
    fourth = d.send(name="Barnsley Council", item="/b/abc123", email="dem@barnsley.gov.uk")
    assert "  (on no council's page: --council)\n" in d.same(["list-statements"]).stdout.split(f"#{fourth} ")[1]


# ---- Where Landlords Stand: one command with an option for each action, which becomes commands ---------------------


def lines(said: Said) -> list[dict[str, Any]]:
    return [json.loads(line) for line in said.stdout.splitlines()]


def test_where_landlords_stands_commands(landlords, tmp_path):
    d = landlords
    d.send()
    d.next_day()
    d.send(name="Sam Officer", role="Head of housing, Example Council", item="areas/leeds/",
           email="sam@example-council.gov.uk")
    theirs, listed = d.both(["statements"], ["statements", "list"])
    # as the site prints it: its own names for the fields, one JSON object a line, and how many words. The same
    # lines, but newest first where the site listed oldest first (docs/AS-BUILT.md)
    assert listed.exit_code == theirs.exit_code == 0 and listed.stdout.splitlines() == theirs.stdout.splitlines()[::-1]
    assert [(row["id"], row["page"], row["landlord"], row["words"]) for row in lines(listed)] == [
        (2, "areas/leeds/", None, 19), (1, "landlords/example-housing/", "example-housing", 19)]

    # --checked: the site's own code asked for it (exit 1); now Typer does, as on the other sites (exit 2)
    theirs, ours = d.both(["statements", "--publish", "1"], ["statements", "publish", "1"])
    assert theirs == Said(1, "Not done: say how you confirmed who sent it (--checked), for the log\n", "", None)
    assert ours.exit_code == 2 and "--checked" in ours.stderr
    assert d.not_done(["statements", "--publish", "1", "--checked", " "],
                      ["statements", "publish", "1", "--checked", " "])[1] == \
        "Not done: say how you confirmed who sent it (checked), for the log"
    d.next_day()
    note = "replied from the landlord's own address, 14 Nov"
    done = d.same(["statements", "--publish", "1", "--checked", note],
                  ["statements", "publish", "1", "--checked", note])
    assert lines(done) == [{"id": 1, "status": "published", "name": "Jane Example",
                            "page": "landlords/example-housing/", "part": "", "landlord": "example-housing",
                            "email": "jane@example-housing.org.uk", "pages_changed": 0, "shown": 1}]
    # an area's page: which landlord? Each asks in its own words; then the site's own check of the landlord's page
    assert d.not_done(["statements", "--publish", "2", "--checked", "phoned the council"],
                      ["statements", "publish", "2", "--checked", "phoned the council"]) == (
        "Not done: statement 2 is about areas/leeds/: say which landlord it speaks for (--landlord)",
        "Not done: statement 2 is beside areas/leeds/: say whom it speaks for (about)")
    assert d.same(["statements", "--publish", "2", "--checked", "phoned", "--landlord", "nobody"],
                  ["statements", "publish", "2", "--checked", "phoned", "--landlord", "nobody"]) == Said(
        1, "Not done: no landlord's page landlords/nobody/ on the site\n", "", None)
    d.same(["statements", "--publish", "2", "--checked", "phoned the council", "--landlord", "example-council"],
           ["statements", "publish", "2", "--checked", "phoned the council", "--landlord", "example-council"])
    assert d.not_done(["statements", "--publish", "1", "--checked", "again"],
                      ["statements", "publish", "1", "--checked", "again"]) == (
        "Not done: statement 1 is published, not pending",) * 2  # here the site's words were already the package's

    words = tmp_path / "new.txt"
    words.write_text("Our newer results are published every quarter on our website.", encoding="utf-8")
    d.next_day()
    updated = d.same(["statements", "--update", "1", "--text-file", words, "--reason", "the author's new version"],
                     ["statements", "update", "1", "--text-file", words, "--reason", "the author's new version"])
    assert updated.exit_code == 0 and lines(updated)[0]["shown"] == 2
    words.write_text(" ".join(["extraordinarily"] * 140), encoding="utf-8")
    assert d.same(["statements", "--update", "1", "--text-file", words],
                  ["statements", "update", "1", "--text-file", words]) == Said(
        1, "Not done: A statement can be up to 2,000 characters. This one is 2,239.\n", "", None)

    third = d.send(name="X. Candidate", text="Vote for me, whatever this page says.", email="x@example.org")
    assert d.not_done(["statements", "--decline", third], ["statements", "decline", third, "--reason", " "]) == (
        "Not done: give the reasons (--reason): the sender is told why",
        "Not done: give the reason: the sender is told why")
    d.same(["statements", "--decline", third, "--reason", "It appeals for votes."],
           ["statements", "decline", third, "--reason", "It appeals for votes."])
    # a withdrawal needs its reason on this site (docs/AS-BUILT.md: the requirement stays in its command)
    assert d.not_done(["statements", "--withdraw", "1"], ["statements", "withdraw", "1"]) == (
        "Not done: say why (--reason): \"withdrawn by the author\", or the rule it broke",
        "Not done: say why it is withdrawn (--reason), for the log")
    d.next_day()
    withdrawn = d.same(["statements", "--withdraw", "1", "--reason", "withdrawn by the author"],
                       ["statements", "withdraw", "1", "--reason", "withdrawn by the author"])
    assert lines(withdrawn)[0] | {"status": "withdrawn", "shown": 1} == lines(withdrawn)[0]
    assert d.changes == [1, 2, 1, third, 1]  # the pages were written again after each change, and only then

    logged = d.same(["statements", "--log", "1"], ["statements", "log", "1"])
    assert [(e["action"], e["note"]) for e in lines(logged)] == [
        ("received", None), ("published", note), ("updated", "the author's new version"),
        ("withdrawn", "withdrawn by the author")]

    # every statement: the same lines, but newest first where the site listed oldest first (docs/AS-BUILT.md)
    theirs, ours = d.both(["statements", "--all"], ["statements", "list", "--all"])
    assert [row["id"] for row in lines(theirs)] == [1, 2, 3] and [row["id"] for row in lines(ours)] == [3, 2, 1]
    assert ours.stdout.splitlines() == theirs.stdout.splitlines()[::-1]
    assert [(row["status"], row["checked"], row["reason"]) for row in lines(ours)] == [
        ("declined", None, "It appeals for votes."), ("published", "phoned the council", None),
        ("withdrawn", note, "withdrawn by the author")]

    # reports: a request to remove a person's details first, on both
    d.report()
    d.next_day()
    d.report(kind="takedown", message="Please remove my name.")
    listed = d.same(["reports"], ["reports", "list"])
    assert [(row["id"], row["kind"], row["email"]) for row in lines(listed)] == [
        (2, "takedown", "reader@example.org"), (1, "wrong", "reader@example.org")]
    # what was done was the site's --outcome; it is the note now, and the outcome is one of the policy's two
    assert d.same(["reports", "--close", "2", "--outcome", "Removed the name."],
                  ["reports", "close", "2", "--outcome", "resolved", "--note", "Removed the name."]) == Said(
        0, '{"closed": true}\n', "", None)
    assert [row["id"] for row in lines(d.same(["reports"], ["reports", "list"]))] == [1]
    # docs/AS-BUILT.md: closing a closed report is refused; the site said so and ended as if all were well
    theirs, ours = d.both(["reports", "--close", "2", "--outcome", "Again."],
                          ["reports", "close", "2", "--outcome", "resolved"])
    assert theirs == Said(0, '{"closed": false}\n', "", None)
    assert ours == Said(1, "Not done: no open report 2\n", "", None)


# ---- names and options ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("key, commands", [
    ("mps", ("statements list", "statements publish", "statements decline", "statements update",
             "statements withdraw")),
    ("countries", ("reports", "close-report", "statements", "list-statements", "publish-statement",
                   "decline-statement", "update-statement", "withdraw-statement")),
    ("councils", ("list-reports", "close-report", "list-statements", "publish-statement", "decline-statement",
                  "update-statement", "withdraw-statement")),
])
def test_every_option_a_sites_own_command_takes_is_still_taken(key, commands, tmp_path, monkeypatch, request):
    """Under the same name, and required where it was required. The package's commands take more besides (--about
    beside the site's own name for it, --status and --all on every list)."""
    d = Desk(key, tmp_path, monkeypatch, request)
    for name in commands:
        theirs, ours = options(d.cli.app, name), options(d.app, name)
        ours_by_name = {opt: (required, default) for opts, required, default, _ in ours.values() for opt in opts}
        for opts, required, default, _ in theirs.values():
            for opt in (o for o in opts if o.startswith("--")):
                assert opt in ours_by_name and ours_by_name[opt][0] == required, (name, opt)
                # Where MPs Stand's "pending" is ``listed`` now, and the sentence its function gave a withdrawal
                # without a note is the option's own
                if (key, opt) not in (("mps", "--status"), ("mps", "--note")):
                    assert ours_by_name[opt][1] == default, (name, opt)
        arguments = [v for v in theirs.values() if not v[0][0].startswith("--")]
        assert len(arguments) == len([v for v in ours.values() if not v[0][0].startswith("--")]) == (
            0 if "list" in name or name in ("reports", "statements") else 1), name


def test_a_sites_own_descriptions_are_shown_in_place_of_the_packages(tmp_path, monkeypatch, request):
    d = Desk("mps", tmp_path, monkeypatch, request)
    assert options(d.app, "statements decline")["reason"][3] == options(d.cli.app, "statements decline")["reason"][3]
    assert options(d.app, "statements withdraw")["note"][3] == options(d.cli.app, "statements withdraw")["note"][3]
    assert "Statements beside items (the right of reply)" in run(d.app, ["--help"], tmp_path).stdout.replace("\n", " ")


# ---- the package's own: what every site gains ----------------------------------------------------------------------


def app_of(site: Open, **more: Any) -> Any:
    commands, wording = REPLIES[site.key]
    its_own: dict[str, Any] = {}
    if site.key == "landlords":  # its line for what was done says what its pages did
        its_own = {"about": landlord, "changed": lambda statement: {"pages_changed": 0, "shown": 0}}
    return mounted(replies_commands(lambda: site.replies, commands, wording, **{**its_own, **more}))


def named(site: Open, key: str) -> list[str]:
    return str(getattr(REPLIES[site.key][0], key)).split()


def test_show_and_log_give_one_statement_and_everything_done_to_it(site, tmp_path):
    app, sid = app_of(site), site.send()
    site.clock.advance(days=1)
    site.show(sid, **({"about": "example-housing"} if site.key == "landlords" else {}))
    listed = run(app, [*named(site, "statements_list"), "--all"], tmp_path)
    shown = run(app, [*named(site, "statements_show"), sid], tmp_path)
    logged = run(app, [*named(site, "statements_log"), sid], tmp_path)
    assert shown.exit_code == logged.exit_code == 0 and shown.stdout == listed.stdout + logged.stdout
    assert len(logged.stdout.splitlines()) == 2 and "received" in logged.stdout and "published" in logged.stdout
    for command in ("statements_show", "statements_log"):
        missing = run(app, [*named(site, command), "999"], tmp_path)
        assert missing.exit_code == 1 and "no statement 999" in missing.stdout + missing.stderr


def test_a_published_statement_that_breaks_the_rules_is_removed_with_the_reason(site, tmp_path):
    app, sid = app_of(site), site.send()
    remove = named(site, "statements_remove")
    waiting = run(app, [*remove, sid, "--reason", "It names a member of staff."], tmp_path)
    assert waiting.exit_code == 1 and f"statement {sid} is pending, not published" in waiting.stdout + waiting.stderr
    site.show(sid, **({"about": "example-housing"} if site.key == "landlords" else {}))
    assert run(app, [*remove, sid], tmp_path).exit_code == 2  # the reason is required
    assert run(app, [*remove, sid, "--reason", "It names a member of staff."], tmp_path).exit_code == 0
    assert site.replies.statement(sid)["status"] == "removed" and site.replies.published(everywhere=True) == []
    assert site.replies.log(sid)[-1]["note"] == "It names a member of staff."


def test_an_item_is_hidden_listed_and_shown_again(site, tmp_path):
    app, address = app_of(site), site.case.address
    assert run(app, ["hide", address], tmp_path).exit_code == 2  # the note shown in its place is required
    hid = run(app, ["hide", address, "--note", "Under review after a complaint."], tmp_path)
    assert hid.exit_code == 0 and address in hid.stdout
    assert site.replies.hidden(address)["note"] == "Under review after a complaint."
    listed = run(app, ["hidden"], tmp_path)
    assert listed.exit_code == 0 and address in listed.stdout and "Under review after a complaint." in listed.stdout
    twice = run(app, ["hide", address, "--note", "Again."], tmp_path)
    assert twice.exit_code == 1 and "is already hidden" in twice.stdout + twice.stderr
    assert run(app, ["unhide", address], tmp_path).exit_code == 0 and site.replies.hidden(address) is None
    assert run(app, ["hidden"], tmp_path).stdout == ""
    again = run(app, ["unhide", address], tmp_path)
    assert again.exit_code == 1 and "is not hidden" in again.stdout + again.stderr


def test_waiting_counts_what_is_waiting_and_how_long(site, tmp_path):
    app = app_of(site)
    site.send()
    site.replies.report(**site.case.report)
    site.replies.hide(site.case.address, "Under review.")
    site.clock.advance(days=4)  # sent on a Friday: Tuesday is two working days on
    said = run(app, ["waiting"], tmp_path)
    assert said.exit_code == 0
    if site.key == "landlords":
        assert json.loads(said.stdout) == {"reports": 1, "statements": 1, "oldest_working_days": 2, "hidden": 1}
    else:
        assert said.stdout == ("1 reports and 1 statements waiting, 1 items hidden; the oldest has waited 2 working "
                               "days\n")


def test_a_report_is_shown_and_closed_with_its_outcome_and_notes(site, tmp_path):
    app = app_of(site)
    rid = site.replies.report(**site.case.report, contact="reader@example.org")
    shown = run(app, [*named(site, "reports_show"), rid], tmp_path)
    listed = run(app, named(site, "reports_list"), tmp_path)
    assert shown.exit_code == 0 and shown.stdout == listed.stdout and "reader@example.org" in shown.stdout
    close = named(site, "reports_close")
    wrong = run(app, [*close, rid, "--outcome", "binned"], tmp_path)
    assert wrong.exit_code == 1 and "resolved or dismissed" in wrong.stdout + wrong.stderr
    done = run(app, [*close, rid, "--outcome", "dismissed", "--note", "Nothing was wrong.", "--public-note",
                     "A reader asked about a date; it was right."], tmp_path)
    assert done.exit_code == 0
    row = site.replies.reports(open_only=False)[0]
    assert (row["status"], row["resolution"], row["contact"]) == ("dismissed", "Nothing was wrong.", None)
    assert site.replies.corrections()[0]["note"] == "A reader asked about a date; it was right."
    assert run(app, [*named(site, "reports_show"), "999"], tmp_path).exit_code == 1
    # with no outcome given: the site's own, where it has one; else it must be said
    again = site.replies.report(**site.case.report)
    assert run(app, [*close, again], tmp_path).exit_code == (0 if REPLIES[site.key][0].outcome else 2)


def test_what_changed_tells_the_site_and_adds_to_what_is_said(site, tmp_path):
    seen: list[tuple[int, str]] = []

    def changed(statement: Mapping[str, Any]) -> dict[str, Any]:
        seen.append((statement["id"], statement["status"]))
        return {"pages_changed": 3, "shown": 1}

    app, sid = app_of(site, changed=changed), site.send()
    about = ["--about", "example-housing"] if site.key == "landlords" else []
    done = run(app, [*named(site, "statements_publish"), sid, "--checked", CHECKED, *about], tmp_path)
    assert done.exit_code == 0 and seen == [(sid, "published")]
    assert ('"pages_changed": 3' in done.stdout) == (site.key == "landlords")
    refused = run(app, [*named(site, "statements_publish"), sid, "--checked", CHECKED], tmp_path)
    assert refused.exit_code == 1 and seen == [(sid, "published")]  # nothing changed, so nothing was told
    run(app, [*named(site, "statements_list")], tmp_path)
    assert seen == [(sid, "published")]


def test_the_address_of_the_sender_is_not_taken_as_the_note_of_how_they_were_confirmed(site, tmp_path):
    app, sid = app_of(site), site.send()
    said = run(app, [*named(site, "statements_publish"), sid, "--checked",
                     f"Reply from {site.case.statement['email']}"], tmp_path)
    assert said.exit_code == 1 and "leave their email address out of it" in said.stdout + said.stderr
    assert site.replies.statement(sid)["status"] == "pending"


def test_a_status_there_is_not_is_refused(site, tmp_path):
    said = run(app_of(site), [*named(site, "statements_list"), "--status", "binned"], tmp_path)
    assert said.exit_code == 1 and "no such status 'binned'" in said.stdout + said.stderr


def test_names_are_the_sites_to_give(countries, tmp_path):
    commands, wording = REPLIES["countries"]
    replies = countries.replies

    def built(**names: Any) -> Any:
        import dataclasses

        return mounted(replies_commands(lambda: replies, dataclasses.replace(commands, **names), wording))

    # a command the site does not want is left out
    assert run(built(hide=None, unhide=None), ["hide", "/b/AbC123xy", "--note", "x"], tmp_path).exit_code == 2
    # two words put a command in a group, which a site may describe
    grouped = built(statements_list="replies waiting", help={"replies": "Statements under the right of reply."})
    assert run(grouped, ["replies", "waiting"], tmp_path).exit_code == 0
    assert "Statements under the right of reply." in run(grouped, ["--help"], tmp_path).stdout
    with pytest.raises(ValueError, match="can't be both a command and a group"):
        built(reports_show="reports show")  # "reports" is the list itself on this site
    with pytest.raises(ValueError, match="names no command of the package's: statement_list"):
        built(also={"all-statements": "statement_list"})


def test_the_packages_own_names_are_groups_of_commands(tmp_path):
    """A new site, which gives no names of its own."""
    case = Open(SITES["councils"], tmp_path)
    app = mounted(replies_commands(lambda: case.replies, RepliesCommands(listed=("pending",)), REPLIES["councils"][1]))
    sid = case.send()
    for args in (["reports", "list"], ["statements", "list"], ["statements", "show", sid], ["statements", "log", sid],
                 ["hidden"], ["waiting"]):
        assert run(app, args, tmp_path).exit_code == 0, args
    assert run(app, ["statements", "publish", sid, "--checked", CHECKED, "--about", BARNSLEY], tmp_path).stdout == \
        "published\n"
    for args in (["reports", "show", "9"], ["reports", "close", "9", "--outcome", "resolved"],
                 ["statements", "decline", sid, "--reason", "x"], ["statements", "remove", "9", "--reason", "x"],
                 ["statements", "withdraw", "9"], ["statements", "update", "9", "--name", "A Name"], ["unhide", "/x"]):
        assert run(app, args, tmp_path).exit_code == 1, args
    with pytest.raises(NotDone):
        case.replies.withdraw(99)
