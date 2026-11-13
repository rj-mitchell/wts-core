# ADR 0012: The record of each briefing, statistics, alerts and experiments

Status: proposed, for the owner's review. It decides what is kept about each briefing and for how long, and it
proposes one sentence for each privacy notice, so it is on the list to check first. 13 November 2026.

## Context

The brief (3.6, 3.7) asks that every briefing leave one record: how long each stage took, what it cost, what the
checks found, how it ended and what the reader did next; that a `stats` command and a weekly report turn those
records into a list of things to fix; that alerts fire when things get worse; that real questions can be proposed
as test questions; and that versions of the method can be tried side by side. All with **no new data about
readers**.

What the sites keep today, from their code and privacy notices:

- every briefing with its question, at its own address, "while the site runs, unless withdrawn" (all three);
- spending: one row per model call, with the day's visitor code (a salted hash that can't be linked to the next
  day's or turned back into an address);
- notes of failed briefings with the question and the error: deleted after 90 days on Where Countries Stand, as its
  notice says; the latest 500 kept on Where MPs Stand; not kept on Where Councils Stand;
- on Where MPs Stand: how often each question is asked per day, "Was this useful?" answers saved with the question,
  and daily counts of visitors who asked, followed up or opened a source;
- all three notices say "requests are not logged".

## The record

One row in `wts_briefing_log` per question asked, written once by the briefing desk when the briefing ends,
whichever way it ends.

