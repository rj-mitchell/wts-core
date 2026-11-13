# Adding a new site to the family

13 November 2026. The checklist for a new Where They Stand site built on `wts-core`, in order. Each step gives
the command to run or the file to change. The last section records what happened when the checklist was followed
from scratch.

**The way to start is to copy the example site,** [`examples/minimal-site/`](../examples/minimal-site/). There is
no `wts-core new-site` command, and none is planned. A scaffolding command would be a second copy of the example,
written as templates, to keep in step with the first. The example is one thing: CI runs it on every change, so it
cannot fall behind the package.

The steps below call the new site Where Rivers Stand, with the package `rivers` and the prefix `RIVERS`. They are
written for the maintainer. Decisions that are the owner's are marked.

## 1. Choose the names

Four names are fixed here and used everywhere after.

| Name | Example | Rule |
|---|---|---|
| The site's name | Where Rivers Stand | "Where X Stand". **The owner's decision** |
| The Python package and command | `rivers` | lower case, one word |
| The settings prefix | `RIVERS` | upper case, one word, unlike every other site's on the shared server. It names every environment variable: `RIVERS_DATA_DIR`, `RIVERS_CONFIG`, `RIVERS_ANTHROPIC_API_KEY`, `RIVERS_CHECK_TOKEN`, `RIVERS_B2_BUCKET` |
| The family id | `rivers` | the `id` in the charity's `family/projects.json` (step 7) |

The prefixes in use are `HANSARD` (Where MPs Stand), `WCS` (Where Countries Stand), `COUNCILS` and `LANDLORDS`.
The example's is `PARKS`.

## 2. Copy the example and rename it

Take the example from the release of `wts-core` the site will pin, so the copy and the package agree.

```bash
git clone --depth 1 --branch v0.1.0 https://github.com/rj-mitchell/wts-core
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
    "wts-core[cli,ai] @ https://github.com/rj-mitchell/wts-core/releases/download/v0.1.0/wts_core-0.1.0-py3-none-any.whl",
    "fastapi>=0.115",
    "pydantic>=2.8",
    "uvicorn>=0.30",
]

[tool.hatch.metadata]
allow-direct-references = true
```

To try a commit that is not yet released, on a developer's machine only, build the wheel from a checkout of the
package (`uv build --wheel`) and give its `file://` address in place of the release's.

Choose the extras the site uses:

| Extra | Brings | For |
|---|---|---|
| none | nothing but Python | settings, limits, the checks, the briefing desk, reports and statements, backup, the record |
| `cli` | Typer | the owner's shared commands |
| `offsite` | httpx | off-site copies of backups |
| `duckdb` | DuckDB | the thread-safe DuckDB connection |
| `ai` | the model's library, fastembed, LanceDB, numpy, pyarrow | the model, embedder and index adapters |

A site with no briefings (like Where Landlords Stand) takes `wts-core[cli,offsite]` and never installs an AI
library.

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

1. **`site.py`:** the `Site` (name, hosts, versions), the `Settings` subclass's accessors, `Messages`,
   `ReplyMessages`, `ReplyRules`, the loaded-words list, the `Verifier`'s three arguments, the `BackupSpec`
   (EXTENDING 1, 2, 3, 5). Every message is rewritten in the site's voice. **The owner approves the wording.**
2. **`config/settings.toml`:** every limit and price (EXTENDING 1.3, 4.2). **The spending caps are the owner's
   decision.**
3. **`pipeline.py`:** the site's record, its search, its instructions to the model (EXTENDING 3.2, 4.6, 4.7). This
   is most of the work, and none of it is the package's.
4. **`app.py`:** the request body, the cache key, `group_of`, the hooks the site needs, its pages (EXTENDING 4).
5. **Where a statement may sit:** the site's `Items` (EXTENDING 5).
6. **The model:** set `[answer] provider = "anthropic"`, the model names and their prices, and give the server
   `RIVERS_ANTHROPIC_API_KEY` (EXTENDING 7). Until then the scripted model keeps every test running.
7. **The two checks every site's tests call** stay in the tests: `assert_statements_stay_out` and
   `assert_no_reader_data` (EXTENDING 11).

## 5. The repository

- The layout is the copy's: `config/`, `data_static/`, `eval/`, `scripts/`, `src/<package>/`, `tests/`. Add
  `deploy/` (step 8), `docs/`, a `Dockerfile` and, if the site has a web front end, `web/`.
