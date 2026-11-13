# Changelog

Kept by hand. Versions follow semantic versioning; while the version is 0.x, a minor version may change the
interface, and each such change is listed under "Changed" with what a site must do (docs/adr/0007-versioning.md).
The line `api: <hash>` under a version is the fingerprint of the public interface at that version
(`docs/api-snapshot.txt`); `tests/test_public_api.py` fails when the interface changes without a new one here.

## 0.1.0 (unreleased)

The first release: everything the four sites did alike, in one place.

api: 86cb9d353511

### Added

- The foundation: `wts_core.ports` (every interface something may be swapped behind), `wts_core.events` (the
  briefing's event format), `wts_core.settings` (layered settings, `Site`, `Messages`), `wts_core.state` (the state
  database and the `wts_` tables), `wts_core.testing` (a fixed clock and fixed chance).
- Shared CI: reusable workflows for Python checks, web checks, the family kit check and the Docker build; shared
  steps for the toolchain and the accessibility check; the toolchain written once in `toolchain.toml`.
