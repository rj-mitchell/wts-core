# ADR 0003: One event format for a streamed briefing

Status: accepted by the owner on 13 November 2026.

## Context

A briefing is a stream of events. Today they are plain dictionaries with a `"type"`, and they pass through two
boundaries:

1. **From the model client to the site's pipeline:** `text` (a piece of the answer), `citation` (the model is citing
   a source), and `final` (the whole message as blocks with their citations, the model's name, why it stopped, and
   the token counts).
2. **From the pipeline to the reader's browser:** `plan` (how the question was read), `sources` (the records
   found, sent before any text is written), `text`, `citation`, `final` (the checked answer, with its flags) and
   `error`. They are sent as server-sent events, `event: <type>` and `data: <JSON>`.

The second form is also **stored**. The answer cache and every saved briefing hold a list of these events as JSON,
and each site's front end reads them. So the reader format is a file format with months of saved data behind it,
and it cannot change shape.

The brief asks for one internal format that the verifier, the cost accounting, the cache and the streamer all read,
so that a change of provider touches only its adapter, and for a "sources ready" event so every site can show
sources early.

## Options

1. **Keep untyped dictionaries everywhere.** No change, no safety: a missing key is found by a reader.
2. **Typed classes everywhere, converted to dictionaries at the edge.** Clean inside. But the reader events carry
   each site's own payloads (its plan, its source cards), and converting saved events back and forth is a place for
   a silent change to hide.
3. **Typed at the boundary that changes with the provider; described, not converted, at the boundary that is
   stored (recommended).**

## Decision: option 3

**Model events** (boundary 1) are small frozen dataclasses in `wts_core.events`. Every adapter emits exactly these:

| Event | Fields |
|---|---|
| `TextDelta` | `text` |
| `CitationDelta` | `document` (the source's number in the request), `quoted` (the words cited) |
| `Completed` | `blocks` (each: `text`, `citations` as document number and quoted words), `model`, `stop_reason`, `usage` (a `Usage`) |

Nothing provider-specific crosses this boundary. The verifier reads `Completed.blocks`; cost reads
`Completed.usage`; time to first token is the first `TextDelta`.

**Reader events** (boundary 2) stay as JSON objects in exactly today's shape. The package describes them with
`TypedDict`s and checks them, but never rebuilds them:

| Event | The package owns | The site owns |
|---|---|---|
| `plan` | `type`, `usage`, `parse_error` | `plan` (its own filters and interpretation) |
| `sources` | `type`, the fact that it is sent before any `text` | `sources` (its cards), `candidates`, `semantic`, `evidence` |
| `text` | all of it | |
| `citation` | all of it | |
| `final` | `answer` (the verifier's report: segments, flags, counts, `grounded_ratio`, `loaded_words`, `no_records`), `usage`, `model`, `stop_reason`, `cached`, `briefing_id`, `note` | any further keys (for example Where MPs Stand's `interests`) |
| `error` | all of it (`message`) | |

- **"Sources ready" is the existing `sources` event,** not a new one. All three AI sites already send it before the
  briefing starts. The package makes that a rule the briefing desk enforces (a `text` event before `sources` is a
  programming error, caught in tests) and records the time it was sent as a stage timing.
- **The format has a version,** `EVENTS_VERSION = 1`, which is today's shape. A saved or cached list of events
  with no version is version 1. Any future change adds a version and a reader for the old one; a saved briefing
  must always show what was originally shown.
- **Compatibility is tested against real saved data:** fixtures of cached and saved event lists from each site (as
  they are in the three state databases' formats today) are read, replayed through the streamer, and compared byte
  for byte with what each site's current code sends.
- **The streamer** (`wts_core.briefing.sse`) is today's `sse()` from Where MPs Stand: a keep-alive comment while the
  model is thinking, and when the reader leaves, the worker stops at the next event and closes the model's stream,
  so a briefing nobody is reading stops being written and paid for.

## Consequences

- A new provider's adapter has a three-class target and a contract suite. Nothing downstream changes.
- The reader format's looseness (site payloads are opaque) is deliberate: the package can't break what it doesn't
  rebuild.
- Unknown keys in reader events are passed through untouched, so a site can add one without a package release.
