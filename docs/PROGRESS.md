# Progress

Read this first, then `docs/NOTES/`. Keep it current: what is done, what is open, the next step.

Last updated: 13 November 2026, 04:30 UTC (session 1).

## Where things stand

| Phase | State | Evidence |
|---|---|---|
| 0. Prerequisites | Done | [`PHASE-0.md`](PHASE-0.md) |
| 1. Converge the copies | Under way | See "Pull requests" below. The verifier fix is committed in all three AI sites; one worker per site is porting the rest |
| 1, the library upgrade | Pull request open; **needs an evaluation run before merging** | rj-mitchell/wherempsstand#43 |
| 1b. "Why use this rather than a chatbot?" | Under way: one worker per repository, stopped twice by usage limits, to be resumed after the ports | worktrees `/home/user/wt/{charity,mps,councils,countries}-1b` |
| 1c. One toolchain | **Done: six pull requests, all green on GitHub** | below |
| 2. Design | **Written; waits for the owner's review** | [`ARCHITECTURE.md`](ARCHITECTURE.md), [`adr/`](adr/), [`MIGRATION.md`](MIGRATION.md), [`API-SKETCH.md`](API-SKETCH.md), [`study/`](study/) |
| 3 to 7 | Not started. Phase 3 waits for the owner's review of the design | |

## Pull requests

| Repository | Step | Branch | Pull request | State |
|---|---|---|---|---|
| wts-core | 0 and 2: the design | `claude/gallant-cerf-xxy2ge` | (this one) | for review |
| wherempsstand | 1: library versions | `claude/wts-1-library-versions` | #43 | open; 523 tests pass locally; not to merge before an evaluation run |
| wherempsstand | 1c | `claude/wts-1c-toolchain` | #42 | green |
| wherecountriesstand | 1c | `claude/wts-1c-toolchain` | #30 | green |
| wherecouncilsstand | 1c | `claude/wts-1c-toolchain` | #48 | green |
| wherelandlordsstand | 1c | `claude/wts-1c-toolchain` | #16 | green |
| wherelivesstand | 1c | `claude/wts-1c-toolchain` | #21 | green |
| wheretheystand-charity | 1c (and `family/TOOLCHAIN.md`) | `claude/wts-1c-toolchain` | #26 | green |
| the four sites | 1: ports | `claude/gallant-cerf-xxy2ge` | not opened yet | workers running |
| three AI sites and the hub | 1b | `claude/wts-1b-why-not-a-chatbot` | not opened yet | workers paused |
| wheretheystand-charity | 1: drift manifest, baseline, ENGINE.md | to do | | after the ports |

## What could not be done, and why

- **No evaluation run and no live briefing.** The API key in the build session is refused by Anthropic, and each
  site's evaluation of briefings needs its own archive and index, which are on the server
  (`NOTES/what-the-build-session-cannot-do.md`). This blocks: the before-and-after evaluation for Where MPs Stand's
  library upgrade, and recording model streams as fixtures for the package.
- **Nothing on the server was looked at.** Three questions for the owner come from that: Where Councils Stand's
  `usage` table (MIGRATION 1.2), the front door's handling of `X-Forwarded-For` (MIGRATION 1.3), and whether Where
  MPs Stand's `restore` works across file systems in its container (fixed in phase 1 either way).

## Open, for the owner

1. Review the design: the first page of `ARCHITECTURE.md`, then the eight records it names.
2. Yes or no: the sentence for the privacy notices and 13 months (ADR 0012); the four questions in ADR 0008.
3. A working API key for the build session, if evaluation runs are wanted from it.
4. Make the check token when the nightly check is extended (ADR 0010); nothing is needed before then.

## Next step

Finish and open the ports' pull requests; finish 1b; then the charity repository's phase 1 pull request (the drift
manifest with the right-of-reply modules, the new baseline, ENGINE.md corrected in the five places the study
found). After the owner's review: phase 3.
