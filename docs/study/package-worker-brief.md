# Building a module of wts-core: the rules every module worker follows

You are building one module of `wts-core`, the shared Python package for the four Where They Stand sites. The owner
(one person, not watching) has accepted the design. Read, in this order, before writing anything:

1. /home/user/wts-core/CONTRIBUTING.md : the rules and style. Follow it exactly.
2. /home/user/wts-core/docs/ARCHITECTURE.md sections 2 to 5, and the decision records your task names under docs/adr/.
3. /home/user/wts-core/docs/API-SKETCH.md : the section for your module. It is a sketch: keep its names and shapes
   unless the sites' code shows a better one, and tell me every place you departed and why.
4. /home/user/wts-core/docs/MIGRATION.md : the section for your module: every per-site difference the module must be
   able to reproduce.
5. The study for your module under /home/user/wts-core/docs/study/ (your task says which sections): what each
   site's copy does today, with file and line. Then READ THE SITES' CODE ITSELF: the studies were made by reading and
   are sometimes wrong; the code wins.
6. The foundation you build on: /home/user/wts-core/src/wts_core/ports.py, events.py, settings.py, state.py,
   testing/__init__.py and tests/test_walls.py.

The sites (read-only for you; use each at the commit named, with `git -C <repo> show <ref>:<path>` or by reading the
checkout, which is on that branch): Where MPs Stand /home/user/wherempsstand (package `hansard`), Where Countries
Stand /home/user/wherecountriesstand (`wcs`), Where Councils Stand /home/user/wherecouncilsstand (`councils`),
Where Landlords Stand /home/user/wherelandlordsstand (`landlords`). All four checkouts are on the branch
`claude/gallant-cerf-xxy2ge`, which has the fixes ported in phase 1: that branch, not `main`, is the behaviour to
reproduce. Never change anything in those four repositories.

## How to work

1. Make your own worktree and branch from the package branch (other workers are building other modules at the same
   time, each in its own worktree):
   `git -C /home/user/wts-core fetch -q origin && git -C /home/user/wts-core worktree add /home/user/wt/core-<name> -b claude/wts-3-<name> origin/claude/wts-3-package`
   Work only in /home/user/wt/core-<name>. Run `uv sync` there once (add `--extra …` for the extras your module
   needs, and say which in your report).
2. Touch only the files your task names (your module's files and its tests). Do NOT edit ports.py, events.py,
   settings.py, state.py, testing/__init__.py, pyproject.toml, CONTRIBUTING.md or anything under docs/. If you need
   a change in one of those (a missing field, a new port, a dependency), do not make it: write the exact change you
   need at the top of your report, and work around it locally meanwhile (for example a private helper in your
   module).
3. Commit often (each finished piece), with messages as CONTRIBUTING.md says, each ending with exactly these two
   lines:
   `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`
   `Claude-Session: https://claude.ai/code/session_01Lb3YfaLZeKK1rVxYtwZMCk`
   and push after each commit (`git push -q -u origin claude/wts-3-<name>`), so nothing is lost if you are stopped
   by a usage limit. Do not open a pull request; I merge the branches.
4. Before you finish: `uv run ruff check .`, `uv run mypy`, `uv run pytest` must all pass in your worktree. Report
   the real numbers.
5. Be economical: read what you need, don't re-read; don't narrate. You have no API key and must make no network
   call to any model or outside service.

## Never

Change the sites; weaken any check on briefings; store or log anything about readers beyond what the sites store
today; name an AI model in files, commits or reports (a model's id in a settings example copied from a site is
fine); merge, deploy, force-push; push to any branch but your own.

## Report back (concise)

Changes you need in the foundation files (exact); what you built (files, public names); every departure from
API-SKETCH.md and why; behaviours of a site's copy that the module can NOT reproduce yet, and why; test counts
(`pytest`, and that ruff and mypy pass); which of the sites' tests you brought across and any you could not;
anything in the studies that the code contradicts; anything uncertain.
