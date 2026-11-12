# Progress

Read this first, then `docs/NOTES/`. Keep it current: what is done, what is open, the next step.

Last updated: 13 November 2026 (session 1).

## Where things stand

| Phase | State | Evidence |
|---|---|---|
| 0. Prerequisites | Done | [`PHASE-0.md`](PHASE-0.md) |
| 1. Converge the copies | Not started (waits for the study of the copies) | |
| 1b. "Why use this rather than a chatbot?" | Under way: one worker per repository (hub, MPs, Councils, Countries) | worktrees `/home/user/wt/*-1b`, branch `claude/wts-1b-why-not-a-chatbot` |
| 1c. One toolchain | Under way: one worker, six repositories | worktrees `/home/user/wt/*-1c`, branch `claude/wts-1c-toolchain` |
| 2. Design | Under way: the study of the copies (`docs/study/`), then ARCHITECTURE, the ADRs, MIGRATION | this branch |
| 3 to 7 | Not started. Phase 3 waits for the owner's review of the design | |

## How the work is organised

- One branch per step in each repository, so each pull request is small: `claude/gallant-cerf-xxy2ge` (the
  convergence in the sites; the design here), `claude/wts-1b-why-not-a-chatbot`, `claude/wts-1c-toolchain`,
  `claude/wts-1-library-versions` (Where MPs Stand only).
- Work in the sites happens in git worktrees under `/home/user/wt/`, so parallel workers don't collide.
- Screenshots for phase 1b are saved under `/home/user/wt/shots/<site>/` and committed to the charity repository's
  1b branch (`plans/family/img/why-chatbot/`), not to the public site repositories.

## Open

- The owner's review of the design (the one fixed checkpoint).
- Evaluation runs need each site's data, which is not in the build session (see `PHASE-0.md`, section 5).

## Next step

Finish the study, write the design, port the fixes the study lists (phase 1), open the pull requests.