- `LICENSE`: AGPL-3.0, as every site.
- `README.md`: start from the template in the charity's `family/README.md`, "A project's README", with the
  endorsement, the charity line and the independence line from `family/GLOSSARY.md`.
- `.gitignore`: the copy's ignores `data/`. Do not ignore `eval/runs/`: the note of each passing evaluation run
  (`passed.jsonl`) must reach the server.
- Dependency updates: `.github/dependabot.yml` in the family's shape (the charity's `family/TOOLCHAIN.md`,
  "Dependency updates").

## 6. The family kit

The kit is what every site carries in the same form: the endorsement in the masthead, the family shelf in the
footer, the favicon and link card, `theme-color` and the heading type. The instructions are the charity's
`family/README.md`, "Using the kit". In short, from a checkout of the charity's repository, after step 7:

1. **Copy it in,** into the folder the site serves at `/family/`:

   ```bash
   node family/kit/sync.mjs --site rivers --out <the site's public folder>/family
   ```

   Commit the files it writes. Do not edit the copies.
2. **Check it in CI.** The same command with `--check` writes nothing and exits 1 if the copy differs. While the
   kit is in the charity's private repository a site's CI cannot run it, so the shared workflow `kit.yml` checks
   the `VERSION` stamp the sync wrote (step 9).
3. **Put the parts on every page:** the contents of `head.html` in `<head>`; the contents of `endorsement.html`
   in the masthead, beside or under the site's name; the contents of `shelf.html` inside the site's `<footer>`;
   and `class="wts-headings"` on `<body>` to set the headings in Source Serif 4. Give the root element
   `color-scheme: light dark`. Serve `family/favicon.ico` at `/favicon.ico` too.

## 7. Register the site in `family/projects.json`

In the charity's repository. The steps are `family/README.md`, "Adding a project":

1. Choose the next cloth on the site's shelf, away from the UK parties' colours, and add it to the charity's
   brand spec. **The owner's decision.**
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

The old step 7 there ("if it copies the Python engine, add its copies to `tools/shared-modules.json`") does not
apply: a site on `wts-core` copies nothing.

## 8. The shared server

The steps are the charity's `family/OPERATIONS.md`, "Adding a site", and Where MPs Stand's `docs/HOSTING.md`. In
short:

1. Cloudflare for the domain: a proxied `@` record, a `www` redirect, Full (strict), an origin certificate.
2. `git clone` the site into `/opt/<repository>`, fill in `deploy/.env`, and run its `update.sh`, which installs
   its timers.
3. Add `domain=container` to `SITES`, then run `bash /opt/hansardgpt/deploy/cloudflare.sh site <domain>`.
4. Run `bash /opt/hansardgpt/deploy/check.sh`.

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
| nightly | `rivers nightly` | the site's own housekeeping of reports and statements: lapsed statements, old addresses, old counts |
| nightly | `rivers tidy` | applies the retention to the record of briefings and the weekly reports; forgets old visitor codes and old copies of the database |
| weekly | `rivers weekly-report` | saves the week's figures, and fails if a figure is over its threshold |
| after each update | `rivers stats --check` | fails if a figure is over its threshold |

The Docker build must reach `github.com` and GitHub's release-download host, to fetch the wheel. It needs no
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
    uses: rj-mitchell/wts-core/.github/workflows/python.yml@v0.1.0
    with:
      type-check: "uv run mypy"

  # the family kit: the copy is the version the site says it synced
  kit:
    uses: rj-mitchell/wts-core/.github/workflows/kit.yml@v0.1.0
    with:
      version: "1.4.0"
      site: rivers
      path: web/family

  # the image the server builds, and one command run in it
  docker:
    uses: rj-mitchell/wts-core/.github/workflows/docker.yml@v0.1.0
    with:
      tag: whereriversstand:ci
      run: rivers --help

  # the site's own: start it, then check its pages
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: rj-mitchell/wts-core/.github/actions/setup@v0.1.0
      - run: uv sync --frozen
      - run: uv run rivers serve --port 8000 &
      - run: curl --retry 20 --retry-connrefused --fail http://127.0.0.1:8000/api/health
      - uses: rj-mitchell/wts-core/.github/actions/a11y@v0.1.0
        with:
          url: "http://127.0.0.1:8000"
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

