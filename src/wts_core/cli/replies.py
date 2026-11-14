"""The owner's commands for reports, statements under the right of reply and hidden items, for a site to add to
its own command line (ADR 0008).

``replies_commands`` gives, over one ``wts_core.replies.Replies``:

* ``reports list | show | close``;
* ``statements list | show | publish | decline | update | withdraw | remove | log``;
* ``hide``, ``unhide``, ``hidden`` (what is hidden now) and ``waiting`` (what is waiting for the owner);
* ``tidy-replies``: the right of reply's nightly housekeeping, for a site's timer. ``replies_tidy`` is the same
  work as a step, for a site whose one nightly command is the statistics group's ``tidy``
  (``stats_commands(..., also_tidy=[replies_tidy(replies, wording)])``).

The four sites each wrote these out, under different names and with different words (docs/study/
reports-statements.md, section 1): ``hansard statements publish 3``, ``wcs publish-statement 3``,
``councils list-reports``. A site keeps its own. ``RepliesCommands`` says what each command is called (two words
put it in a group, one word leaves it beside the site's other commands, None leaves it out), what the option that
says whom a statement speaks for is called, and what the commands do when an option is not given.
``RepliesWording`` holds every line printed: a function for each kind of thing listed, and a line for each thing
done. The package has no line of its own but the reason something could not be done, which is
``replies.NotDone``'s, in words for the owner; a site's own words for a statement that breaks a rule
(``replies.Refused``) are printed as they are. Either ends the command with exit status 1.

One shape is not offered: Where Landlords Stand's single ``statements`` command with an option for each action
(``--publish 3``). Its actions become commands like the other sites'; what each prints is still its own. A site
that must keep such a shape working for a while keeps it itself, as the callback of a group of its own, and gives
that group to ``replies_commands`` (``groups={"statements": its_group}``): the package's commands then join it,
in the one call.

Typer is imported when the commands are built, so ``wts_core.cli`` can be imported without it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from wts_core.replies import NotDone, Refused, Replies, StatementStatus, word_count

if TYPE_CHECKING:
    import typer

__all__ = ["RepliesCommands", "RepliesWording", "replies_commands", "replies_tidy"]

# a line said when something was done: a template filled with the fields of what it was done to, or a function of
# those fields
type Line = str | Callable[[Mapping[str, Any]], str]
type Lines = Callable[[Mapping[str, Any]], Sequence[str]]


@dataclass(frozen=True, kw_only=True)
class RepliesCommands:
    """What a site calls each command, and what each does when an option is left out. The names here are the
    package's own, for a new site; each of the four older sites gives its own.

    A name of two words is a command in a group (``"statements publish"``); of one word, a command beside the
    site's others (``"publish-statement"``); None leaves the command out."""

    listed: tuple[str, ...]  # the statuses ``statements list`` shows when no option is given
    reports_list: str | None = "reports list"
    reports_show: str | None = "reports show"
    reports_close: str | None = "reports close"
    statements_list: str | None = "statements list"
    statements_show: str | None = "statements show"
    statements_publish: str | None = "statements publish"
    statements_decline: str | None = "statements decline"
    statements_update: str | None = "statements update"
    statements_withdraw: str | None = "statements withdraw"
    statements_remove: str | None = "statements remove"
    statements_log: str | None = "statements log"
    hide: str | None = "hide"
    unhide: str | None = "unhide"
    hidden: str | None = "hidden"
    waiting: str | None = "waiting"
    tidy: str | None = "tidy-replies"  # the nightly housekeeping (``replies_tidy``)
    # further names for a command, kept out of the help: {"list-statements": "statements_list"}
    also: Mapping[str, str] = field(default_factory=dict)
    # the site's own name for --about, the option that says whom a statement speaks for: "--person", "--country"
    about_option: str | None = None
    # what a withdrawal's note is when none is given (Where Countries Stand: "Withdrawn by its author."), and
    # whether one must be given (Where Landlords Stand)
    withdraw_note: str | None = None
    withdraw_note_required: bool = False
    # how a report is closed when --outcome is not given ("resolved" or "dismissed"); None: it must be given
    outcome: str | None = None
    # the site's own descriptions: of a group ("statements"), of a command ("statements_publish"), of an option
    # ("statements_publish.checked"). Where there is none the package's plain one is used
    help: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RepliesWording:
    """Every line the commands print. A site supplies each line its commands need, and the package has none to
    put in its place. A line for a command the site left out (``None`` in ``RepliesCommands``) need not be given;
    one missing for a command the site has stops the commands being built, naming the line.

    The listing functions are given one row and return its lines. A statement's row is what ``Replies.statement``
    returns, with ``words`` (how many) and ``log`` (``Replies.log``: the note of how its sender was confirmed is
    there). The lines for what was done are templates filled with that same row as it now is (``"published
    #{id}"``), and with whatever the site's ``changed`` returned; or functions of it."""

    not_done: str  # {message}: why the owner's request could not be done, in the package's words
    refused: str  # {message}: the site's own words for new wording that breaks a rule
    errors_to_stderr: bool  # where those two are said: standard error, or standard output
    report: Lines | None = None  # one report, as ``Replies.reports`` returns it
    statement: Lines | None = None
    log_entry: Lines | None = None  # one thing done to a statement: at, action, note, previous
    hidden_item: Lines | None = None  # item, note, at
    waiting: Line | None = None  # reports, statements, hidden, oldest_working_days
    published: Line | None = None
    declined: Line | None = None
    updated: Line | None = None
    withdrawn: Line | None = None
    removed: Line | None = None
    closed: Line | None = None  # the report's fields, as they now are
    hid: Line | None = None  # item, note
    unhid: Line | None = None  # item
    # what the nightly housekeeping did, each a count: lapsed (statements nobody decided in three months, now
    # declined), contacts (old open reports whose contact details were deleted), emails (confirming addresses
    # deleted three months after their statements ended), counts (rows of earlier days' daily counts deleted)
    tidied: Line | None = None


