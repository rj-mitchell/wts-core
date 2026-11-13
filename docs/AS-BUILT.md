# As built: where the package differs from the sketch, and what adoption must know

[`API-SKETCH.md`](API-SKETCH.md) was the sketch the owner reviewed with the design. The code is the reference now
(and `docs/api-snapshot.txt`, once the interface is frozen for v0.1.0). This file lists, module by module, where
the built package departs from the sketch and why, and what each site's adoption (phase 4) has to handle. Each
entry comes from the hand-back of the worker that built the module, checked against the code.

## `wts_core.replies` (reports and statements)

### Differs from the sketch

- **`Replies(db, …)` takes the `StateDB`.** There is no `ReplyStore` interface and no contract for one: SQLite in
  the site's state file is the only store there will be (ADR 0005).
- **No `wts_corrections` table.** The corrections log is worked out from closed reports and removed statements.
  The tables are `wts_reports`, `wts_statements`, `wts_statement_log`, `wts_hidden`, `wts_reply_counts`
  (migrations 30 to 34).
- **`Messages` has no `replies` field.** `Replies` takes `messages=ReplyMessages(…)` directly, so the right of
  reply shares nothing with the briefing flow's wording either.
- `submit` and `report` return `int | None`: None is the filled trap field (a robot), accepted silently, with
  nothing kept and nothing counted.
- `Item` has a third field, `part` (Where Landlords Stand places statements by it), and it is in `PUBLIC_FIELDS`:
  `id, item, part, about, name, role, text, link, date`.
