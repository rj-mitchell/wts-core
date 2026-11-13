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
| 3 to 7 | Not started. Phase 3 waits for the owner's review of the design | |

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

1. Review the design: the first page of `ARCHITECTURE.md`, then the eight records it names.
2. Yes or no: the sentence for the privacy notices and 13 months (ADR 0012); the four questions in ADR 0008.
3. A working API key for the build session, if evaluation runs are wanted from it.
4. Make the check token when the nightly check is extended (ADR 0010); nothing is needed before then.

## Next step

After the owner's review of the design: phase 3, the package, starting with the proof that a site can install a
release's wheel in a slim image with no `git` (ADR 0006), then the modules in the order of ARCHITECTURE.md's
section 4, with the example site growing beside them. Before that, worth doing if there is time: a second reviewer
with fresh context on the design, and on each site's ports. It was done for Where MPs Stand's ports and found a
real fault (`NOTES/a-second-pass-must-be-as-strict-as-the-first.md`), so it is worth the cost for the others too.
