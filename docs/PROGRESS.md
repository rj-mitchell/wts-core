# Progress

Read this first, then `docs/NOTES/`. Keep it current: what is done, what is open, the next step.

Last updated: 14 November 2026, 13:15 UTC (session 1).

## Where things stand

| Phase | State | Evidence |
|---|---|---|
| 0. Prerequisites | Done | [`PHASE-0.md`](PHASE-0.md) |
| 1. Converge the copies | **Done: five pull requests, all green**, and the charity repository's (drift list, baseline, ENGINE.md) | below; the drift report before and after is in [`study/`](study/) |
| 1, the library upgrade | **Merged on the owner's word, 13 November 2026** (the site's own evaluation run still needs the server's data) | rj-mitchell/wherempsstand#43 |
| 1b. "Why use this rather than a chatbot?" | **Done: four pull requests** (the hub and three AI sites); screenshots in the charity repository's | below |
| 1c. One toolchain | **Done: six pull requests, all green on GitHub** | below |
| 2. Design | **Written; waits for the owner's review** | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`adr/`](adr/), [`MIGRATION.md`](MIGRATION.md), [`API-SKETCH.md`](API-SKETCH.md), [`study/`](study/) |
| 3. Build the package | **Done and released: `v0.1.0`** (rj-mitchell/wts-core#2 and #3 merged; the release has the wheel, sha256 `29d6f59d…2572`) | https://github.com/rj-mitchell/wts-core/releases/tag/v0.1.0 |
| 4. Adopt, one site at a time | **Where Landlords Stand: merged** (rj-mitchell/wherelandlordsstand#21). **Where Countries Stand: merged** (rj-mitchell/wherecountriesstand#37, 14 November: python, docker, kit and accessibility green; `/api/ask` byte for byte on 21 scripted cases and 7 through the real pipeline). **Where Councils Stand** (`/home/user/wt/councils-adopt`) and **Where MPs Stand** (`/home/user/wt/mps-adopt`) under way. Then Where Landlords Stand's move to 0.2.0. **The owner deploys each with its `update.sh`** | the adoption workers' brief: `docs/study/adoption-worker-brief.md` |
| 5 to 7 | Not started | |

## Pull requests

**All seventeen were merged on 13 November 2026, at the owner's request** (squash merges, as each
repository's history has them; a merge commit for this repository's design and for Where Lives Stand). Each
branch was brought up to date with `main` and its checks re-run before it was merged.

| Repository | Step | Pull request | State |
|---|---|---|---|
| wts-core | 0 and 2: the design | rj-mitchell/wts-core#1 | merged |
| wherempsstand | 1: ports | rj-mitchell/wherempsstand#44 | merged |
| wherecountriesstand | 1: ports | rj-mitchell/wherecountriesstand#31 | merged |
| wherecouncilsstand | 1: ports | rj-mitchell/wherecouncilsstand#49 | merged |
| wherelandlordsstand | 1: ports | rj-mitchell/wherelandlordsstand#17 | merged |
| wheretheystand-charity | 1: drift list, baseline, ENGINE.md | rj-mitchell/wheretheystand-charity#28 | merged |
| wherempsstand | 1: library versions | rj-mitchell/wherempsstand#43 | merged (538 tests passed with `main` merged in; real briefings worked on both sides of the upgrade on the sample data; the site's own evaluation set was not run, as it needs the server's data) |
| wheretheystand-charity | 1b: the hub, the glossary's wording, all screenshots | rj-mitchell/wheretheystand-charity#27 | merged; the hub published itself and shows the new text |
| wherempsstand | 1b | rj-mitchell/wherempsstand#45 | merged |
| wherecountriesstand | 1b | rj-mitchell/wherecountriesstand#32 | merged (the one-line conflict in `docs/DECISIONS.md` resolved by keeping both rows) |
| wherecouncilsstand | 1b | rj-mitchell/wherecouncilsstand#50 | merged |
| the six repositories | 1c | wherempsstand#42, wherecountriesstand#30, wherecouncilsstand#48, wherelandlordsstand#16, wherelivesstand#21, wheretheystand-charity#26 | merged |

**Nothing is deployed on the shared server until the owner runs each site's `update.sh`** (`/opt/hansardgpt`,
`/opt/wherecountriesstand`, `/opt/wherecouncilsstand`, `/opt/wherelandlordsstand`). The hub and Where Lives Stand
publish themselves on a merge.

