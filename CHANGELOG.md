# Changelog

Kept by hand. Versions follow semantic versioning; while the version is 0.x, a minor version may change the
interface, and each such change is listed under "Changed" with what a site must do (docs/adr/0007-versioning.md).
The line `api: <hash>` under a version is the fingerprint of the public interface at that version
(`docs/api-snapshot.txt`); `tests/test_public_api.py` fails when the interface changes without a new one here.

## 0.1.0 (13 November 2026)

The first release: everything the four sites did alike, in one place.

api: 86cb9d353511

### Added

- **The foundation:** `wts_core.ports` (every interface something may be swapped behind), `wts_core.events` (the
  briefing's event format), `wts_core.settings` (layered settings, `Site`, `Messages`), `wts_core.state` (the state
  database, the `wts_` tables, numbered migrations, a site's one-off import of its old rows).
- **The checks on briefings** (`wts_core.checks`): the citation verifier, quotations, unsupported sentences, loaded
  words, British spelling, typography and balance, with each site's own words and patterns passed in, and
  `check_briefing`, the one order they run in. Never weaker than the strictest site's copy.
- **Limits and money** (`wts_core.usage`): the rate limiter, the day's visitor code, prices, the spending record,
  caps, briefings in progress, the answer cache, saved briefings, failures.
- **The briefing flow** (`wts_core.briefing`): the desk (cache, caps, places in progress, the pipeline's events,
  saving, the record), stage timings and the streamer, with hooks for what each site does differently.
- **Reports and the right of reply** (`wts_core.replies`), kept apart from everything that touches the model.
- **The record of each briefing, statistics, the weekly report and alerts** (`wts_core.observe`), and structured
  logs that can hold no reader's words.
- **The evaluation harness** (`wts_core.eval`): replay of recorded briefings, free and offline, and live runs with
  a spending limit, thresholds and a "passed" line.
- **Operations** (`wts_core.ops`): backup, restore, off-site copies and their alerts.
- **Adapters** (`wts_core.adapters`): the Anthropic client, two embedders, the LanceDB index, Backblaze B2, the
  thread-safe DuckDB wrapper. Only these import an outside library.
- **Shared commands** (`wts_core.cli`): backup, right of reply, statistics and evaluation commands for a site's
  own command line, and the nightly check route.
- **For a site's tests** (`wts_core.testing`): a fixed clock and chance, a scripted model with real recordings, an
  embedder and index in memory, contract tests for each adapter, and the checks that statements stay out and
  that nothing about a reader is kept.
- **An example site** (`examples/minimal-site`), `docs/EXTENDING.md`, `docs/NEW-SITE.md`.
- **Shared CI:** reusable workflows for Python checks, web checks, the family kit check and the Docker build; shared
  steps for the toolchain and the accessibility check; the toolchain written once in `toolchain.toml`.

### For a site adopting it

`docs/AS-BUILT.md` lists, module by module, what differs from each site's copy and what its adoption must handle.
`docs/MIGRATION.md` is the plan for each site.
