# Upgrading

How the maintainer moves a site to a new version of wts-core, how a fix reaches every site, and how a site can be
put back on the code it ran before the package. How a release is made is in
[`CONTRIBUTING.md`](../CONTRIBUTING.md#releasing).

The version rules are in [ADR 0007](adr/0007-versioning.md): while the version is 0.x a minor version (0.3 to
0.4) may change the public interface, and a patch version (0.3.0 to 0.3.1) renames and removes nothing a site
calls. A patch may still change what a site is given or keeps when the old behaviour was a fault. Every change a
site must act on is listed in [`CHANGELOG.md`](../CHANGELOG.md) with what to do.

## Moving a site to a new version

One pull request in the site, holding nothing but the upgrade:

1. Read the changelog for every version between the one the site pins and the new one, and note what each
   change asks of the site.
2. Raise the version in the site's `pyproject.toml`. The dependency is the address of the release's wheel, which
   holds the version twice, in the tag and in the file name
   (`…/releases/download/v0.3.1/wts_core-0.3.1-py3-none-any.whl`). Leave `[tool.hatch.metadata]
   allow-direct-references = true` in place: without it the build refuses a dependency given as an address.
3. Run `uv lock`, then `uv sync`. The lock file records the new wheel's hash, so a file changed after its release
   fails the build.
4. Raise the tag of the shared workflows and actions to the same version, wherever the site's `.github/workflows/`
   call them (`rj-mitchell/wts-core/.github/workflows/python.yml@v0.3.1`, and the same for `kit.yml`,
   `docker.yml`, `web.yml`, `actions/setup` and `actions/a11y`). The site then has one version number.
   Dependabot is told to leave these alone ([`NEW-SITE.md`](NEW-SITE.md#9-ci)), so they are raised only here.
5. Make the changes the changelog asks for, then run the site's checks: `uv run ruff check .`, `uv run mypy`,
   `uv run pytest`, and the free replay of its recorded briefings (`<site> eval replay eval/fixtures`). If the
   new version changes the checks on briefings or anything a briefing is written with, make an evaluation run
   before and after the change and commit both.
6. When CI is green, merge, and deploy as below.

Take a new version to one site at a time, in this order: Where Landlords Stand, Where Councils Stand, Where
Countries Stand, then Where MPs Stand, the largest. A fault then shows on a smaller site before it reaches the
largest.

## Deploying a new version

The owner deploys by running the site's `deploy/update.sh` on the server. The image fetches the wheel from
GitHub's release-download host, with no `git` and no token. The script does three things, in this order:

1. Build the new image. If the build fails, nothing has changed.
2. Bring the site up on the new image and wait for it to answer. The site's start opens the state database on
   the new code, which runs the package's migrations and any one-off import the site declares.
3. Only then install or refresh the timer units. A unit runs a command of the image, so units installed before a
   build that then fails would run commands the old image does not have.

Migrations and imports run on whichever command first opens the state database on the new code, which need not
be the site's start. So no command of the new image may run while the old site is still serving: do not deploy
in the hours the site's timers run, and run nothing of the new image by hand before the restart. An import made
in that gap is made while the old site is still writing, and what the old site writes afterwards is never brought
across.

Migrations only add tables and columns. To go back to an earlier version of the package, pin it again: it finds
its tables as it left them and ignores anything the newer version added.

## Going back to the old code

The four sites moved onto the package in November 2026. Each keeps the tables it had before the package (its "old
tables") until 1 February 2027, and until then can be put back on its old code, which is kept in a private
archived repository, `rj-mitchell/<repository>_old`. Each site's `docs/OPERATIONS.md` has its own steps; these
are the rules they follow.

The rule: run the site's undo script first (`deploy/undo-wts-core.sql`, which writes the old tables again from the
package's tables and forgets that the import ran), then check out the old code. Coming forward again, the import
runs afresh over everything.

The undo script clears the package's copies of what the import brings across, and the import's mark in
`wts_schema`, or everything would be there twice. That includes `wts_account_months` and the public's monthly
visitor counts (`DELETE FROM wts_visitor_days WHERE who != '*'`), which summarise spending rows the undo has taken
away. The package also guards this: when an import runs and `wts_spending` is empty, it empties both first.

If the old code is run without the undo script, what it writes goes to the old tables only, and the new code
would never see it. So each site's `Import` declares, with `written_at`, the column of each old table that holds
the time a row was written ([`EXTENDING.md`](EXTENDING.md#6-the-state-database-migrations-and-a-sites-one-off-import)).
Opening the database while an old table holds a row written after the second the import ran raises
`state.StateError`, naming the tables, and the site does not start. The mend is the site's
`deploy/redo-wts-core.sql`, which forgets the move so that the import runs again from the old tables, keeping what
the old code wrote; or, where the alarm is false, the undo script. The four sites' lines, checked against their old
schemas by a test of the package:

| Site | Its import | The line |
|---|---|---|
| Where Councils Stand | `councils-state` | `written_at={"usage": "at", "answer_cache": "at", "briefings": "at", "reports": "at", "statements": "at"}` |
| Where Countries Stand | `wcs-state` | `written_at={"usage": "at", "answer_cache": "created_at", "failures": "at", "briefings": "at", "reports": "at", "statements": "at"}` |
| Where Landlords Stand | `landlords-reports-and-statements` | `written_at={"reports": "at", "statements": "at", "statement_log": "at"}` |
| Where MPs Stand | `hansard-state` | `written_at={"usage": "at", "answer_cache": "created_at", "briefings": "created_at", "failures": "at", "reports": "at", "statements": "at"}` |

The check cannot see a row written in the very second the import ran, a row with no time, or a change the old
code made to a row that was already there (a report closed, a statement decided). If the server's clock was put
back between the old code's last write and the move, it stops a site that lost nothing: the undo script, then a
fresh start, loses nothing. Each site's operations page says so.

## A fix to the sites

A fix goes one way:

1. Fix it in the package, with a test that fails without the fix ([`CONTRIBUTING.md`](../CONTRIBUTING.md)).
2. Release it as a new patch version. A release is never changed: a fix to a fix is another version.
3. Raise the pin in each site, as above.

A site never patches its installed copy, copies a module of the package or imports a private name to work round
a fault ([`EXTENDING.md`](EXTENDING.md#12-what-a-site-must-never-do)). If the package cannot do what a site needs,
the package is changed.

To try an unreleased fix on a developer's machine, build the wheel from a checkout of the package
(`uv build --wheel`) and give its `file://` address in place of the release's. Never deploy a site pinned that way.
