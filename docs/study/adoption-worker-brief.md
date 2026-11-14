# Adopting wts-core in a site: the brief every adoption worker follows

You are moving ONE of the Where They Stand sites onto `wts-core`, the shared package its engine was extracted
into. The package is released: v0.2.0 (14 November 2026), public, at https://github.com/rj-mitchell/wts-core. Its checkout, with all
its documents, is at `/home/user/wts-core` (read only for you: never edit it; if the package is wrong or awkward,
say so in your hand-back, with the file and what you would change, and work round it in the site only if that is
clean).

The owner's rule for the whole project: **the site's behaviour is the specification. Readers must see no change
unless a document below lists it, and you prove that with parity tests.** The owner is one person, not watching;
they deploy by running the site's `update.sh` on the server after a pull request is merged. You never touch the
server, never deploy, never send email, never force-push.

## Read first, in this order

1. `/home/user/wheretheystand-charity/plans/family/wts-core-brief.md`: the "Musts", "Never", and "Phase 4: Adopt".
2. `/home/user/wts-core/docs/MIGRATION.md`: the plan for each module, with your site's column, and section 2
   (the order of work in a site).
3. `/home/user/wts-core/docs/AS-BUILT.md`: for every module, "At adoption": what differs from your site's copy
   and what you must handle. This wins over MIGRATION and over `docs/API-SKETCH.md` where they differ.
4. `/home/user/wts-core/docs/EXTENDING.md`, `docs/NEW-SITE.md`, `docs/UPGRADING.md`, `CHANGELOG.md` (0.2.0: what
   changed since the first site adopted), and the example site `examples/minimal-site/` (a whole small site on the
   package: copy its shape, not its words). For an AI site the wiring is `briefing.desk_parts(...)` then
   `DeskParts.desk(config, ...)`, with the configuration from `observe.briefing_config(...)`: the example's
   `app.py` and `/home/user/wts-core/tests/briefing_sites.py` (how each real site would wire it) show both.
   The first site to adopt, Where Landlords Stand, is the worked example for the base slice: its merged work is at
   `/home/user/wt/landlords-adopt` (on 0.1.0: `tests/golden/record.py`, `tests/golden/shared.py`,
   `tests/test_parity.py`, `tests/test_import.py`, `tests/test_privacy.py`, `tests/test_dependencies.py`,
   `src/landlords/state.py`, `replies.py`, `cli.py`, `deploy/undo-wts-core.sql`) and its pull request description
   at `/home/user/wt/landlords-adopt-PR.md`. Copy its method, not its words.
5. `/home/user/wts-core/docs/NOTES/independent-review-of-the-package.md` (what a privacy claim must be tested with).
6. Your site's own `README.md`, `docs/` (its `DECISIONS.md` style), `CLAUDE.md` if it has one, tests layout, and
   the modules you are replacing, whole.
7. `/home/user/wheretheystand-charity/family/GLOSSARY.md`, "Style": everything you write (docs, comments, commit
   messages, reader text) is in that plain British English. No AI model brand names in prose (model ids copied
   from settings are fine).

## Where you work

- `git -C /home/user/<repo> fetch origin main` then
  `git -C /home/user/<repo> worktree add -b claude/wts-4-adopt-core /home/user/wt/<short>-adopt origin/main`.
  Work ONLY in that worktree. Never edit `/home/user/<repo>` itself, another worktree, or another repository.
