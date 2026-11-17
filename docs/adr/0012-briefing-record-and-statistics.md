# ADR 0012: The record of each briefing, statistics, alerts and experiments

Status: accepted, 13 November 2026.

This record decides what is kept about each briefing, for how long, and what the package promises about tying it
to a reader. It also sets out how statistics, alerts and experiments use the record.

## Context

The sites need to know how each briefing went (how long each stage took, what it cost, what the checks found, how
it ended and what the reader did next), so that they can be measured and improved. They must do it with no new
data about readers. Before the package the sites kept: each briefing with its question, at its own address;
spending, one row per model call with the day's visitor code; notes of failed briefings; and, on Where MPs Stand,
daily counts of visitors and "Was this useful?" answers. Every privacy notice said "requests are not logged".

Considered and rejected: deriving everything from what was already stored (no timings, and no outcome for a
briefing that was never saved); an outside analytics or tracing service (data about use sent to a third party);
and linking each row to the visitor's code to study sessions (new data about readers).

## Decision

### The record

One row in `wts_briefing_log` for each question, written once by the briefing desk when the briefing ends,
whichever way it ends.

| Group | Fields |
|---|---|
| Identity | `id` (random), `at` (the hour the question was asked), `kind` (`reader`, `check` for the nightly question, `eval`) |
| What was asked | `question` (see retention), `follow_up`, `mode`, `filters_set` (which filters were set, never their values) |
| Configuration | `config_id`, `model`, `parse_model`, `instructions`, `package_version`, `site_version`, `experiment`, `arm`. The settings behind each `config_id` are kept once in `wts_configs` |
| What went in | `sources`, `spread` (sources per group: party, region or body), token counts |
| What came out | `output_tokens`, `cost_usd`, `stop_reason` |
| What the checks found | `citations_total`, `citations_invalid`, `grounded_ratio`, `unsupported`, `quotes_unverified`, `loaded_words` |
| Timings, in milliseconds | `t_parse`, `t_search`, `t_rank`, `t_sources_sent`, `t_first_token`, `t_written`, `t_checked`, `t_total` |
| How it ended | `outcome`: `completed`, `cached`, `no_records`, `sources_only`, `paused_cap`, `paused_limit`, `busy`, `left` (with `left_at`, the stage), `error` (with `error_type`, the exception's class name) |
| What happened next | `briefing_id`, `useful`, `reported`, `corrected`, `followed_up` |

No row holds a visitor code, an address or anything from the request's headers. `followed_up` is a yes or no on
the earlier briefing: the later question is not linked to it, since a chain of linked questions would be a record
of one reader's session. Daily totals of things like how often a disclosure is opened go in `wts_counts`, with no
visitor code.

### Retention

| What | Kept |
|---|---|
| A row's question, for `completed`, `cached` and `no_records` | as long as the row: the site already keeps it with the saved briefing or the cached answer |
| A row's question, for `error` | 90 days, then blanked, as for the note of a failed briefing |
| A row's question, for `sources_only`, `paused_cap`, `paused_limit`, `busy` and `left`, and for a refused request whose search failed | never: the site keeps such a question nowhere else |
| The whole row | 13 months (the owner's decision, 13 November 2026), long enough to compare a month with the same month a year before |
| Weekly totals (`wts_weekly`) | indefinitely: they hold no question |
| The structured log | 14 days or 50 MB a site, whichever is less |

The nightly `tidy` applies these.

### The structured log

One JSON object per line: `at`, `level`, `site`, `event`, `briefing` (the record's id), `stage`, `ms`,
`error_type`. `event` and `stage` come from fixed lists and the id has one fixed shape, so nothing a reader typed
can be written there. Never in a line: the question, any text of a briefing or source, the visitor code, an
address or a header. A line says "briefing 4f2a… spent 310 ms ranking": a note about the site's work that holds
nothing of the reader's request. A contract test asks a question containing a marker and fails if the marker reaches
any log line.

Each site's privacy notice says what the record keeps. The sentence is in
[`NEW-SITE.md`](../NEW-SITE.md#11-privacy-and-accessibility-statements).

### What is kept about spending, and what can be promised

The record shares its token counts and cost with the spending rows. If a spending row kept its time and whose it
was for good, the two could be joined to give back who asked each briefing and when. Two independent reviews
showed this, the second against the package's first attempt to prevent it. So, once a day is over
(`usage.forget_earlier_days`, run by the next day's first model call and by the nightly `tidy`):

- a spending row keeps its day with no time, no visitor code, no account and no mark that it was an account's;
- each signed-in account keeps one line per calendar month: its calls, its cost to the cent, and how many visitor
  codes it was seen with (`wts_account_months`);
- the record of a briefing keeps the hour it was asked (hours, because the statistics take periods of hours).

Spending rows are never deleted, since they are the site's account of what it spent. The shared `backup` command
does the same forgetting in the database before it copies it, so a backup holds nothing of earlier days that the
live file does not.

Promised, and tested as stated by `testing.assert_briefings_tied_to_no_one`: once its day is over,

1. a record of a briefing is beside no row that says whose it was, or that it was an account's;
2. no time finer than the record's own hour can be given back to it from the spending rows;
3. about an account and a time gone by, the package keeps one line a calendar month, to the cent, and nothing
   finer.

Not promised, because it is not so:

- Today's rows. While its day lasts a spending row holds the visitor code, the account and the time, for the
  daily limits. A backup holds its own day's rows so far (on the sites' schedule, midnight to about half past
  four) until the backup is deleted.
- A month in which an account's briefings were the only ones, or nearly so, such as the first day or two of a
  month: the account's month total is then plainly the sum of its own records.
- A site on which everyone signs in. Taking a single day, the accounts' totals give away a third to a half of the
  briefings with two or three accounts, and a few in a hundred with nine. No site of the family requires sign-in.
- A briefing whose cost is unlike any other that month, which its account's total alone gives away.
- Two backups from different nights: the difference between an account's month in each is what it spent between
  them, which is the single-day case above.
- A record's second, from three tables that keep the time something was stored, each holding nothing about who:
  the answer cache (168 hours on every site), the note of a failed briefing (90 days), and the saved briefing
  (for good, as each site always kept it, since a page shows it).
- The structured log, for its 14 days: each line has a record's id and the second it was written.
- Whatever a site keeps of its own, which its own privacy notice describes.

What the attack still gets is measured by `scripts/measure_account_split.py`, which goes through every way of
making up each account's kept total from the records of its month (`testing.split_by_account_totals`). With one
to nine accounts among 30 to 60 visitors, it gives no briefing to any account, on a month one day old or of
twenty days. With few visitors (one account among two to ten, or three among five to ten) it gives back up to 14
of an account's 49 briefings in a month one day old, and none over a month of twenty days unless an account is
alone. It never gave a briefing to the wrong account. The attack is in the package so that the next change to
what is kept is measured the same way before it is released.

### Statistics, the weekly report and alerts

- `<site> stats --since 7d [--json]` gives every figure beside the same figure for the four weeks before.
  Question themes are grouped with the site's own embedder, so no question leaves the server.
- The weekly report is the same output saved to `data/reports/<year>-W<week>.md` and `.json` by a timer, with its
  totals in `wts_weekly`.
- Alerts are thresholds under `[alerts]` in each site's settings (p95 time to the full briefing, error rate,
  check-failure rate, "not useful" rate, daily cost). `<site> stats --check` exits non-zero and says what tripped,
  so the server's alerting emails the owner. Thresholds start unset: the first weekly report proposes values,
  and the owner writes them in. An alert never fires from a guessed number.

How to read and act on them is in [`IMPROVING.md`](../IMPROVING.md).

### Experiments

A site may run one experiment at a time, declared in settings (`[experiment]`: name, arms and their shares, first
and last day, and the rate that decides it). It keeps the impartiality policy's principle 6:

- each reader's briefing is given an arm at random (`ports.Random`), with no cookie, account or stored
  identifier. The nightly check's and the evaluation harness's questions are never in an experiment, and nor is
  a question outside the experiment's dates;
- the arm is in the record (`experiment`, `arm`, `config_id`) and in the answer cache's key, so arms never serve
  each other's answers, and a saved briefing always shows what was originally shown;
- an arm may change only the model, the instructions' version and a `variant` word the site's pipeline reads.
  Any other key is refused, so a check, the loaded words, a threshold or the balance of sources cannot differ;
- an arm that changes anything runs only after an evaluation run of exactly its configuration has passed the
  site's thresholds on the whole test set (`eval.has_passed`), and only if its model has a price table of its
  own;
- while an experiment runs, a briefing whose report lacks any check's figure is not shown, saved or cached;
- a fault in the declaration never stops the site. The experiment does not run, an error names what is wrong,
  the check route reports it, and `stats --check` fails so the owner is told;
- the statistics give each arm's figures side by side and one of three verdicts on the deciding rate: too few
  briefings to tell, no difference chance could not explain, or a difference at the stated level. They name no
  winner: a person decides.

`tests/test_briefing_experiment.py` tests each rule, and the example site's `tests/test_experiment.py` runs one
end to end.

## Consequences

- The sites can be measured and improved from the first day, with nothing new kept about readers.
- What is kept about spending is coarser than the sites kept before the package. Nothing a reader sees changes.
