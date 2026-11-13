# Moving each site onto wts-core

13 November 2026. Part of the design for review. For each shared module: what replaces it in each site, any
difference in behaviour, and how sameness will be proved. Every fact about today's copies comes from the studies in
[`study/`](study/), which give the file and line.

**How to read the "difference" columns.** *None* means the site behaves exactly as before. Otherwise the difference
is marked **R** (a reader or a named person could notice), **O** (only the owner could: a command, a message in a
terminal, a file) or **N** (nobody: internal). Differences marked *phase 1* are fixes ported before the package
exists; the adoption itself then changes nothing.

**The order.** Where Landlords Stand (base only), Where Councils Stand, Where Countries Stand, Where MPs Stand.

## 1. Module by module

### 1.1 Settings (`wts_core.settings`)

Replaces each site's `config.py` loader. Each site keeps a `Settings` subclass holding its own accessors.

| | MPs | Countries | Councils | Landlords |
|---|---|---|---|---|
| Deleted | `load_settings`, `save_local_settings`, `get_settings`, `_resolve` | `load_settings`, `get_settings`, `_resolve` | the same | the same, and `load_toml` |
| Kept in the site | its accessors (`parlparse_dir`, `regions`, `record_dirs`…) | its accessors (`born_digital_from`…) | its accessors (`modgov`…) | `fetch`, `raw_dir`, `staging_dir`, and its two environment settings (`LANDLORDS_SITE_URL`, `LANDLORDS_LAUNCHED`) as a declared list |
| Difference | None | None | None | None. The local layer and keyword overrides become available; nothing uses them |

- The loader is the same statements in the three AI sites today, so the package's is theirs: `settings.toml`, then
  `<data>/settings.local.toml` merged one level deep, then keyword overrides; `<PREFIX>_CONFIG` and
  `<PREFIX>_DATA_DIR`. The site passes its prefix and its repository root (the package can't find the root from
  its own path, as each `config.py` does now).
- `save_local_settings` (only Where MPs Stand has it) moves as it is, writing the same file byte for byte.
- **New, at start-up:** every model named in settings must have a price; every message and limit the package needs
  must be present. A missing one stops the site with the key's name. Prices keep their place in `[usage]` and
  `[usage.models."…"]` (a `[pricing]` table is read too, and preferred if present), so no server's local settings
  break.
- Each site's code fallbacks (a limit used when a key is absent) are written into its `settings.toml` at adoption
  with today's values, because the package has none. Where MPs Stand's three "at once" keys, absent from its file
  today, are written in during phase 1.
- **Parity:** a sample configuration per site (its real `settings.toml`, a local file, overrides, each environment
  variable) resolved by the old loader and the new; the two `raw` dictionaries and every accessor's value compared.

### 1.2 The state database (`wts_core.state`)

[ADR 0005](adr/0005-state-database.md). The package's tables are new, named `wts_…`, in the same file. Each site
declares one import, run once:

