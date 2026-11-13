# ADR 0007: Versioning, the public interface and compatibility

Status: accepted by the owner on 13 November 2026.

## Context

Four sites will pin this package and upgrade by pull request. One person maintains all of them. The policy has to
make an upgrade boring: a site should know from the version number alone whether it needs to change anything.

## Options

1. **Semantic versioning, with the public interface defined by `__all__` (the brief's default).** Clear and
   conventional. Its weakness is that "public" is easy to change by accident.
2. **Calendar versions (2026.11.0).** Says when, not what changed. A site can't tell a safe upgrade from a breaking
   one.
3. **No versions: every site tracks `main`.** One fix reaches every site at once, including a wrong one, on the live
   flagship first.

## Decision

Option 1, with these rules.

- **Semantic versioning, tags `v0.1.0`, `v0.2.0`…, a `CHANGELOG.md` kept by hand.** While the version is 0.x, a
  minor version may break the interface; each break is listed under "Changed" with what a site must do.
- **The public interface is exactly what `wts_core.__all__` and each subpackage's `__all__` export.** Anything else
  is private, and names that start with an underscore are private everywhere.
- **A snapshot guards it.** `tests/test_public_api.py` compares the exported names and their signatures with a
  committed snapshot, `docs/api-snapshot.txt`. A change to the snapshot without a new entry in `CHANGELOG.md` fails
  CI. So the interface can't change silently, and every change is written down where sites will read it.
- **Three more things are part of the interface,** because sites and their data depend on them: the reader-event
  format (ADR 0003), the tables whose names start `wts_` (ADR 0005), and the settings keys the package reads. Each
  has its own version number or migration list and its own compatibility tests.
- **Deprecate before removing.** A deprecated name keeps working for at least one minor version, warns with
  `DeprecationWarning` naming its replacement, and is listed in the changelog.
- **Supported ranges are stated in `pyproject.toml`** for Python and every dependency. CI runs the tests against
  the lowest and the highest supported versions of `anthropic` and `duckdb`, and runs the example site against the
  lowest and highest FastAPI the sites use.
- **Sites pin an exact release** and upgrade by pull request. The shared CI workflows are taken at the same tag, so a
  site has one number to raise.
- **A fix flows one way:** fix in the package, release, one pull request per site. A site never patches its
  installed copy.

## Consequences

- A release is cheap, so fixes ship as patch versions rather than waiting.
- The snapshot test adds a small chore to every interface change. That is its purpose.
