# ADR 0005: The state database: the package's own tables, beside each site's

Status: proposed, for the owner's review. This one touches live data, so it is on the list to check first.
13 November 2026.

## Context

Every site keeps a small SQLite file (`data/state.sqlite` on Where MPs Stand, `data/state.db` on the others): spending,
the answer cache, saved briefings, readers' reports, statements, and each site's own tables (Where MPs Stand's
accounts, visit counts and update history, for example). It is the one thing on the server that can't be rebuilt
from public sources, and it is backed up nightly.

The four sites' tables for the *same* things have grown apart:

| Table | Where MPs Stand | Where Countries Stand | Where Councils Stand |
|---|---|---|---|
| `usage` | `id`, `user_id`, `visitor`, `at`, … | `id`, `visitor`, `at`, … (no `user_id`) | no `id`; an extra `day` column that must be filled; rows inserted by position |
| `answer_cache` | `key`, `created_at`, `events` | the same | `key`, `at`, `events` |
| `briefings` | `created_at`, `settings`, `records_up_to`, `model` | `at`, `options` | `at`, `options` |
| `reports` | `status`, `resolution`, `public_note`, `briefing_id`, `visitor` | `closed_at` only | `closed_at` only |
| `statements` | `item_path`, `person`, `published_at`, `closed_at`, `checked` | `page`, `country`, `shown_on`, `ended_at`, `log` | `page`, `council`, `shown_on`, `ended_at`, `log` |

The package's stores need one shape. The data is live, the owner deploys by merging and running `update.sh`, and
if a deploy goes wrong the remedy is to deploy the previous version again: so **the previous version's code must
still work on the database the new version leaves behind.**

## Options

1. **Teach the package every site's tables.** Each store takes a description of the table and columns it should use.
   No data moves. But the four shapes become permanent, every query is written against a mapping, and Where
   Councils Stand's positional inserts and missing ids can't be described by a mapping at all.
2. **Change each site's tables in place to one shape** (rename and add columns). One shape afterwards, but the
   previous version's code breaks on the changed tables, so a deploy can't be undone without restoring last night's
   backup, which loses any report, statement or saved briefing made since.
3. **The package has its own tables, with their own names, beside the site's (recommended).** On first start with
   the package, each site copies its rows across once. Its old tables are left exactly as they were.

## Decision: option 3

- **Every table the package owns has a name starting `wts_`** (`wts_spending`, `wts_answer_cache`, `wts_briefings`,
  `wts_briefing_log`, `wts_reports`, `wts_statements`, `wts_hidden`, `wts_corrections`, `wts_kv`, `wts_schema`).
  Everything else in the file is the site's. The prefix is the ownership line: the package never reads or writes a
  table without it, and a site never writes one with it except through the package.
- **The package's tables are versioned.** `wts_schema` records which numbered migrations have run. Migrations only
  add (tables, columns with defaults, indexes), run inside one transaction at start-up, and are idempotent. A
  release never drops or renames a column in the same version that stops using it.
- **Each site brings its own rows across once,** with an *import* it declares in its own repository (a short list of
  `INSERT INTO wts_… SELECT … FROM <its old table>` statements, run by the package's migration runner in the same
  transaction, and recorded in `wts_schema` so it never runs twice). The knowledge of a site's old shape stays in
  that site; the package holds none of it.
- **The old tables are not touched** in the release that adopts the package. If that deploy is undone, the previous
  code finds its tables as it left them. Anything written in between (a report, a statement, a saved briefing) is in
  the `wts_` tables of the same file, and `docs/MIGRATION.md` gives the one statement per table that copies it back.
- **The old tables are dropped one release later,** by a migration the site turns on once the owner is content.
- **Before the first import, the package copies the database file** to `state.pre-wts-core.<date>` beside it (the
  files are small: megabytes), and the import refuses to run if the copy fails.
- **Connections:** one helper for every store: a short-lived connection per operation, a 30-second busy timeout,
  rows by name. The journal mode is left as each site's file has it today (Where MPs Stand's web app and update job
  are separate processes writing to the same file, so its file uses write-ahead logging). Every site's backup
  already copies the database with SQLite's own online backup, which is safe in either mode.
- **Saved data keeps its meaning.** Token counts in `wts_spending` are stored as they are today (input including
  cache writes), and saved and cached events are copied byte for byte (ADR 0003).

## Parity

For each site, the import is tested against a fixture database built by that site's *current* code (its real
`SCHEMA`, with rows of every kind, including a withdrawn briefing, a closed report, and statements in every
status). The tests assert that every row arrives, that today's and this month's spending, each visitor's count for
the day, every cached answer and every saved briefing read the same through the package as through the old code,
and that the old tables are byte-identical afterwards.

## Consequences

- For one release each site's state file holds both sets of tables, so it is roughly twice its usual size. These
  files are megabytes; the backup grows by the same.
- The spending caps count from `wts_spending` after the switch. Because the month's rows are imported, a cap that
  was 80% used before the deploy is 80% used after it.
- The package can never "just read" a site's table. That is the point: a site's tables can change without a
  package release, and the other way round.
