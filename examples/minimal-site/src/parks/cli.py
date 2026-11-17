"""The owner's command line: ``parks``.

A site keeps its own Typer app, with its own commands for its own record, and adds the package's shared commands
to it: backups, reports and statements, statistics, and evaluation (``wts_core.cli``). The package prints nothing
of its own for backups, reports and statements: every line is the site's, set out below.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import typer
from wts_core.briefing import Experiment, arm_configs, experiment_switch
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
from wts_core.ports import SYSTEM_CLOCK, BriefingConfig, ExperimentState
from wts_core.replies import Replies
from wts_core.usage import Spending

from parks.evaluation import ParksEval
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

# The site's own commands


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


# The package's commands: backups

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

# The package's commands: reports, statements, hiding


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
    lapsing=lambda w: (f"At the next tidy, {w['statements']} statements would lapse and {w['reports']} open "
                       f"reports would lose their contact details (those sent before {w['before']})."
                       + (f" Statements: {w['statement_ids']}." if w["statements"] else "")
                       + (f" Reports: {w['report_ids']}." if w["reports"] else "")),
    tidied="{lapsed} statements lapsed with no decision in three months; {contacts} old reports' contact details "
           "deleted; {emails} confirming addresses deleted, three months after their statements ended; {counts} "
           "counts of earlier days' reports and statements deleted.",
    not_done="Not done: {message}",
    refused="Not done: {message}",
    errors_to_stderr=True,
)

app.add_typer(replies_commands(_replies, REPLIES_COMMANDS, REPLIES_WORDING))  # reports …, statements …, hide, …

# The package's commands: statistics, the weekly report, the nightly tidy



def _site_configuration() -> BriefingConfig:
    """The site's own configuration, worked out and not kept: for the commands, which write no reader's briefing."""
    settings = load()
    return configuration(settings, embedder_from_settings(settings), None)


def _experiment() -> ExperimentState | None:
    """The site's experiment as it stands, read and checked afresh as the site itself does when it starts."""
    settings = load()
    return experiment_switch(settings, _site_configuration(), log=None, runs=settings.runs_dir,
                             thresholds=settings.section("eval")["thresholds"],
                             prices=prices(settings)).state(SYSTEM_CLOCK)


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
    # tidy also deletes cached answers older than the site keeps them, which otherwise go when the next is stored
    cache_hours=lambda: float(load().usage["answer_cache_hours"]),
    experiment=_experiment,  # stats says whether the experiment is running, and why not
    # no question of a briefing that is hidden while a concern about it is decided is proposed as a test question
    proposals_leave_out=lambda briefing: _replies().hidden(f"/b/{briefing}") is not None,
))  # stats, weekly-report, tidy, propose-questions

# The package's commands: evaluation


def _configuration() -> Mapping[str, Any]:
    """What an evaluation run is filed under: the parts the site's configuration is made of. No record of
    briefings is given, so nothing is kept: a run is not a reader's briefing."""
    return _site_configuration().settings


def _arms() -> Mapping[str, Mapping[str, Any]]:
    """The configuration of each arm of the site's experiment, for `parks eval run --arm …`: the run an arm must
    pass before it can go live is made with exactly what the arm would run with, and filed under its id."""
    experiment = Experiment.from_settings(load())
    if experiment is None:
        return {}
    return {name: arm.settings for name, arm in arm_configs(experiment, _site_configuration()).items()}


def _spending() -> Spending:
    """The site's spending record: an evaluation run's model calls are recorded in it (as the kind "eval"), so
    that what a run costs shows in the site's spending and counts towards its caps."""
    settings = load()
    return Spending(open_state(settings), prices(settings))


app.add_typer(eval_commands(
    lambda: ParksEval(load()),
    config=_configuration, config_id=config_id,  # the id the record of briefings gives the same parts
    pricing=lambda: prices(load()),
    thresholds=lambda: load().section("eval")["thresholds"],
    runs=lambda: load().runs_dir,
    max_cost_usd=lambda: float(load().section("eval")["max_cost_usd"]),  # no run starts without a limit
    verifier=lambda: VERIFIER, loaded_words=lambda: LOADED_WORDS,
    spending=_spending, arms=_arms,
))  # eval run [--arm] | compare | replay

if __name__ == "__main__":
    app()