# the lines each command prints: a site that has the command gives them
_LINES: dict[str, tuple[str, ...]] = {
    "reports_list": ("report",), "reports_show": ("report",), "reports_close": ("closed",),
    "statements_list": ("statement",), "statements_show": ("statement", "log_entry"),
    "statements_publish": ("published",), "statements_decline": ("declined",), "statements_update": ("updated",),
    "statements_withdraw": ("withdrawn",), "statements_remove": ("removed",), "statements_log": ("log_entry",),
    "hide": ("hid",), "unhide": ("unhid",), "hidden": ("hidden_item",), "waiting": ("waiting",),
    "tidy": ("tidied",),
}

# the package's own descriptions of each command and option, used where a site gives none
_HELP: dict[str, str] = {
    "reports": "Problems and requests sent through the site's form.",
    "statements": "Statements under the right of reply: list, publish, decline, update, withdraw and remove them.",
    "reports_list": "Reports that are open, requests to remove a person's name or details first.",
    "reports_list.all": "include reports already closed",
    "reports_show": "One report.",
    "reports_close": "Close a report. Its contact details are deleted.",
    "reports_close.outcome": "how it ended: resolved or dismissed",
    "reports_close.note": "what was found and done (kept privately)",
    "reports_close.public_note": "what the corrections log says of it; it must name no one who reported",
    "statements_list": "Statements, with the address to confirm who sent each.",
    "statements_list.status": "only those with this status: pending, published, declined, withdrawn, removed or all",
    "statements_list.all": "every statement, whatever its status",
    "statements_show": "One statement, and everything done to it.",
    "statements_publish": "Show a waiting statement, as written, once you have confirmed who sent it.",
    "statements_publish.checked": "how you confirmed who sent it, for the log (never shown; leave their email "
                                  "address out of it)",
    "statements_publish.about": "whom it speaks for, when its item's address doesn't say",
    "statements_decline": "Decline a waiting statement, with the reason its sender is told.",
    "statements_decline.reason": "why: its sender is told, and it is never shown",
    "statements_update": "Replace a statement's words, name, role or link at its author's request.",
    "statements_update.text": "the author's new words, as sent",
    "statements_update.text_file": "a file holding the author's new words, as sent",
    "statements_update.name": "the new name",
    "statements_update.role": "the new role",
    "statements_update.link": "the new link to the record; \"\" takes it away",
    "statements_update.about": "whom it speaks for",
    "statements_update.note": "a note for the log, such as what the update took out",
    "statements_withdraw": "Take a statement down, or stop one waiting, because its author asked.",
    "statements_withdraw.note": "a note for the log, such as the date they asked",
    "statements_remove": "Take a published statement down because it breaks the rules.",
    "statements_remove.reason": "the rule it broke: its author is told",
    "statements_log": "Everything done to a statement, oldest first.",
    "hide": "Hide an item while a concern about it is decided.",
    "hide.note": "what its pages show in its place",
    "unhide": "Show a hidden item again.",
    "hidden": "The items hidden now, longest hidden first.",
    "waiting": "What is waiting for a decision, and how long the oldest has waited.",
    "tidy": "Delete what the right of reply no longer keeps: old confirming addresses, the contact details of old "
            "reports, what nobody decided in three months, and earlier days' counts. For the nightly timer.",
}


