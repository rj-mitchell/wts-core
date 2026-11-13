"""The evaluation commands, for a site to add to its own command line (docs/ARCHITECTURE.md, section 6).

``eval_commands`` gives three, over ``wts_core.eval``::

    app.add_typer(eval_commands(lambda: MyEvalSite(load_settings()), config=…, config_id=…, pricing=…,
                                thresholds=…, runs=lambda: ROOT / "eval" / "runs", max_cost_usd=2.0))

* ``eval run``: asks the site's test questions of the configuration the site gives, saves the run under the site's
  ``eval/runs/``, prints its figures and holds them to the site's thresholds. A run that asked the whole set and
  met every threshold is noted as a pass (``eval.mark_passed``: the line the experiment guard reads). One that
  failed a threshold, or stopped at its budget, prints why in plain sentences and ends with status 1.
* ``eval compare A B``: two saved runs side by side.
* ``eval replay DIR``: the checks run again over recorded briefings, free and offline; every difference from what
  was recorded is printed, and any that is weaker ends with status 1 (the checks on briefings never weaken).
  Offered when the site gives its verifier and its loaded words.

**A run costs money, so it never starts without a limit.** ``max_cost_usd`` has no default in the package: the
site passes its own figure, or None, and then ``--max-cost`` must be given each time. The charity's evaluation
budget is small.

These commands are new on every site but Where MPs Stand, whose own ``eval`` group keeps its own commands: it adds
these to that group (``group=None``). What they print is the package's, in the plain style of the comparison page.

Typer is imported when the commands are built, so ``wts_core.cli`` can be imported without it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wts_core.checks import LoadedWords, Verifier
from wts_core.eval import (
    CaseResult,
    EvalSite,
    check_thresholds,
    compare,
    load,
    load_fixture,
    mark_passed,
    replay,
    run,
    save,
)
from wts_core.eval.compare import _LABELS, _number
from wts_core.ports import SYSTEM_CLOCK, Clock, Pricing

if TYPE_CHECKING:
    import typer

__all__ = ["eval_commands"]


def eval_commands(site: Callable[[], EvalSite], *, config: Callable[[], Mapping[str, Any]],
                  config_id: Callable[[Mapping[str, Any]], str], pricing: Callable[[], Pricing],
                  thresholds: Callable[[], Mapping[str, float]], runs: Callable[[], Path],
                  max_cost_usd: float | Callable[[], float | None] | None,
                  verifier: Callable[[], Verifier] | None = None,
                  loaded_words: Callable[[], LoadedWords] | None = None, curled: bool = False,
                  group: str | None = "eval", clock: Clock = SYSTEM_CLOCK) -> typer.Typer:
    """The site's evaluation commands, to add to its own app with ``app.add_typer(...)``.

    Everything is asked for when a command runs, never when the commands are built. ``site`` is the site's
    ``EvalSite``; ``config`` the configuration to evaluate (the site's settings as they stand, or as the owner is
    trying them) and ``config_id`` the id the site's record of briefings gives it (``observe.config_id`` of the
    parts the site chooses); ``pricing`` the site's prices; ``thresholds`` its evaluation thresholds
    (``min_grounded_ratio`` and the like); ``runs`` the folder runs are kept in. ``max_cost_usd`` is what a run
    may spend when ``--max-cost`` is not given: the site's own figure, or a function that gives it when the
    command runs (for a site that keeps it in its settings), or None to make the owner say each time.

    ``verifier`` and ``loaded_words`` are the site's own checks, for ``replay`` (and ``curled`` whether the site
    curls its quotation marks). ``group`` is the name the three commands sit under; None puts them straight into
    the app returned, for a site that adds them to a group of its own."""
    import typer

    app = typer.Typer(add_completion=False)
    commands = app
    if group is not None:
        commands = typer.Typer(no_args_is_help=True)
        app.add_typer(commands, name=group, help="Measure the site on its test questions before a change ships.")

    def stop(why: object) -> typer.Exit:
        typer.echo(str(why), err=True)
        return typer.Exit(1)

    def progress(result: CaseResult) -> None:
        if result.outcome == "not_run":
            return
        typer.echo(f"{result.id}: {result.outcome}" + (f" ({result.error_type})" if result.error_type else "")
                   + f", ${result.cost_usd:.4f}")

    only_option = typer.Option(None, "--only", help="ask only the question with this id (may be given more than "
                                                    "once)")
    limit_option = typer.Option(None, "--limit", help="ask no more than this many, from the start of the set")
    # a figure given outright is the option's default, shown in its help; one read from settings is asked for
    # only when the command runs
    cost_option = typer.Option(None if callable(max_cost_usd) else max_cost_usd, "--max-cost",
                               help="stop once this many US dollars are spent")
    fixtures_option = typer.Option(None, "--record-fixtures", help="save each briefing written in this folder, "
                                                                    "as a fixture for replay")
    out_option = typer.Option(None, "--out", help="where to save the run; the site's own folder of runs if not "
                                                  "given")

    @commands.command("run", help="Ask the site's test questions, save the run and hold it to the thresholds.")
    def run_(only: list[str] | None = only_option, limit: int | None = limit_option,
             max_cost: float | None = cost_option, record_fixtures: Path | None = fixtures_option,
             out: Path | None = out_option) -> None:
        if max_cost is None and callable(max_cost_usd):
            max_cost = max_cost_usd()
        if max_cost is None:
            raise typer.BadParameter("say how much this run may spend, in US dollars: the site sets no figure of "
                                     "its own, and no run starts without a limit", param_hint="--max-cost")
        if max_cost < 0:
            raise typer.BadParameter("the most a run may spend cannot be less than nothing", param_hint="--max-cost")
        settings = config()
        limits = thresholds()
        try:
            made = run(site(), settings, config_id=config_id(settings), pricing=pricing(), clock=clock,
                       record_fixtures=record_fixtures, only=only or None, limit=limit, max_cost_usd=max_cost,
                       progress=progress)
            failures = check_thresholds(made, limits)
        except ValueError as exc:  # no question with that id, or a threshold whose name is not a figure
            raise stop(exc) from exc
        folder = out if out is not None else runs()
        saved = save(made, folder)
        typer.echo("")
        for figure, label in _LABELS.items():
            if figure in made.summary:
                typer.echo(f"{label}: {_number(made.summary[figure])}")
        typer.echo(f"\nSaved as {saved}")
        left = int(made.summary.get("not_run", 0))
        if left:
            failures = [f"The run stopped at its limit of ${max_cost:,.2f}: {left} "
                        f"question{'' if left == 1 else 's'} not asked.", *failures]
        if failures:
            typer.echo(f"The run did not pass (configuration {made.config_id}):")
            for sentence in failures:
                typer.echo(f"- {sentence}")
            raise typer.Exit(1)
        try:
            noted = mark_passed(made, limits, folder)
        except ValueError as exc:  # part of the set only, or no thresholds to hold it to: nothing failed
            typer.echo(f"Not noted as a pass: {exc}.")
            return
        typer.echo(f"Passed: every threshold met by configuration {made.config_id}. Noted in {noted}")

    first_argument = typer.Argument(..., exists=True, dir_okay=False, help="the earlier run, or the one in use")
    second_argument = typer.Argument(..., exists=True, dir_okay=False, help="the run being tried")

    @commands.command("compare", help="Two saved runs side by side: better and worse are the second against "
                                      "the first.")
    def compare_(a: Path = first_argument, b: Path = second_argument) -> None:
        try:
            page = compare(load(a), load(b)).to_markdown()
        except ValueError as exc:  # not a run saved by this harness
            raise stop(exc) from exc
        typer.echo(page.rstrip("\n"))

    if verifier is not None and loaded_words is not None:
        checks = (verifier, loaded_words)
        folder_argument = typer.Argument(..., exists=True, file_okay=False, help="a folder of recorded briefings")

        @commands.command("replay", help="Run the checks again over recorded briefings and say what they now say "
                                         "differently. Free: no model is called.")
        def replay_(folder: Path = folder_argument) -> None:
            recordings = sorted(folder.glob("*.jsonl"))
            if not recordings:
                raise stop(f"There are no recorded briefings (*.jsonl) in {folder}.")
            try:
                differences = replay([load_fixture(path) for path in recordings], checks[0](), checks[1](),
                                     curled=curled)
            except ValueError as exc:  # a recording with no report beside it, or of a stream that never finished
                raise stop(exc) from exc
            for difference in differences:
                typer.echo(str(difference))
            weaker = sum(1 for d in differences if d.kind == "weaker")
            briefings = f"{len(recordings)} recorded briefing{'' if len(recordings) == 1 else 's'}"
            if not differences:
                typer.echo(f"The checks say of {briefings} exactly what they said when each was recorded.")
            else:
                typer.echo(f"{len(differences)} difference{'' if len(differences) == 1 else 's'} in {briefings}: "
                           f"{weaker} weaker.")
            if weaker:
                typer.echo("The checks on briefings have weakened: something that was flagged is no longer "
                           "flagged.", err=True)
                raise typer.Exit(1)

    return app
