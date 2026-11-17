# Improving the sites: the weekly routine

How the maintainer of the Where They Stand sites reads each site's weekly report and turns it into a better site:
the routine, every statistic, alerts, the test sets and experiments. It assumes no background in statistics:
where a number can mislead, it says how.

Every AI site built on this package keeps one record of how each briefing went: how long each step took, what it
cost, what the checks found, how it ended and what the reader did next. Nothing in it says who asked
([ADR 0012](adr/0012-briefing-record-and-statistics.md)). From that record the site writes a report each week.
This page is how to turn the report into a better site, a little each week, without ever weakening what makes the
sites worth using.

The commands are the same on every site; `<site>` below is the site's own command (`hansard`, `wcs`, `councils`).
A site may have renamed one (Where Countries Stand has a `stats` of its own): its README says.

## The routine, in one page

Once a week, for each site:

1. Read the report. `data/reports/<year>-W<week>.md` on the server, written by the weekly timer. Start with
   "Alerts", then the four numbers in [where to start](#where-to-start).
2. Pick the one problem that reaches most readers. Slow, wrong or flagged, nothing found, and not useful are
   roughly in order of how often each turns out to be fixable. Work on one problem at a time.
3. Change one thing, in the site's own code (retrieval, ranking, instructions, how sources are set out: they
   are the site's, not the package's), in one pull request.
4. Measure before it ships. An evaluation run on the site's test questions with the change and without it
   (`<site> eval run`, `<site> eval compare`). The run is held to the site's thresholds; a change that fails one
   does not ship. If the change touches the checks themselves, `<site> eval replay eval/fixtures` first: it is
   free, and it fails if any check has become weaker.
5. Release it, and write one line in the site's `DECISIONS.md` or its changelog: what changed and why.
6. Measure after. The next week's report sets the new configuration beside the old one ("By
   configuration"). If the number the change set out to move has not moved, say so in the same place, and either go
   back or try the next idea. A change that did not help is a result too: record it so that it is not tried
   again in six months.