The drift check, run strict against the merged `main` branches
([`study/drift-2026-11-13-main-after-merges.txt`](study/drift-2026-11-13-main-after-merges.txt)): one pair was below
the baseline, the DuckDB wrapper (0.77), until #43 was merged. Run again after it
([`study/drift-2026-11-13-main-after-all-merges.txt`](study/drift-2026-11-13-main-after-all-merges.txt)): the strict
check passes, with no pair further apart than the baseline.

## Phase 3: how it is being built

The package branch was `claude/wts-3-package`, merged as rj-mitchell/wts-core#2 on 13 November 2026.
The foundation is on it: `ports`, `events`, `settings`, `state`, `testing` (clock and chance), the wall tests, the
toolchain file and its test, the shared workflows and the package's own CI, `CONTRIBUTING.md`, `CHANGELOG.md`.
Proved locally: the wheel builds, installs alone with `git` off the PATH, and every base module imports with
nothing else installed.

Each module is built by one worker in its own worktree and branch, from the same brief
(`CONTRIBUTING.md`, the API sketch, MIGRATION, the study, and the sites' code at their phase 1 branches), with
parity tests that import each site's own functions and compare results. I merge the branches into the package branch.

| Module | Branch | Worktree | State |
|---|---|---|---|
| `checks` (verifier, loaded words, spelling, typography, balance) | `claude/wts-3-checks` | `/home/user/wt/core-checks` | **merged into the package branch** (264 tests; identical to each site's copy on generated briefings) |
| `usage` (limiter, visitor code, prices, spending, caps, in progress, cache, saved briefings, failures) | `claude/wts-3-usage` | `/home/user/wt/core-usage` | **merged** |
| `ops`, `adapters.b2`, `adapters.duckdb` | `claude/wts-3-ops` | `/home/user/wt/core-ops` | **merged into the package branch** (compared with all four sites' own backup, restore, off-site and alert code) |
| `replies` | `claude/wts-3-replies` | `/home/user/wt/core-replies` | **merged** (443 tests on its branch; compared with each site's own code; see [`AS-BUILT.md`](AS-BUILT.md)) |
| `adapters.anthropic`, `.hashing`, `.fastembed`, `.lancedb`; testing fakes and contracts | `claude/wts-3-adapters` | `/home/user/wt/core-adapters` | **merged** (three real recordings made with the charity's key, about one US cent; see [`AS-BUILT.md`](AS-BUILT.md)) |
| `briefing` (the desk, stages, the streamer) | `claude/wts-3-briefing` | `/home/user/wt/core-briefing` | **merged** (each site's real `/api/ask` and the desk give the same bytes and the same rows on every case) |
| `observe` (the briefing log, statistics, alerts) | `claude/wts-3-observe` | `/home/user/wt/core-observe` | **merged** |
| `eval` (replay and live runs) | `claude/wts-3-eval` | `/home/user/wt/core-eval` | **merged** (replays the shipped recordings against golden reports; reads each site's real question file) |
| `cli` (the shared commands) and the `/api/check` route; the remaining testing helpers | `claude/wts-3-cli` | `/home/user/wt/core-cli` | **merged** (each site's own commands and the package's print the same lines and exit alike) |
| `examples/minimal-site`, `docs/EXTENDING.md`, `docs/NEW-SITE.md`, `README.md` | `claude/wts-3-example` | `/home/user/wt/core-example` | **merged** (61 tests of its own, its real server included; the new-site checklist was followed from scratch twice) |
| An independent review of the whole package against the brief's Musts | read-only | | **done and acted on**: [`NOTES/independent-review-of-the-package.md`](NOTES/independent-review-of-the-package.md) |
| The public-interface snapshot test, then tag `v0.1.0` | on the package branch | | the snapshot is in (`docs/api-snapshot.txt`); the tag follows the merge |

The workers' brief is kept at `docs/study/package-worker-brief.md`.

## Version 0.2.0: the rough edges the example site found

Building the example made its author the package's first user, and it found ten rough edges. Version 0.2.0
removes nine of them before Where Councils Stand adopts the package, while no site uses the briefing desk and its
interface may still change (ADR 0007). The bytes a reader receives, and the rows written, are unchanged: the
comparisons with each site's own flow (`tests/test_briefing_parity.py`, `tests/test_usage_parity.py`) pass as
they stood, with only the way the desk's side is built rewritten. `CHANGELOG.md` has each change and what a site
must do; `docs/AS-BUILT.md` has what adoption must know.

Closed:

| Rough edge | What was done |
|---|---|
| 1. A builder for the desk, with one start-up check | `briefing.desk_parts` builds every part from a site's settings on one clock and one source of chance, and `DeskParts.desk` makes the desk. `briefing.desk_settings` is the check: everything missing or wrong in one error that names the file and each key. The three desk sides in `tests/briefing_sites.py`, the example and the README's quick start are built on it |
| 2. `config` was a mapping with string keys | `ports.BriefingConfig`, made by `observe.briefing_config`, which works out the id and keeps the parts in `wts_configs` in the same call |
| 3. The model client's type had no `close()`; "is there a key?" needed a provider's module | `ports.ModelStream`; `adapters.has_model` |
| 4. Housekeeping the nightly update must call | one command: `tidy` takes the right of reply's housekeeping as a step (`cli.replies_tidy`); `tidy-replies` for a site with no record of briefings |
| 6. Two arguments were plain values; the off-site `keep` was fixed at 60 | `max_cost_usd` and `similarity` may be functions read when the command runs; `BackupSpec.keep_offsite` |
| 7. A restore accepted a sister site's backup | `StateDB(..., site=…)` marks the file, `BackupSpec(site=…)` refuses another's mark; a backup with no mark is accepted as before |
| 8. `events.to_reader` returned a typed dictionary | one plain type, `events.Event`, wherever events are passed |
| 9. `FixedRandom.token()` gave nine characters | as many as a real token for the bytes asked: eleven for the desk's eight |
| 10. `replies.long_date` lived where a pipeline must not import it | `wts_core.dates.long_date`; still exported from `replies` |

Also done on the way: the weekly page says "1 day" and the tidy command "1 record"; `Hooks.usages` says in its
docstring that only Where MPs Stand needs it and why; `docs/UPGRADING.md` is written.

**What the first site to adopt found** (Where Landlords Stand, on 0.1.0, while this was being built) is in 0.2.0
too:

| Found | What was done |
|---|---|
| Publishing no longer refused a landlord whose page had gone | `Replies.publish` asks the site whether the item is still shown, and refuses a hidden one |
| The site was not told after `hide`, `unhide` or `reports close`; it had to write lines for commands it does not have; keeping its older, option-shaped commands took three calls and two groups of its own | `changed` is called after all three; `RepliesWording` needs only the lines the site's commands print; `replies_commands(groups=…)` takes the site's own groups |
| `ops_commands` took its clock when built | every command group takes a clock or a function that gives one when a command runs |
| No section was made for an unset `EnvSetting` | `load_settings` makes it, empty |
| An import could not allow for a column missing from an old backup | an `Import`'s statement may be a function of the connection; `state.columns` |
| `assert_no_reader_data` needed a question | `question` is optional |
| Its CI failed on a test that read `--help` | the shared `python.yml` turns Typer's colour off |
| Four mistakes in the guides | corrected: AS-BUILT (a site's `required_tables`), MIGRATION 1.1 (`load_toml` is kept), NEW-SITE (Dependabot, the colour variables), ADR 0006 (the host, and what was verified) |

That site's own tests were then run against 0.2.0 in a copy (170 passed, 10 skipped) with the three changes the
changelog asks of it. Its pull request to move to 0.2.0 is the next shift's, once the release is made.

Left, and why:

- **5. About forty lines of wording for a new site's backup and right-of-reply commands, with no defaults.** Not
  done, on purpose: ADR 0004 says no wording has a default in the package, so that the package cannot change a
  site's words by accident, and the owner accepted that. Giving the owner's commands default lines would be a
  change to that decision, not a rough edge to sand. 0.2.0 adds one more such line (`RepliesWording.tidied`). If
  the owner wants defaults for words only the owner reads, it is a small change: say so and it is the next
  shift's.
- **The quick start did not get shorter.** The builder reads a site's settings so that its one error can name the
  file, and the quick start has no settings file, so it writes a `Settings` in code: 105 lines where 0.1.0 had 98.
  The example site's `build` and the three desk sides did get shorter.
- **The new-site checklist was followed again only as far as its steps 2 and 3** (`docs/NEW-SITE.md`, "Tried
  again for 0.2.0").
- **`months_before` is written twice,** in `observe` and in `replies` (the wall between them is why). It could
  join `long_date` in `wts_core.dates`; nothing depends on it, so it was left.
- **The evaluation commands still take the configuration as a mapping** (`eval_commands(config=…, config_id=…)`):
  a site passes `BriefingConfig.settings` and `observe.config_id`, as the example does. Taking the
  `BriefingConfig` itself would be tidier and can wait for the first site that runs the harness.

## For the package's next release: what the AI sites' adoptions found

From Where Countries Stand's adoption (rj-mitchell/wherecountriesstand#37, on 0.2.0). None blocks a site; each
was worked round in the site, cleanly.

1. **No way to see what would lapse before it does.** `Replies.waiting()` and the listings tidy before they
   answer, so the owner cannot be shown, after a deploy, what the first write will lapse. A read-only
   `would_lapse()`.
2. `SqliteAnswerCache` has no delete, so a hidden briefing's cached copy cannot be dropped (the site intercepts it
   in `on_cached`).
3. `testing.assert_statements_stay_out` is typed for the package's fake embedder and index; a site on a real
   LanceDB engine passes look-alikes. A small interface for the four things it reads.
4. `adapters.lancedb`: no public way to ask whether an index was opened to add vectors; the "unknown" embedder id
   is not exported.
5. `cli/stats.py`: `stats --json` wraps the figures in `{"stats": …}` (say so in the docs); `weekly-report` loads
   the real embedding model whenever it runs, so a site's test of the command must stand one in.
6. `cli/replies.py`: an old command name kept through `also` works silently; ADR 0008 says old names "say what
   replaces them". The `waiting` line prints "None" for the oldest's age when nothing waits.
7. `ops.BackupSpec.required_tables`: a site with no table only it has must name the old tables now and change
   the spec in the release that drops them. The site mark (0.2.0) is what tells sister sites apart from now on;
   say so in AS-BUILT.
9. **Shared CI:** a job that leaves `uv run <site> serve &` in the background fails at its end, when the `setup`
   action's uv cache tidying waits for that process (Where Countries Stand's accessibility job, after the check
   had passed). Say so in NEW-SITE's CI section, with the pattern that works (the environment's own program, a
   pid, a last step that stops it); consider `prune-cache: false` in the `setup` action. Also: a recorder of the
   old code's outputs must be exempt from import sorting (`# ruff: noqa: I001`), since the linter sorts imports of
   deleted modules differently in a fresh checkout.
8. Docs: MIGRATION 1.9 says Where Countries Stand "gains both" the trap and the daily limit, but passing a
   visitor code would be something new kept, so it passes none (the adoption brief's rule); MIGRATION should say
   so. AS-BUILT says the pre-import copy is "the whole file as it was": it is made after the package's empty
   tables exist.

## What could not be done, and why

- **No full evaluation run.** Each site's evaluation of briefings needs its own archive and index, which are on
  the server (`NOTES/what-the-build-session-cannot-do.md`). The API key works since 13 November, so real briefings
  on Where MPs Stand's sample data and real recordings for the package's fixtures were made; the before-and-after
  evaluation on a site's own question set still needs the server's data.
- **Nothing on the server was looked at.** Two questions for the owner come from that: the front door's handling of
  `X-Forwarded-For` (MIGRATION 1.3), and whether Where MPs Stand's `restore` works across file systems in its
  container (fixed in phase 1 either way). A third, about Where Councils Stand's `usage` table, was settled from the
  repository's history: the column was always there.

## Open, for the owner

1. Running each site's `update.sh` on the server.
2. The check token, when the nightly check is extended (ADR 0010); nothing is needed before then.

The owner has also said (13 November) to merge the package's own pull request when it is ready.

The API key works since 13 November (`NOTES/what-the-build-session-cannot-do.md`); spend so far is under 25p.

Decided by the owner on 13 November 2026: the design is accepted; the privacy notice changes are accepted; the four
right-of-reply questions were left to the maintainer and are decided in ADR 0008.

## Next step

1. Where Landlords Stand is merged. Left for a follow-up on 0.2.0 there: `hide` and `unhide` (its built pages
   cannot yet show a note in an item's place), the package's corrections log, and taking out the site's
   `OwnersDesk` once `Replies.publish` itself refuses an item no longer shown. **The owner deploys it with
   `update.sh`**; what to expect is in the pull request.
2. **Version 0.2.0 is released** (rj-mitchell/wts-core#4 merged, 14 November; the wheel's sha256 is
   `460bd523…6c8a`; a scratch project locks and installs it by its address). Where Landlords Stand moves to it in a
   follow-up (three small changes, listed in the changelog), with its `hide`, `unhide` and corrections log.
3. Then Where Councils Stand on 0.2.0, Where Countries Stand, Where MPs Stand, each with the adoption brief; then
   phases 5 to 7.

**ADR 0006 is proved outside the package** (14 November): Where Landlords Stand's `docker` job built the site's
image (`python:3.12.15-slim`, no `git`, no token) from the released wheel by its address, and its `tests` job
installed it with `uv sync --frozen`. Checked on 13 November: `uv lock` and `uv sync --frozen` against the wheel's
address work, and the hash in the lock file is the release's. (A bare `uv pip install <address>` fails inside the build session only: its proxy
answers a HEAD request for that address with 401.)