| The package's table | From MPs | From Countries | From Councils | From Landlords |
|---|---|---|---|---|
| `wts_kv` | `kv` (the day's salt only) | the same | the same | its own key-value rows, if any |
| `wts_spending` | `usage`, with `user_id` | `usage` | `usage` (its `day` column dropped; a row id given) and `questions` (the day's counts) | none |
| `wts_answer_cache` | `answer_cache` | `answer_cache` | `answer_cache` (`at` → `created_at`) | none |
| `wts_briefings` | `briefings` (`created_at`, `settings`, `records_up_to`, `model`) | `briefings` (`at`, `options`) | `briefings` (`at`, `options`) | none |
| `wts_failures` | `failures` | `failures` | none (it has no such table) | none |
| `wts_reports` | `reports` | `reports` | `reports` | its reports table |
| `wts_statements`, `wts_statement_log` | `statements` (no log: one "imported" entry each) | `statements` and its JSON `log` | the same | `statements` and `statement_log` |

- The site's own tables (Where MPs Stand's accounts, sessions, update history, visit and question counts, feedback,
  topic versions; Where Landlords Stand's missed searches and approval links) stay the site's and are not touched.
- A saved briefing keeps its site's shape: Where MPs Stand stores no `text` event and serves a saved briefing as one
  object; the others store and serve events. `wts_briefings.events` holds each site's JSON as it is, and `extra`
  holds the columns only one site has.
- **Difference: none for readers.** **O:** the state file roughly doubles for one release; a file
  `state.pre-wts-core.<date>` appears beside it once.
- **Undoing a deploy:** the previous code finds its tables untouched. To carry back what was written in between,
  one statement per table, for example
  `INSERT INTO reports (at, kind, page, message, contact) SELECT at, kind, page, message, contact FROM wts_reports WHERE at > '<time of the deploy>'`.
  Each site's adoption pull request carries its exact statements, tested.
- **Parity:** a database built by the site's current code with rows of every kind; after the import: every row
  present; today's and the month's spending, each visitor's count today, every cached answer and saved briefing
  read the same through the package as through the old code; the old tables byte-identical.
- **Checked, and not a worry:** Where Councils Stand inserts into `usage` by position, so a table made before
  `cache_write_tokens` was added would have failed every insert. The repository's history shows the column was
  there in the file's first commit (25 October 2026), before the site was first deployed, and phase 1 replaces the
  positional insert with named columns.

### 1.3 Limits, cost and caps (`wts_core.usage`)

| Part | What every site gets | Kept each site's own (passed in) | Difference |
|---|---|---|---|
| Rate limiter | Where MPs Stand's: a lock, idle keys forgotten | requests a minute (20; Landlords 10); the size at which idle keys are forgotten (50,000; Councils 10,000) | Landlords: **N** (it gains the lock and the forgetting, in phase 1). Others: none |
| Visitor code | IPv4 address or IPv6 /64, a salt that changes daily and is deleted | how the site reads the address behind the proxy (see the note below) | None |
| Token counts and cost | one `Usage` with four unambiguous counts; the same formula, rounded to six places | prices and the write multiplier, from settings | None. The same figure to the last decimal, proved on recorded usage in both of today's forms |
| Unknown model | stops the site at start-up | | **O:** today it is priced silently at the site's base prices. Each site's settings get an explicit entry for every model they name |
| Spending record | one row per model call | MPs' `user_id` | None |
| Caps | the visitor's daily limit, today's spending, the month's; `>=` as today; the estimate for briefings in progress | every limit; every message (MPs and Countries say "budget … used up", Councils "limit … keeps its costs down"; MPs alone has signed-in users and their message) | None |
| In progress | Where Countries Stand's: a refused visitor leaves nothing behind | per visitor (2), in all (8), the estimate (MPs and Councils $0.15, Countries $0.10); both messages (the same words on all three today) | None (phase 1 ports the fix) |
| Answer cache | key = SHA-256 of the site's parts; expiry; old rows deleted on each store | the parts (each site's differ: `scope`, `compare`, `follows` on MPs; the data stamp; `instructions` or `v`); the digest's length (64; Councils 32); hours (168); whether follow-ups are cached | None. Keys are computed exactly as today, so the week's cache survives adoption |
| Failures noted | the newest 500, and none older than 90 days | | MPs: **N** (it gains the 90 days). Councils: see 1.9 |

**A note for the owner on the visitor's address.** Where Countries Stand and Where Landlords Stand take the first
entry of `X-Forwarded-For`; Where MPs Stand and Where Councils Stand leave it to the web server's proxy setting.
Both are right only if the front door replaces that header rather than adding to it. If a visitor can set it, they
can dodge every limit. The front door's files are in Where MPs Stand's `deploy/` and weren't part of the study. The
package keeps each site's way and offers one function for both; which is right is a question about the Caddy
configuration, worth ten minutes before phase 4.

### 1.4 The checks (`wts_core.checks`)

| Part | From | Each site's own | Difference |
|---|---|---|---|
| The citation verifier | Where MPs Stand's copy, now the fullest (it has everything Where Countries Stand's has, and the lead-in handling on recheck) | honorifics whose full stop ends no sentence (Councils adds `Cllr`, `Rev`, `Revd`, `Hon`); the "no records" opening words; the site's `Source` type, through a two-field interface (`n`, `blocks`) | None after phase 1 |
| Recheck of saved and cached briefings | the same, with the phase 1 fixes (never clears a flag for shortness, nor takes a whole line or a closed sentence for a lead-in), and one thing more: see below | | **R, stricter, phase 1:** a flag that used to clear when a briefing was shown again can now stay |
| The "note about the evidence" rule | see below | | see below |
| Quotation check | identical in all three | | None |
| Loaded words | the mechanism, identical in all three | each site's whole word list, as today (Countries' "regime", "the West"…; Councils' 22 more) | None |
| British spelling | identical in all three | | None |
| Curly quotes | Where Countries Stand's `typography.py`, offered to all | on or off (only Countries turns it on) | None |