7. Grow the test set. `<site> propose-questions` now and then; approve the good ones by hand
   ([below](#growing-the-test-sets)).

A week with nothing worth changing is a good week. Do not change things to have changed them.

## Where to start

Four numbers say most of what a week was like. Each is in the report's first tables.

| Look at | Where | Worry when |
|---|---|---|
| The share of checked briefings in which a check found a problem | "What the checks found", first row | it rises against the weeks before, with at least 20 or so briefings checked |
| The time within which 95 in 100 briefings were fully written | "How long it took", the row "Until the full briefing", the column "95 in 100 within" | it is longer than a reader should wait, or has grown |
| The share of questions that found no records | "How readers fared", first row | it rises: a gap in coverage, or questions being read badly |
| What briefings cost a day | "What it cost", the row "A day" | it nears the daily cap in the site's settings |

Then read the two lists that quote real questions: "Questions that found no records" and "The worst-checked
briefings". They are where next week's change usually comes from.

## Reading a number without being fooled by it

Three habits cover nearly everything.

Look at how many it was counted in. Every rate in the report is written as a share *and* a count: "12.5% (2
of 16)". Read the count first. Two in sixteen is two briefings: one more or one fewer next week would make it
6% or 19%, and nothing would have changed. As a rule of thumb, a rate counted in fewer than about 20 is a list of
individual cases (go and read them), one counted in 20 to 100 moves by several percentage points from week to
week on its own, and only above a few hundred does a change of a point or two mean something.

Compare like with like. Each figure sits beside the same figure for the four weeks before. That earlier
period is four times as long, so its *counts* and *costs* are also given "at that rate" (scaled down to one
week). Its *rates*, *medians* and *times* need no scaling: compare them directly. A quiet week (a holiday, a
recess) has few questions of an unusual kind; do not read much into it.

A median and a "95 in 100" are different questions. The median is the middle briefing: half were quicker.
The "95 in 100 within" figure (the 95th percentile, or p95) is the slow end: one reader in twenty waited longer
than that. A site can have a fine median and a poor p95: most readers are happy and a few are waiting a minute.
Improve the p95 by finding what the slow ones have in common ("The slowest briefings" lists them), not by
shaving the median. With fewer than 20 briefings the p95 is simply the slowest one that week.

What counts as noise, in one place: a rate moving by less than a few points on under a hundred briefings; a
p95 on under 20 briefings; one very slow or very dear briefing in a quiet week; any single week against any
other single week. What does not count as noise: the same movement three weeks running; a change that
starts in the week a configuration changed; a jump in errors of one type.

## Every statistic, one by one

The names in `code type` are the names in the report's JSON file (`<year>-W<week>.json`, under `stats`) and in
`<site> stats --json`: the fields of `wts_core.observe.Stats` and of its two periods, `period` (this week) and
`earlier` (the weeks before). Each entry says what the number is, what moves it, and what is only noise.

### The period

- `since`, `until`, `start`, `end`, `days`: the period the figures are for, in UTC. A record keeps the hour a
  question was asked in and no finer, so a period is whole hours.
- `compare_weeks`: how many weeks before the period it is compared with (four).
- `scale`: what to multiply an earlier count or cost by to compare it with this period (a quarter, for one week
  against four). The report does this in the "At that rate" column.

### How the questions ended

- `questions`: readers' questions asked. Moved by how many people came, and rarely by any change to the site.
- `by_outcome`: how many ended each way. Every question ends exactly one way:
  - `completed`: a briefing was written. The outcome that costs money and that the checks run on.
  - `cached`: answered from the answer cache, at no cost. See `cache_hits`.
  - `no_records`: the site found nothing in the record. See `no_records`.
  - `sources_only`: the reader asked for the sources without a briefing, or there was no model to write one.
  - `paused_cap`: a spending cap had been reached, so the sources were shown with a note. More than a handful
    in a week means the cap is too low for the traffic, or something is costing more than it should.
  - `paused_limit`: the reader had reached their own daily limit.
  - `busy`: too many briefings were being written at once. A few at a busy moment is the limit doing its work;
    many means the limit is too low or briefings are too slow.
  - `left`: the reader went before the briefing was finished. See `left`.
  - `error`: something failed. See `errors`.
- `by_kind`: readers' questions (`reader`), the nightly check's own question (`check`) and evaluation runs'
  (`eval`). Every other figure is for readers' questions only, so the check and the test runs never colour them.

### How long it took

Times are from the moment the question arrived, for questions *not* answered from the cache, over those that
reached each point. Each is given as how many were measured (`n`), the `median` and the `p95`.

- `times`: the time until each point was reached:
  - `t_parse`: the question was read (by the small model, or by the site's own rules).
  - `t_search`: the search was done. Moved by the index and the embedder.
  - `t_rank`: the sources were chosen.
  - `t_sources_sent`: the reader could see the sources. This is the first thing a reader sees: keep it short.
  - `t_first_token`: the briefing's first words. The wait a reader feels most. Moved by how much is sent to the
    model (the sources' length), by the model, and by whether the instructions were read from the prompt cache.
  - `t_written`: the full briefing. Moved by the length of the briefing and by the model's speed that hour.
  - `t_checked`: the checks were done. Milliseconds; if it grows, something is wrong in the site.
  - `t_total`: everything was finished, saving included.
- `steps`: the same points, as the time each *step* took from the point before. This is the table that shows
  where a slow briefing spent its time. "Waiting for the first words" and "Writing" are the provider's
  time and move with its load from hour to hour: a slow day there is not the site's doing. "Searching" and "Ranking"
  are the site's own, and steady: a change there is real.
- `cached_total`: how long an answer from the cache took. It should be a fraction of a second.
- `slowest`: the five slowest briefings, each with its question where the briefing is saved and still stands.
  Read them. If they are all one kind of question (a long date range, a broad topic), that is the thing to fix.

What is noise here: the provider's speed varies by the hour and the day, so a p95 "to the full briefing" can
move by several seconds between weeks with nothing changed. Judge it over three or four weeks, or compare two
configurations in the same week.

### What it cost

In US dollars, as the provider prices its tokens.

- `cost_usd`: the period's cost of readers' questions.
- `cost_per_written_usd`: the cost of a briefing that was written. The number to watch when changing how many
  sources are sent or which model writes. It should be steady from week to week: it moves only when the
  configuration does, or when questions of a dearer kind (the comprehensive mode) become commoner.
- `cost_per_question_usd`: the cost of a question asked, cached and refused ones included. It falls when the
  cache is hit more; it says little on its own.
- `cost_per_day_usd`: the period's cost over its length in days, quiet days included. This is what the daily
  cap is set against, and what the `daily_cost_usd` alert watches.
- `cost_by_day`: each day's cost. Look for a single day far above the rest: one visitor asking a great deal, or
  a fault that repeats a call.

### The answer cache and prompt caching

- `cache_hits`: the share of questions answered from the answer cache (the same question, asked again within the
  site's cache hours). Moved by how often readers ask the same things (featured questions on the home page are
  asked a lot) and by how often the record changes: a new day's data makes every key new. A fall after a
  release is expected, since a change of model or instructions empties the cache by design.
- `prompt_cache`: whether the provider's prompt caching paid for itself. Reading instructions from its cache is
  cheaper than sending them; writing them to it is dearer. `read_tokens` and `write_tokens` are how many tokens
  went each way, `saved_usd` what the reads saved, `extra_usd` what the writes cost over plain input, and
  `paid_back` whether the first is the greater. On a quiet site questions come more than five minutes apart,
  the cache is written and never read, and caching costs money: if `paid_back` is false for a month, turn it
  off or try the longer cache lifetime, with an evaluation run either side.

### What the checks found

Over the briefings whose checks ran. These are the numbers the sites exist for: a briefing with a problem is
shown to the reader with the problem marked, so a rise here is a rise in briefings readers must check for
themselves.

- `any_check`: the share in which any check found a problem. The headline, and what `check_failure_rate` watches.
- `invalid_citation`: a citation whose quoted words are not in the source it points to. The gravest: it should be
  at or near nought. If it rises, look at how sources are cut into passages.
- `unsupported`: a sentence that states a claim with no citation. The commonest. Moved by the instructions and
  by the model.
- `unverified_quote`: words in quotation marks that are not found word for word in a cited source.
- `loaded_word`: a judgemental word in the site's own voice (from the site's own list).
- `worst_checked`: the five briefings with the most problems, the least grounded first among equals. Read them
  before changing anything: three briefings with the same fault are a pattern; five unlike ones are chance.

What moves these: the model (a new model version at the provider can move them with no change of yours, which is
what the weekly evaluation run is for), the instructions, and the sources chosen. What is noise: with 30
briefings checked in a week, one or two more or fewer with a flag is the ordinary scatter.

### How readers fared

- `no_records`: the share of questions for which the site found nothing. Some are right (the record really has
  nothing); others are a question read wrongly or a gap in what the site holds. `no_record_questions` lists them
  (up to 20, the most asked first): read the list, and sort it into "truly nothing" and "should
  have found something".
- `not_useful`: of the briefings readers rated, the share rated not useful. Few readers rate anything, so this is
  nearly always counted in a handful: treat each one as a letter from a reader, not as a rate, until there are
  dozens. Watched by `not_useful_rate`.
- `left`: the share of questions whose reader went before the end. `left_at` says at which stage they had got
  to. Readers who leave while the briefing is being written, on a slow day, point to its speed; those who leave
  before the sources are shown point to the wait for anything at all.
- `reported`: of saved briefings, the share a reader sent a problem report about.
- `corrected`: of saved briefings, the share since withdrawn or corrected. Each one is in the site's public
  corrections log already; this is the count.
- `followed_up`: of saved briefings, the share after which a follow-up question was asked. Not good or bad in
  itself: it may mean the briefing invited another question, or failed to answer the first.

### Errors

- `errors`: the share of questions that ended in an error. Watched by `error_rate`.
- `errors_by_type`: how many of each type, by the error's class name. One type suddenly common is one fault:
  the provider overloaded, a key expired, an index missing. The site's log has the rest (never the question).

### Themes

- `themes`: the commonest questions, grouped (`themes_by` says how: by `meaning`, with the site's own embedding
  model, or by `text`). Each has an example wording, how many times it was asked and in how many wordings. This
  is what readers come for. A common theme that the site answers badly is worth more than any other fix; a
  common theme is also a candidate for a featured question.

### By configuration, and the experiment

- `headline`: the short list of figures for the whole site (`questions`, `written`, `first_token`,
  `full_briefing`, `cost_per_written_usd`, `cache_hits`, `any_check`, `no_records`, `not_useful`, `left`,
  `errors`), as they are kept for good in the weekly totals.
- `by_config` and `by_config_earlier`: the same short list for each configuration id, this period and before.
  This is how to see whether a change helped. Every release that changes the model, the instructions, the
  retrieval settings or the package's version has a new configuration id; the week of the release shows the old
  and the new side by side.
- `experiment`: whether the site's experiment is running, and if it is not, why
  ([below](#running-an-experiment)).
- `by_arm`: the short list for each arm of an experiment.
- `decided_by`: the rate the experiment is decided by, and `arms`: each pair of arms compared on it, with a
  `verdict` that is one of three words: `too_few` (not yet enough briefings for the comparison to be made at
  all), `no_difference` (made, and a gap this size could well be chance) or `different` (unlikely to be chance).

## Alerts and thresholds

Five figures are watched, under `[alerts]` in each site's settings: `p95_full_briefing_ms`, `error_rate`,
`check_failure_rate`, `not_useful_rate` and `daily_cost_usd`. When a figure is over its threshold the weekly
report says so in a plain sentence and its timer fails, so the server's own alerting emails the maintainer. The
same check runs after each update (`<site> stats --check`).

Setting them the first time. Thresholds start unset, and an alert never fires from a number nobody chose.
The first weekly report with real traffic proposes a value for each: that week's figure plus a quarter. Do not
copy them in blindly:

- wait for two or three weeks of reports and take the *worst* ordinary week as the baseline, not the first;
- a rate counted in few briefings needs more room than a quarter: if 2 of 16 were flagged, a threshold of 16%
  will fire on 3 of 16, which is no change at all. Set it where a change is truly worth being told of;
- `daily_cost_usd` should sit below the site's daily cap, so that the maintainer hears before readers are turned away.

Write them into the site's `config/settings.toml` in a pull request, with the week they were taken from in the
commit message.

Reviewing them. Look at them again whenever one fires, and at least every quarter:

- an alert that fires and turns out to be nothing, twice, is set too tight: loosen it, and say why in the commit;
- after a change that makes a figure lastingly better, tighten its threshold to the new normal plus a margin, so
  that sliding back is noticed;
- never loosen `check_failure_rate` to stop it firing while the briefings it counts are still flagged. That
  alert is the one that says the site is getting worse at its own job.

The evaluation harness has thresholds of its own, under `[eval.thresholds]` (`min_grounded_ratio`,
`max_invalid_citations` and the like). They are set the same way, from the first full run of the site's test
set, and they are what a change must meet before it ships. They may be tightened when the site improves. They
are not loosened to let a change through.

## Growing the test sets

Each site's test questions are in its `eval/questions.toml`. A test set that never changes slowly stops
resembling what readers ask. Real questions join it like this:

1. `<site> propose-questions --since 30d` writes a file under the site's data folder (it prints the path) with
   up to ten questions of each of three kinds: those that found no records, those a reader rated not
   useful, and those whose briefings the checks flagged most. Only questions the site already keeps are
   proposed: of saved briefings that have not been withdrawn, corrected or reported and are not hidden while a
   concern about them is decided, and of questions that found no records. Never a question whose briefing
   failed, a request for the sources only, or one a limit stopped. The file is deleted by the nightly tidy
   once the oldest question it could hold is older than the record of briefings is kept (13 months).
2. The maintainer reads the file. Email addresses, web addresses and long numbers have been replaced with `[removed]`;
   a name can only be spotted by a person. Drop or reword any question that names a private individual.
3. For each question worth keeping, the maintainer says what a careful reader would expect: the filters it should be
   read as (`[q.expect]`), or `no_records = true` where finding nothing is the right answer, or the sources
   that must be among the evidence (`include`), as the site's other questions do. Give it an id and a category.
4. The maintainer copies it into `eval/questions.toml` by hand, in a pull request. Nothing else puts a question
   there.
5. Make an evaluation run with the new questions in the set. If the run now fails a threshold, that is the
   question doing its work: it has found something the old set missed. Fix the site, not the threshold; if the
   question is simply beyond what the record holds, mark it `no_records` or take it out again.
6. Delete the proposals file when finished with it (the nightly tidy deletes it after 13 months anyway).

Aim for a set that grows by a handful of questions a month and covers what the themes say readers ask. A set of
30 good questions is worth more than 300 unread ones, and every question costs a few pence each time the set is
run.

When the set is run. On every change that could alter a briefing (step 4 of the routine); and once a week
against the site as it stands, by a timer where the site has one, to catch the provider's model changing
underneath. A weekly run that suddenly fails with no change to the site is that. Each run costs money and never starts
without a limit (`--max-cost`, or the site's `[eval] max_cost_usd`); where the site passes its spending record,
the run's cost shows in the site's spending and counts towards its caps.

## Running an experiment

Most changes need no experiment. Measure them with the evaluation harness before release, and by period after
it ("By configuration"): that is cheaper, and it is how nearly every change should be judged.

An experiment is for the question the harness cannot answer: what readers do. Whether readers find briefings
written one way more useful than another, or leave less often, or ask more follow-ups, can only be seen on real
questions. Two versions run side by side, each briefing given one or the other by chance.

Do not run one when:

- the evaluation harness can settle it (speed, cost, what the checks find on the test set): use the harness;
- the site has too little traffic to tell. As a rough guide: to see a rate move from 10% to 5% needs some
  four hundred briefings in each arm; from 20% to 10%, about two hundred. If the site writes 30 briefings a
  week, an experiment on a rated-not-useful rate will never finish. The report says "not yet enough briefings to
  tell a difference" until there are; if it will say so for a year, do not start;
- an election or a referendum is under way (the impartiality policy, section 6: nothing new is launched then);
- another experiment is running on that site. One at a time.

How to run one.

1. Decide the one thing that differs, and the one rate that will decide it (`decided_by`: one of `cache_hits`,
   `any_check`, `no_records`, `not_useful`, `left`, `errors`), before looking at any figures. Write both
   down in the site's `DECISIONS.md` now.
2. Declare it in the site's settings (`[experiment]`: its name, its arms and their shares, its first and last
   day, and that rate). The first arm is the control: the site as it stands. Another arm may change the model,
   the version of the instructions, or one variant word that the site's pipeline reads, and nothing else. It
   cannot change a check, the loaded-words list, a threshold or how sources are balanced: the package refuses
   such a key ([`EXTENDING.md`](EXTENDING.md#48-an-experiment)).
3. If an arm names another model, give that model a price table of its own first
   (`[usage.models."<name>"]`): without one the arm is not run, and its evaluation run is refused, because its
   briefings would be costed at the site's own model's prices and the spending caps would count them wrongly.
4. Make an evaluation run of each arm that changes anything: `<site> eval run --arm <name>`. An arm that has
   not passed, on the whole test set, under the site's thresholds as they stand, never goes live: the site
   starts on its control alone and says why.
5. Deploy. `<site> stats` now has a section "The experiment": whether it is running, each arm's figures side by
   side, and the comparison on the deciding rate. If the experiment is declared and not running,
   `<site> stats --check` fails and says why.
6. Leave it alone until its last day. Looking every day and stopping the moment one arm is ahead is the
   surest way to be fooled: early leads come and go. The dates are in the settings so that the end is decided
   before the start.
7. On its last day, read the section. The comparison gives one of the following, and never "this arm won":
   - *not yet enough briefings to tell a difference*: the experiment has said nothing. Run it longer if
     the traffic will get there; otherwise stop, and keep the control;
   - *no difference can be told*: a gap this size could well be chance. Keep whichever arm is better on the
     figures already trusted (cost, speed, the checks), which is usually the control;
   - *the difference is unlikely to be chance*: read each arm's *other* figures before deciding. An arm that
     readers rate more useful and whose briefings are flagged more often is not an improvement.
8. The owner decides, and the decision and its reasons go in the site's `DECISIONS.md`. Release the version
   chosen (or keep the site as it is) and take `[experiment]` out of the settings. The statistics never
   declare a winner, and nothing switches itself.

What an experiment never does: it does not follow a reader. The version is chosen afresh for each briefing, with
no cookie, account or stored identifier, so the same reader may be given both. Every version is recorded with
its briefing, each saved briefing shows what was originally shown, and no version is served another's cached
answer.

Before a site's first experiment, check its public wording: where a page says the same question always returns
the same sources, reword it to say that this holds within a version of the method, and that versions may be
tried side by side.

## Limits on the routine

These limits are never traded for a better number.

1. Never weaken a check. Not the verifier, the loaded-words list, the spelling rules or the balance of
   sources, even for one release, one arm of an experiment or to quieten an alert. A check is
   changed only to make it stricter or more exact, with `eval replay` showing that nothing once flagged is now
   passed. If a check flags too much, the briefings are at fault, or the check is wrong in a way that can be shown
   on recorded briefings: say which in the pull request.
2. Never collect anything new about readers. No cookie, no account for the purpose, no address, no
   analytics service, no linking of one question to the next. The record holds no visitor's code and keeps the
   hour, not the moment; a spending row says who it was for, and what time of day it was made, for its own day
   only, and then not even whether it was a signed-in account's. If an idea needs to
   know who a reader is or what else they asked, it is not an idea for these sites. If anything would be kept
   that the privacy notices do not describe, stop and ask the owner, with the notice's new wording drafted.
3. Never spend past the evaluation budget. Every run has a limit; the family's budget for evaluation and
   test questions is about £20 in all without the owner's word. A weekly run on three sites adds up: check what
   a run costs (`cost_usd` in its summary) before putting it on a timer, and prefer a smaller set run weekly to
   a large one run once.

And one habit: one change at a time. Two changes in one release cannot be told apart in the next report, and
the routine is only worth its time if each week's report can answer "did that help?".

## Where things are

| For | Command or file |
|---|---|
| This week's figures, now | `<site> stats --since 7d` (add `--themes` to group questions by meaning; `--json` for the numbers) |
| The weekly report | `data/reports/<year>-W<week>.md` and `.json`, written by `<site> weekly-report` |
| What is over its threshold | `<site> stats --check` (ends with status 1 if anything is) |
| Thresholds for alerts | `[alerts]` in `config/settings.toml` |
| Thresholds a change must meet | `[eval.thresholds]` in `config/settings.toml` |
| A run of the test set | `<site> eval run`; of an experiment's arm, `<site> eval run --arm <name>` |
| Two runs side by side | `<site> eval compare <earlier> <later>` |
| The checks on recorded briefings, free | `<site> eval replay eval/fixtures` |
| Proposed test questions | `<site> propose-questions --since 30d` |
| The test set | `eval/questions.toml` |
| An experiment | `[experiment]` in the settings; its state in `<site> stats` |
| What every figure is, exactly | `wts_core/observe/figures.py`, whose docstring says how each is worked out |
