"""The commands a site adds to its own command line, and the route the nightly check asks.

A site keeps its own Typer app, with its own commands for its own record, and adds the shared ones to it::

    app.add_typer(ops_commands(SITE, load_settings, SPEC, OPS_WORDING))          # backup, restore, offsite, …
    app.add_typer(replies_commands(replies, REPLIES_COMMANDS, REPLIES_WORDING))  # reports …, statements …, hide, …

Every name and every printed line is the site's own, passed in: ``OpsWording`` and its parts, ``RepliesCommands``
and ``RepliesWording``. The package prints nothing of its own but the reason an owner's request could not be
done.

``check_route`` is what answers ``GET /api/check`` (ADR 0010): a plain function a site's own route calls, so this
package imports no web framework. It, and importing this module, need no outside library: Typer (the ``cli``
extra) is imported only when ``ops_commands`` or ``replies_commands`` is called.
"""

from __future__ import annotations

from wts_core.cli.check import backup_ages, check_route
from wts_core.cli.ops import BackupCheckWords, BackupWords, OpsWording, RestoreWords, ops_commands
from wts_core.cli.replies import RepliesCommands, RepliesWording, replies_commands

__all__ = [
    "BackupCheckWords",
    "BackupWords",
    "OpsWording",
    "RepliesCommands",
    "RepliesWording",
    "RestoreWords",
    "backup_ages",
    "check_route",
    "ops_commands",
    "replies_commands",
]