- Commit often (one logical piece per commit, messages in the site's own style, what and why in sentences), each
  ending with the two lines
  `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01Lb3YfaLZeKK1rVxYtwZMCk`,
  and push after each (`git push -u origin claude/wts-4-adopt-core`): a usage limit may stop you at any moment.
- Open NO pull request. Make no model call and use no API key unless your own brief says otherwise.

## The dependency

In `pyproject.toml`, the wheel by its address, with the extras your site needs (docs/adr/0006, NEW-SITE.md):

    "wts-core[...] @ https://github.com/rj-mitchell/wts-core/releases/download/v0.2.0/wts_core-0.2.0-py3-none-any.whl"

and `[tool.hatch.metadata]` `allow-direct-references = true` (hatchling refuses the address without it). Then
`uv lock`. Check `uv sync --frozen` works, and that the site's Dockerfile needs no `git` for it. If the address
does not resolve (the release is minutes old), say so at once rather than depending on a local path.

## The order of work (do not skip the first step)

1. **Golden outputs, before you change anything.** With the site's code as it is on `main`, record what its own
   functions give on its own fixtures, into `tests/golden/` (JSON): settings resolved from a sample configuration
   and from the real `config/settings.toml`; rate-limit decisions over a scripted sequence; backup names and
   contents listing, restore refusals; every refusal message of reports and statements, what the public endpoints
   return, the owner commands' printed output; and for an AI site: the verifier's and loaded-words' output on its
   test briefings and saved-briefing fixtures, cost for a table of recorded usages, cache keys for a table of
   questions, caps decisions, and the exact bytes of `/api/ask` for scripted pipelines (fresh, cached, refused,
   sources only, error). Write the recorder as a script kept in `tests/golden/record.py` so it can be re-run on
   the old code from git history. Commit the goldens BEFORE the switch, in their own commit.
2. **Switch one module at a time**, in MIGRATION section 2's order: implement the site's hooks, delete the site's
   own copy (the file goes; do not leave a shim that re-exports unless other site code imports many names from
   it, and then say so), run the site's whole test suite, commit.
3. **Parity tests, committed:** each golden compared with what the site gives now. A difference is either a bug
   you fix, or one of the differences AS-BUILT lists for your site, which you then assert explicitly in the test
   with a comment naming the AS-BUILT entry. Nothing is skipped silently.
4. **The state database:** the site's `Import` statements (docs/adr/0005; EXTENDING "migrations and a site's
   one-off import"), copying its old rows into the `wts_` tables. Test the import on a database made by the OLD
   code (build one with the old schema and realistic rows, including NULLs: use `coalesce` where the old column
   allows NULL and the new does not), then check counts and values, that the old tables are untouched, that the
   copy `state.pre-wts-core.<date>` is made, that a second start imports nothing, and that the site's own
   figures (spending today and this month, a visitor's count, cached answers still served, saved briefings still
   open at their addresses, statements still shown) are the same after as before.
5. **Reports and statements** on `wts_core.replies`, keeping the site's pages, forms, wording and how statements
   look. Do NOT pass a visitor code to `submit`/`report` unless the site counts by visitor today (a new code kept
   would be something new collected). Words the site has none of today (AS-BUILT lists them): write them in the
   site's voice, short and plain, and list every one in your hand-back for the owner to approve.
6. **Operations:** backup, restore, off-site on `wts_core.ops` and the shared commands, every printed line as
   today; the nightly `update.sh` gains the `tidy` step where the site uses the record (AS-BUILT), and
   `forget_old_copies` with the site's backup retention. `update.sh` and `deploy/` are files in the repository:
   edit them there; nothing is run on a server.
7. **CI:** the site's `.github/workflows/ci.yml` calls the shared workflows at the same tag
   (`rj-mitchell/wts-core/.github/workflows/python.yml@v0.2.0` and the others it uses: read each workflow's
   header in `/home/user/wts-core/.github/workflows/` for its inputs; docs/adr/0010). Keep every check the site
   runs today (count the steps before and after and list them in the hand-back).
8. **Docs:** the site's README and docs where they describe the replaced modules; a row in its `DECISIONS.md` in
   its own style; the privacy notice sentences the owner has accepted (ADR 0012 and ADR 0008 give them: add
   exactly those, only where the site turns the feature on).

A test that reads a command's `--help` must turn Typer's colours off before Typer is imported (GitHub Actions
makes Typer colour its help, which splits option names): at the very top of `tests/conftest.py`, before other
imports, `os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"` and `os.environ["NO_COLOR"] = "1"`. Run the suite
once with `GITHUB_ACTIONS=true` set before you hand back.

Before you hand back, run the site's lint and tests once in a CLEAN export of your branch, as CI's fresh checkout
sees it (`git archive HEAD | tar -x -C <a scratch folder of your own>`, then the site's lint command there with the
worktree's `.venv/bin/ruff`): in the worktree, the cache folders of modules you deleted are still about, and the
linter then sorts imports of those modules differently from CI (this failed Where Countries Stand's first CI run).
A file that must import deleted modules (the recorder of the old code's outputs) takes `# ruff: noqa: I001` with a
comment saying why.

In a CI job that starts the site in the background (the accessibility job, a smoke test), start it with the
environment's own program (`.venv/bin/<command> serve … &`, keeping its pid), never through `uv run … &`, and stop
it in a last step with `if: always()`. A `uv run` left in the background holds uv's cache, and the shared `setup`
action's tidying of that cache at the end of the job then waits five minutes and fails the job (this failed Where
Countries Stand's accessibility job after the check itself had passed).

## What "done" means

- The site's full test suite passes, its lint passes, its front-end tests pass if it has a front end you touched,
  and the count of tests is not lower than before except for tests of deleted modules that the package now has
  (list those).
- Every golden is compared; every difference is asserted and listed.
- `wts_core.testing.assert_no_reader_data` runs in the site's tests against its real tables after a scripted
  question (and for an AI site `assert_statements_stay_out` against its real pipeline with the scripted model).
- No file of the site imports a private name of the package (anything not in a module's `__all__`).
- `git grep` shows no leftover copy of a replaced function.

## Hand back (this is all the lead sees: be exact and brief)

1. The branch, its head commit, and the test results with numbers (before and after).
2. **Every behaviour change**, each marked R (a reader or named person could notice), O (only the owner) or N
   (nobody), with the AS-BUILT or MIGRATION entry it comes from, or "new: found here".
3. Words you wrote that the owner must approve, each with where it is shown.
4. What the owner must do or know at deploy (a setting to add, a first-start import, how long it takes, how to
   go back: the old tables are untouched and the pre-import copy is there).
5. What in the package was wrong or awkward (file, what you would change): this feeds the next release.
6. What you did not do, and why.
7. A draft of the pull request's description in the site's usual form, ending with the two lines
   `🤖 Generated with [Claude Code](https://claude.com/claude-code)` and
   `https://claude.ai/code/session_01Lb3YfaLZeKK1rVxYtwZMCk`, saved as `/home/user/wt/<short>-adopt-PR.md`
   (outside the repository).
