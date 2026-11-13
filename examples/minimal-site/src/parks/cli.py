"""The owner's command line: ``parks``.

A site keeps its own Typer app, with its own commands for its own record, and adds the package's shared commands
to it: backups, reports and statements, statistics, and evaluation (``wts_core.cli``). The package prints nothing
of its own for backups, reports and statements: every line is the site's, set out below.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import typer
from wts_core.cli import (
    BackupCheckWords,
    BackupWords,
    OpsWording,
    RepliesCommands,
    RepliesWording,
    RestoreWords,
    eval_commands,
    ops_commands,
    replies_commands,
    replies_tidy,
    stats_commands,
)
from wts_core.observe import config_id
from wts_core.replies import Replies

from parks.evaluation import RUNS, ParksEval
from parks.pipeline import configuration, embedder_from_settings, load_minutes
from parks.site import (
    BACKUP_ALERTS,
    BACKUPS,
    LOADED_WORDS,
    SITE,
    VERIFIER,
    load,
    open_replies,
    open_state,
    prices,
)

app = typer.Typer(no_args_is_help=True, add_completion=False, help=f"{SITE.name}: the owner's commands.")

# ---- the site's own commands -------------------------------------------------------------------------------------


@app.command()
def serve(host: str = typer.Option("127.0.0.1", help="the address to listen on"),
          port: int = typer.Option(8000, help="the port to listen on")) -> None:
    """Run the site."""
    import uvicorn

    uvicorn.run("parks.app:create_app", factory=True, host=host, port=port)


@app.command()
def minutes(park: str = typer.Option("", help="only this park's")) -> None:
    """List the record: every minute the site's briefings are drawn from."""
    for minute in load_minutes(load().minutes_file):
        if not park or minute.park == park:
            typer.echo(f"{minute.date}  {minute.park}: item {minute.item}, {minute.title}")


# ---- the package's commands: backups -----------------------------------------------------------------------------

OPS_WORDING = OpsWording(
    backup=BackupWords(
        folder="backups",  # under the data folder, unless --to says otherwise
        keep=BACKUPS.keep,
        nothing_to_back_up="There is no state database yet, so there is nothing to back up.",
        backed_up="Backed up to {archive} ({kept} kept).",
        failed=None,  # a backup that cannot be made is an error, shown as it is
        offsite_stored="A copy is stored off site in {bucket} ({stored} there now).",
        offsite_not_set_up="No copy was sent off site: off-site copies are not set up.",
        offsite_failed="The backup was made, but the off-site copy failed: {error}",
        help="Back up the state database, and send a copy off site if that is set up.",
    ),
    restore=RestoreWords(
        archive_must_exist=True,
        confirm="Replace {state_db} with the database in {archive}? Stop the site first.",
        says_aborted=True,
        restored="Restored {state_db} from {archive}.",
        replaced=" The database it replaced is kept as {kept}.",
        not_restored="Not restored: {error}",
        help="Put a backup back. Stop the site first.",
    ),
    backup_check=BackupCheckWords(
        folder="data/backups",
        no_folder="There is no folder {folder}.",
        alert="{level}: {text}",
        up_to_date="Backups are up to date.",
        alerts=BACKUP_ALERTS,
        help="Say whether the nightly backup and its off-site copy have stopped.",
    ),
    errors_to_stderr=True,
)

app.add_typer(ops_commands(SITE, load, BACKUPS, OPS_WORDING))  # backup, restore, offsite, backup-check

# ---- the package's commands: reports, statements, hiding ---------------------------------------------------------


def _replies() -> Replies:
    return open_replies(open_state(load()))


def _statement(s: Mapping[str, Any]) -> list[str]:
    lines = [f"#{s['id']}  {s['status']}  {s['at'][:10]}  beside {s['item']}", f"    from {s['name']}, {s['role']}"]
    if s["email"]:
        lines.append(f"    confirm with: {s['email']}")
    if s["link"]:
        lines.append(f"    their link: {s['link']}")
    lines += [f"    | {line}" for line in s["text"].splitlines()]
    return [*lines, f"    ({s['words']} words)"]


