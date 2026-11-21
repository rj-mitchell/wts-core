# Changelog

What changed in each version, and what a site must do about it. Versions follow semantic versioning: while the
version is 0.x a minor version may change the public interface ([ADR 0007](docs/adr/0007-versioning.md)). The
`api:` line under each version is the fingerprint of the public interface in `docs/api-snapshot.txt`;
`tests/test_public_api.py` fails if the interface changes without a new entry here.

## 0.4.0 (21 November 2026)

The display rule for quotations beside their citation, the check strip's counts, and share cards for saved
briefings, for the family's design of checked briefings (`family/BRIEFINGS.md` in the charity's repository; the
review plan of 21 November 2026, B1 and B5). Nothing is renamed or removed, and no check changes.

api: c921c08b0fe4

### What changed

- `wts_core.checks.quotes_beside(answer)` returns the answer as it is shown. A passage marked unsupported that ends
  in a quotation the verifier found in the source cited straight after it is split: the quotation is shown as that
  source's passage (`"beside": True`), and the words before it keep their "unsupported" mark. The text, the counts
  and every other passage are unchanged (a property test over 3,000 made-up briefings says so). It was found in
  Where Countries Stand's saved briefing `kGfKBI3cRLw`, where Italy's quotation, found word for word in its source,
  was shown as if nothing supported it because the citation sat on "in November 2025".
- `wts_core.checks.check_counts(shown)` gives the strip's three counts (`CheckCounts`): citations matched of those
  made, quotations found of those checked, and passages shown as having no source.
- `wts_core.adapters.cards.briefing_card(style, title=, counts=, prepared=)` draws a saved briefing's share card
  (1200 by 630 PNG) in the site's cloth, with the counts in words, using Pillow (the new `cards` extra). The site
  chooses the title: its own neutral title for a reader's briefing, never the reader's question.

### What a site must do

1. Raise its pin to the 0.4.0 wheel, and the shared workflows and actions to `@v0.4.0`, then `uv lock`
   ([`docs/UPGRADING.md`](docs/UPGRADING.md)).
2. Pass every answer it shows (a new briefing's final event, a saved or cached briefing) through `quotes_beside`
   after `recheck`, and count the sentences without a source from the segments it returns.
3. Keep showing the verifier's own counts in the check details.
4. For share cards, add the `cards` extra and pass `CardStyle` its fonts and icon.

## 0.3.2 (18 November 2026)

Fixes for four faults an audit of 0.3.1 found: briefings that did not finish were never charged, a briefing in
progress was reserved at less than it can cost, short claims passed the check on unsupported sentences, and a
backup held the day's visitor secret beside the day's visitor codes. Nothing is renamed or removed.

api: 3edad3a164c9

### What a site must do

1. Raise its pin to the 0.3.2 wheel, and the shared workflows and actions to `@v0.3.2`, then `uv lock`
   ([`docs/UPGRADING.md`](docs/UPGRADING.md)).
2. Set `[usage] briefing_estimate_usd` to at least the most one briefing can cost: `[answer] max_tokens` of
   output at the briefing model's output price, plus what the model reads for the site's largest briefing. At
   16,000 tokens and $10 a million (claude-sonnet-5-5) the output alone is $0.16, more than the sites reserved
   under 0.3.1 ($0.15 on Where MPs Stand and Where Councils Stand, $0.10 on Where Countries Stand); they have since
   raised theirs to $0.30, $0.25 and $0.25. Until the setting is raised, the package reserves the output figure
   instead and says so in a warning at start-up. Where Landlords Stand has no briefings and nothing to set.
3. Expect its own tests to say what changed, and update them: the spending rows after a reader leaves or a
   model fails part-way (now an `unfinished` row), reports stamped `"rules": 2`, and short uncited claims now
   `unsupported` in golden reports. Run `<site> eval replay` on its recorded briefings: every difference it lists
   must be "stricter".
4. Read its privacy notice and its words for the daily limit: a briefing the reader leaves once the model has
   begun, or that the model breaks off, now counts towards that reader's limit, as it is paid for.

### Changed

- A briefing whose model was called but whose cost never reached the desk in an event (the reader left, the
  model's stream broke off, the site's pipeline failed after the call, or its error event carried no counts) is
  charged when it ends, in a row of kind `unfinished`. The model's adapter reports what each call has used as it
  goes (`briefing.Stages.model_call`, `briefing.ModelCall`): the Anthropic adapter takes the input from the API's
  first event and the output from its counts or, until it counts, from the length of what has been written
  (thinking included); `testing.ScriptedModel` does the same. A call nothing is known of yet, and a briefing
  whose model wrote through an adapter that reports nothing, is charged the estimate a briefing in progress is
  reserved at. `Spending.briefings_today` counts `unfinished` rows with `answer` rows, so they count towards the
  daily limits; the owner's reports still count only `answer` rows as briefings.
- A model call the spending record could not take (a locked database) no longer ends the reader's briefing: the
  error is logged, the call is tried again when the briefing ends, and a call that still cannot be written is
  logged as critical, as missing from the spending record. No log line holds the question or the reader's code.
- `desk_parts` never reserves a briefing in progress at less than `[answer] max_tokens` at the `[answer] model`'s
  output price, where both are set (`DeskSettings.most_output_usd`). An `[answer] max_tokens` that is not a number
  stops the site with the other faults in its settings.
- The checks on briefings are version 2 of the rules (`checks.RULES_VERSION`), stricter than version 1 in two
  places and nowhere weaker. A short uncited line that is a sentence of its own ("The minister took bribes.",
  "Labour voted against the bill") is a claim: it is still a join where it leads on to what follows (a comma, a
  colon), carries a cited sentence on to its close ("in September."), is a transition or label of a word or three
  ("By contrast", "In the Lords"), the site's words for no records, or a short note on what the records do not
  hold. And the looser signs of a note about the evidence ("the evidence is", "gaps", "caveats", a line opening
  "Note:") make a note only in a line about the records themselves ("the records retrieved", "the sources
  supplied", "no records", "the evidence base"). Over the seven real briefings recorded in the sites' checkouts
  and in this package, every uncited passage judged with each site's inputs, no passage changed. In the saved
  briefings of the sites' own tests one passage did, wherever it appears: a sentence of its own after a citation
  (`" The minister admitted that the organisation was at fault.`). A briefing saved under version 1 is judged
  again when it is shown, as before, which only ever clears a flag.
- A backup's copy of the state database holds no visitor secret (today's included) and no visitor's code: they
  are taken out of the copy, with `secure_delete`, before it is checked and packed (`ops.make_backup`). The live
  database keeps today's for the limits. A database restored from a backup starts a new secret, and its visitors
  start the day afresh. Where the backup cannot forget the days before today, what it says it holds now names
  accounts and times of day only.

### Added

- `briefing.ModelCall`, `Stages.model_call` and `Stages.model_calls`; `SpendingRecord.add(cost_usd=…)` and
  `InProgress.estimate_usd` (a site's own implementation of either, of which there are none today, needs them);
  `DeskSettings.most_output_usd`.

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
