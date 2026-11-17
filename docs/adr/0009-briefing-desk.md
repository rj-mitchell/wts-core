# ADR 0009: The briefing desk: one request flow, with each site's steps hung on it

Status: accepted, 13 November 2026.

This record decides that the package runs the flow of every briefing from question to last event, with each
site's own steps hung on it.

## Context

In each AI site, about a hundred lines of `api/app.py` took a question from arrival to the last event. Read side
by side, the three were the same flow:

1. Count the request against the rate limit; work out the visitor's code.
2. Work out the answer cache's key and look for a cached answer.
3. If there is none, check the caps (this visitor's daily limit, today's spending, this month's).
4. Reserve a place among the briefings in progress, and check the caps again counting the others.
5. Run the site's pipeline, passing its events to the reader as they come.
6. As events pass: record the cost, note a failure, save the finished briefing at its own address, keep what is
   needed to replay it.
7. Put the replay in the answer cache.
8. If a cap or limit stopped the briefing, send the sources anyway with a note saying why, at no cost.
9. Whatever happens, release the place reserved in step 4, and stop the model if the reader leaves.

Each site hung its own steps on it: Where MPs Stand records a third cost and adds a note for one reader only;
Where Countries Stand judges a cached answer's flags again by the current rules; Where Councils Stand takes the
token counts out of what it sends. And every outcome worth recording for a briefing (completed, from the cache,
no records, paused by a cap, the reader left, an error) is decided in this flow and nowhere else.

## Options

1. Share the parts (limiter, caps, cache, cost, streamer) and let each site keep its flow. Each site would then
   add the same timing and outcome recording by hand, in code that had already drifted.
2. A framework: the package owns the `/api/ask` route. That takes web routes away from the sites.
3. A briefing desk in the package that owns the flow but not the route.

## Decision

Option 3. `briefing.BriefingDesk` is built once per site from the shared parts and the site's wording
(`briefing.desk_parts` does it from the site's settings). For each question the site's route builds an `Ask` (the
question, the visitor's code, the cache key, and two functions of its own: `write()`, which runs its pipeline,
and `sources_only(note, free)`) and streams what `desk.handle(ask)` gives back.

A site may fill these hooks, each a method of `briefing.Hooks` that does nothing by default: `on_cached`
(before a cached answer is replayed), `usages` (further model calls an event reports), `on_event` (as each event
passes), `finish` (before the final event is saved or cached) and `for_this_reader` (after saving, for this
reader's copy only). [`EXTENDING.md`](../EXTENDING.md#45-hooks-the-steps-only-some-sites-have) says what each
may change.

The desk guarantees, for every site:

- the order of the nine steps, including the second check of the caps;
- that the reserved place is always released, and the model's stream closed when the reader leaves;
- exactly one row in the record of briefings for every question, with its outcome and stage timings (ADR 0012);
- that nothing meant for one reader reaches the cache or the saved copy;
- that a failure never leaves the reader waiting: an `error` event in the site's words.

The site makes the cache key, with `usage.cache_key` over its own parts, so that each site kept the key it had
and nothing cached was lost in the move. The desk adds only an experiment's arm. Putting the model, the
instructions' version and a stamp of the data in the key is therefore each site's to do, and each site tests that
its key changes with each of them.

The parts stay public (`RateLimiter`, `Caps`, `BriefingsInProgress`, `SqliteAnswerCache` and the rest), so a site
can compose them itself.

## Consequences

- This was the largest move of behaviour into the package. Each site's adoption first recorded golden
  transcripts of its own flow (a fresh question, a repeat, a follow-up, sources only, each cap reached, the model
  failing mid-stream, the reader leaving, no records, no key) and the desk had to produce the same bytes and the
  same rows.
- The record of each briefing, the stage timings, experiments and stopping the model when the reader leaves are
  the same on every site, with one implementation.
- Where Landlords Stand writes no briefings and does not use the desk.
