# ADR 0007: Versioning, the public interface and compatibility

Status: accepted, 13 November 2026.

This record decides how the package is versioned, what counts as its public interface, and how compatibility is
kept.

## Context

Four sites pin this package and upgrade by pull request, and one person maintains all of them. An upgrade has to
be boring: a site should know from the version number whether it needs to change anything.

## Options

1. Semantic versioning, with the public interface defined by `__all__`. Clear and conventional; its weakness is
   that "public" is easy to change by accident.
2. Calendar versions (2026.11.0), which say when but not what changed.
3. No versions: every site tracks `main`, so one wrong fix reaches every site at once.

## Decision

Option 1, with these rules.

- Semantic versioning, tags `v<version>`, and a `CHANGELOG.md` kept by hand. While the version is 0.x a minor
  version may break the interface; each break is listed with what a site must do.
- The public interface is exactly what `wts_core.__all__` and each module's `__all__` export. Anything else is
  private, and a name starting with an underscore is private everywhere.
- A snapshot guards it. `tests/test_public_api.py` compares the exported names and signatures with
  `docs/api-snapshot.txt`, and the snapshot's fingerprint with the `api:` line of the newest changelog entry. So
  the interface cannot change without the changelog saying so.
- Three more things are part of the interface, because sites and their data depend on them: the reader-event
  format (ADR 0003), the tables whose names start `wts_` (ADR 0005), and the settings keys the package reads.
- A deprecated name keeps working for at least one minor version, warns with a `DeprecationWarning` naming its
  replacement, and is listed in the changelog.
- Supported ranges for Python and every dependency are stated in `pyproject.toml`. CI runs the tests on Python
  3.12 and 3.13, and at the lowest and highest versions the ranges allow.
- Sites pin an exact release and take the shared CI workflows at the same tag, so a site has one number to raise.
- A fix flows one way: fixed in the package, released, then taken by each site in a pull request. A site never
  patches its installed copy.

## Consequences

- A release is cheap, so fixes ship as patch versions and do not wait for other work.
- The snapshot adds a small chore to every interface change. That is its purpose.
