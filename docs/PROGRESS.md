# Progress

Read this first, then `docs/NOTES/`. Keep it current: what is done, what is open, the next step.

Last updated: 13 November 2026, 04:30 UTC (session 1).

## Where things stand

| Phase | State | Evidence |
|---|---|---|
| 0. Prerequisites | Done | [`PHASE-0.md`](PHASE-0.md) |
| 1. Converge the copies | **Done: five pull requests, all green**, and the charity repository's (drift list, baseline, ENGINE.md) | below; the drift report before and after is in [`study/`](study/) |
| 1, the library upgrade | Pull request open and green; **needs an evaluation run before merging** | rj-mitchell/wherempsstand#43 |
| 1b. "Why use this rather than a chatbot?" | **Done: four pull requests** (the hub and three AI sites); screenshots in the charity repository's | below |
| 1c. One toolchain | **Done: six pull requests, all green on GitHub** | below |
| 2. Design | **Written; waits for the owner's review** | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`adr/`](adr/), [`MIGRATION.md`](MIGRATION.md), [`API-SKETCH.md`](API-SKETCH.md), [`study/`](study/) |
| 3. Build the package | **Under way** (the owner accepted the design on 13 November 2026) | branch `claude/wts-3-package`; see "Phase 3" below |
| 4 to 7 | Not started | |

## Pull requests (17, none merged)

| Repository | Step | Branch | Pull request |
|---|---|---|---|
| wts-core | 0 and 2: the design | `claude/gallant-cerf-xxy2ge` | rj-mitchell/wts-core#1 |
| wherempsstand | 1: ports | `claude/gallant-cerf-xxy2ge` | rj-mitchell/wherempsstand#44 |
| wherecountriesstand | 1: ports | `claude/gallant-cerf-xxy2ge` | rj-mitchell/wherecountriesstand#31 |
| wherecouncilsstand | 1: ports | `claude/gallant-cerf-xxy2ge` | rj-mitchell/wherecouncilsstand#49 |
| wherelandlordsstand | 1: ports | `claude/gallant-cerf-xxy2ge` | rj-mitchell/wherelandlordsstand#17 |
| wheretheystand-charity | 1: drift list, baseline, ENGINE.md | `claude/gallant-cerf-xxy2ge` | rj-mitchell/wheretheystand-charity#28 |
| wherempsstand | 1: library versions | `claude/wts-1-library-versions` | rj-mitchell/wherempsstand#43 (not before an evaluation run) |
| wheretheystand-charity | 1b: the hub, the glossary's wording, all screenshots | `claude/wts-1b-why-not-a-chatbot` | rj-mitchell/wheretheystand-charity#27 (merging publishes the hub) |
| wherempsstand | 1b | `claude/wts-1b-why-not-a-chatbot` | rj-mitchell/wherempsstand#45 |
| wherecountriesstand | 1b | `claude/wts-1b-why-not-a-chatbot` | rj-mitchell/wherecountriesstand#32 |
| wherecouncilsstand | 1b | `claude/wts-1b-why-not-a-chatbot` | rj-mitchell/wherecouncilsstand#50 |
| wherempsstand | 1c | `claude/wts-1c-toolchain` | rj-mitchell/wherempsstand#42 |
| wherecountriesstand | 1c | `claude/wts-1c-toolchain` | rj-mitchell/wherecountriesstand#30 |
| wherecouncilsstand | 1c | `claude/wts-1c-toolchain` | rj-mitchell/wherecouncilsstand#48 |
| wherelandlordsstand | 1c | `claude/wts-1c-toolchain` | rj-mitchell/wherelandlordsstand#16 |
| wherelivesstand | 1c | `claude/wts-1c-toolchain` | rj-mitchell/wherelivesstand#21 |
| wheretheystand-charity | 1c (and `family/TOOLCHAIN.md`) | `claude/wts-1c-toolchain` | rj-mitchell/wheretheystand-charity#26 |

