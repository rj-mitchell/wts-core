"""The owner's command line: ``parks``.

A site keeps its own Typer app, with its own commands for its own record, and adds the package's shared commands
to it: backups, reports and statements, statistics, and evaluation.
"""

from __future__ import annotations

import typer

from parks.pipeline import load_minutes
from parks.site import SITE, load

app = typer.Typer(no_args_is_help=True, add_completion=False, help=f"{SITE.name}: the owner's commands.")


@app.command()
def serve(host: str = typer.Option("127.0.0.1", help="the address to listen on"),
          port: int = typer.Option(8000, help="the port to listen on")) -> None:
    """Run the site."""
    import uvicorn

    uvicorn.run("parks.app:create_app", factory=True, host=host, port=port)


@app.command()
def minutes(park: str = typer.Option("", help="only this park's")) -> None:
    """List the record: every minute the site's briefings are drawn from. This command is the site's own."""
    for minute in load_minutes(load().minutes_file):
        if not park or minute.park == park:
            typer.echo(f"{minute.date}  {minute.park}: item {minute.item}, {minute.title}")


# TODO(wts_core.cli): add the package's command groups here once ``wts_core.cli`` is on the package branch:
#   app.add_typer(ops_commands(...))       backup, restore, offsite
#   app.add_typer(replies_commands(...))   reports, statements, hide, unhide
#   app.add_typer(stats_commands(...))     stats, weekly-report, tidy
#   app.add_typer(eval_commands(...))      eval run | compare | replay

if __name__ == "__main__":
    app()
