"""The commands a site adds to its own command line, and the route the nightly check asks.

A site keeps its own Typer app, with its own commands for its own record, and adds the shared ones to it::

    app.add_typer(ops_commands(SITE, load_settings, SPEC, OPS_WORDING))          # backup, restore, offsite, …
    app.add_typer(replies_commands(replies, REPLIES_COMMANDS, REPLIES_WORDING))  # reports …, statements …, hide
    app.add_typer(stats_commands(SITE, state, thresholds=…, folder=…))           # stats, weekly-report, tidy
    app.add_typer(eval_commands(eval_site, config=…, …, max_cost_usd=2.0))       # eval run | compare | replay

For the commands the four sites already had (backups, reports and statements), every name and every printed line
is the site's own, passed in: ``OpsWording`` and its parts, ``RepliesCommands`` and ``RepliesWording``. There the
package prints nothing of its own but the reason an owner's request could not be done. The statistics and
evaluation commands are new on every site, and say what they say in the package's own plain words, as the weekly
report does; a site may still rename them.

``check_route`` is what answers ``GET /api/check`` (ADR 0010): a plain function a site's own route calls, so this
package imports no web framework. It, and importing this module, need no outside library: Typer (the ``cli``
extra) is imported only when one of the four ``…_commands`` functions is called.
"""

from __future__ import annotations

from wts_core.cli.check import backup_ages, check_route, last_day_figures
from wts_core.cli.eval import eval_commands
from wts_core.cli.ops import BackupCheckWords, BackupWords, OpsWording, RestoreWords, ops_commands
from wts_core.cli.replies import RepliesCommands, RepliesWording, replies_commands
from wts_core.cli.stats import StatsNames, stats_commands

__all__ = [
    "BackupCheckWords",
    "BackupWords",
    "OpsWording",
    "RepliesCommands",
    "RepliesWording",
    "RestoreWords",
    "StatsNames",
    "backup_ages",
    "check_route",
    "eval_commands",
    "last_day_figures",
    "ops_commands",
    "replies_commands",
    "stats_commands",
]
