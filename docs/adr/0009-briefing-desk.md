# ADR 0009: The briefing desk: one request flow, with each site's steps hung on it

Status: accepted by the owner on 13 November 2026.
on the list to check first. 13 November 2026.

## Context

In each AI site, about a hundred lines of `api/app.py` take a question from arrival to the last event. Read side by
side, the three are the same flow:

1. Count the request against the rate limit; work out the visitor's code.
2. Work out the answer cache's key; look for a cached answer.
3. If there is none, check the caps (this visitor's daily limit, today's spending, this month's).
4. Reserve a place among the briefings in progress, and check the caps again counting the others in progress.
5. Run the site's pipeline, passing its events to the reader as they come.
6. As events pass: record the cost of reading the question and of writing the briefing; note a failure; save the
   finished briefing at its own address; keep what is needed to replay it.
7. Put the replay in the answer cache.
8. If a cap or a limit stopped the briefing, send the sources anyway with a note saying why, which costs nothing.
9. Whatever happens, release the place in step 4. If the reader leaves, stop the model.

Each site hangs its own steps on this: Where MPs Stand records a third cost (matching registered interests), adds a
donation reminder to one reader's copy only, and gives old cached answers an address; Where Countries Stand
re-judges a cached answer's flags by today's rules; Where Councils Stand takes the token counts out of the events it
sends, and reads the question by its free rules when a limit has been reached; each has its own wording for every
refusal.

The brief lists the *parts* (limiter, caps, cache, cost, streamer) as shared and leaves the flow in each site. But the
brief also asks for one record per briefing saying how it ended (completed, from the cache, no records, paused by a
cap, the reader left and at which stage, an error) and how long each stage took. Every one of those endings is
decided in this flow, and nowhere else.

## Options

1. **Share the parts; each site keeps its flow** (the brief's default). Each site then adds the same timing and
   outcome recording to its own flow by hand: four more copies of the code that most needs to agree, in a place
   that has already drifted (Where Councils Stand's flow notes no failed briefings, which the other two do, and
   counts a visitor's questions in a table of its own).
2. **A framework: the package owns the route.** The package would define the `/api/ask` endpoint and its request
   body. That takes web routes away from the sites, which the brief's Musts forbid.
3. **A briefing desk in the package: the flow, not the route (recommended).** The site's route stays the site's. It
   builds a description of the request and hands it to the desk, which runs the nine steps and yields the events to
   send.

## Decision: option 3

`wts_core.briefing.BriefingDesk` is built once per site from the shared parts (limiter, spending record, caps,
in-progress count, answer cache, saved briefings, the briefing log, the clock) and the site's wording. For each
question, the site's own route calls `desk.handle(ask)` and streams what comes back.

**What the site passes in (`Ask`):** the question; the visitor's code and, where a site has accounts, the account;
the cache key's parts (or none, for a follow-up that must not be cached); whether only sources were asked for; and
two functions of its own: `write()`, which runs its pipeline, and `sources_only(note)`, which finds the sources
without the model.

**The hooks a site may fill** (each has a default that does nothing):

| Hook | When | Used today by |
|---|---|---|
| `on_cached(events)` | before a cached answer is replayed | Countries (re-judging flags), MPs (old answers given an address) |
| `on_event(event)` | as each event passes | MPs (the interests cost, stripping a private key) |
| `finish(final, kept)` | when the final event arrives, before it is saved or cached | each site's own saved-briefing fields |
| `for_this_reader(final)` | after saving and caching | MPs (the donation reminder, never saved or cached) |

**What the desk guarantees, for every site:**

- the order of the nine steps, including the second check of the caps with the others in progress counted;
- that the place in step 4 is always released, and the model's stream closed when the reader leaves;
- that exactly one line is written to the briefing log for every question, with its outcome and stage timings
  (ADR 0012), whichever way it ended;
- that nothing meant for one reader (step `for_this_reader`) can reach the cache or the saved copy;
- that in an experiment the version being tried is part of the cache key. (As first written, this said the desk
  also guaranteed the model, the instructions' version and the data's stamp were in the key. As built, the site
  makes the key, with `usage.cache_key` over its own parts, so that each site's key is the one it has today and
  nothing cached is lost at adoption; the desk is handed the finished key and cannot see inside it. So those
  three are each site's to keep, and each site's adoption has a test that its key changes with each of them);
- that a failure never leaves the reader waiting: an `error` event with the site's wording.

**What stays the site's:** the route, its request body, the pipeline, how sources are found, every message a reader
sees (passed in as a `Messages` object: the desk holds no wording of its own), what goes in the cache key beyond
the four parts above, and what a saved briefing records.

The parts stay public too (`RateLimiter`, `Caps`, `InProgress`, `AnswerCache`…). A site that outgrows the desk can
compose them itself; the desk is the paved road, not a wall.

## Parity

This is where a change in behaviour could hide, so each site's adoption records golden transcripts first: for a
fixed set of requests against the site's *current* flow with a scripted model (a fresh question, the same question
again, a follow-up, sources only, each cap reached, each in-progress refusal, the model failing mid-stream, the
reader leaving, no records, no API key), the exact bytes sent, the rows written to spending, the cache and saved
briefings, and the failures noted. The same requests through the desk must produce the same bytes and the same
rows. `docs/MIGRATION.md` lists the cases per site.

## Consequences

- The largest single move of behaviour into the package. It is also what makes the per-briefing record, the stage
  timings, experiments and the "reader left" saving the same on every site without four implementations.
- Where MPs Stand's flow has the most of its own steps; it adopts the desk last, after the hooks have been proved
  on two smaller sites, and if a step doesn't fit a hook the hook is fixed in the package rather than worked around
  in the site.
- Where Landlords Stand has no briefings and doesn't use the desk.
