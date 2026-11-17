# Contributing to wts-core

The rules for changing the package, its code style and tests, and how a release is made. The design is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and the decisions behind it are in [`docs/adr/`](docs/adr/). Read
the module's docstring and its tests before changing it.

## Setting up

The commands are in the README, under [Running the checks](README.md#running-the-checks). CI runs them for the
package and for the example site, on Python 3.12 and 3.13, and also at the lowest and highest dependency versions
the ranges in `pyproject.toml` allow.

## Rules for the package

1. The sites' behaviour is the specification. A module must be able to reproduce what each site did before it
   adopted the package. Where the sites differ on purpose (a limit, a message, a word list, a file name), the
   difference is a parameter with no default in the package. Where they differ by accident, take the best
   version's behaviour and say which in the module's docstring.
2. The checks on briefings never get weaker. Anything in `wts_core.checks` must flag at least what the strictest
   site flagged, case for case.
3. Nothing about readers is stored or logged beyond what the sites' privacy notices describe: no IP address, no
   request header, no visitor code outside the spending record, and never a question or briefing text in a log
   line.
4. Only `wts_core/adapters/` imports an outside library, and each adapter imports its library when first used, so
   `import wts_core` works with nothing else installed. `wts_core/cli` may import `typer`.
   `tests/test_walls.py` enforces this and the separation of `wts_core.replies`.
5. Everything is passed in. There is no module-level state and no direct reading of the environment or the clock:
   take `clock: Clock = SYSTEM_CLOCK`, `random: Random = SYSTEM_RANDOM` and `env: Mapping[str, str] | None = None`.
   The package holds no reader-facing wording; it comes from the site's `Messages` or the module's own messages
   class, with every field required.
6. Tables are named `wts_…` and created by a `Migration` the module exports from `migrations()`. Migration numbers
   are allocated by module: state 1–9, usage 10–19, briefing 20–29, replies 30–39, observe 40–49. Migrations only
   add. Use `StateDB.connect()`, read rows by name, and take times from `wts_core.state.iso(clock)` and
   `today(clock)`.
7. The public interface is `__all__` in every module. Private names start with an underscore. Export only what a
   site needs; `tests/test_public_api.py` fails when the interface changes without a changelog entry.

## Style

- Python 3.12: `from __future__ import annotations`, `X | None`, `type` aliases and `def f[T](...)` generics.
- Fully typed and clean under `mypy --strict` and `ruff`. A `# type: ignore` needs a reason on the same line.
  Lines are kept to 120 characters by hand.
- Docstrings and comments in plain British English: say what a thing is for and why it is done this way. Keep
  them short, and leave the history of a change to the changelog.
- Small frozen dataclasses for values, and `Protocol`s for what a site implements. No inheritance except from
  `wts_core.settings.Settings`.
- Errors a reader may see are exceptions that carry the site's message. Errors for the site's maintainer name the
  file or setting to change.
- Wording shared across the sites follows the family glossary (`family/GLOSSARY.md` in the charity's private
  repository, `rj-mitchell/wheretheystand-charity`).

## Tests

- Tests live in `tests/test_<module>.py` and are named as sentences
  (`test_a_refused_visitor_leaves_nothing_behind`).
- Parametrise over the sites' differing inputs (word lists, limits, messages) with small fixtures named after the
  sites.
- Use `wts_core.testing.FixedClock` and `FixedRandom`; never the real clock, the network or a real model.
- A fix needs a test that fails without it.
- A change to a check on briefings needs a property or fuzz test that compares the old and new behaviour, not
  only hand-picked cases.
- A privacy guarantee is tested by attempting the attack it rules out, for example joining two tables on time
  and token counts. Checking which columns exist is not enough.

## Commits and pull requests

Keep each commit to one logical change. Write the subject as a short sentence saying what changed, and use the
body, if needed, to say why. A pull request describes the change, any behaviour a site or reader would notice,
and what a site must do.

## Releasing

1. In a pull request: set the version in `pyproject.toml` and `src/wts_core/__init__.py`; add the changelog entry
   `## <version> (<date>)`, saying what changed and what a site must do, with its `api:` line
   (`WTS_UPDATE_API=1 uv run pytest tests/test_public_api.py -s` writes `docs/api-snapshot.txt` and prints the
   line); and run `uv lock` here and in `examples/minimal-site`.
2. Once it is merged, run the "Release" workflow on `main` from the Actions page, with the version. The workflow
   checks that the three places agree, runs the tests, builds the wheel, tags the commit `v<version>` and attaches
   the wheel to a GitHub release. Pushing the tag by hand starts the same workflow.
3. A published release is never changed. A fix is a new version.
4. Move each site to the new version ([`docs/UPGRADING.md`](docs/UPGRADING.md)).
