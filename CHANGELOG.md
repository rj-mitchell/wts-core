# Changelog

Kept by hand. Versions follow semantic versioning; while the version is 0.x, a minor version may change the
interface, and each such change is listed under "Changed" with what a site must do (docs/adr/0007-versioning.md).
The line `api: <hash>` under a version is the fingerprint of the public interface at that version
(`docs/api-snapshot.txt`); `tests/test_public_api.py` fails when the interface changes without a new one here.

## 0.2.0 (14 November 2026)

The rough edges the example site found, removed before the three AI sites adopt the package, and what the first
site to adopt (Where Landlords Stand, on 0.1.0) found. No site uses the briefing desk yet, so its interface could
still change (ADR 0007); the bytes a reader receives through it, and the rows written, have not.
`docs/UPGRADING.md` says how a site moves to a new version.

api: b75cd9950cac

### Changed

Each entry says what a site must do. No site has adopted the briefing desk, so there the answer is nothing yet:
the change is met when the site adopts. Where Landlords Stand has adopted settings, the state database, reports
and statements, backups and the shared commands, and the entries that touch those say what it must do.

- **`BriefingDesk` takes `config: ports.BriefingConfig`, and no `parse_model`.** The configuration was a mapping
  with string keys, where a misspelt key was recorded as empty; it is now a frozen dataclass with a field for each
  (`config_id`, `model`, `parse_model`, `instructions`, `package_version`, `site_version`, `experiment`, `arm`,
  and `settings`, the parts behind the id). The model a question's reading is priced as is its `parse_model`.
  *What a site must do:* nothing yet. At adoption, make the configuration with `observe.briefing_config` and pass
  it as `config`.
- **`ports.ModelClient.stream` returns a `ports.ModelStream`,** which has `close()` in its type: a pipeline
  stops the model with `stream.close()` and needs no `getattr`. A generator is one, so the adapter and the
  scripted model do what they did. *What a site must do:* nothing; a model adapter of a site's own must return
  something with `close()` (the contract test checks).
- **Events are one plain type everywhere, `events.Event` (`dict[str, Any]`).** `events.to_reader` returned a
  typed dictionary and the desk took plain ones, so a site's pipeline needed a cast. `to_reader`,
  `EvalSite.ask`, `checks.curl_event` and `checks.curl_events` now give and take `Event`, and `briefing.Event` is
  the same alias. `events.ReaderEvent` stays, as the description of the events every site sends.
  *What a site must do:* nothing; a `dict(...)` or `cast(...)` around these can go.
- **`Replies.publish` looks at the item again.** A statement is not published beside an item that is no longer
  shown (the site's `Items.shown`, asked of the stored item with whom the statement now speaks for) or that is
  hidden while a concern is decided: `NotDone`, in words for the owner. Where Landlords Stand's own command
  refused a landlord whose page had gone, and lost that on 0.1.0. *What a site must do:* nothing, if its
  `Items.shown` answers for an `Item` made from a stored address (`address`, `about`, `part`), as it already
  must for `submit`.
- **`cli.RepliesWording` asks only for the lines a site's commands print.** Every line but `not_done`, `refused`
  and `errors_to_stderr` may be left out; one missing for a command the site has stops `replies_commands`, naming
  it. There is one new line, `tidied`, for what the right of reply's nightly housekeeping did (the counts
  `lapsed`, `contacts`, `emails` and `counts`), needed by `tidy-replies` and by `replies_tidy`.
  *What a site must do:* nothing; it may delete the lines it wrote for commands it does not have, and it gives
  `tidied` or leaves the new command out (`RepliesCommands(tidy=None)`).
- **`replies_commands(changed=…)` is also called after `hide`, `unhide` and `reports close`,** with the hidden
  item (`item`, `note`), the item shown again (`item`) and the closed report. It was called only after a change
  to a statement. *What a site must do:* a `changed` that reads a statement's fields (`row["status"]`) must
  allow for the other rows; one that only writes its pages again needs no change.
- **`testing.assert_no_reader_data(state, log_lines, *, address, question=None, visitor=None)`:** `question` may
  be left out by a site with no questions. *What a site must do:* nothing (both were, and are, given by name).
- **`load_settings` makes the section of every `EnvSetting`,** empty when nothing fills it, as each site's own
  loader did. *What a site must do:* nothing; a `raw.setdefault("site", {})` after loading can go.
- **`Limits.from_settings` and `PriceTable.from_settings` say everything that is wrong at once,** and name the
  key of a figure that is not a number (`[usage] daily_spend_cap_usd is not a number: 'lots'`). Both take
  `file=`, the settings file to name in the error. `SettingsError` gains `problems`, each thing wrong on its own.
  *What a site must do:* nothing. The sentences for a missing key are unchanged.