The nightly family check stays in the charity's repository. It reads `family/projects.json`, so step 7 is what
adds the site to it. It asks the site's `/api/health`, `/api/status`, `/api/check` and one real question.

## 10. The evaluation set

1. Write the site's test questions in `eval/questions.toml`: an `id`, a `question`, a `category` and an `expect`
   table for each, with `include` or `no_records` where they apply. Never a reader's question.
2. Set the thresholds in `[eval.thresholds]` in `config/settings.toml`. A threshold is `min_` or `max_` and the
   name of a figure.
3. Run the set, keeping each briefing as a fixture:

   ```bash
   uv run rivers eval run --record-fixtures eval/fixtures
   ```

   With a real model this costs money. The run stops at the limit in `site.py` (`EVAL_MAX_COST_USD`) unless
   `--max-cost` says otherwise.
4. Commit `eval/runs/` (the run, and `passed.jsonl` if it passed) and `eval/fixtures/`.
5. Replay the fixtures in CI, so a change to the checks is measured before it ships. It is free:

   ```bash
   uv run rivers eval replay eval/fixtures
   ```

## 11. Privacy and accessibility statements

**The owner approves both pages.** The privacy notice must say what the code does. For a site on the package,
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

- the nightly timer runs `tidy` and the site's own nightly command (step 8), which apply the 13 months, the 90
  days and the three months;
- off-site copies are kept at the package's 60 a site, one a night. A site that keeps more, or backs up more
  often, changes the sentence on backups to match.

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

## Tried on 13 November 2026

The checklist was followed from scratch into a temporary folder, as far as a machine with no server and no
charity repository to change can go: steps 1 to 3, and the commands of steps 8 and 10. The example was copied and
renamed to a second invented site, Where Rivers Stand (`rivers`, `RIVERS`). It was installed from a wheel, not
from the source, and then:

- `uv run ruff check .`, `uv run mypy` and `uv run pytest` passed: 61 tests, including the one that starts the
  real server;
- `rivers serve` ran, and `/api/ask` over HTTP sent 1 `plan`, 1 `sources`, 5 `citation`, 22 `text` and 1 `final`
  event; `/` showed "Where Rivers Stand"; `/api/check` answered 404, as it should with no token set;
- `rivers backup` wrote `rivers-state-2026-11-13.sqlite.gz`; `rivers waiting`, `rivers stats --since 24h`,
  `rivers eval run --record-fixtures` (passed, and noted) and `rivers eval replay` all ran.

What was wrong or unclear the first time, and what was changed:

| What happened | What was changed |
|---|---|
| **The build refused the package's address.** The build backend (hatchling) does not allow a dependency written as an address unless `[tool.hatch.metadata] allow-direct-references = true` is set. `uv sync` failed with that message. ADR 0006's example line has the same gap | The example's `pyproject.toml` now carries the two lines, and step 3 says to keep them |
| **The package folder was not renamed.** Step 2 used `git mv -k src/parks src/rivers \|\| mv …`. In a new repository nothing is tracked yet, so `git mv -k` did nothing and reported success, and the plain `mv` never ran | Step 2 uses `mv` |
| The renaming command searched `.git` as well | `--exclude-dir=.git` was added, and a last line that shows whether anything of the old name is left |
| `rivers waiting` printed "The oldest has waited None working days" on a site with nothing waiting | The example's wording for `waiting` is now a function that leaves the sentence out |
| It was not said that the copy still holds the example's record after the renaming, so the question to try is still about parks | Step 2 and step 3 say so |
| The site's data went into `data/` in the repository when the server was tried | Step 3 names `RIVERS_DATA_DIR` |

What the trial could not follow as written:

- **`v0.1.0` is not released yet.** Step 2 was done from the branch the example was built on, and step 3 with a
  wheel built from that branch (`uv build --wheel`), given by its `file://` address. The release's address, and
  `uv sync --frozen` in the sites' Docker image with no `git`, are still to be tried once the tag exists
  (ADR 0006, "To verify in phase 3").
- **Steps 5 to 9 and 11 were not carried out:** they change the charity's repository, the shared server and
  GitHub. The workflow file in step 9 was checked only for being well-formed, and the actions and inputs it names
  were read against the files in `.github/`. Steps 6 to 8 repeat the charity's own pages; if those change, they
  win.
