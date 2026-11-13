# Progress

Read this first, then `docs/NOTES/`. Keep it current: what is done, what is open, the next step.

Last updated: 13 November 2026, 15:30 UTC (session 1).

## Where things stand

| Phase | State | Evidence |
|---|---|---|
| 0. Prerequisites | Done | [`PHASE-0.md`](PHASE-0.md) |
| 1. Converge the copies | **Done: five pull requests, all green**, and the charity repository's (drift list, baseline, ENGINE.md) | below; the drift report before and after is in [`study/`](study/) |
| 1, the library upgrade | **Merged on the owner's word, 13 November 2026** (the site's own evaluation run still needs the server's data) | rj-mitchell/wherempsstand#43 |
| 1b. "Why use this rather than a chatbot?" | **Done: four pull requests** (the hub and three AI sites); screenshots in the charity repository's | below |
| 1c. One toolchain | **Done: six pull requests, all green on GitHub** | below |
| 2. Design | **Written; waits for the owner's review** | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`adr/`](adr/), [`MIGRATION.md`](MIGRATION.md), [`API-SKETCH.md`](API-SKETCH.md), [`study/`](study/) |
| 3. Build the package | **Done: merged** (rj-mitchell/wts-core#2, every CI job green). The release `v0.1.0` is made by the release workflow, started from the Actions page | `main`; see "Phase 3" below |
| 4 to 7 | Not started | |

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

## Rough edges the example site found, kept for the first AI site's adoption

Building the example made its author the package's first user. These are real, and each is better settled against
a real site's wiring than guessed at now. They are the first things to do in phase 4, before Where Councils Stand:

1. **A builder for the desk.** `BriefingDesk` takes twelve required arguments and a site builds about ten objects
   first, alike on every site. One function from settings, a `StateDB` and `Messages` would cut each site's wiring
   and the room for error. With it: one start-up check that names the file for a missing limit or price.
2. **`config` is a mapping with string keys.** A misspelt key is recorded as empty. A small dataclass, built once
   with its id and remembered in `wts_configs` by the same call.
3. **The model client's type has no `close()`**, and "is there a key?" needs a provider-specific import. Both
   belong with phase 5's proof that a provider can be swapped.
4. **Housekeeping the nightly update must call** is now: the `tidy` command (the record, reports, visitor codes,
   old copies) and the check route (the right of reply's, through `waiting()`). A site with no check token set
   needs a command for the second.
5. **About forty lines of wording** for a new site's backup and right-of-reply commands, with no defaults.
6. Two command arguments are plain values where the rest are callables (`max_cost_usd`, `similarity`); the
   off-site `keep` is fixed at 60.
7. **A restore accepts a sister site's backup** when both have only `wts_` tables. A stamp of the site's package
   in `wts_kv`, checked on restore, would close it.
8. `events.to_reader` returns a typed dictionary and the desk takes plain ones, so a site needs a cast.
9. `FixedRandom.token()` gives nine characters and the structured log takes only the desk's eleven.
10. `replies.long_date` (the family's date format) lives in the right-of-reply module, where a pipeline must not
    import it.

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

Merge `briefing`, `observe` and `eval` as each finishes; then `cli` (the shared commands and the check route),
the remaining testing helpers, the example site and the guides. Then the interface snapshot, the package's pull
request, and (once merged) the tag. [`AS-BUILT.md`](AS-BUILT.md) lists what adoption must handle for each module.
