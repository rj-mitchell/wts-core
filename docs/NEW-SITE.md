# Adding a new site to the family

The checklist, in order, for the maintainer building a new Where They Stand site on `wts-core`. Each step gives
the command to run or the file to change. Decisions that are the owner's are marked.

A new site starts as a copy of the example site, [`examples/minimal-site/`](../examples/minimal-site/), which CI
runs on every change, so it cannot fall behind the package. There is no scaffolding command.

The steps below call the new site Where Rivers Stand, with the package `rivers` and the prefix `RIVERS`.

## 1. Choose the names

Four names are fixed here and used everywhere after.

| Name | Example | Rule |
|---|---|---|
| The site's name | Where Rivers Stand | "Where X Stand". The owner's decision |
| The Python package and command | `rivers` | lower case, one word |
| The settings prefix | `RIVERS` | upper case, one word, unlike every other site's on the shared server. It names every environment variable: `RIVERS_DATA_DIR`, `RIVERS_CONFIG`, `RIVERS_ANTHROPIC_API_KEY`, `RIVERS_CHECK_TOKEN`, `RIVERS_B2_BUCKET` |
| The family id | `rivers` | the `id` in the charity's `family/projects.json` (step 7) |

The prefixes in use are `HANSARD` (Where MPs Stand), `WCS` (Where Countries Stand), `COUNCILS` and `LANDLORDS`.
The example's is `PARKS`.

## 2. Copy the example and rename it

Take the example from the release of `wts-core` the site will pin, so the copy and the package agree.

```bash
git clone --depth 1 --branch v0.3.2 https://github.com/rj-mitchell/wts-core
mkdir whereriversstand
git -C wts-core archive HEAD examples/minimal-site | tar -x --strip-components=2 -C whereriversstand
cd whereriversstand
git init
rm uv.lock
mv src/parks src/rivers
grep -rl --exclude-dir=.git -e parks -e Parks -e PARKS . | xargs sed -i \
    -e 's/Where Parks Stand/Where Rivers Stand/g' -e 's/parks/rivers/g' -e 's/Parks/Rivers/g' -e 's/PARKS/RIVERS/g'
grep -rn --exclude-dir=.git -i parks . || echo "nothing is left of the example's name"
```

`git archive` copies only what is committed: no virtual environment, no data folder. The lock file is deleted
because the next step changes where the package comes from. The renaming is blind on purpose: it changes the
example's addresses, test questions and recorded briefings alike, so the copy still passes its own tests. The
record is still the example's park minutes until step 4 replaces it.

What the copy holds, and what becomes of each part:

| Path | What it is | In a real site |
|---|---|---|
| `pyproject.toml` | dependencies, the command, lint and type settings | kept; step 3 changes one dependency |
| `config/settings.toml` | every limit, price and model, each with a comment | kept; every value reviewed |
| `src/<package>/site.py` | the site's name, prefix, wording, word list, limits | kept; every word rewritten for the site |
| `src/<package>/pipeline.py` | reading a question, finding sources, the instructions | replaced: this follows the site's own record |
| `src/<package>/app.py` | the routes around the package's parts | kept; pages replaced |
| `src/<package>/cli.py` | the owner's commands | kept; the site's own commands added |
| `src/<package>/evaluation.py`, `eval/questions.toml` | the test questions | kept; the questions replaced (step 10) |
| `data_static/` | the example's record and recorded briefings | replaced by the site's own |
| `scripts/make_recordings.py` | writes the recorded briefings | kept while the site has no key; then real recordings |
| `tests/` | the ask flow, the right of reply, backup, the server | kept and extended |

## 3. Pin the package

In `pyproject.toml`, replace the dependency on `wts-core` with the address of the release's wheel, and delete the
`[tool.uv.sources]` table ([ADR 0006](adr/0006-distribution.md)). Keep the two lines under `[tool.hatch.metadata]`:
without `allow-direct-references = true` the build refuses a dependency written as an address.