def replies_tidy(replies: Callable[[], Replies], wording: RepliesWording) -> Callable[[], list[str]]:
    """The right of reply's nightly housekeeping, as a step that says what it did in the site's own words
    (``RepliesWording.tidied``): confirming addresses deleted three months after their statements ended, what
    nobody decided in three months lapsed, and earlier days' counts (which hold visitor codes) emptied.

    The site's routes do the same on every write, the owner's listings on every reading, and the nightly family
    check when it asks what is waiting. This is for the night nobody writes in, on a site with no check token
    set: the privacy notice's three months must not depend on a visitor. Give it to the statistics group, so the
    site's timer runs one command (``stats_commands(..., also_tidy=[replies_tidy(replies, wording)])``); or run
    the command ``replies_commands`` adds (``RepliesCommands.tidy``), which calls this."""

    line = wording.tidied
    if line is None:
        raise ValueError("RepliesWording.tidied is not given: the nightly housekeeping says what it did in the "
                         "site's own words")

    def tidy() -> list[str]:
        desk = replies()
        emails = desk.forget_old_emails()
        lapsed, contacts = desk.lapse_undecided()
        counts = desk.forget_old_counts()
        row = {"lapsed": lapsed, "contacts": contacts, "emails": emails, "counts": counts}
        return [line(row) if callable(line) else line.format(**row)]

    return tidy