- **`ops.send_offsite(..., keep=None)`:** how many copies stay off site is now the spec's `keep_offsite` (60 if
  the spec does not say, as before); `keep` still overrides it for one call. *What a site must do:* nothing to
  keep 60. A test that read the figure from the function's signature reads `BackupSpec.keep_offsite` instead
  (Where Landlords Stand's test of its privacy page does).
- **`testing.FixedRandom.token()` gives ids of the real shape:** as long as `secrets.token_urlsafe` gives for the
  bytes asked (`token000001` for 8 bytes; it was `token0001`). The sequence is still fixed and numbered.
  *What a site must do:* nothing, unless one of its tests writes such an id out by hand.
- **The owner's `tidy` and the statistics page count in the singular** ("1 record", "1 day"; they said "1
  records", "1 days"). *What a site must do:* nothing.

### Added

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
- `adapters.has_model(settings, site, env=None)`: whether the provider named in the settings has what it is
  called with, so a site imports no provider's module to ask.
- **One nightly command.** `stats_commands(..., also_tidy=[...])`: the statistics group's `tidy` runs the rest of
  a site's nightly housekeeping and prints what each step says. `cli.replies_tidy(replies, wording)` is the right
  of reply's step (`forget_old_emails`, `lapse_undecided`, `forget_old_counts`), so a site with no check token
  set still keeps the privacy notice's three months on a night nobody writes in. `replies_commands` adds the same
  as a command of its own, `tidy-replies` (`RepliesCommands.tidy`), for a site with no record of briefings.
- `eval_commands(max_cost_usd=…)` and `stats_commands(similarity=…)` each take a function as well as a number,
  called when the command runs, so the figure can come from the site's settings.
- `ops_commands`, `stats_commands` and `eval_commands` take `clock` as a clock or as a function that gives one
  when a command runs, so a site's test can fix a backup's name through the command.
- `replies_commands(groups={"statements": its_group})`: a group of the site's own for a group of the commands to
  join, which keeps its own callback. A site that must keep an older, option-shaped command working
  (`statements --publish 3`) does so with one call.
- `state.Import`: a statement may be a function, given the connection when the import runs and returning the SQL
  to run, for an old table that is not the same in every copy of the database. `state.columns(con, table)` reads
  a table's column names.
- **The shared `python.yml` workflow turns Typer's colour off** (`_TYPER_FORCE_DISABLE_TERMINAL`, `NO_COLOR`) for
  the lint, type-check and test steps: on GitHub Actions the colour codes split an option's name in `--help`, so a
  site's test that reads a command's help passed locally and failed in CI.
- `ops.BackupSpec.keep_offsite` (60 by default): how many of a site's copies stay in the off-site store. The
  backup command follows it.
- **A restore refuses a sister site's backup.** `StateDB(..., site=…)` marks a state database with its site's
  package name (`wts_kv`, key `site`), never writes over another site's mark and refuses to open a file that has
  one. `ops.BackupSpec(site=…)` makes `restore_backup` refuse a backup marked as another site's
  (`RestoreRefused.why == "other-site"`). Both are optional. A backup with no mark, as every backup made before
  this has none, is accepted as before.
- `wts_core.dates.long_date`: the family's date format ("12 November 2026") in a module that imports nothing
  else from the package, so a pipeline may use it. `replies.long_date` is the same function, still exported.
- `docs/UPGRADING.md`: how a site moves to a new version, how a fix reaches the sites, how a release is made.

### Tried against the first site to adopt

Where Landlords Stand's own tests (its adoption branch, on 0.1.0) were run against this version, in a copy, with
nothing changed in the site but what the entries above ask. They pass with three changes: the `tidy` command
left out or its line given (`RepliesCommands(tidy=None)`), the figure for off-site copies read from
`BackupSpec.keep_offsite`, and the package's version where a test writes it out.

### Corrected in the guides, from the first adoption

- `docs/AS-BUILT.md`: a site's `BackupSpec` names tables only that site has and that stay when the old shared
  tables are dropped (Where Landlords Stand: `missed`, `approvals`), not `reports`.
- `docs/MIGRATION.md`: Where Landlords Stand keeps its `load_toml`; the package has nothing in its place.
- `docs/NEW-SITE.md`: Dependabot must ignore `rj-mitchell/wts-core*`, so the workflows' tag cannot drift from the
  wheel's version; a test that reads a command's help sets the two colour variables in its `conftest.py`.
- `docs/adr/0006`: the image build must reach `objects.githubusercontent.com`; what was verified on 13 November
  2026.
- `docs/EXTENDING.md`: a form with a separate field for the part of a page passes `submit` an `Item`; a site with
  a "not found" page of its own adds the check route only when a token is set.

### The example site

Built on all of the above: its desk from `desk_parts`, its configuration from `briefing_config`, one nightly
command (`parks tidy`; its own `nightly` is gone), its state database marked as its own, and the limit on an
evaluation run and the similarity for themes moved from its code into `config/settings.toml`.

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
