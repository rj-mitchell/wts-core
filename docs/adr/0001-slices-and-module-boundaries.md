# ADR 0001: Slices by dependency, modules by reason to change

Status: accepted, 13 November 2026.

This record decides how the package is split: which parts need which libraries, and where each module's
boundary lies.

## Context

The shared code could be sorted by topic, into "no AI" (settings, backup, state, usage, the streamer, reports and
statements) and "AI" (the model client, the citation verifier, loaded words, British spelling, the embedder, the
index). What matters, though, is dependencies: Where Landlords Stand writes no briefings and must be able to
install the package without `anthropic`, `lancedb` or `fastembed`.

The two do not line up. The checks on briefings are plain Python over text and import no AI library. The streamer
imports nothing from FastAPI. And the part most alike across the three AI sites was the hundred lines in each
`api/app.py` that take a question through the rate limit, the cache, the caps, the pipeline, the cost record and
the saved briefing. Every outcome worth recording for a briefing is decided there.

## Options

1. Two slices by topic, with the checks in an `ai/` module and each site keeping its own request flow.
2. Slices by dependency and modules by reason to change, with the request flow moved into the package as one
   module with explicit hooks.
3. Several small packages, each versioned alone: the most flexible, and four times the releases for one
   maintainer.

## Decision

Option 2. One distribution, `wts-core`, whose base install needs only the standard library. Extras add the
libraries a site uses (`cli`, `offsite`, `duckdb`, `ai`); the README lists what each brings. A site with no
briefings installs `wts-core[cli,offsite]`, and the AI sites `wts-core[cli,offsite,duckdb,ai]`.

Each module has one reason to change:

| Module | Holds | Changes when |
|---|---|---|
| `wts_core.ports` | every interface something can be swapped behind, and the values they pass | a new kind of thing becomes swappable |
| `wts_core.events` | the event format of a briefing | the format gains a version |
| `wts_core.settings` | layered settings, the base `Settings`, validation at start-up | a settings rule changes |
| `wts_core.state` | the SQLite state database, its connections and migrations | storage changes |
| `wts_core.usage` | the rate limiter, visitor codes, prices, spending, caps, briefings in progress, the answer cache | a limit or price rule changes |
| `wts_core.checks` | the citation verifier, quotations, loaded words, British spelling | a rule of the impartiality policy's section 3 changes |
| `wts_core.briefing` | the briefing desk, stage timings, the streamer | the flow of a briefing changes |
| `wts_core.replies` | readers' reports, the right of reply, the corrections log, hidden items | the impartiality policy's section 7 changes |
| `wts_core.observe` | the record of each briefing, structured logs, statistics, alerts, experiments | what is measured changes |
| `wts_core.eval` | the evaluation harness | how briefings are judged changes |
| `wts_core.ops` | backup, restore, off-site copies, backup alerts | operations change |
| `wts_core.adapters` | one file per outside tool: Anthropic, fastembed, LanceDB, Backblaze B2, DuckDB | that tool changes |
| `wts_core.cli` | the shared commands, as Typer groups a site adds to its own | a command changes |
| `wts_core.testing` | fakes, recorded fixtures, and the contract tests adapters and sites must pass | a contract changes |

Dependencies point one way. `ports` and `events` import nothing from the package; `briefing` composes `usage`,
`checks` and `observe`; `adapters` implement `ports`, and only a site (or the one factory that reads
`[answer] provider`) imports them. `replies` and the modules that touch the model share no imports in either
direction (ADR 0008). `tests/test_walls.py` checks these rules, and CI installs the base wheel alone and fails if
any outside library arrives with it.

## Consequences

- The checks are installed on every site, including Where Landlords Stand, where nothing calls them. They cost
  nothing there: no dependencies and a few hundred lines.
- The request flow is shared code, the largest move of behaviour into the package, so it has the heaviest parity
  tests (ADR 0009).
