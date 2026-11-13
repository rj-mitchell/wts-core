# Working on wts-core

How code in this package is written, so that every module reads as if one person wrote it. The design is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the interface each module must offer is sketched in
[`docs/API-SKETCH.md`](docs/API-SKETCH.md); what each site's copy does today, line by line, is in
[`docs/study/`](docs/study/).

## The rules

1. **The sites' behaviour is the specification.** A module here must be able to reproduce what each site's copy
   does today. Where the copies differ on purpose (a limit, a message, a word list, a file name), the difference is
   a parameter with **no default in the package**. Where they differ by accident, take the best copy's behaviour,
   and say which in the module's docstring. Read the study for your module and the code it points to before writing.
2. **The checks on briefings never weaken.** Anything in `wts_core.checks` must flag at least what the strictest
   site copy flags today, case for case. Bring every test the sites have for it.
3. **Nothing about readers is stored or logged** beyond what the sites store today: no address, no header, no
   visitor code outside the spending record, never a question or briefing text in a log line.
4. **Only `wts_core/adapters/` imports an outside library,** and each adapter imports its own when first used
   (inside the function or method), so `import wts_core` works with nothing installed. `wts_core/cli` may import
   `typer`. `tests/test_walls.py` enforces this and the wall around `wts_core.replies`.
5. **Everything is passed in.** No module-level state, no reading the environment or the clock directly: take
   `clock: Clock = SYSTEM_CLOCK`, `random: Random = SYSTEM_RANDOM`, `env: Mapping[str, str] | None = None`. No
   reader-facing wording: it comes from the site's `Messages` (or the module's own messages class, every field
   required).
6. **Tables are named `wts_…`,** created by a `Migration` the module exports from a function `migrations()`
   (numbers: state 1–9, usage 10–19, briefing 20–29, replies 30–39, observe 40–49). Migrations only add. Use
   `StateDB.connect()`; rows by name; times from `wts_core.state.iso(clock)` and `today(clock)`.
7. **The public interface is `__all__`,** in every module. Private names start with an underscore. Don't export
   what a site doesn't need.

## Style

- Python 3.12: `from __future__ import annotations`, `X | None`, `type` aliases, generics as `def f[T](…)`.
- Fully typed, `mypy --strict` clean (`uv run mypy`). No `# type: ignore` without a reason on the same line.
- `ruff` clean (`uv run ruff check .`). Lines to 120 by hand.
- Docstrings and comments in plain British English, in the sites' voice: say what a thing is for and why, in full
  sentences; colons rather than dashes; no "we". Keep the sites' own comments where the code is theirs: they record
  hard-won reasons.
- Small frozen dataclasses for values; `Protocol`s for what a site implements; no inheritance except from
  `wts_core.settings.Settings`.
- Errors a reader may see are exceptions that carry the site's message. Errors for the owner name the file or
  setting to change.

## Tests

- `uv run pytest`. Tests live in `tests/test_<module>.py`, named as sentences
  (`test_a_refused_visitor_leaves_nothing_behind`).
- Bring across **every** test the sites have for the module (the study lists them, with the cases only one site
  covers), adapted to the package's interface, and parametrise over the sites' differing inputs (word lists,
  limits, messages) with small fixtures named after the sites.
- Use `wts_core.testing.FixedClock` and `FixedRandom`; never the real clock, network or model.
- A fix needs a test that fails without it.

## Commits

One logical piece per commit, message in the sites' style (what and why, in sentences), ending with the two
attribution lines used throughout this repository's history. Never name an AI model in a file, commit or pull
request.

## Releasing

1. In a pull request: set the version in `pyproject.toml` and `src/wts_core/__init__.py`, head the changelog's
   entry `## <version> (<date>)` with its `api:` line (`tests/test_public_api.py` says how), and run `uv lock`
   here and in `examples/minimal-site`.
2. When it is merged, on GitHub: Actions, "Release", "Run workflow" on `main`, with the version. The workflow
   checks the three places agree, runs the tests, builds the wheel, makes the tag `v<version>` on that commit and
   attaches the wheel to a release. (Pushing the tag by hand starts the same workflow.)
3. A release is never changed. A fix is a new version.
