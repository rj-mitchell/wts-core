# ADR 0002: Ports and adapters: which interfaces, and how narrow

Status: accepted, 13 November 2026.

This record decides which parts of the package can be swapped, and the shape of the interfaces ("ports") they
are swapped behind.

## Context

The aim is that changing the AI model is a setting, and changing the provider, embedder, index or off-site store
is one new adapter, never a rewrite. Two facts shape the interfaces:

- The model is used in two ways. A briefing is streamed with citations: the sources go in as numbered documents,
  and the text comes back with citations that point at a document and quote it. A question is read with a second,
  non-streamed call that returns structured output.
- Citations of this kind are one provider's feature. An interface that renamed that provider's stream would not
  survive a change of provider. The interface has to say what a citation is for this family: a document's number
  and the words quoted from it.

## Options

For storage:

1. One generic store (get, put, query) over SQLite. Over SQL it is either too thin to be useful or a query
   language of its own.
2. No interfaces: modules use SQLite directly. Simple, but another database means editing every module.
3. A small interface for each need, each with one SQLite implementation and a contract test.

For the model:

1. One `stream()` that mirrors the provider's SDK: the least work, and it fails the aim above.
2. A neutral request and neutral events, in the family's own terms.
3. A third-party abstraction layer: another dependency, and none models citations the way the verifier needs.

## Decision

Option 3 for storage and option 2 for the model. Every interface is a `typing.Protocol` in one module,
`wts_core.ports`, so what can be swapped is one file.

| Interface | In short | The package's implementation |
|---|---|---|
| `ModelClient` | `stream(request)` for a briefing, `structured(request, schema)` for reading a question; `provider` and `supports` | `adapters.anthropic` |
| `Pricing` | `price_for(model)`, `cost(usage, model)` | `usage.PriceTable`, read from settings |
| `Embedder` | `embed_documents`, `embed_query`; `id`, `dimension` | `adapters.fastembed`, and `adapters.hashing` for tests |
| `VectorIndex` | `replace`, `add_vectors`, `search_words`, `search_meaning`, `build_indexes`, `tidy`; `meta` | `adapters.lancedb` |
| `SpendingRecord`, `AnswerCache`, `BriefingLog`, `KeyValue` | a few operations each | SQLite, in `wts_core.usage`, `wts_core.observe` and `wts_core.state` |
| `Limiter`, `InProgress` | `allow(key)`; `start(key)`, `finish(key)`, `pending_usd()` | in memory, for one process |
| `OffsiteStore` | `put`, `list`, `delete`, `close` | `adapters.b2` |
| `Clock`, `Random` | the time; chance, for experiments and ids | the system's, and fixed ones for tests |

Rules:

- No module outside `wts_core/adapters/` imports an outside library. A test reads the imports.
- `Usage` is a value with four unambiguous counts (`input_uncached`, `cache_write`, `cache_read`, `output`). The
  sites' stored data used "input tokens" in two senses; `Usage.from_mapping()` reads both, so stored data still
  reads correctly.
- The provider and models are chosen in settings (`[answer] provider`, `model`, `query_parse_model`), with prices
  under `[usage]`. A site that writes briefings asks for strict prices (`desk_parts(require_prices_for=…)`), so a
  model with no price table of its own stops the site at start-up rather than being costed at another's prices.
- An index records the embedder it was built with. `VectorIndex` raises `IndexOutOfDate` when opened with another
  embedder, and search by meaning stays off until the index is rebuilt. Vectors from two models are never mixed.
- Each adapter passes a contract suite in `wts_core.testing.contracts`, using recorded fixtures, never live calls.
  A new adapter is accepted when it passes.

## Consequences

- There are more storage interfaces than one generic store, each a few lines. Swapping the database is one class
  per interface, with tests that say when it is done.
- A provider without native citations needs an adapter that makes them, for example by asking the model to mark
  its quotations. The verifier checks every citation against its source whatever produced it, so a weak adapter
  shows up as invalid citations in the evaluation harness, never as unchecked text reaching readers.
- `structured()` takes any schema class with `model_json_schema()` and `model_validate()`, so `ports` does not
  import Pydantic.