| Group | Fields | Notes |
|---|---|---|
| Identity | `id` (random), `at` (to the second), `kind` (`reader`, `check` for the nightly question, `eval`) | no visitor code, no address, nothing from the request's headers |
| What was asked | `question`, `follow_up` (yes or no), `mode` (summary or comprehensive), `filters_set` (which filters the reader set, not their values) | the question is already kept with the saved briefing; see retention below |
| Configuration | `config_id`, `model`, `parse_model`, `instructions`, `package_version`, `site_version`, `experiment`, `arm` | `config_id` is the first 12 characters of a hash of the others plus the site's retrieval settings; the full settings behind each id are kept once in `wts_configs` |
| What went in | `sources`, `spread` (sources per group, as JSON: party, region or body), `input_tokens`, `cache_read_tokens`, `cache_write_tokens` | the spread is what the impartiality policy's principle 3 asks the site to show |
| What came out | `output_tokens`, `cost_usd`, `stop_reason` | |
| What the checks found | `citations_total`, `citations_invalid`, `grounded_ratio`, `unsupported`, `quotes_unverified`, `loaded_words` | straight from the verifier's report |
| Timings, in milliseconds | `t_parse`, `t_search`, `t_rank`, `t_sources_sent`, `t_first_token`, `t_written`, `t_checked`, `t_total` | measured by the desk from a monotonic clock |
| How it ended | `outcome`: `completed`, `cached`, `no_records`, `sources_only`, `paused_cap`, `paused_limit`, `busy`, `left` (with `left_at`: the stage), `error` (with `error_type`: the exception's class name, not its message) | exactly one per row |
| What happened next | `briefing_id` (the saved briefing), `useful` (yes, no or not answered), `reported` (a problem report names this briefing), `corrected` (it was later withdrawn or corrected), `followed_up` (a later question followed on from it) | filled in later by the routes that already receive these signals |

`followed_up` is a yes or no on the earlier row. The later question's row is **not** linked to the earlier one: a
chain of linked questions would be a record of one reader's session, which the sites don't keep today.

The phase 1b count of how often "Why use this rather than a chatbot?" is opened is a daily total in `wts_counts`
(`day`, `name`, `n`), the same shape as Where MPs Stand's existing daily page-view totals, with no visitor code.

## Retention

| What | Kept | Why |
|---|---|---|
| A row's `question` when `outcome` is `error` | 90 days, then blanked | Where Countries Stand's notice already promises this for failed briefings; the package applies the stricter promise on every site |
| The whole row | 13 months, then deleted [for the owner to confirm] | long enough to compare a month with the same month a year before |
| Weekly totals (`wts_weekly`: counts, rates, medians per week and configuration) | indefinitely | they hold no question text |
| Structured log files | 14 days or 50 MB a site, whichever is less, then rotated away | see below |

A nightly tidy (run by each site's update) applies these.

## Structured logs

One JSON object per line, the same shape on every site: `at`, `level`, `site`, `event`, `briefing` (the record's
id), `stage`, `ms`, `error_type`. Written to `data/logs/briefings.jsonl`, rotated by size, with the limits above.

**Never in a log line:** the question, any text of a briefing or a source, the visitor code, an address, a header.
With those out, a line says "briefing 4f2a… spent 310 ms ranking", which is a note about the site's work, not a
log of a reader's request. The contract tests include one that runs a briefing whose question is a canary string and
fails if the canary appears in any log line.

## Check against the privacy notices

| Field or file | Already described? | Verdict |
|---|---|---|
| `question`, `briefing_id` | Yes: "Each briefing is saved with its question" (all three) | within the notices. The 90-day rule for failed briefings is extended from Countries to all |
| Timings, token counts, cost, check results, outcome, configuration | Partly: Countries' notice mentions "the time and cost of each briefing"; MPs' and Councils' mention costs only as a purpose | about the site's work, not the reader; but the notices set out to list what is stored, so **one sentence should be added** (below) |
| `useful`, `reported` | Yes on MPs ("the answer is saved with the question"); reports on all | within the notices |
| `followed_up` | MPs counts follow-ups per day already | a yes or no on a briefing, not a link between questions: within the notices |
| Structured logs | The notices say "requests are not logged" | the log holds nothing from a request (see above). To keep the sentence plainly true, the added sentence says what the technical log is |
| Visitor code | Not stored in the record at all | no change. It stays in the spending rows as today, for the daily limit |
| Experiments | The arm is chosen by chance for each briefing; nothing is stored to keep a reader in a group | no new data |

**The sentence proposed for each site's privacy notice,** to go in with the adoption pull request (phase 4), under
"Your questions and the briefings written for them":

> For each briefing the site also notes how long each step took, what it cost and what the automatic checks found,
> so that slow or poorly checked briefings can be found and fixed. These notes hold nothing that identifies you;
> they are kept for 13 months, and the question of a briefing that could not be written is removed from them after
> 90 days.

This goes slightly beyond what Where MPs Stand's and Where Councils Stand's notices describe today, so under the
brief's rule it **needs the owner's agreement before it is switched on** on those sites. Nothing in phase 3
(building the package) collects anything; the question arises at each site's adoption.

## Statistics, the weekly report and alerts

- `<site> stats --since 7d [--json]`: everything in the brief's list (3.7), each figure beside the same figure for
  the previous four weeks. Question themes are grouped with the site's own embedder, through the `Embedder` port,
  so no question leaves the server.
- **The weekly report** is the same command's output saved to `data/reports/<year>-W<week>.md` and `.json` by a
  timer in the site's `deploy/` (added at adoption), and its totals written to `wts_weekly`.
- **Alerts:** thresholds under `[alerts]` in each site's settings for p95 time to the full briefing, error rate,
  check-failure rate, "not useful" rate and daily cost. `<site> stats --check` exits non-zero and prints what
  tripped, so the existing `OnFailure=alert@` route emails it. It runs after the weekly report and after each
  update. **Thresholds start unset:** the first weekly report proposes values from that week's baseline (its figure
  plus a margin), and the owner writes them into settings. An alert never fires from a guessed number.

## Experiments

One declared in settings at a time (`[experiment]`: name, the versions and their share of traffic, start and end
dates, the statistic that decides it). The record's fields and the cache key's part for the version are in
`v0.1.0`; the switch itself arrives in `v0.2.0`, once a site has a baseline and its public wording allows it (the
brief's 3.7). The package enforces the policy's principle 6:

- an arm is chosen at random for each briefing, from the `Random` port, with no cookie, account or stored
  identifier; the nightly check's and the evaluation harness's briefings are never in an experiment;
- the arm is in the record (`experiment`, `arm`, `config_id`) and in the answer cache's key, so versions never
  serve each other's answers, and a saved briefing always shows what was originally shown;
- **an arm can't be switched on unless it has passed:** start-up refuses an experiment whose arm has no passing
  evaluation run recorded in the site's `eval/runs/` for that exact `config_id`, with every check and balance
  threshold met;
- `stats` reports each arm side by side and says "too few briefings to tell" until a difference is unlikely to be
  chance (a two-proportion or rank test at a stated level, the test named in the output);
- a second `[experiment]` while one is running is a start-up error.

## Options considered

- **Derive everything from what is stored today** (spending rows, saved briefings). No timings, no outcomes for
  briefings that weren't saved (errors, caps, readers leaving, no records), so most of the brief's list can't be
  answered.
- **An outside analytics or tracing service.** Sends data about use to a third party; against the sites' promise of
  no third-party analytics.
- **Link each row to the visitor code** to study sessions. Rejected: new data about readers.
- **One row per briefing, written by the desk, with nothing about the reader (chosen).**