**A suggested order for merging:** the six toolchain pull requests (independent of everything); the four ports;
the four "why" pull requests; then the charity repository's drift pull request (#28, after the ports, so its
baseline matches `main`); the design (#1) whenever it has been reviewed; Where MPs Stand's library versions (#43)
only after an evaluation run. Checked by merging every open branch of each repository onto `main` together in a throwaway copy: all merge
cleanly, with one exception. In Where Countries Stand, the ports (#31) and the "why" pull request (#32) both change
the last rows of the table in `docs/DECISIONS.md`. Merge one, then on the other choose "Resolve conflicts" and keep
both rows (row 16 as #31 words it, and row 17).

## Phase 3: how it is being built

The package branch is `claude/wts-3-package` (stacked on the design branch until rj-mitchell/wts-core#1 is merged).
The foundation is on it: `ports`, `events`, `settings`, `state`, `testing` (clock and chance), the wall tests, the
toolchain file and its test, the shared workflows and the package's own CI, `CONTRIBUTING.md`, `CHANGELOG.md`.
Proved locally: the wheel builds, installs alone with `git` off the PATH, and every base module imports with
nothing else installed.

Each module is built by one worker in its own worktree and branch, from the same brief
(`CONTRIBUTING.md`, the API sketch, MIGRATION, the study, and the sites' code at their phase 1 branches), with
parity tests that import each site's own functions and compare results. I merge the branches into the package branch.

| Module | Branch | Worktree | State |
|---|---|---|---|
| `checks` (verifier, loaded words, spelling, typography, balance) | `claude/wts-3-checks` | `/home/user/wt/core-checks` | building |
| `usage` (limiter, visitor code, prices, spending, caps, in progress, cache, saved briefings, failures) | `claude/wts-3-usage` | `/home/user/wt/core-usage` | building |
| `ops`, `adapters.b2`, `adapters.duckdb` | `claude/wts-3-ops` | `/home/user/wt/core-ops` | building |
| `replies` | `claude/wts-3-replies` | `/home/user/wt/core-replies` | building |
| `adapters.anthropic`, `.hashing`, `.fastembed`, `.lancedb`; testing fakes and contracts | `claude/wts-3-adapters` | `/home/user/wt/core-adapters` | building |
| `briefing` (the desk, stages, the streamer) | to start once `usage` and `checks` are merged | | |
| `observe` (the briefing log, statistics, alerts) | after `briefing` | | |
| `eval` (replay and live runs) | after `checks` and the adapters | | |
| `cli` (the shared commands) and the `/api/check` route | after `ops`, `replies`, `observe` | | |
| `examples/minimal-site`, `docs/EXTENDING.md`, `docs/NEW-SITE.md` | last | | |
| The public-interface snapshot test, then tag `v0.1.0` | last (the tag needs the pull requests merged first) | | |

The workers' brief is kept at `docs/study/package-worker-brief.md`.

## What could not be done, and why

- **No evaluation run and no live briefing.** The API key in the build session is refused by Anthropic, and each
  site's evaluation of briefings needs its own archive and index, which are on the server
  (`NOTES/what-the-build-session-cannot-do.md`). This blocks: the before-and-after evaluation for Where MPs Stand's
  library upgrade, and recording model streams as fixtures for the package.
- **Nothing on the server was looked at.** Two questions for the owner come from that: the front door's handling of
  `X-Forwarded-For` (MIGRATION 1.3), and whether Where MPs Stand's `restore` works across file systems in its
  container (fixed in phase 1 either way). A third, about Where Councils Stand's `usage` table, was settled from the
  repository's history: the column was always there.

## Open, for the owner

1. A working API key. `HANSARD_ANTHROPIC_API_KEY` was changed in the environment's settings on 13 November, but the
   running session still held a value Anthropic refuses; test it again at the start of the next session
   (`NOTES/what-the-build-session-cannot-do.md`), before any evaluation run.
2. Merging the 17 open pull requests, in the order given above, and running each site's `update.sh`.
3. The check token, when the nightly check is extended (ADR 0010); nothing is needed before then.

Decided by the owner on 13 November 2026: the design is accepted; the privacy notice changes are accepted; the four
right-of-reply questions were left to the maintainer and are decided in ADR 0008.

## Next step

Merge the five module branches as each finishes (checks first), apply the changes they ask for in the foundation
files, then start `briefing`, `observe`, `eval`, `cli` and the example site. Then the interface snapshot, the
package's pull request, and (once merged) the tag.
