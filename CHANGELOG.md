# Changelog

What changed in each version, and what a site must do about it. Versions follow semantic versioning: while the
version is 0.x a minor version may change the public interface ([ADR 0007](docs/adr/0007-versioning.md)). The
`api:` line under each version is the fingerprint of the public interface in `docs/api-snapshot.txt`;
`tests/test_public_api.py` fails if the interface changes without a new entry here.

## 0.3.1 (17 November 2026)

Documentation, comments and the example site's wording only. No change to the public interface or to behaviour,
and nothing for a site to do beyond raising its pin ([`docs/UPGRADING.md`](docs/UPGRADING.md)).

api: 30eea86130b4

## 0.3.0 (16 November 2026)

Changes asked for by the sites' adoptions, tests proving that the model, the embedder and the provider can each be
swapped, and live experiments. Every site moved onto the package at this version.

api: 30eea86130b4

### Changed

- The nightly `tidy` runs in a fixed order: the package's own deletions, the site's `also_tidy` steps, the old
  tables (`StateDB.retire_old`), and last `StateDB.compact`, which writes the file out afresh. A second night in a
  row on which the file could not be written afresh ends the command with status 1. `stats_commands` takes
  `cache_hours`.
- The shared `backup` command forgets earlier days' visitor codes, accounts and secrets before it copies the
  database.
- After its day is over, a spending row keeps its date without a time, no visitor code and no account. Each
  account's calls, cost and visitors are kept by calendar month in `wts_account_months`. The record of each
  briefing keeps only the hour a question was asked ([ADR 0012](docs/adr/0012-briefing-record-and-statistics.md)).
- `replies_commands(changed=…)` passes the kind of change as a second argument (one of `cli.CHANGES`). A callback
  with one argument still works in 0.3.x, with a `DeprecationWarning`.
- An older command name kept through `RepliesCommands.also` prints its replacement on standard error
  (`RepliesWording.old_name`, or `also_silent=True` to keep it quiet).
- A site gives `RepliesWording.lapsing`, or sets `RepliesCommands(would_lapse=None)`.
- `Replies.corrections()` returns the whole log unless a limit is given.
- A model name takes the price table of the longest name it begins with.
- `Hooks.on_cached` may return `None` to refuse a cached answer, which is then written afresh.
- `ModelClient.structured` raises `ports.NoStructuredAnswer`, carrying `usage` and `stop_reason`, whenever an
  answered call cannot be read into the schema, so that the call is still recorded and counted.
- `FastEmbedEmbedder.id` covers only the named model's own files. An index stamped by 0.2.x is accepted once
  under its earlier id and stamped again (until 0.4.0).
- A new briefing id never begins with `-`.

### Added

- `PRAGMA secure_delete = ON` on every connection, and `StateDB.compact()`, so that deleted data does not survive
  in the file or in backups ([ADR 0005](docs/adr/0005-state-database.md)).
- `Import(written_at=…)` and `state.StateError`, which stop a site whose old code has written to its old tables
  since the import ([`docs/UPGRADING.md`](docs/UPGRADING.md#going-back-to-the-old-code)).
- `OldTables(drop_after_days=…)`, `StateDB.old_tables_due()` and `BackupSpec(required_tables_until=…)`.
- The `would-lapse` and `propose-questions` commands, and `replies.lapse_cutoff`, `has_lapsed` and `lapses_on`.
- `Replies(hidden_with=…)`, `ReplyMessages.item_hidden` and `ReplyRules(form_max=…)`.
- Live experiments (`briefing.experiment_switch`, `eval run --arm`, `stats_commands(experiment=…)`).
- `eval_commands(spending=…)`, so that evaluation runs count towards the caps.
- `cli.latest_week_figures(db)`, and `check_route(weekly=…, experiment=…)`.
- LanceDB helpers for a site that builds its own table, and `adapters.skeleton_provider`, a template for a
  second model provider.
- `testing.assert_briefings_tied_to_no_one` and `testing.split_by_account_totals`.
- [`docs/IMPROVING.md`](docs/IMPROVING.md), and the scripts `measure_secure_delete.py` and
  `measure_account_split.py`.

## 0.2.1 (15 November 2026)

Fixes found while reviewing the first sites' adoptions, mostly to what is kept about readers and senders.

api: c312225c58f5

- The record of each briefing keeps the question only where the site already keeps it elsewhere.
- `Replies.corrections()` returns only what is fit to publish: a report's entry has `date`, `kind` and `note`.
- `Replies(hideable=…)` resolves what the owner typed to the one address an item is filed under.
- `state.OldTables` and `StateDB.retire_old()` keep a site's old tables within its promises and drop them on a
  stated day.
- A server's local settings file is merged two levels deep (`Settings.local_path`, `Settings.files`).
- `Replies.would_lapse()`, `RepliesWording.nothing_waiting`, and `SqliteAnswerCache.delete` and
  `delete_briefing`.

## 0.2.0 (14 November 2026)

Rough edges found by the example site and the first adoption.

api: b75cd9950cac

- `briefing.desk_parts(...)` builds every part of the desk from a site's settings, and `observe.briefing_config`
  makes the `ports.BriefingConfig` the desk takes.
- `ports.ModelClient.stream` returns a `ports.ModelStream`, which has `close()`.
- `stats_commands(also_tidy=…)` for one nightly command, and the right of reply's `tidy-replies`.
- A restore refuses a sister site's backup (`StateDB(site=…)`, `BackupSpec(site=…)`).

## 0.1.0 (13 November 2026)

The first release: the interfaces and event format, settings, the state database, limits and caps, the checks on
briefings, the briefing desk, reports and the right of reply, the record of each briefing and its statistics, the
evaluation harness, backup, the adapters, the shared commands, the testing helpers, the example site and the
shared CI workflows.

api: 86cb9d353511