def replies_commands(replies: Callable[[], Replies], commands: RepliesCommands, wording: RepliesWording, *,
                     about: Callable[[str], str] | None = None,
                     changed: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
                     groups: Mapping[str, typer.Typer] | None = None) -> typer.Typer:
    """The site's commands for reports, statements and hidden items, to add to its own app with
    ``app.add_typer(...)`` (no name: they join the site's other commands, under the names the site gave).

    ``replies`` is called when a command runs, never when the commands are built. ``about`` turns what the owner
    typed for whom a statement speaks for into what is stored (a country's code, a council's, a landlord's page),
    or raises ``ValueError`` with the site's words.

    ``changed`` is called after each change that a page may show, so that a site whose pages are built ahead of
    time can write them again (Where Landlords Stand does): after a change to a statement, with the statement as
    it now is; after a report is closed, with the report; after an item is hidden or shown again, with its
    ``item`` (and its ``note``, when hidden). What it returns is added to the fields the line for what was done
    is filled with. It is not called when nothing changed.

    ``groups`` gives a group of the site's own for a group of these commands to join: ``{"statements":
    its_group}`` puts ``statements publish`` and the rest into ``its_group``, which keeps its own description and
    its own callback. That is how a site keeps an older shape of command working beside the new ones
    (``statements --publish 3``, as the group's callback), with one call here."""
    import typer

    app = typer.Typer(add_completion=False)
    made: dict[str, typer.Typer] = {}
    own = dict(groups or {})
    singles: set[str] = set()

    def described(key: str) -> str:
        return commands.help.get(key, _HELP[key])

    def option(key: str, default: Any, *names: str, **more: Any) -> Any:
        return typer.Option(default, *names, help=described(key), **more)

    def place(key: str) -> Callable[[Callable[..., None]], Callable[..., None]]:
        """Register a command under the site's name for it, and under any further names it has."""

        def register(function: Callable[..., None]) -> Callable[..., None]:
            called = [(getattr(commands, key), False), *((name, True) for name, of in commands.also.items()
                                                         if of == key)]
            for name, out_of_help in called:
                if name is None:
                    continue
                *group, last = name.split()
                if len(group) > 1 or (not group and last in made) or (group and group[0] in singles):
                    raise ValueError(f"RepliesCommands.{key}: {name!r} can't be both a command and a group")
                if group and group[0] not in made:
                    if group[0] in own:  # the site's own group: its description and its callback stay its own
                        made[group[0]] = own[group[0]]
                        app.add_typer(made[group[0]], name=group[0])
                    else:
                        made[group[0]] = typer.Typer(no_args_is_help=True)
                        app.add_typer(made[group[0]], name=group[0],
                                      help=commands.help.get(group[0], _HELP.get(group[0])))
                if not group:
                    singles.add(last)
                (made[group[0]] if group else app).command(last, help=described(key), hidden=out_of_help)(function)
            return function

        return register

    unknown = sorted(set(commands.also.values()) - {f.name for f in fields(commands)})
    if unknown:
        raise ValueError(f"RepliesCommands.also names no command of the package's: {', '.join(unknown)}")
    has = {key for key in _LINES if getattr(commands, key) is not None or key in commands.also.values()}
    missing = sorted({line for key in has for line in _LINES[key] if getattr(wording, line) is None})
    if missing:
        raise ValueError("RepliesWording needs " + ", ".join(missing) + ": the site has the commands that print "
                         "them. Give the lines, or leave those commands out (None in RepliesCommands)")
    in_use = {str(name).split()[0] for key in has for name in (getattr(commands, key), *(
        n for n, of in commands.also.items() if of == key)) if name is not None and len(str(name).split()) == 2}
    unused = sorted(set(own) - in_use)
    if unused:
        raise ValueError(f"groups names {', '.join(unused)}, and no command is in a group of that name: a command "
                         "joins a group by a name of two words (\"statements publish\")")

    def line(name: str) -> Any:
        return getattr(wording, name)  # there, or the commands would not have been built

    def told(row: Mapping[str, Any]) -> dict[str, Any]:
        """The row a line is filled with, once the site has been told of the change."""
        return {**row, **((changed(row) or {}) if changed is not None else {})}

    def say(said: Line, row: Mapping[str, Any]) -> None:
        typer.echo(said(row) if callable(said) else said.format(**row))

    def show(lines: Sequence[str]) -> None:
        for each in lines:
            typer.echo(each)

    @contextmanager
    def answering() -> Iterator[None]:
        """What can't be done is said in a line, and the command ends with status 1."""
        try:
            yield
        except (NotDone, Refused) as exc:
            template = wording.refused if isinstance(exc, Refused) else wording.not_done
            typer.echo(template.format(message=exc), err=wording.errors_to_stderr)
            raise typer.Exit(1) from exc

    def whom(typed: str | None) -> str | None:
        if typed is None or about is None:
            return typed
        try:
            return about(typed)
        except (NotDone, Refused):
            raise
        except ValueError as exc:  # the site's own check of a country, council or landlord, in its words
            raise NotDone(str(exc)) from exc

    def whole(desk: Replies, row: Mapping[str, Any]) -> dict[str, Any]:
        return {**row, "words": word_count(row["text"]), "log": desk.log(row["id"])}

    def found(desk: Replies, sid: int) -> dict[str, Any]:
        row = desk.statement(sid)
        if row is None:
            raise NotDone(f"no statement {sid}")
        return whole(desk, row)

    def done(said: Line, desk: Replies, sid: int) -> None:
        say(said, told(found(desk, sid)))

    number = typer.Argument(..., help="its number, from the list")
    about_names = ("--about", *((commands.about_option,) if commands.about_option else ()))

    # ---- reports ------------------------------------------------------------------------------------------------

    every_report = option("reports_list.all", False, "--all")

    @place("reports_list")
    def reports_list(everything: bool = every_report) -> None:
        for row in replies().reports(open_only=not everything):
            show(line("report")(row))

    @place("reports_show")
    def reports_show(rid: int = number) -> None:
        with answering():
            show(line("report")(_report(replies(), rid)))

    outcome_option = option("reports_close.outcome", commands.outcome if commands.outcome is not None else ...,
                            "--outcome")
    close_note = option("reports_close.note", None, "--note")
    public_note_option = option("reports_close.public_note", None, "--public-note")

    @place("reports_close")
    def reports_close(rid: int = number, outcome: str = outcome_option, note: str | None = close_note,
                      public_note: str | None = public_note_option) -> None:
        desk = replies()
        with answering():
            desk.close(rid, outcome=outcome, note=note, public_note=public_note)
            say(line("closed"), told(_report(desk, rid)))

    # ---- statements ---------------------------------------------------------------------------------------------

    status_option = option("statements_list.status", None, "--status")
    every_statement = option("statements_list.all", False, "--all")

    @place("statements_list")
    def statements_list(status: str | None = status_option, everything: bool = every_statement) -> None:
        desk = replies()
        with answering():
            if everything or status == "all":
                rows = desk.statements()
            elif status:
                rows = desk.statements(cast("StatementStatus", status))  # the desk refuses a status there isn't
            else:
                rows = [row for row in desk.statements() if row["status"] in commands.listed]
        for row in rows:
            show(line("statement")(whole(desk, row)))

    @place("statements_show")
    def statements_show(sid: int = number) -> None:
        desk = replies()
        with answering():
            row = found(desk, sid)
        show(line("statement")(row))
        for entry in row["log"]:
            show(line("log_entry")(entry))

    checked_option = option("statements_publish.checked", ..., "--checked")
    publish_about = option("statements_publish.about", None, *about_names)

    @place("statements_publish")
    def statements_publish(sid: int = number, checked: str = checked_option, speaks_for: str | None = publish_about,
                           ) -> None:
        desk = replies()
        with answering():
            desk.publish(sid, checked=checked, about=whom(speaks_for))
            done(line("published"), desk, sid)

    decline_reason = option("statements_decline.reason", ..., "--reason")

    @place("statements_decline")
    def statements_decline(sid: int = number, reason: str = decline_reason) -> None:
        desk = replies()
        with answering():
            desk.decline(sid, reason)
            done(line("declined"), desk, sid)

    text_option = option("statements_update.text", None, "--text")
    text_file_option = option("statements_update.text_file", None, "--text-file", exists=True, dir_okay=False)
    name_option = option("statements_update.name", None, "--name")
    role_option = option("statements_update.role", None, "--role")
    link_option = option("statements_update.link", None, "--link")
    update_about = option("statements_update.about", None, *about_names)
    update_note = option("statements_update.note", None, "--note", "--reason")

    @place("statements_update")
    def statements_update(sid: int = number, text: str | None = text_option, text_file: Path | None = text_file_option,
                          name: str | None = name_option, role: str | None = role_option,
                          link: str | None = link_option, speaks_for: str | None = update_about,
                          note: str | None = update_note) -> None:
        desk = replies()
        words = text_file.read_text(encoding="utf-8") if text_file is not None else text
        with answering():
            desk.update(sid, text=words, name=name, role=role, link=link, about=whom(speaks_for), note=note)
            done(line("updated"), desk, sid)

    withdraw_note = option("statements_withdraw.note", commands.withdraw_note, "--note", "--reason")

    @place("statements_withdraw")
    def statements_withdraw(sid: int = number, note: str | None = withdraw_note) -> None:
        desk = replies()
        with answering():
            if commands.withdraw_note_required and not (note or "").strip():
                raise NotDone("say why it is withdrawn (--reason), for the log")
            desk.withdraw(sid, note)
            done(line("withdrawn"), desk, sid)

    remove_reason = option("statements_remove.reason", ..., "--reason")

    @place("statements_remove")
    def statements_remove(sid: int = number, reason: str = remove_reason) -> None:
        desk = replies()
        with answering():
            desk.remove(sid, reason)
            done(line("removed"), desk, sid)

    @place("statements_log")
    def statements_log(sid: int = number) -> None:
        desk = replies()
        with answering():
            row = found(desk, sid)
        for entry in row["log"]:
            show(line("log_entry")(entry))

    # ---- hiding an item, and what is waiting --------------------------------------------------------------------

    item_argument = typer.Argument(..., help="the item's address, as the site files it")
    hide_note = option("hide.note", ..., "--note")

    @place("hide")
    def hide(item: str = item_argument, note: str = hide_note) -> None:
        desk = replies()
        with answering():
            desk.hide(item, note)
            say(line("hid"), told(desk.hidden(item) or {"item": item, "note": note}))

    @place("unhide")
    def unhide(item: str = item_argument) -> None:
        with answering():
            replies().unhide(item)
            say(line("unhid"), told({"item": item.strip()}))

    @place("hidden")
    def hidden() -> None:
        for row in replies().all_hidden():
            show(line("hidden_item")(row))

    @place("waiting")
    def waiting() -> None:
        say(line("waiting"), asdict(replies().waiting()))

    @place("tidy")
    def tidy() -> None:
        show(replies_tidy(replies, wording)())

    return app


def _report(desk: Replies, rid: int) -> dict[str, Any]:
    row = next((r for r in desk.reports(open_only=False) if r["id"] == rid), None)
    if row is None:
        raise NotDone(f"no report {rid}")
    return row