- `submit(item=…)` takes the pasted address or an `Item` the site has already resolved (Where Countries Stand and
  Where Councils Stand add the request's own host first).
- `published(…, everywhere=False)`: every published statement, for a site that builds its pages ahead of time.
- `Refused.why` names the rule broken, so a route can answer 429 for a limit and 400 or 422 otherwise.
  `NotDone(ValueError)` is new: an owner's action that can't be done; its words are for the owner.
- Added: `update(…, note=)`, `statement(sid)`, `lapse_undecided()`, `all_hidden()`,
  `corrections(limit, *, withdrawn=(), removed=False)`, and `Waiting.hidden`.
- `ReplyRules` has more fields than the sketch, all without defaults except `max_words=150` and
  `email_kept_months=3` (both the policy's).
- `statement_html` wraps a statement in a `div` with `role="note"`, because search engines honour
  `data-nosnippet` only on `div`, `span` and `section`.

### Decided while building

- Tidying (forgetting old addresses, lapsing what has waited three months) runs on every write and on the owner's
  listings.
- A statement beside a hidden item is hidden with it, and no new one is taken beside it.
- `publish` refuses a `checked` note that contains the sender's own address; when an address is forgotten it is
  also replaced by `[address deleted]` in the log's notes.
- A lapsed report stays open; only its contact is deleted.
- The daily limits count per UTC day, not the last 24 hours.

### At adoption

- **The first write after the import can lapse old rows at once**: any imported statement that has waited more
  than three months, and the contact of any report open that long. That is ADR 0008 as decided, but the owner
  should be shown what would lapse before the first deploy (`waiting()` and the listings give it).
- No link is stored as NULL (Where Countries Stand and Where Councils Stand had `""`); their `shown_on` becomes
  `date`. Each site's pages and API must be checked for the difference.
- Text cleaning now closes runs of blank lines on Where Countries Stand and Where Councils Stand, and tidies inner
  spaces in names and roles on Where MPs Stand and Where Landlords Stand.
- Where MPs Stand's "decline" of a published statement is refused: `remove` is the word for it. Closing a closed
  report is refused (it used to overwrite).
- Order of checks when two things are wrong: the package's order is trap, daily limit, words, name, role, link,
  email, address, item shown. Where MPs Stand and Where Landlords Stand checked name and role before the words;
  the other two checked the address first (kept if the site passes an `Item`). A sender with two faults may be
  told about a different one first.
- No listing limits (Where MPs Stand had 200 and 100). Statements list newest first (Where Landlords Stand listed
  oldest first).
- Where Landlords Stand: an over-long message or contact is refused, not cut. Its requirement of a reason for a
  withdrawal stays in its command.
- Where MPs Stand's stored visitor codes are not imported (the tables have no such column; a code means nothing
  after its day).
- Wording the sites have no words for today, which the owner must supply: on Where MPs Stand the refusals for too
  many characters, a name, role or link that is too long, a report's kind, a report or contact that is too long,
  and "this item is not shown"; on the other three both daily-limit messages and the report refusals.
- Not in the package, so each site's own tests keep them: the command lines' exact output (until `wts_core.cli`),
  page placement, Where Councils Stand's "I act for them" box, route statuses.

## `wts_core.adapters` and the testing fakes

### Differs from the sketch

- `LanceIndex(path, embedder | IndexMeta | None, *, schema, scalar_columns, passages=, vectors=, number_type=,
  min_vector_index_rows=, vector_index_growth=)`. `scalar_columns` is a `ScalarColumns`, not a list of names: the
  sites index columns three ways. Opened with `None` it adds no vectors and still searches by words: this is how
  a site keeps working after `IndexOutOfDate`. `start_again(embedder)` is the rebuild.
- **The number type (16-bit or 32-bit floats) is recorded but a mismatch is not refused**: Where MPs Stand reads
  and writes a table in its own type until it converts it. A different embedder, dimension or schema version is
  refused, on opening and before every write.
- Method names follow the interface: `replace`, `search_words`, `search_meaning`, `build_indexes`, `tidy`.
- `AnthropicClient(…, client=None)` lets tests pass a fake SDK client, as the sites' own tests did.
- The fakes live in `wts_core.testing.models`, `.index` and `.contracts` (the last imports pytest, so it is not
  re-exported from `wts_core.testing`).
- `ports.Usage.cache_write_long` and `ports.Price.cache_write_long_multiplier` were added: the one-hour cache
  costs twice the input price to write, and the client can now ask for it. No site uses it today.

### What the real recordings showed

- **A citation arrives before the text of its block**, the opposite of every site's test fake. Nothing may depend
  on the order.
- The text of a cited block is the model's paraphrase; the quotation is only in the citation.
- The fall-back beta was accepted with the charity's key, so the retry without it is covered by fakes only.

### At adoption

- **The lock file resolves newer libraries than the sites have** (anthropic 2.8.0, lancedb 0.41.0; the sites are
  on 2.3.0 and 0.40.0, and Where MPs Stand on 1.12.1 until rj-mitchell/wherempsstand#43 is merged). The adapters'
  tests were also run in Where Countries Stand's own environment and (the client's) in Where MPs Stand's: all
  passed. The package's CI runs the lowest and highest allowed versions.
- When the vector index is retrained: the rule is Where Countries Stand's (more than 1.2 times the rows it was
  trained on; an unknown count retrains once). Where Councils Stand used "at least", and rebuilt its word index
  at the same time. Where Countries Stand keeps its count in its own `state.json`: call `note_trained(n)` once at
  adoption, or accept one retrain.
- The first opening of an existing index writes `wts_index.json`, so that process needs to be able to write to
  the index folder.
- `structured` raises when the model returns nothing; Where MPs Stand's interests check treats that as "no
  matches" today, so its caller must catch.
- An empty `<PREFIX>_ANTHROPIC_BASE_URL` counts as unset (the sites would pass `""`).
- `FastEmbedEmbedder.id` covers every model file under its cache folder, as Where MPs Stand's check does: a
  second model downloaded into the same folder changes the id and puts the index out of date. Give each model its
  own folder.
- A site must keep one model client for the life of the process (what it has learned about the fall-back beta is
  kept on the client, not in a module).
- Each site's own methods stay its own, as functions over the index: Where MPs Stand's `similarities`, Where
  Countries Stand's `group_rows` and `set_groups`.

## `wts_core.observe` (the record of each briefing, statistics, the weekly report, alerts)

### Differs from the sketch

- The modules are `observe.log`, `observe.config`, `observe.logs` (the JSON log lines), `observe.figures` (the
  statistics; `observe.stats` is the function) and `observe.report`.
