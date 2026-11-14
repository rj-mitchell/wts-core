# As built: where the package differs from the sketch, and what adoption must know

[`API-SKETCH.md`](API-SKETCH.md) was the sketch the owner reviewed with the design. The code is the reference now
(and `docs/api-snapshot.txt`, once the interface is frozen for v0.1.0). This file lists, module by module, where
the built package departs from the sketch and why, and what each site's adoption (phase 4) has to handle. Each
entry comes from the hand-back of the worker that built the module, checked against the code.

## What version 0.2.0 changed

Version 0.2.0 removed the rough edges the example site found, before any AI site adopted the briefing desk. The
sections below are kept as they were written for 0.1.0, with the lines that 0.2.0 made untrue corrected in
place. In one list, what is different (`CHANGELOG.md` says what a site must do for each):

- **The desk's configuration is typed.** `BriefingDesk` takes `config: ports.BriefingConfig` and no
  `parse_model`. `observe.briefing_config(log=…, model=…, parse_model=…, instructions=…, site_version=…,
  also=…)` makes it, works out its id and keeps the parts in `wts_configs` in one call; `log=None` is said out
  loud by a site that has not turned the record on.
- **The desk's parts are built in one call:** `briefing.desk_parts(settings, db, messages, new_id=…,
  at_once_per_visitor=…, forget_over=…, keep_failures=…)`, then `DeskParts.desk(config, log=…, hooks=…,
  group_of=…)`. It is two steps because a site's pipeline and hooks are made from the parts (the spending record,
  the limits, the cache, the saved briefings) before the desk is. The clock and the source of chance are given
  once.
- **The start-up check** is `briefing.desk_settings`, run first by `desk_parts`: every limit, price, figure and
  message the flow needs, with all that is missing or wrong in one `SettingsError` that names the settings file
  and each key. `Limits.from_settings` and `PriceTable.from_settings` say everything wrong at once and take
  `file=`.
- **A model's stream has `close()` in its type** (`ports.ModelStream`), and `adapters.has_model(settings, site,
  env)` says whether there is a model to ask without a site naming the provider.
- **One nightly command.** The statistics group's `tidy` takes `also_tidy`, and `cli.replies_tidy` is the right
  of reply's housekeeping as a step for it; `replies_commands` adds the same as `tidy-replies`.
  `RepliesWording` has a line for it, `tidied`. `eval_commands`' `max_cost_usd` and `stats_commands`'
  `similarity` may be functions, read when the command runs. How many copies stay off site is
  `BackupSpec.keep_offsite`.
- **A state database is marked as its site's** (`StateDB(..., site=…)`: `wts_kv`, key `site`), and with
  `BackupSpec(site=…)` a restore refuses a backup marked as another site's (`why="other-site"`). A backup with
  no mark is accepted as before.
- **Events are one plain type,** `events.Event`, wherever they are passed. `testing.FixedRandom` gives ids of
  the real length. `wts_core.dates.long_date` is the family's date format where a pipeline may import it.

- **From the first adoption** (Where Landlords Stand, on 0.1.0): `Replies.publish` asks the site whether the item
  is still shown, and refuses a hidden one; `replies_commands` tells the site (`changed`) after `hide`, `unhide`
  and `reports close` as well, asks only for the wording its commands print, and takes a group of the site's own
  (`groups`) so that an older shape of command can be kept with one call; the command groups take their clock
  when a command runs; `load_settings` makes the section of every `EnvSetting`; an `Import`'s statement may be
  built when it runs (`state.columns`); `assert_no_reader_data` needs no question; the shared `python.yml` turns
  Typer's colour off.

### At adoption, because of 0.2.0

- Each AI site's settings have every key `desk_parts` reads under the names it reads them by
  (`requests_per_minute`, `answer_cache_hours`, `briefing_estimate_usd`, `briefings_at_once`), and each passes
  the start-up check today: `tests/test_briefing_build.py` reads each site's own `config/settings.toml`. A site
  says the name of its "at once, for one visitor" setting (`briefings_at_once_per_reader` on Where MPs Stand,
  `briefings_at_once_per_visitor` on the other two) and the number its limiter forgets at (50,000, and 10,000 on
  Where Councils Stand), which is in its code today.
- The fallbacks each site's code has for those figures (`.get("requests_per_minute", 20)` and the like) go: a
  missing one now stops the site when it starts, by name.
- **The mark is written the first time a site opens its state database with `site=`.** Backups made before that
  have none and stay restorable. Once a site passes `site=` to its `BackupSpec`, a backup made by a sister site
  after *its* adoption is refused. A site must give the same package name to both (`Site.package`).
- **A state database restored from a sister site's unmarked backup would be marked as this site's** on the next
  start: the mark closes the gap only for backups made after both sites have adopted it. `required_tables`
  should still name a table of the site's own while it has one.
- The owner supplies each site's `tidied` line with the other words of the reports and statements commands. The
  stand-in is in `tests/cli_sites.py`, marked as such.
- Each site's nightly timer runs one command, `tidy`, once the site gives it `also_tidy`. Where Landlords Stand
  has no record of briefings and runs `tidy-replies`.

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

## `wts_core.briefing` (the desk, stage timings, the streamer)

Proved against each site's real application: all three sites' own `create_app()` are built in the package's tests
and driven through `/api/ask`, beside the desk configured as that site would configure it. The bytes a reader
receives and the rows written (spending, cache, saved briefings, failures) are compared field by field on every
case in ADR 0009, for each site.

### Differs from the sketch

- `sse(events, keep_alive=15)`: all three sites use 15 seconds; the sketch's 10 would have added lines to what a
  reader receives.
- Events are plain dictionaries (`events.Event`, which `briefing.Event` is), because Where MPs Stand's
  `progress` and `interests` events are not in `events.ReaderEvent`. Since 0.2.0 `events.to_reader` and
  `EvalSite.ask` give the same type, so a site needs no cast.
- `Ask` gains `filters_set`, `options` and `save(final, kept, text)`; the route calls `desk.allow(key)` itself.
- `Hooks.send` is gone: what Where Councils Stand strips must be stripped before the briefing is kept, so it is
  `on_event`. `Hooks.usages` names any further model calls an event reports.
- `BriefingDesk` takes no `site` and no `experiment`; it gains `config`, `group_of`, `strict`. `config` is a
  `ports.BriefingConfig` since 0.2.0 (it was a mapping, and `parse_model` a separate argument). With an arm in
  it, the experiment and arm are part of the cache key.
- `handle()` looks in the cache and makes the first check of the caps before it returns, as the sites do before
  the response starts, so a storage fault is still an HTTP error.
- `Stages.spent(usage, cost)` is new: a site's sources-only function tells the briefing's record what its reading
  of the question cost, since that stream carries no token counts.
- `marking(stages, events)` makes the stages current for each step, so it works under a framework's thread pool.
- `gather_first` (reading the question and searching at once) is not built: it belongs to phase 6.

### How each site's difference is expressed (no branch in the desk names a site; a test checks)

| Difference | Where it lives |
|---|---|
| Where Councils Stand sends no `usage` | `Hooks.on_event`, before keeping |
| `parse_error` | removed by the desk on every site; noted as a failure if the site keeps failures |
| Where Countries Stand does not cache follow-ups | `Ask.cache_key=None` |
| Where MPs Stand's `briefing_key` | `Hooks.finish` |
| Where MPs Stand's `interests_usage` | `Hooks.usages`, then removed in `on_event` |
| Where MPs Stand's reminder of what briefings cost | `Hooks.for_this_reader`, on a copy, so it is never saved or cached |
| Where MPs Stand's old cached answer given an address | `Hooks.on_cached` |
| Where MPs Stand's saved shape | `Ask.save` |
| Who reads the question when no briefing is written | `Ask.sources_only(note, free)` |
| The model declining | the pipeline's own `error` event; the desk notes it and records its cost |

### At adoption

- Each site's own `test_api.py` tests of the ask flow stay in the site as the gate for its adoption: the parity
  tests here use a scripted pipeline, not the site's index.
- Where Councils Stand with `answer_cache_hours = 0` stored a cache row that could never be read; the desk stores
  none. The bytes are the same.
- Where MPs Stand's reminder count is taken when the final event is sent, after saving, not straight after the
  answer is recorded. It differs only if the same visitor finishes another briefing in those milliseconds.
- A reader who leaves is recorded as `left` only for a briefing that was being written; a refusal, a sources-only
  request or a cached replay closed early keeps its outcome and gains `left_at`.
- Where Councils Stand keeps no failures and counts questions in its own table: it passes `failures=None`.
- The desk keeps the sites' `log.exception("ask failed")`, which carries the exception's message as today; the
  record of the briefing carries only the exception's class name.
- Each site's sources-only function should call `current_stages().spent(usage, cost)` after it records its
  spending, or those records show no cost.

## `wts_core.observe` (the record of each briefing, statistics, the weekly report, alerts)

### Differs from the sketch

- The modules are `observe.log`, `observe.config`, `observe.logs` (the JSON log lines), `observe.figures` (the
  statistics; `observe.stats` is the function) and `observe.report`.
- `config_id(parts)` takes a mapping the site builds, not the site and its settings. Since 0.2.0 a site calls
  `briefing_config`, which calls it and keeps the parts.
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

## `wts_core.checks` (the checks on briefings)

This section and the two after it were written from the code and its tests on the package branch, statement by
statement, and not from a worker's hand-back. For the checks, "the sketch" is the section the owner reviewed; the
checks section of `API-SKETCH.md` has since been rewritten as built.

### Differs from the sketch

- **`Verifier(*, no_records, evidence_notes, honorifics=COMMON_HONORIFICS)`: the "note about the evidence" rule is
  one compiled pattern, required, with no default.** The sketch had a list of a site's extra patterns, empty by
  default. The package exports the two forms the sites have today: `EVIDENCE_NOTES_WIDE` (Where MPs Stand and Where
  Countries Stand) and `EVIDENCE_NOTES_STRICT` (Where Councils Stand). The arguments are given by name.
- **The "strict form plus a narrow one" that MIGRATION 1.4 proposes is not in the package.** It has the two forms
  above and nothing between them. A site that wants a narrower rule writes the pattern itself.
- `check_quotes` asks more of a source than `verify` does. `verify` reads `n` and `blocks` (`SourceText`).
  `check_quotes` also reads `title` and `meta` (`TitledSource`): a quotation is looked for in the source's title
  and in `meta["heading"]` as well as in its text.
- `recheck(answer, *, curled=False)`. With `curled=True` the saved text is read with straight quotes and comes back
  as it was saved; only the statuses and the two counts change.
- `check_briefing(blocks, sources, verifier, loaded_words, *, curled=False)` is new: the five checks in their one
  order, then the answer as it is sent and saved.
- `Verification` has `rules` and `markdown()`. `RULES_VERSION` (1 today), `curl_quotes` and `curl_event` are
  exported.
- `Verifier.rules_version` is an attribute, set from `RULES_VERSION`. It is not an argument, so a site cannot pass
  a version of its own.
- The three ranking functions take what the sites' arithmetic takes. `blend(word_scores, meaning_scores, *,
  word_weight, meaning_floor, meaning_ceiling)` scores a whole set at once, because a word score is divided by the
  best in the set. `recency_factor(d, today, *, recency, floor, min_half_life_years)` takes dates and the reader's
  slider. `round_robin(pool, limit, *, group_of, key_of, score_of, caps=(), seeds=())` takes caps as pairs of a
  function and a number, and records to take first.
- `Verifier` and `LoadedWords` are final: a site passes its inputs and does not subclass.

### Decided while building

- What a site passes in, because the three copies differ there: the opening words of a "no records" answer; the
  honorifics whose full stop ends no sentence; its form of the evidence-note rule; its whole loaded-words pattern,
  compiled with its own flags; whether its briefings are shown with curly quotes. For ranking: the grouping, the
  caps, the weights, the seeds, and a pool already cut at the site's relevance floor.
- The other patterns, word lists and limits are the same in the package as in each site's copy.
  `tests/test_checks_parity.py` compares them character for character, and compares the results on 400 generated
  briefings for each site. Run on this branch against the sites' checkouts (their phase 1 code), the comparisons
  passed and none was skipped.
- The order in `check_briefing` is: citations, openers about the records dropped, British spelling, loaded words,
  quotations. Curly quotes come last, on the finished answer.
- `to_dict()` writes today's keys and then `rules`. `recheck` returns the same object, untouched, when `rules` is
  a whole number at or above the verifier's own. An answer with no stamp, a lower one, or a stamp that is not a
  whole number is judged again.
- Judging again only clears: an "unsupported" passage may become "connective", and `unsupported_segments` and
  `grounded_ratio` are worked out again. The result keeps the stamp it had, and nothing is written back to the
  saved row.
- `LoadedWords.still_loaded` does not look at the stamp. It judges the marks on a saved answer each time, by the
  site's present pattern, and can only remove a mark.
- Honorifics are matched as written, capital letter and all. "the hon. Member" is cut at "hon." on all three
  sites.

### At adoption

- **Each site passes its own form of the evidence-note rule, and the two forms differ in strength.** The wide form
  also takes for a note a sentence with "is/are/was/were (not) supplied/retrieved", "votes/data were (not)
  supplied" or "no vote data/records/tables", unless the sentence reports what someone said. So "Gas was supplied
  to two million homes" is not flagged on Where MPs Stand and Where Countries Stand. The strict form flags it, and
  also flags real notes such as "The votes on the second reading were not supplied". Adoption passes each site the
  form it has today, so nothing changes then. The narrowing is still to be made, as its own change at each site,
  with replay fixtures and the site's evaluation run before and after (ARCHITECTURE's table of findings,
  MIGRATION 1.4).
- **A narrower rule will not reach briefings already saved or cached.** `recheck` never newly flags. A sentence the
  wide form cleared stays cleared in a saved briefing, and in a cached one until the cache drops it or the site
  changes a part of its cache key.
- **Answers from before adoption carry no stamp, so `recheck` judges them again each time it is called on them.**
  For those answers it gives what the site's own `recheck_flags` gives (the parity tests). Answers written after
  adoption are stamped and left alone. MIGRATION 1.4 says Where MPs Stand does not recheck its cached answers
  today: if its adoption does, a cached answer from before adoption can lose a flag until the cache drops it.
- A site that later changes its own pattern or honorifics does not change `rules`. Answers stamped before the
  change are not judged again by the new pattern.
- `honorifics` and `no_records` are not checked for being empty. With an empty tuple of honorifics the verifier
  takes a full stop after a word for no sentence end, which clears claims. An empty `no_records` marks each answer
  as "no records".
- What each site passes, as `tests/checks_sites.py` has it. Where MPs Stand: `COMMON_HONORIFICS`, the wide form,
  and `COMMON_LOADED_WORDS` alone. Where Countries Stand: the same honorifics and form, its words for governments
  and blocs added to the pattern ("the West" only with its capital), and `curled=True` in `check_briefing` and in
  `recheck`. Where Councils Stand: `Cllr`, `Rev`, `Revd` and `Hon` added to the honorifics, the strict form, and its
  22 more words. All three open a "no records" answer with "No records found." Where Landlords Stand has no
  briefings and does not use this module.
- Each site's `select_evidence` keeps its relevance floor, grouping, caps and seeds, and is rewritten on
  `round_robin`. `tests/test_checks_parity.py` has the three written that way, selecting the same records as each
  site's own function.

## `wts_core.usage` (limits, cost, caps, the answer cache, saved briefings)

### Differs from the sketch

- **A model with no price entry is costed at the base prices; it does not stop the site.** `price_for` never
  raises. `PriceTable.require(models, *, base_counts)` is the start-up check, and the site must call it: with
  `base_counts=True` it checks nothing (today's rule); with `False` it raises `UnknownModel` for a model that
  matches no name under `[usage.models]`. ADR 0002 and MIGRATION 1.3 say an unknown model stops the site.
- **No `[pricing]` table is read.** Prices are read from `[usage]` and `[usage.models."<name>"]` only.
  `PriceTable.from_settings(usage, *, section="usage")` takes that mapping, not the `Settings`.
- **Saved briefings are in this module, not behind a port.** `BriefingArchive(db, *, new_id, clock)` has `save`,
  `get`, `withdraw`, `withdrawn` and `recent`, and returns `SavedBriefing` and `BriefingListing`. `new_id` has no
  default: `token_id(nbytes)` is Where Countries Stand's and Where Councils Stand's way, `alphabet_id(alphabet,
  length)` is Where MPs Stand's. The interfaces `SavedBriefings`, `FailureLog` and `SpendingFigures` are in
  `usage.interfaces`.
- `RateLimiter(per_minute, *, forget_over, clock)`: `forget_over` has no default.
- `visitor_code(kv, address, *, day=None, forget_undated_salt=False, clock, random)`. For it, `ports.KeyValue`
  gained `set_if_absent` and `delete`, and `ports.Random` gained `token_hex`.
- `Spending(db, pricing, *, clock)`. `add` takes a `Usage` or the token counts in either of today's forms. It also
  has `totals(since)`, `by_day(since)` and `by_account(since)`, the figures for the owner's reports.
- `Limits.from_settings(usage, *, section="usage")`. `Caps` raises `SettingsError` when a site has a message for
  signed-in accounts and no limit for them, or the limit and no message.
- `busy_refusal(busy, messages)` is new: it turns what `BriefingsInProgress.start` returns into a `Refusal`.
  `BriefingsInProgress.running` is new.
- `SqliteAnswerCache(db, *, clock)` and `Failures(db, *, clock)`. `Failures.recent(limit=20, *, since=None)`;
  `limit=None` gives all.
- `migrations()` is new: the tables `wts_spending`, `wts_answer_cache`, `wts_briefings` and `wts_failures`
  (migrations 10 to 13). A site passes it to `StateDB` with the other modules'.
- Not on the branch: the sketch's contract suites for the spending record and the answer cache.

### Decided while building

- **Which limits follow the UTC day and which roll.** Requests a minute: the last 60 seconds for each key, by the
  process's own clock; a request exactly 60 seconds old still counts. The visitor's and the account's daily limit:
  rows of kind `answer` in `wts_spending` since midnight UTC, not the last 24 hours. The daily cap: spending since
  midnight UTC. The monthly cap: spending since the first of the calendar month, UTC. The answer cache: the last
  `max_hours`, to the second. Notes of failures: the last 90 days and the newest 500.
- The comparisons are `>=`: a limit of 40 gives 40 briefings, and a cap of 0 stops them all. The order is the
  account's or the visitor's limit, then the day's cap, then the month's. A signed-in account is counted by its own
  limit and not as a visitor. The estimate for briefings in progress (`pending_usd`) is added to the day's and to
  the month's spending.
- The limiter and the briefings in progress are kept in memory, for one process.
- No row is written when there is no usage (`None` or an empty mapping), as on Where Councils Stand. A `Usage` of
  noughts is written.
- Token counts are stored in the sites' own form: `input_tokens` includes the cache writes. Writes to the one-hour
  cache are costed at their own multiplier, but `wts_spending` has no column for them.
- A model's entry is used when the model's id equals the entry's name or starts with it. The first match wins, in
  the order of the settings file. An entry's figures are laid over the base prices.
- The visitor's code is 24 characters of a SHA-256 of the day's secret and the visitor's network (an IPv4 address,
  or an IPv6 /64). The secret is `visitor_salt:YYYY-MM-DD` in `wts_kv`. Making a new day's secret deletes the
  others in `wts_kv`.
- `client_address(headers, peer, *, behind_proxy, trust_forwarded_first)` reads the address in the two ways the
  sites do: the web server's own (Where MPs Stand, Where Councils Stand), or the first entry of `X-Forwarded-For`
  behind the proxy (Where Countries Stand, Where Landlords Stand).
- An answer exactly `max_hours` old is still given. Storing an answer deletes the rows older than that call's
  `max_hours`. With no hours, nothing is given.
- A note of a failure keeps 500 characters of the question and of the error. Old notes are deleted when a new one
  is written.
- `BriefingArchive` has no way to delete a saved briefing. If an id is taken another is tried, five in all, and
  the new id replaces the old one in the events' `briefing_id`.

### At adoption

- **Each site writes its own import into the `wts_` tables; none is in the package.** It must give each `NOT NULL`
  column a value. In `wts_spending` those are `at`, `kind`, the four token counts and `cost_usd`; in
  `wts_answer_cache`, `created_at` and `events`; in `wts_failures`, `at`, `kind` and `error`. Where Countries
  Stand's `usage`, `answer_cache` and `failures` allow NULL in those columns, and Where Councils Stand's token
  counts do, so their imports should use `coalesce`. A failed import is rolled back whole, and `StateDB` raises.
- What the imports rename. Where MPs Stand's `user_id` becomes `account` and its `settings` becomes `options`.
  Where Countries Stand's and Where Councils Stand's briefings' `at` becomes `created_at`, as does Where Councils
  Stand's cache's `at`. Where MPs Stand's `records_up_to` and `model` go into `extra`, a JSON object. Events are
  kept as they are.
- **The daily limits and the caps are sums over `wts_spending`,** so the day's and the month's rows must be
  imported with their visitor codes, accounts and kinds. Only rows of kind `answer` count towards a daily limit.
  Where Councils Stand keeps that count in its `questions` table today; the package does not read it, and counts
  the imported `usage` rows of kind `answer`.
- **The visitor's code stays the same across adoption only if the day's secret is imported** from `kv` into
  `wts_kv` under the same key. Without it, each visitor's count starts again once, on that day.
- **The package deletes old secrets from `wts_kv` only.** The last secret in a site's old `kv` table, and in the
  copy of the file made before the import, is not deleted by the package. `forget_undated_salt=True` (Where MPs
  Stand) deletes the un-dated key from `wts_kv`, not from `kv`.
- **The four prices are required in `[usage]`, with no fallback in code:** `price_input_per_mtok`,
  `price_output_per_mtok`, `price_cache_read_per_mtok`, `cache_write_multiplier`. A missing one raises
  `SettingsError`, naming it. The three sites' `settings.toml` have all four today.
  `cache_write_long_multiplier` is optional, in `[usage]` or in a model's entry; without it the multiplier is 2.0.
- A site that wants unknown models refused calls `require(models, base_counts=False)` at start-up. It then needs
  an entry for each model it names. Today Where MPs Stand has none for `claude-opus-5-5`, and Where Countries Stand
  and Where Councils Stand have none for `claude-sonnet-5-5`: those models take the base prices. An empty entry is
  enough.
- `Limits.from_settings` requires `per_visitor_daily_questions`, `daily_spend_cap_usd` and
  `monthly_spend_cap_usd`; `per_user_daily_questions` is read where present (Where MPs Stand). The other figures
  (requests a minute, the cache's hours, the estimate, and the two "at once" figures) are read by
  `briefing.desk_parts` since 0.2.0, under the names all three sites use; the one they name differently
  (`briefings_at_once_per_reader` on Where MPs Stand, `briefings_at_once_per_visitor` on the other two) the site
  names. A site that builds the pieces by hand still reads them itself and passes numbers. The package has no
  fallback for these either.
- **Where Councils Stand gains a table of failures.** Today it only logs a failed briefing. With `Failures` it
  keeps up to 500 characters of the question for 90 days. Its privacy notice should be checked before that is
  turned on. Where MPs Stand gains the 90 days.
- Where Landlords Stand hashes the address before its limiter keeps it. `RateLimiter` keeps the key it is given,
  so the site passes a visitor's code or its own hash, not the address.
- Where MPs Stand and Where Countries Stand wrote a row of noughts for a call with no usage; the package writes
  none.
- Where Councils Stand's cache gave an answer up a second sooner at the end of its life. Its key stays 32
  characters only if it passes `length=32` to `cache_key`: the default is 64, and with that its cached answers are
  not found and are written again.
- The cache key is the same for the same parts (compared byte for byte with each site's own). The week's cache
  survives only if the site passes the same parts and imports its cached rows.
- Whether the front door replaces `X-Forwarded-For` is still to be read (MIGRATION 1.3). The package keeps each
  site's way.

## `wts_core.ops`, `adapters.b2` and `adapters.duckdb` (backup, restore, off-site copies)

### Differs from the sketch

- **`BackupSpec` is given by keyword, and `keep` and `required_tables` have no default.** It is not a field of
  `Site`: the site builds one and passes it to each function. New: `wal` (whether the database keeps a write-ahead
  log), `suffix` and `archives(folder)`.
- `RestoreRefused(message, *, why)`. `why` is one of "kept-copy", "unreadable", "foreign", "not-a-database",
  "damaged" and "swap-failed", for a command that words the refusal itself; and, since 0.2.0, "other-site".
- `send_offsite(archive, store, spec, *, keep=None, clock)` (the spec's `keep_offsite`, 60, unless `keep` is
  given) and `check_offsite(store, spec, *, how_to_set_up=None)`.
- `Alert(level, text)` and `AlertWording` are exported. `AlertWording` has six fields, all required: the package
  has no alert wording.
- `ports.OffsiteStore` has `name` and `close()` as well as `put`, `list` and `delete`. It raises
  `ports.OffsiteError`; `OffsiteUnavailable` is the store not reached. Both are exported from `ops` too.
- `B2Store(bucket, key_id, application_key, client=None, *, env_prefix=None)`. `configured(site, env=None, *,
  client=None)` reads `<PREFIX>_B2_BUCKET`, `_B2_KEY_ID` and `_B2_APPLICATION_KEY`. `how_to_set_up(site)` is new.
- `SharedConnection` and `shared` are as sketched.
- Not on the branch: `wts_core.cli` (the shared `backup`, `restore`, `offsite` and `backup-check` commands), which
  the docstring of `ops` names, and the sketch's `MemoryOffsiteStore` and contract suite for an off-site store.

### Decided while building

- `restore_backup` follows Where Countries Stand's order, with Where MPs Stand's additions. The archive is unpacked
  beside the database and checked (SQLite's integrity check, then the required tables) before anything is touched.
  The database it replaces is kept as `<name>.before-restore`, with its write-ahead log where the spec says `wal`.
  A kept copy from an earlier restore stops the next one until it is moved or deleted.
- A restore takes one of the site's archives or an uncompressed database, so a kept copy can itself be put back.
- A tar's extra files replace the ones in the data folder after the swap. No copy of those is kept.
- A backup is named by the UTC time. With a date-only stamp a second backup on the same day replaces the first.
  Pruning keeps the newest `keep` by name, of this site's archives only; zero or less deletes nothing.
- `send_offsite` treats a store that refuses to delete as a copy stored (a warning is logged), and a store that
  cannot be reached, at whichever step, as a failed copy. It records the outcome in `offsite.json` and closes the
  store.
- Backblaze is offered the key when the store is first used, not when it is made. httpx's errors are raised as
  `OffsiteUnavailable`. `check_offsite` raises `OffsiteError` for a refused key or no network.
- `backup_alerts` only returns the alerts. "Stale" is more than `stale_hours` (50). A record of a copy made with no
  time, or a time with no zone, raises, as each site's own code does.
- The DuckDB wrapper calls `complete()` on the thread's cursor before `register`, `sql` and the like: DuckDB 2
  refuses them while the last result has rows unread.

### At adoption

- **`required_tables` must name at least one table** (an empty tuple is refused when the spec is made: with none
  named, a restore would take any sound SQLite file, an empty one included).
- **A site's spec should name tables that only that site has, and that stay when the old shared tables are
  dropped.** Where Landlords Stand's adoption (the first) named `missed` and `approvals`: its own tables, in every
  backup made before the package or after, and in no sister site's. This document first gave `reports` for it,
  which was wrong on both counts: every site has a `reports` table until it drops it, and a spec that names a
  table the package's import replaces refuses every backup made once that table is gone. The package's own tests
  (`tests/test_ops_sites.py`) still build each site's backups from its old tables (Where MPs Stand `manifest`,
  `usage`, `briefings`, `reports`; Where Countries Stand and Where Councils Stand `usage`, `briefings`; Where
  Landlords Stand `reports`), because they compare with each site's own restore as it stands today: they are not
  the specs to adopt.
- **A site with no table of its own** names the package's (`wts_` tables) and passes `site=` to its `BackupSpec`
  and its `StateDB`, so that the mark tells its backups from a sister site's (0.2.0). A backup made before
  adoption has no `wts_` tables, so such a spec refuses it: keep one table of the site's own in the list for as
  long as backups from before adoption must be restorable.
- The rest of each spec, as in `tests/test_ops_sites.py`. Where MPs Stand: `where-they-stand-`, a tar holding
  `state.sqlite` and `settings.local.toml`, 14 kept, `wal=True`. Where Countries Stand: `wcs-state-`, 14. Where
  Councils Stand: `councils-state-`, 7. Where Landlords Stand: `landlords-state-` with the stamp `%Y%m%d-%H%M%S`,
  14; its name carries the time, so 14 kept there and 60 off site are runs, not days.
- Compared with each site's own code, the package makes the same file and deletes the same files, and restores a
  backup the site's code made. Where MPs Stand's and Where Countries Stand's own restores take one the package
  made.
- Where Councils Stand and Where Landlords Stand gain `restore_backup`. Until `wts_core.cli` is merged, the command
  around it is each site's to write, as are the wording and exit codes of `backup`, `offsite` and `backup-check`.
- Where MPs Stand's restore replaces `settings.local.toml` with the archive's, as it does today, and keeps no copy
  of the one replaced.
- Where MPs Stand's "move or delete it first" loses its full stop. The other refusals are word for word those of
  Where MPs Stand's and Where Countries Stand's own restores.
- Each site passes its own alert wording: Where MPs Stand's and Where Councils Stand's sentences, Where Countries
  Stand's lower-case form with "is wcs-backup.timer running?". Where Landlords Stand has none and takes Where
  Councils Stand's. Who calls `backup_alerts` each day, and who is emailed, stays in each site's command and
  timer.
- `offsite.json` has the same keys as before, so the file already on a server is read.
- The warning that old off-site copies were not deleted is logged as `wts_core.ops.offsite`, not under the site's
  own name.
- `adapters.b2` needs the `offsite` extra (httpx). `adapters.duckdb` needs the `duckdb` extra, which asks for
  DuckDB 2. Where MPs Stand and Where Countries Stand use the wrapper; the other two do not need the extra.
- Unit and timer files stay in each site's `deploy/`.

## `wts_core.cli` (the shared commands and the check route) and the last testing helpers

Proved against all four sites' own commands, loaded from their checkouts and run side by side with the package's
on the same rows: what is printed, where, and the exit code.

### Differs from the sketch

- `ops_commands(site, settings, spec, wording, *, store, how_to_set_up, env, clock, before)`: the backup spec is
  passed (`Site` has no `backup` field), and every printed line comes from the site's `OpsWording`.
- `replies_commands(replies, commands, wording, *, about, changed)`: `commands` names each command as the site
  has it (two words make a group, one a flat command, `None` leaves it out); `changed` is called after each
  change (Where Landlords Stand rebuilds its pages there).
- `check_route(site, *, replies, backups, figures, token, clock)` returns `(status, body)` for a site's route to
  send: 404 with no token set, 401 for a wrong or missing one. It passes on only numbers, yes-or-no values and
  empty values, under plain lower-case names, so nothing a reader wrote can leave by it. `last_day_figures(log)`
  and `backup_ages(...)` fill it.
- `stats_commands` adds `stats` (with `--check`), `weekly-report` and `tidy`; `eval_commands` adds `eval run`,
  `compare` and `replay`. `eval run` has no spending limit of its own: the site passes one (a number, or since
  0.2.0 a function read when the command runs), or it refuses to run.
- Typer is imported only when a command group is built, so `import wts_core.cli` and the check route need
  nothing outside the standard library. The `cli` extra asks for Typer 0.15 or later (earlier versions cannot
  merge a group's commands into the site's own).
- `wts_core.testing` gains `MemoryOffsiteStore`, `OffsiteStoreContract`, `assert_no_reader_data`,
  `assert_statements_stay_out` and `golden`. `assert_no_reader_data` allows the day's visitor code only in
  `wts_spending.visitor` and `wts_reply_counts.visitor`, where the sites keep it today.

### At adoption

- **Words the owner must supply, where a site has none today:** the lines for `hide`, `unhide`, `hidden`,
  `waiting` and `remove` on every site, and all of Where MPs Stand's report lines. The stand-ins are in
  `tests/cli_sites.py`, marked as such.
- Where each site printed one fixed line when something could not be done ("no waiting statement with that
  number"), the owner now sees the exact reason. The exit code is 1 as before.
- Where MPs Stand: declining a published statement is refused; `remove` is the command.
- Where Landlords Stand: its one-command shape (`statements --publish 3`) becomes subcommands
  (`statements publish 3`); its free-text `--outcome` becomes `--note` with `--outcome resolved|dismissed`; a
  missing `--checked` exits 2 (Typer's own) rather than 1; a closed report closed again is refused; lists are
  newest first. **Its server scripts and the owner's habits must change with it.**
- Where Countries Stand: takedown requests are listed first.
- Where MPs Stand had no tests of its backup, restore or off-site commands: the side-by-side runs are the first.
- `last_day_figures` gives the last 24 hours only; the weekly figures ADR 0010 mentions come from `wts_weekly`
  when the family's nightly check is extended (phase 5).