def _report(r: Mapping[str, Any]) -> list[str]:
    lines = [f"#{r['id']}  {r['kind'] or 'no kind'}  {r['at'][:10]}  {r['page'] or 'no page given'}",
             f"    {r['message']}"]
    return [*lines, f"    reply to: {r['contact']}"] if r["contact"] else lines


def _waiting(w: Mapping[str, Any]) -> str:
    said = f"{w['reports']} reports and {w['statements']} statements are waiting, and {w['hidden']} items are hidden."
    if w["oldest_working_days"] is None:  # nothing is waiting
        return said
    return said + f" The oldest has waited {w['oldest_working_days']} working days: the promise is five."


# The package's own names for the commands. Its nightly housekeeping is left out as a command of its own: on this
# site `parks tidy` does it with the rest (see the statistics commands below), so the timer runs one command.
REPLIES_COMMANDS = RepliesCommands(listed=("pending", "published"), outcome=None, tidy=None)

REPLIES_WORDING = RepliesWording(
    report=_report,
    statement=_statement,
    log_entry=lambda e: [f"{e['at'][:16]}  {e['action']}" + (f": {e['note']}" if e["note"] else "")],
    hidden_item=lambda h: [f"{h['item']}  hidden since {h['at'][:10]}: {h['note']}"],
    waiting=_waiting,
    published="Published statement {id}. It is shown beside {item}.",
    declined="Declined statement {id}. Tell its sender why; their address is deleted in three months.",
    updated="Updated statement {id}.",
    withdrawn="Withdrew statement {id}. Its sender's address is deleted in three months.",
    removed="Removed statement {id}. Tell its author why; their address is deleted in three months.",
    closed="Closed report {id}. Its contact details are deleted.",
    hid="Hidden: {item}. Its page now shows the note.",
    unhid="Shown again: {item}.",
    tidied="{lapsed} statements lapsed with no decision in three months; {contacts} old reports' contact details "
           "deleted; {emails} confirming addresses deleted, three months after their statements ended; {counts} "
           "counts of earlier days' reports and statements deleted.",
    not_done="Not done: {message}",
    refused="Not done: {message}",
    errors_to_stderr=True,
)

app.add_typer(replies_commands(_replies, REPLIES_COMMANDS, REPLIES_WORDING))  # reports …, statements …, hide, …

# ---- the package's commands: statistics, the weekly report, the nightly tidy -------------------------------------

app.add_typer(stats_commands(
    SITE, lambda: open_state(load()),
    thresholds=lambda: load().section("alerts"),  # empty until the owner sets them
    folder=lambda: load().reports_dir,
    embedder=lambda: embedder_from_settings(load()),
    similarity=lambda: float(load().section("embedding")["theme_similarity"]),  # read when a command runs
    pricing=lambda: prices(load()),
    backup_days=BACKUPS.keep_offsite,  # tidy deletes copies of the database older than the backups are kept
    # The one command the site's timer runs each night does the right of reply's housekeeping too: what the
    # privacy notice promises of old addresses and undecided statements must not wait for a visitor.
    also_tidy=[replies_tidy(_replies, REPLIES_WORDING)],
))  # stats, weekly-report, tidy

# ---- the package's commands: evaluation --------------------------------------------------------------------------


def _configuration() -> Mapping[str, Any]:
    """What an evaluation run is filed under: the parts the site's configuration is made of. No record of
    briefings is given, so nothing is kept: a run is not a reader's briefing."""
    settings = load()
    return configuration(settings, embedder_from_settings(settings), None).settings


app.add_typer(eval_commands(
    lambda: ParksEval(load()),
    config=_configuration, config_id=config_id,  # the id the record of briefings gives the same parts
    pricing=lambda: prices(load()),
    thresholds=lambda: load().section("eval")["thresholds"],
    runs=lambda: RUNS,
    max_cost_usd=lambda: float(load().section("eval")["max_cost_usd"]),  # no run starts without a limit
    verifier=lambda: VERIFIER, loaded_words=lambda: LOADED_WORDS,
))  # eval run | compare | replay

if __name__ == "__main__":
    app()
