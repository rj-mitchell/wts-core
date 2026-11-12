# ADR 0001: Slices by dependency, modules by reason to change

Status: proposed, for the owner's review (it changes Defaults in the brief: the two slices in section 2 and the
layout in phase 3). 13 November 2026.

## Context

The brief sorts the shared code into two slices by topic: "no AI" (settings, backup, state, usage, the streamer,
reports and statements) and "AI" (the model client, the citation verifier, loaded words, British spelling, the
embedder, the index). The Must behind the slices is about dependencies: Where Landlords Stand must be able to install
the first without `anthropic`, `lancedb` or `fastembed`.

Reading the code shows the two ideas don't line up:

- **The checks on briefings import nothing from any AI library.** The verifier, the loaded-words check and British
  spelling are plain Python over text and lists. They are "AI" by subject only.
- **The streamer imports nothing from FastAPI.** `sse()` turns an iterator of events into an iterator of bytes.
- **DuckDB is used by some sites' record stores, not by anything shared except the wrapper itself.** The state
  database is SQLite everywhere.
- **The part most alike across the three AI sites isn't in the brief's list at all:** the hundred lines in each
  `api/app.py` that take a question through the rate limit, the cache, the caps, the briefings-in-progress count,
  the pipeline, the cost record, the saved briefing and the cache again. It is the same skeleton three times, with
  each site's own steps hung on it. Every outcome the brief wants recorded for each briefing (completed, from the
  cache, no records, paused by a cap, the reader left, an error) is decided there.

## Options

1. **The brief's layout:** two slices by topic; `ai/` holds the checks; the sites keep their own request flow and call
   shared helpers from it.
2. **Slices by dependency, modules by reason to change (recommended):** what a module imports decides its slice;
   what makes it change decides its boundary. The request flow moves into the package as one module with explicit
   hooks.
3. **Several small packages** (`wts-settings`, `wts-usage`, `wts-checks`…), each versioned alone. The most
   flexible, and four times the releases for one maintainer.

## Decision: option 2

**One distribution, `wts-core`, whose base install needs only the standard library.** Extras add the libraries a
site actually uses:

| Extra | Brings | For |
|---|---|---|
| (none) | nothing beyond Python | settings, the state database, usage and caps, the checks, the briefing desk, the streamer, reports and statements, backup, records and statistics |
| `[cli]` | `typer` | the shared commands a site adds to its own command line |
| `[duckdb]` | `duckdb` | the thread-safe DuckDB wrapper |
| `[ai]` | `anthropic`, `fastembed`, `lancedb`, `numpy`, `pyarrow` | the adapters: the Anthropic client, the fastembed embedder, the LanceDB index |

Where Landlords Stand installs `wts-core[cli,duckdb]`. The AI sites install `wts-core[cli,duckdb,ai]`. A test in CI
installs the base alone and fails if any AI library arrives with it, or if any module outside `adapters/` imports
one.

**Modules, and the one reason each has to change:**

| Module | Holds | Changes when |
|---|---|---|
| `wts_core.ports` | every interface something might be swapped behind, and the small value types they pass | a new kind of thing becomes swappable |
| `wts_core.events` | the briefing's event format: what a model adapter emits, and what a reader's browser receives | the format gains a version |
| `wts_core.settings` | layered settings, the base `Settings`, validation at start-up | a settings rule changes |
| `wts_core.state` | the SQLite state database: connections, the package's own tables, migrations | storage changes |
| `wts_core.usage` | the rate limiter, the visitor code, prices and cost, the spending record, caps, briefings in progress, the answer cache | a limit or price rule changes |
| `wts_core.checks` | the citation verifier, quotation checks, loaded words, British spelling | a rule of the impartiality policy's section 3 changes |
| `wts_core.briefing` | the briefing desk (the request flow above), stage timings, the streamer | the flow of a briefing changes |
| `wts_core.replies` | readers' reports, statements under the right of reply, the corrections log, hidden items | the impartiality policy's section 7 changes |
| `wts_core.observe` | the per-briefing record, structured logs, statistics, alerts, experiments | what is measured changes |
| `wts_core.eval` | the evaluation harness | how briefings are judged changes |
| `wts_core.ops` | backup, restore, off-site copies, backup alerts | operations change |
| `wts_core.adapters` | one file per outside tool: Anthropic, fastembed, LanceDB, B2, DuckDB | that tool changes |
| `wts_core.cli` | the shared commands, as Typer groups a site mounts | a command changes |
| `wts_core.testing` | fakes, recorded fixtures, the contract tests each adapter and each site must pass | a contract changes |

**Dependencies point one way,** checked by a test that reads the imports: `ports` and `events` import nothing from
the package; the middle modules import only those two (and `state`, `settings`); `briefing` composes `usage`,
`checks` and `observe`; `adapters` implement `ports`; nothing imports `adapters` except a site (or the one factory
that reads `[answer] provider`). `replies` imports nothing from `checks`, `briefing` or `adapters`, and they import
nothing from it: that is half of how "statements never reach the model, the index or the record" is kept (ADR 0008).

## Consequences

- The verifier and its companions are installed everywhere, including Where Landlords Stand, where nothing calls
  them. They cost nothing there: no dependencies, a few hundred lines.
- "Slice 1" and "slice 2" in ENGINE.md and the drift manifest become "the base" and "the `[ai]` adapters".
  ENGINE.md is updated to say so.
- The request flow becomes shared code. This is the largest move of behaviour into the package, so it gets the
  heaviest parity tests (ADR 0009 and MIGRATION.md), and Where MPs Stand, whose flow has the most of its own steps,
  adopts it last.