```toml
dependencies = [
    "wts-core[cli,ai] @ https://github.com/rj-mitchell/wts-core/releases/download/v0.3.2/wts_core-0.3.2-py3-none-any.whl",
    "fastapi>=0.115",
    "pydantic>=2.8",
    "uvicorn>=0.30",
]

[tool.hatch.metadata]
allow-direct-references = true
```

To try a commit that is not yet released, on a developer's machine only, build the wheel from a checkout of the
package (`uv build --wheel`) and give its `file://` address in place of the release's.

Choose the extras the site uses from the table in the [README](../README.md#design). A site with no briefings
(like Where Landlords Stand) takes `wts-core[cli,offsite]` and never installs an AI library.

Then lock, install and run everything once. All of it must pass before anything is changed.

```bash
uv lock
uv sync
uv run ruff check .
uv run mypy
uv run pytest
uv run rivers serve --port 8000
```

With the server running, in another terminal:

```bash
curl -N -X POST http://127.0.0.1:8000/api/ask -H 'Content-Type: application/json' \
     -d '{"question": "What have park committees decided about dogs?"}'
```

The answer is a stream of events: `plan`, `sources`, then `citation` and `text`, then `final`. Nothing needs a
key: the model is a recording. Set `RIVERS_DATA_DIR` to keep the site's data out of the repository's `data/`
folder while trying it.

## 4. Make it the site's own

Work through [`EXTENDING.md`](EXTENDING.md) in its order. Each section names the hook, shows the example's lines
and says what to change.

1. `site.py`: the `Site` (name, hosts, versions), the `Settings` subclass's accessors, `Messages`,
   `ReplyMessages`, `ReplyRules`, the loaded-words list, the `Verifier`'s three arguments, the `BackupSpec`
   (EXTENDING 1, 2, 3, 5). Every message is rewritten in the site's voice. The owner approves the wording.
2. `config/settings.toml`: every limit and price (EXTENDING 1.3, 4.2). The spending caps are the owner's
   decision.
3. `pipeline.py`: the site's record, its search, its instructions to the model (EXTENDING 3.2, 4.6, 4.7). This
   is most of the work, and none of it is the package's.
4. `app.py`: the request body, the cache key, `group_of`, the hooks the site needs, its pages (EXTENDING 4).
   The desk and its parts are built there in two calls (`desk_parts`, then `parts.desk`: EXTENDING 4.1), which
   also check every limit, price and message when the site starts.
5. Where a statement may sit: the site's `Items`; and what can be hidden, the `hideable` its `Replies` is
   given, so that an item is filed under one address however the owner types it (EXTENDING 5).
6. The model: set `[answer] provider = "anthropic"`, the model names and their prices, and give the server
   `RIVERS_ANTHROPIC_API_KEY` (EXTENDING 7). Until then the scripted model keeps every test running.
   A site that writes briefings asks for strict prices: it passes `require_prices_for=(its answer model, its
   question-reading model)` to `desk_parts`, as the copy does, and keeps a table under `[usage.models]` for every
   model its settings may name, the server's own `settings.local.toml` included. Without that a model with no
   table is costed at the base prices, so a dearer model named on the server undercounts spending and the caps
   bite late (EXTENDING 4.2).
7. The three checks every site's tests call stay in the tests: `assert_statements_stay_out`,
   `assert_no_reader_data` and `assert_briefings_tied_to_no_one` (EXTENDING 11).
8. A new site has no tables from before the package and skips this. An existing site moving onto the package
   declares its one-off `Import`, with `written_at` for each old table, and its `OldTables`, with
   `drop_after_days` set to the days it keeps a backup (EXTENDING 6). Its operations page says how to put it back
   on its old code, by the rules in [`UPGRADING.md`](UPGRADING.md#going-back-to-the-old-code).

## 5. The repository

- The layout is the copy's: `config/`, `data_static/`, `eval/`, `scripts/`, `src/<package>/`, `tests/`. Add
  `deploy/` (step 8), `docs/`, a `Dockerfile` and, if the site has a web front end, `web/`.
- `LICENSE`: AGPL-3.0, as every site.
- `README.md`: start from the template in the charity's `family/README.md`, "A project's README", with the
  endorsement, the charity line and the independence line from `family/GLOSSARY.md`.
- `.gitignore`: the copy's ignores `data/`. Do not ignore `eval/runs/`: the note of each passing evaluation run
  (`passed.jsonl`) must reach the server.
- Dependency updates: `.github/dependabot.yml`, copied from an existing site and set up as in step 9.

## 6. The family kit

The kit (version 2) is what every site carries in the same form: the endorsement in the header, the family shelf
in the footer, the favicon and link card, `theme-color` in the site's cloth, and the two typefaces, Source Serif 4
for headings and Source Sans 3 for text. The shared look is white pages with the site's cloth as a band across
the top of every page (the charity's `family/GLOSSARY.md`, "Style"). The instructions are the charity's
`family/README.md`, "Using the kit". From a checkout of the charity's repository, after step 7:

1. Copy it in, into the folder the site serves at `/family/`:

   ```bash
   node family/kit/sync.mjs --site rivers --out <the site's public folder>/family
   ```

   Commit the files it writes. Do not edit the copies.
2. Check it in CI. The same command with `--check` writes nothing and exits 1 if the copy differs. While the
   kit is in the charity's private repository a site's CI cannot run it, so the shared workflow `kit.yml` checks
   the `VERSION` stamp the sync wrote (step 9).
3. Put the parts on every page: the contents of `head.html` in `<head>`; the contents of `endorsement.html`
   in the header, beside or under the site's name; the contents of `shelf.html` inside the site's `<footer>`;
   and `class="wts-headings"` on `<body>` to set the headings in Source Serif 4. Give the root element
   `color-scheme: light dark`. Serve `family/favicon.ico` at `/favicon.ico` too.

## 7. Register the site in `family/projects.json`

In the charity's repository. The steps are `family/README.md`, "Adding a project":

1. Choose the next cloth on the site's shelf, away from the UK parties' colours, and add it to the charity's
   brand spec. The owner's decision.
2. Add a record to `family/projects.json`, and the site's mark to `brand/assets/marks/<id>/`. Then run
   `kit/build.mjs` to draw its icons and link card. The record has this shape:

   ```json
   {
     "id": "rivers",
     "kind": "site",
     "name": "Where Rivers Stand",
     "short": "One line: what it does, from which record.",
     "url": "https://whereriversstand.com/",
     "checkPage": "/about",
     "domain": "whereriversstand.com",
     "shelf": "uk",
     "cloth": { "name": "The cloth's name", "hex": "#000000", "dark": "#000000", "textDark": "#000000" },
     "status": "in-development",
     "repository": "https://github.com/rj-mitchell/whereriversstand",
     "runsOn": "shared server",
     "contact": "admin@whereriversstand.com",
     "independence": "Where Rivers Stand is independent. It is not affiliated with or endorsed by A or B."
   }
   ```

   `shelf` is `uk`, `international` or `games`. `status` is `live`, `beta`, `alpha` or `in-development`.
   `checkPage` is the inner page the nightly family check visits besides the home page.
3. Sync the kit into the new site and into every other site, so the new spine appears on every footer shelf.
4. Run `node site/tools/hub.mjs` in the charity's repository, which rebuilds the hub's project lists.

A site on `wts-core` copies no engine code, so it is not added to the drift check's `tools/shared-modules.json`.

## 8. The shared server

The steps are the charity's `family/OPERATIONS.md`, "Adding a site", and Where MPs Stand's `docs/HOSTING.md`. In
short:

1. Cloudflare for the domain: a proxied `@` record, a `www` redirect, Full (strict), an origin certificate.
2. `git clone` the site into `/opt/<repository>`, fill in `deploy/.env`, and run its `update.sh`, which installs
   its timers.
3. Add `domain=container` to `SITES`, then run `bash /opt/hansardgpt/deploy/cloudflare.sh site <domain>`.
4. Run `bash /opt/hansardgpt/deploy/check.sh`.

The site's `update.sh` builds the new image, brings the site up on it, and only then installs or refreshes the
timer units (copies the `.service` and `.timer` files, reloads systemd, enables the timers). The order, and why
nothing of the new image may run before the restart, are in
[`UPGRADING.md`](UPGRADING.md#deploying-a-new-version). In CI, the image's own `--help` is the check that it runs.

A unit that runs the nightly tidy as `ExecStopPost=` needs `TimeoutStopSec=`. A site that runs `tidy` after
its backup, in the backup's unit, runs it in the unit's stop phase. systemd's limit for that phase is its stop
timeout (90 seconds unless set), not the unit's start timeout, so a `TimeoutStartSec=30min` does not cover it and
a long tidy is killed part-way. Set `TimeoutStopSec=` on the unit to what the tidy may take.

Copy a sibling site's `deploy/` folder. Its compose file needs its own `name:`, a `mem_limit`, the `sites` network
with the container's alias, and capped logs. Its update unit needs the lock and `OnFailure=alert@%n.service`. Its
update time needs a free slot. Its backup goes to the B2 bucket under its own names: the `prefix` of the site's
`BackupSpec`. Then add the site to `OPERATIONS.md` and to `family/README.md`.

What `deploy/.env` holds for a site on the package:

| Variable | For |
|---|---|
| `RIVERS_DATA_DIR` | the data folder in the container |
| `RIVERS_ANTHROPIC_API_KEY` | the model |
| `RIVERS_CHECK_TOKEN` | the family's check token: the same value as on every site ([ADR 0010](adr/0010-ci-and-nightly-check.md)) |
| `RIVERS_B2_BUCKET`, `RIVERS_B2_KEY_ID`, `RIVERS_B2_APPLICATION_KEY` | off-site copies of backups |
| `RIVERS_BEHIND_PROXY` | `true`: the site is behind the server's front door |

The timers run the site's commands. With the example's names:

| When | Command | What it does |
|---|---|---|
| nightly | `rivers backup` | backs up the state database and sends a copy off site |
| nightly, after it | `rivers backup-check --in <backups folder>` | fails, so the owner is emailed, if backups have stopped |
| nightly | `rivers tidy` | the one housekeeping command: applies the retention to the record of briefings and the weekly reports; forgets old visitor codes and old copies of the database; keeps the site's old tables, if it has any, within its promises and drops them on the day it stated; does the right of reply's (lapsed statements, old addresses, old counts); and last writes the database's file out afresh, so that nothing deleted stays in it or in a backup. It fails if the old tables could not be dropped on their day, or if the file could not be written afresh two nights running |
| weekly | `rivers weekly-report` | saves the week's figures, and fails if a figure is over its threshold |
| after each update | `rivers stats --check` | fails if a figure is over its threshold, or if an experiment the site declares cannot run |
| when the owner sits down to improve the site | `rivers propose-questions --since 30d` | writes a file of test questions proposed from real use, for a person to read and approve; adds nothing to the test set ([`IMPROVING.md`](IMPROVING.md)) |

The Docker build must reach `github.com` and GitHub's release-download host, `objects.githubusercontent.com`, to
fetch the wheel. It needs no
`git` in the image and no token.

## 9. CI

A site calls the shared workflows in this repository at the same tag as the package it pins, so it has one number
to raise ([ADR 0010](adr/0010-ci-and-nightly-check.md)). Its own `ci.yml` keeps only what is its own: how it
starts, and its smoke pages. In `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  # lint, strict types and tests, installed from the site's lock file
  python:
    uses: rj-mitchell/wts-core/.github/workflows/python.yml@v0.3.2
    with:
      type-check: "uv run mypy"

  # the family kit: the copy is the version the site says it synced
  kit:
    uses: rj-mitchell/wts-core/.github/workflows/kit.yml@v0.3.2
    with:
      version: "2.0.1"
      site: rivers
      path: web/family

  # the image the server builds, and one command run in it
  docker:
    uses: rj-mitchell/wts-core/.github/workflows/docker.yml@v0.3.2
    with:
      tag: whereriversstand:ci
      run: rivers --help

  # the site's own: start it, then check its pages
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: rj-mitchell/wts-core/.github/actions/setup@v0.3.2
      - run: uv sync --frozen
      # started with the environment's own program, not `uv run`, and its process number kept to stop it by
      - run: |
          RIVERS_DATA_DIR="$RUNNER_TEMP/data" nohup .venv/bin/rivers serve --port 8000 > "$RUNNER_TEMP/site.log" 2>&1 &
          echo $! > "$RUNNER_TEMP/site.pid"
      - run: curl --retry 20 --retry-connrefused --fail http://127.0.0.1:8000/api/health
      - uses: rj-mitchell/wts-core/.github/actions/a11y@v0.3.2
        with:
          url: "http://127.0.0.1:8000"
      - name: What the site logged
        if: failure()
        run: cat "$RUNNER_TEMP/site.log" || true
      - name: Stop the site
        if: always()
        run: kill "$(cat "$RUNNER_TEMP/site.pid")" 2>/dev/null || true
```

| Shared part | What it does |
|---|---|
| `workflows/python.yml` | `uv sync --frozen`, `ruff`, the type check, `pytest` |
| `workflows/web.yml` | `npm ci`, type check, tests, build, for a site with a web front end in a folder |
| `workflows/kit.yml` | checks the kit's `VERSION` stamp |
| `workflows/docker.yml` | builds the image with the layer cache and runs one command in it |
| `actions/setup` | the family's toolchain: Python, `uv`, Node |
| `actions/a11y` | runs the site's `scripts/a11y.mjs` with Playwright and axe against an address the job has started |

The accessibility step needs the site's own `scripts/a11y.mjs`: copy a sibling site's and list this site's pages
in it. The example has none.

A site started in the background. Start it with the environment's own program (`.venv/bin/rivers serve &`),
keep its process number, and stop it in a last step marked `if: always()`, as the `smoke` job above does. Do not
leave `uv run rivers serve &` running: it keeps a `uv` process alive, and a site that is never stopped is a job
that ends only when the runner kills it, with its log lost.

`data/` in `.gitignore`. A site ignores its data folder with a line `data/`, which ignores every folder of
that name, at any depth. A LanceDB table keeps its rows in a folder called `data`, so a small index committed as
a test fixture loses them silently: the tests pass locally and fail in CI with an empty table. Write the line as
`/data/` (the folder at the root only), or add an exception after it, as Where Councils Stand does:

```gitignore
data/
!tests/fixtures/**/data/
```

A test that reads a command's `--help`. On GitHub Actions, Typer draws help with colour codes, and the codes
split an option's name in two, so such a test passes on a developer's machine and fails in CI. The shared
`python.yml` sets `_TYPER_FORCE_DISABLE_TERMINAL=1` and `NO_COLOR=1` for the lint, type-check and test steps, so
CI is covered. The site's own `tests/conftest.py` should set the same two, before Typer is first imported, so that
the tests also pass for a developer who has `FORCE_COLOR` set. The example's does.

From `examples/minimal-site/tests/conftest.py`:

```python
# Typer draws its help with colour codes when it thinks a terminal is watching, which it does on GitHub Actions;
# the codes split an option's name in two. It reads these when first imported, so they are set before it is.
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"
os.environ["NO_COLOR"] = "1"
```

Dependabot must leave the shared workflows alone. They are called at the tag of the package the site pins,
and the two are raised together, by hand, in one pull request ([`UPGRADING.md`](UPGRADING.md)). Dependabot does
not raise a dependency written as a wheel's address, but it does raise an action's tag, so left to itself it
would move the workflows ahead of the wheel. In the site's `.github/dependabot.yml`, under the `github-actions`
updates:

```yaml
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    ignore:
      # raised by hand with the wheel's version in pyproject.toml, in one change
      - dependency-name: "rj-mitchell/wts-core*"
```

A test in the site that reads the tag from `ci.yml` and the version from `pyproject.toml`, and fails when they
differ, keeps the two the same (Where Landlords Stand has one).

The nightly family check stays in the charity's repository. It reads `family/projects.json`, so step 7 is what
adds the site to it. What it asks each site is in the charity's `family/OPERATIONS.md`, "The nightly check".

## 10. The evaluation set

1. Write the site's test questions in `eval/questions.toml`: an `id`, a `question`, a `category` and an `expect`
   table for each, with `include` or `no_records` where they apply. Never a reader's question.
2. Set the thresholds in `[eval.thresholds]` in `config/settings.toml`. A threshold is `min_` or `max_` and the
   name of a figure.
3. Run the set, keeping each briefing as a fixture:

   ```bash
   uv run rivers eval run --record-fixtures eval/fixtures
   ```

   With a real model this costs money. The run stops at the limit in `config/settings.toml`
   (`[eval] max_cost_usd`) unless `--max-cost` says otherwise.
4. Commit `eval/runs/` (the run, and `passed.jsonl` if it passed) and `eval/fixtures/`.

   In a container, a run's output folder must be on the data volume. The site's code is at `/app` in its
   image, which is read-only, and the container a command runs in is removed when it ends. A run started on the
   server with `docker compose run --rm app rivers eval run` therefore cannot write to `eval/runs/` under the
   code, and anything it wrote elsewhere inside the container is gone with it. Give `eval_commands` a `runs`
   folder that follows the data folder when the site is in its container (`runs=lambda: load().data_dir / "eval"
   / "runs"`, or the repository's `eval/runs/` when that is writable), or pass `--out` and `--record-fixtures` a
   path under the data folder each time; then copy the run out of the volume to commit it. The experiment guard
   reads `passed.jsonl` from the same folder, so it must find it there too.
5. Replay the fixtures in CI, so a change to the checks is measured before it ships. It is free:

   ```bash
   uv run rivers eval replay eval/fixtures
   ```

## 11. Privacy and accessibility statements

The owner approves both pages. The privacy notice must say what the code does. For a site on the package,
that includes these sentences.

For the record of each briefing ([ADR 0012](adr/0012-briefing-record-and-statistics.md)), under "Your questions
and the briefings written for them":

> For each briefing the site also notes how long each step took, what it cost and what the automatic checks found,
> so that slow or poorly checked briefings can be found and fixed. These notes hold nothing that identifies you;
> they are kept for 13 months, and the question of a briefing that could not be written is removed from them after
> 90 days.

For the address that confirms who sent a statement ([ADR 0008](adr/0008-reports-and-statements.md)): the address

> is kept while the statement is waiting or shown, and deleted three months after it is withdrawn, declined or
> removed.

For backups (ADR 0008):

> Backups of the site's database are kept for up to two months, so a deleted address can remain in a backup until
> then.

The notice must also say, as every site's does: that each briefing is saved with its question at its own address;
that a visitor is counted for the daily limit by a code made from their network and a secret that changes every
day, and that the address itself is never stored; that a report's contact details are deleted when the report is
closed; and who the data controller is, in the words of `family/GLOSSARY.md`.

Two conditions make the sentences true, and both are the site's to keep:

- the nightly timer runs `tidy` (step 8), which applies the 13 months, the 90 days and the three months;
- off-site copies are kept at 60 a site, one a night (`keep_offsite` in the site's `BackupSpec`). A site that
  keeps more, or backs up more often, changes the sentence on backups to match.

The accessibility statement says what was tested and how to report a problem. The check behind it is the site's
`scripts/a11y.mjs` (axe, WCAG 2.2 AA, light and dark, desktop and phone), run in CI by the shared `a11y` step and
nightly by the family check on the home page, "If you're named" and the corrections page.

## 12. Before the site is announced

- [ ] `uv run ruff check . && uv run mypy && uv run pytest` passes, and CI is green.
- [ ] An evaluation run has passed and is committed.
- [ ] The privacy notice, the accessibility statement, "If you're named" and the corrections page are published.
- [ ] The kit is on every page, and every other site's shelf shows the new spine.
- [ ] `/api/check` answers the family's token, and the nightly family check is green for the site.
- [ ] A backup has been made, sent off site and restored on a copy.
- [ ] The alert thresholds are set from the first weekly report.