- `config_id(parts)` takes a mapping the site builds, not the site and its settings.
- `tidy(retention) -> Tidied(deleted, blanked)`: the retention is a required argument (`OWNER_ACCEPTED` is the
  13 months and 90 days the owner accepted on 13 November 2026).
- `json_logging(path, *, site, max_bytes, keep, days)` has no defaults: ADR 0012's "14 days or 50 MB, whichever is
  less" needs both, so the handler also starts a new file each UTC day and deletes files older than `days`.
- `stats(log, *, since, until, compare_weeks, embedder, similarity, pricing, decided_by, clock)`. `similarity` is
  required with an embedder: the right figure depends on each site's embedding model.
- `weekly_report(stats, folder, *, site, week, db, …)` writes `2026-W46.md` and `.json` and the week's totals.
- `ports.BriefingLog` gained `since`; `ports.BriefingRecord` gained `cache_write_long_tokens`.

### Decided while building

- Figures are for readers' questions only; the nightly check's and the evaluation harness's rows are counted by
  kind and nowhere else.
- The median is the usual one; p95 is by nearest rank. Times leave out answers served from the cache.
- "Time to the full briefing" is the time the writing ended (`t_written`); its alert is `p95_full_briefing_ms`.
  The other alerts are `error_rate`, `check_failure_rate`, `not_useful_rate`, `daily_cost_usd`. A figure trips only
  when it is over its threshold; an unknown name in `[alerts]` stops the command, naming it.
- A question is quoted in a report only if its briefing is saved and has not been corrected; never from a failed
  briefing. A theme needs at least two questions.
- Two arms of an experiment are compared by a pooled two-proportion z-test at 5%, with no correction for looking
  more than once or for several arms: read a near-miss with care.
- A log line can hold only the named fields, each of the right shape, so a question passed to it by mistake is not
  written; a failed write prints nothing of the call.

### At adoption

- **The weekly report files quote questions that found no records, and themes.** `tidy_reports(folder,
  retention)` deletes report files older than the retention; each site's nightly update must call it (and
  `SqliteBriefingLog.tidy`).
- `wts_counts` (daily totals with no visitor code) is kept indefinitely.
- The prompt-cache figure prices a record's cache tokens at that record's model; if a site records its
  question-reading model's tokens in the same row they are priced at the briefing model's rates.

## `wts_core.eval` (the evaluation harness)

### Differs from the sketch

- `run(site, config, *, config_id, pricing, clock, only, limit, max_cost_usd, record_fixtures, progress)`.
  `max_cost_usd` stops the run cleanly once spending reaches it.
- A site's optional parts are separate interfaces: `Judges.judge`, `Scores.score` (what the site's own
  expectations measure, as met or not) and `Records.recording` (the documents and the model's raw blocks, for
  fixtures: reader events do not carry them).
- `check_briefing` in `wts_core.checks` is new: every check in the one order the sites run them. The harness and
  a site's pipeline both call it.
- `mark_passed(run, thresholds, folder)` writes the line the experiment guard reads; it refuses a run that failed,
  one held to no thresholds, and one that did not ask the whole set. `has_passed(folder, config_id, thresholds)`
  checks the recorded figures against today's thresholds.
- Run files are named `<date>-<time>-eval-<config id>.json`.
- `Case.expect` holds a question's `expect` table and its other keys together (`category`, `no_records`,
  `include`, `history`, `note`).

### At adoption

- **Where Countries Stand and Where Councils Stand ignore all of `eval/runs/` in git**, so `passed.jsonl` would
  never reach the server where the experiment guard reads it. Each needs an exception.
- Where MPs Stand's old run files are plans, graded sources and comparisons, not briefing runs: they stay
  readable by its own code only. Its plan-only runs, graded sources (`judgments.jsonl` is read by
  `load_judgements`) and blind side-by-side judging stay the site's, behind its own `EvalSite`.
- The harness cannot see a judge's own model calls, or Where MPs Stand's interests check, so the budget stop
  under-counts those.

## `wts_core.checks`, `wts_core.usage`, `wts_core.ops`

To be filled in from the code and each worker's notes before v0.1.0 (the checks section of `API-SKETCH.md` was
already rewritten as built).
