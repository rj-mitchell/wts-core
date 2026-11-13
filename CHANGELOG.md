# Changelog

Kept by hand. Versions follow semantic versioning; while the version is 0.x, a minor version may change the
interface, and each such change is listed under "Changed" with what a site must do (docs/adr/0007-versioning.md).
The line `api: <hash>` under a version is the fingerprint of the public interface at that version
(`docs/api-snapshot.txt`); `tests/test_public_api.py` fails when the interface changes without a new one here.

## 0.2.0 (13 November 2026)

The rough edges the example site found, removed before the three AI sites adopt the package. No site uses the
briefing desk yet, so its interface could still change; the bytes a reader receives through it have not.

api: e0f94a7716a5

### Changed

- **`BriefingDesk` takes `config: ports.BriefingConfig`, and no `parse_model`.** The configuration was a mapping
  with string keys, where a misspelt key was recorded as empty; it is now a frozen dataclass with a field for each
  (`config_id`, `model`, `parse_model`, `instructions`, `package_version`, `site_version`, `experiment`, `arm`,
  and `settings`, the parts behind the id). The model a question's reading is priced as is its `parse_model`.
  *What a site must do:* nothing yet (no site has adopted the desk). At adoption, make the configuration with
  `observe.briefing_config` and pass it as `config`.

- **`Limits.from_settings` and `PriceTable.from_settings` say everything that is wrong at once,** and name the
  key of a figure that is not a number (`[usage] daily_spend_cap_usd is not a number: 'lots'`). Both take
  `file=`, the settings file to name in the error. `SettingsError` gains `problems`, each thing wrong on its own.
  *What a site must do:* nothing. The sentences for a missing key are unchanged.

- **`ports.ModelClient.stream` returns a `ports.ModelStream`,** which has `close()` in its type: a pipeline
  stops the model with `stream.close()` and needs no `getattr`. A generator is one, so the adapter and the
  scripted model are unchanged in what they do. *What a site must do:* nothing; a model adapter of a site's own
  must return something with `close()` (the contract test checks).

- **Events are one plain type everywhere, `events.Event` (`dict[str, Any]`).** `events.to_reader` returned a
  typed dictionary and the desk took plain ones, so a site's pipeline needed a cast. `to_reader`,
  `EvalSite.ask`, `checks.curl_event` and `checks.curl_events` now give and take `Event`, and `briefing.Event` is
  the same alias. `events.ReaderEvent` stays, as the description of the events every site sends.
  *What a site must do:* nothing; a `dict(...)` or `cast(...)` around these can go.
- **`testing.FixedRandom.token()` gives ids of the real shape:** as long as `secrets.token_urlsafe` gives for the
  bytes asked (`token000001` for 8 bytes; it was `token0001`). The sequence is still fixed and numbered.
  *What a site must do:* nothing unless one of its tests writes such an id out by hand.
- **The owner's `tidy` and the statistics page count in the singular** ("1 record", "1 day"; they said "1
  records", "1 days"). *What a site must do:* nothing.
- **`cli.RepliesWording` has a new line, `tidied`,** for what the right of reply's nightly housekeeping did (the
  counts `lapsed`, `contacts`, `emails` and `counts`). Like every line of that group it has no default.
  *What a site must do:* give the line when it adopts the commands (no site has yet).
- **`ops.send_offsite(..., keep=None)`:** how many copies stay off site is now the spec's `keep_offsite` (60 if
  the spec does not say, as before); `keep` still overrides it for one call. *What a site must do:* nothing.

### Added

- **One nightly command.** `stats_commands(..., also_tidy=[...])`: the statistics group's `tidy` runs the rest of
  a site's nightly housekeeping and prints what each step says. `cli.replies_tidy(replies, wording)` is the right
  of reply's step (`forget_old_emails`, `lapse_undecided`, `forget_old_counts`), so a site with no check token
  set still keeps the privacy notice's three months on a night nobody writes in. `replies_commands` adds the same
  as a command of its own, `tidy-replies` (`RepliesCommands.tidy`), for a site with no record of briefings.
- **A restore refuses a sister site's backup.** `StateDB(..., site=…)` marks a state database with its site's
  package name (`wts_kv`, key `site`), never writes over another site's mark and refuses to open a file that has
  one. `ops.BackupSpec(site=…)` makes `restore_backup` refuse a backup marked as another site's
  (`RestoreRefused.why == "other-site"`). Both are optional. A backup with no mark, as every backup made before
  this has none, is accepted as before.
- `eval_commands(max_cost_usd=…)` and `stats_commands(similarity=…)` each take a function as well as a number,
  called when the command runs, so the figure can come from the site's settings.
- `ops.BackupSpec.keep_offsite` (60 by default): how many of a site's copies stay in the off-site store. The
  backup command follows it.
- `wts_core.dates.long_date`: the family's date format ("12 November 2026") in a module that imports nothing
  else from the package, so a pipeline may use it. `replies.long_date` is the same function, still exported.
- `adapters.has_model(settings, site, env=None)`: whether the provider named in the settings has what it is
  called with, so a site imports no provider's module to ask.
- **`briefing.desk_parts(settings, db, messages, new_id=…, at_once_per_visitor=…, forget_over=…,
  keep_failures=…)`** builds everything a desk is made of from a site's settings (prices, limits, the spending
  record, caps, the per-minute limiter, briefings in progress, the answer cache, saved briefings, failures) on one
  clock and one source of chance, and returns them as `briefing.DeskParts`; `DeskParts.desk(config, log=…,
  hooks=…, group_of=…)` makes the desk. The parts are the site's to use in its pipeline, hooks and other routes.
  Building the pieces by hand still works.
- **The start-up check,** `briefing.desk_settings` (which `desk_parts` runs first): every limit, price, figure
  and message the briefing flow needs, with everything missing or wrong reported in one error that names the
  settings file and each key.
- `observe.briefing_config(log=…, model=…, parse_model=…, instructions=…, site_version=…, also=…)`: makes a
  site's `BriefingConfig`, works out its id (`config_id` of the parts, with the package's version added) and
  keeps the parts in `wts_configs` in the same call. `log=None`, said out loud, is for a site that has not turned
  the record of briefings on.

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