**The one rule that differs in strength.** Where MPs Stand and Where Countries Stand treat any sentence containing
"is/are/was/were (not) supplied/retrieved" as a note about the evidence. That clears ordinary claims ("Gas was
supplied to two million homes…"). Where Councils Stand lacks that alternative and is the strict copy; the cost there
is false flags on real notes ("The votes … were not supplied…"). The package's rule will be the strict one plus a
narrow form (negated, and about records, votes, lists or data), a pattern each site can extend. **This changes what
is flagged on Where MPs Stand and Where Countries Stand (R, stricter) and removes some false flags on Where Councils
Stand (R).** It is therefore made as its own change at each site's adoption, with replay fixtures and the site's
evaluation run before and after, and is not folded silently into the move.

**Judging a briefing again, done properly.** A saved briefing keeps its segments but not the blocks the model wrote,
so judging it again can never repeat exactly what the verifier did the first time. Phase 1 made the recheck strict
enough that it clears a flag in 17 of 150,000 fuzzed briefings (it was 8,163). The package removes the question:
every answer is stamped with the version of the checking rules that wrote it (a new, optional key, `rules`; the
event format's first version allows unknown keys), and `Verifier.recheck` leaves alone any answer written under the
current rules. Only a briefing saved under older rules is judged again, which is what the recheck was for. A
property test in the package's CI asserts that rechecking anything today's verifier has just written changes
nothing. Until a site adopts the package, Where MPs Stand does not recheck cached answers at all (as on its `main`),
and the other two do, as they did.

- **Parity:** every test the three sites have for these modules (the study lists 60 or so, and which cases only
  one site covers) runs against the package with each site's inputs; golden reports for a set of recorded blocks
  and sources per site.

### 1.5 The model client (`wts_core.adapters.anthropic`)

| | All three AI sites |
|---|---|
| Deleted | `rag/answer.py`'s `make_client`, `api_key`, `cached_system`, `usage_dict`, `_block_to_dict`, the streaming loop and the fallback retry; the `messages.parse` call in each `query_parse.py` |
| Kept in the site | its instructions, its `user_instruction`, how it turns a source into a document, its default `group_by`, its models, efforts and `max_tokens` (settings) |
| Same as today | the key's three sources (`<PREFIX>_ANTHROPIC_API_KEY`, `ANTHROPIC_API_KEY`, the key file); never following an inherited `ANTHROPIC_BASE_URL`; 300 seconds without a byte, 10 to connect, two retries; the instructions sent as one cacheable block; the fallback beta tried and dropped if refused |
| Difference | **N:** that the fallback beta was refused is remembered for the life of the process (today each request finds out again). A refusal by the model is an error everywhere (phase 1). **O:** prompt caching becomes a setting (`[answer] cache_instructions`, on as today; an extended lifetime where offered), so phase 6 can measure it |

- **Parity:** recorded streams from the SDK (made once, with a working key, from each site's evaluation questions)
  replayed through the old code and the adapter; the events and the final blocks, model, stop reason and usage
  compared. Contract suite `ModelClientContract`.

### 1.6 The embedder and the index (`wts_core.adapters.fastembed`, `.lancedb`)

- **The embedder** is identical in all three and moves as it is, with the dependency-free hashing embedder used
  by tests and Where MPs Stand's sample data.
- **The index base** is the twenty or so methods the three `index/lance.py` files share: open or create, replace by
  key, add vectors, build the word and vector indexes, tidy (with the one-hour clean-up), search by words and by
  meaning. Each site keeps its schema, its filters and its two or three methods of its own.
- **New:** the index records its embedder's name, dimension, weights hash and schema version beside it, and every
  writer and reader checks them. Today only Where MPs Stand records the model, and only two of its commands check;
  its own twice-daily update, and the other two sites, would never notice a changed model.
- **Difference: none for readers.** **O:** a changed embedding model stops search by meaning (the site falls back
  to search by words, as it does when no index exists) and says so in the update report, until
  `<site> index --re-embed`.
- **Parity:** the same vectors for the same texts (fastembed's version is the one all three lock); the same top
  results for each site's evaluation questions on its fixture index.

### 1.7 Balanced selection

The study found `rank/evidence.py` only 0.30 to 0.46 alike, but three small pieces are the same lines everywhere:
the round-robin across groups, the blend of relevance scores, and the recency factor. Those three functions
(about 45 lines) move to `wts_core.checks.balance`, taking the grouping function and the caps as arguments.
Everything else in ranking stays with each site. **Difference: none.** Parity: each site's ranking tests, and the
same selected sources for its evaluation questions.

### 1.8 The briefing flow and the streamer (`wts_core.briefing`)

[ADR 0009](adr/0009-briefing-desk.md). Each site's `ask` route keeps its request body and builds an `Ask`; the
hundred lines beneath it are deleted.

| What a reader could notice if it were got wrong | MPs | Countries | Councils |
|---|---|---|---|
| Token counts in the `plan` and `final` events | sent | sent | not sent |
| The error text when a briefing fails | "…The sources found are shown above…" | the same | "…Any sources found are shown above…" |
| Who reads the question when a limit has been reached, or only sources were asked for | the model, while the budget lasts | the free rules | the free rules over a limit; the model for "sources only" (with the caps checked, from phase 1) |
| Follow-ups cached | yes | no | yes |
| A cached answer's flags re-judged on replay | no: replayed as stored (the phase 1 port was withdrawn, as it would have weakened flags; see 1.6). At adoption its `on_cached` may recheck answers written under older rules, which changes bytes for those | yes, with curly quotes | yes |
| Fields only this site adds to `final` | `interests`, `briefing_key`, `support_reminder` (this reader only), `prepared_at`, `records_up_to` | none | none |
| A cached answer with no address yet is given one | yes | no | no |

Each row is a hook or a field of `Messages` in that site, and a case in its golden transcripts.

- **Difference: none,** with one addition on all three: each question writes one line to the briefing log
  (section 1.10).
- The streamer is the same code in all three today and moves as it is.
- **Parity:** golden transcripts, byte for byte, and the rows written, for: a fresh question; the same again (from
  the cache); a follow-up; sources only; the visitor's limit, the daily cap and the monthly cap each reached; one
  place too many for the visitor and for the site; a second check of the caps failing; the model failing
  mid-stream; the model refusing; the reader leaving during writing; no records; no API key.

### 1.9 Reports and the right of reply (`wts_core.replies`)

[ADR 0008](adr/0008-reports-and-statements.md). Each site deletes its store and rules and keeps its routes, pages,
`Items` and wording.

| Difference at adoption | MPs | Countries | Councils | Landlords |
|---|---|---|---|---|
| A public corrections log | has one | gains public notes on closed reports (**R**) | **gains the log (R, the brief's listed change)** | its hand-kept CSV is replaced by the log (**R**) |
| Any item can be hidden with a note while a concern is decided | **gains (R, listed)** | **gains** | **gains** | **gains** |
| A statement the site takes down is "removed" | was "declined" (**O**) | was "withdrawn" (**O**) | the same | the same |
| A log of every action; how the sender was confirmed is required | gains the log (**O**) | gains the required note (**O**, phase 1) | the same | has both |
| The item must exist and still be shown | from phase 1 | has it | a withdrawn briefing refused (phase 1) | has it |
| Too long: refused, not cut | friendlier words than today's validation error (**R**) | has it | has it | **refused (R, phase 1)** |
| Trap field and a daily limit per visitor | has both | **gains both (R: a sixth statement or an eleventh report in a day is refused)** | **the same** | gains the limit; trap on reports from phase 1 |
| Name and role can't be blank | has it | has it | phase 1 | has it |
| A link with quotes or brackets is refused | has it | phase 1 | phase 1 | has it |
| Report outcome recorded on closing | has it | **gains (O)** | **gains (O)** | has a private note; gains the public one |
| Takedown requests listed first | **gains (O)** | **gains (O)** | **gains (O)** | has it |
| The confirming address deleted: checked daily | twice daily today | twice daily | nightly | **daily, was weekly (R: the promise is kept on time)** |
| Owner's commands | `hansard statements …` unchanged; `reports` gained | `wcs statements`, `publish-statement`… become `wcs statements publish`…; old names work for a release (**O**) | `councils list-statements`… the same (**O**) | `landlords statements --publish N` becomes `statements publish N`; old form works for a release (**O**) |
| Least words in a statement; refusal status and shape; where statements show; page text | unchanged, the site's own | unchanged | unchanged | unchanged |

- **Parity:** each site's existing tests for submissions, the owner's commands, what is shown and the deletion of
  addresses (the study lists them per site) run against the package through the site's routes; a golden set of
  accepted and refused submissions with the exact response each site gives today; `assert_statements_stay_out`.

**Drafted for the owner: the privacy notices.** Where MPs Stand, Where Councils Stand and Where Landlords Stand say
the confirming address "is kept while the statement is shown". The code keeps it while the statement is waiting
too, as it must to confirm the sender. Where Countries Stand's notice already says so. Proposed wording for the
other three, in their own voice: "…is kept while the statement is waiting or shown, and deleted three months after
it is withdrawn, declined or removed." The same change on each "If you're named" page.

### 1.10 The briefing log, statistics and alerts (`wts_core.observe`)

New on every site; nothing is replaced. [ADR 0012](adr/0012-briefing-record-and-statistics.md).

- Where MPs Stand's existing counts (questions per day, daily visitor counts, "Was this useful?") stay as they are
  and stay the site's. Its admin page gains the weekly report.
- Where Countries Stand's `wcs usage` and its update report's warnings, and Where MPs Stand's admin alerts, keep
  their wording; underneath they read the package's spending record.
- **Difference: R only through the privacy notice** (one sentence, with the owner's agreement, at each site's
  adoption). Until a site turns the log on, nothing is recorded.

### 1.11 Backup, restore and off-site copies (`wts_core.ops`)

| | MPs | Countries | Councils | Landlords |
|---|---|---|---|---|
| File name | `where-they-stand-YYYY-MM-DD.tar.gz` | `wcs-state-YYYY-MM-DD.sqlite.gz` | `councils-state-YYYY-MM-DD.sqlite.gz` | `landlords-state-YYYYMMDD-HHMMSS.sqlite.gz` |
| Holds | a tar: `state.sqlite`, `settings.local.toml` | the database, gzipped | the same | the same |
| Kept on the server / off site | 14 / 60 | 14 / 60 | 7 / 60 | 14 / 60 |
| **All of the above** | unchanged | unchanged | unchanged | unchanged |
| Making a backup | gains "nothing to back up yet" on a new site (phase 1) | as today | as today | made safely: temporary folder, integrity check, atomic rename (phase 1) |
| `restore` | Where Countries Stand's safe steps, keeping the tar and the local settings (phase 1) | as today | **gains the command (O)** | **gains the command (O)** |
| A stopped backup is emailed | **gains `backup-check` and its timer (O)**; today only the admin page shows it | by its update, as today | by `backup-check`, as today | **gains `backup-check` and its timer (O)** |
| Off-site code | identical in all four today; moves as it is | | | |
| Alert wording | its own, kept | its own (lower case, "is wcs-backup.timer running?"), kept | its own, kept | Councils' wording, in its own name |

- The site passes a `BackupSpec`: the database's path, the prefix, the date format, the format (gzip or a tar with
  extra files), how many to keep, and the tables a restored file must contain.
- Unit and timer files stay in each site's `deploy/`. Where a site gains `backup-check`, its `deploy/` gains the
  unit and timer in the adoption pull request, installed by its `update.sh` when the owner next runs it.
- **Parity:** a backup made by the old code and by the package from the same database: the same file name, the same
  members, the same bytes inside, mode 0600, the same files pruned; a restore of each by the other; the same
  `offsite.json`; the same alerts, word for word, for each condition in the study's table.

### 1.12 The DuckDB wrapper (`wts_core.adapters.duckdb`)

Identical in Where MPs Stand and Where Countries Stand. It moves with the fix made in Where MPs Stand's library
upgrade (DuckDB 2 refuses new work on a cursor with an unread result). Where Councils Stand and Where Landlords
Stand don't use it. **Difference: none.** Parity: the three tests, on DuckDB 2.

## 2. Site by site: what an adoption pull request contains

For every site: the dependency at the release's address; `site.py` (its `Site`, `Messages`, `Items`, `BackupSpec`);
its `Settings` subclass; its import into the `wts_` tables; its own copies deleted; the parity tests above,
committed; its CI moved onto the shared workflows; the weekly report's timer in `deploy/`; README and docs updated;
a list of every behaviour difference from the tables above (the expected answer for readers is "none beyond those
listed").

| Site | Installs | Files deleted (roughly) | What the owner will notice | Before it starts |
|---|---|---|---|---|
| Where Landlords Stand | `wts-core[cli,offsite]` | `offsite.py`, the backup in `cli.py`, the limiter and state helpers in `api.py`, most of `statements.py`, the loader in `config.py` | new commands (`restore`, `backup-check`, `statements publish`…); the nightly check replaces the weekly alert on what is waiting | nothing |
| Where Councils Stand | `wts-core[cli,offsite,duckdb,ai]` | `rag/verify.py`, `neutral.py` (but its word list), `british.py`, `answer.py`, `embed/base.py`, the base of `index/lance.py`, `api/usage.py`, `api/state.py`, `api/statements.py`, `backup.py`, `offsite.py`, the flow and `sse` in `api/app.py`, the loader in `config.py` | a public corrections log; `restore`; renamed statements commands; the weekly report | agreement to the privacy sentence |
| Where Countries Stand | the same | the same list, plus `store/shared.py`, `rag/typography.py` | renamed statements commands; the weekly report | agreement to the privacy sentence |
| Where MPs Stand | the same | the same list, plus `api/reports.py`, most of `api/briefings.py`, the shared tables in `store/state.py` | `backup-check` and its timer; the weekly report on the admin page | its library upgrade merged and deployed for a week; the front door's handling of `X-Forwarded-For` read (1.3) |

## 3. What is not migrated

Retrieval, ranking beyond the three shared functions, the index schema, instructions to the model, reading the
question, formatting sources, fetchers, each site's commands for its own record, web routes and pages, each
site's own tables, and every word a reader sees. They follow each site's record and stay in its repository.
