# ADR 0005: The state database: the package's own tables, beside each site's

Status: accepted, 13 November 2026.

This record decides where the package keeps its data, how each site's earlier data was brought across, and how
deleted data is kept out of the file and its backups.

## Context

Every site keeps a small SQLite file (`data/state.sqlite` on Where MPs Stand, `data/state.db` on the others):
spending, the answer cache, saved briefings, readers' reports, statements, and tables of the site's own. It is
the one thing on the server that cannot be rebuilt from public sources.

Before the package, the four sites' tables for the same things had grown apart (different columns for the same
facts, and on one site rows inserted by position with no id). The package's stores need one shape. The data is
live, and if a deploy goes wrong the remedy is to deploy the previous version again, so the previous version must
still work on the database the new one leaves behind.

## Options

1. Teach the package every site's tables, through a mapping per store. No data moves, but the four shapes become
   permanent, and positional inserts cannot be described by a mapping at all.
2. Change each site's tables in place to one shape. The previous version's code then breaks, so a deploy cannot
   be undone without restoring last night's backup.
3. The package has its own tables beside the site's, and each site copies its rows across once.

## Decision

Option 3.

- Every table the package owns has a name starting `wts_`. The package never reads or writes a table without
  the prefix, and a site never writes one with it except through the package.
- `wts_schema` records which numbered migrations have run. Migrations only add (tables, columns with defaults,
  indexes), run in one transaction at start-up, and never drop or rename a column in the version that stops
  using it.
- Each site brings its own rows across once, with an import declared in its own repository (`state.Import`): a
  few `INSERT INTO wts_… SELECT … FROM <its old table>` statements, run in one transaction and recorded so they
  never run twice. The knowledge of a site's old tables stays in that site.
- Before the first import the package copies the database file to `state.pre-wts-core.<date>.db` beside it,
  readable by its owner only, and refuses to import if the copy fails. The nightly `tidy` deletes the copy once
  it is older than the site's backups.
- The import only reads the old tables. They stay in the file so that the move can be undone (the site's undo
  script writes them again from the package's tables) until a day the site states, at the latest the day the copy
  made before the import is deleted. Until then the site declares what keeps them within its privacy promises
  each night (`state.OldTables`: blank an address the package's row no longer has, delete what has passed its
  retention), and `StateDB.retire_old`, run by the nightly `tidy`, applies it and drops the tables on their day.
  A drop is held back while any import the site declares has not run, and `tidy` then fails so the owner hears.
- An import declares, for each old table, the column that holds when a row was written (`Import.written_at`). If
  the old code writes to its old tables after the import, the site refuses to start rather than lose those rows
  ([`UPGRADING.md`](../UPGRADING.md#going-back-to-the-old-code)).
- Connections are short-lived, with a 30-second busy timeout and rows read by name. The journal mode is left as
  each site's file has it (Where MPs Stand's uses write-ahead logging).
- Saved data keeps its meaning: token counts are stored as the sites stored them, and saved and cached events are
  copied byte for byte (ADR 0003).
- What is deleted is gone from the file. SQLite does not wipe what it deletes, and every backup copies the file's
  unused space; a review of one site found deleted senders' addresses in a backup made 125 days later. So every
  connection sets `PRAGMA secure_delete = ON`, and the nightly `tidy` ends with `StateDB.compact()` (`VACUUM`,
  then `wal_checkpoint(TRUNCATE)`) for what that cannot reach: freed pages left by other connections, and old
  pages in a write-ahead log. A checkpoint blocked by another connection makes `compact` return `False`; a
  second such night in a row ends `tidy` with status 1. `tests/test_state_deleted.py` searches the bytes of the
  file, its log and a backup for each kind of deleted value.

Each site's import was tested against a database built by that site's own code, with rows of every kind: every
row arrives, spending, cached answers and saved briefings read the same through the package as through the old
code, and the old tables are unchanged by the import.

## Consequences

- Until its old tables are dropped, a site's file holds both sets of tables. The files are megabytes.
- The spending caps count from `wts_spending`. Because the month's rows are imported, a cap that was 80% used
  before the move is 80% used after it.
- The package never reads a site's own table, so a site's tables can change without a package release, and the
  other way round.
- Overwriting what is deleted costs little. Measured with `scripts/measure_secure_delete.py` on 5,000 spending
  rows, the only clear cost is on deleting large rows: the nightly purge of 20 cached answers takes about 2
  milliseconds in place of 1. The file is the same size either way. `compact` needs free space of about the
  file's size, or twice that with a write-ahead log.
