# ADR 0002: Ports and adapters: which interfaces, and how narrow

Status: proposed, for the owner's review (it changes Defaults in the brief's table 3.1). 13 November 2026.

## Context

Goal 1: changing the engine is a configuration change or one new adapter, never a rewrite. The brief proposes seven
ports: `ModelClient`, `Usage` and `Pricing`, `Embedder`, `VectorIndex`, `StateStore`/`Cache`/`Limiter` storage,
`OffsiteStore` and `Clock`.

Two things in the code shape the answer.

- **The model is used in two ways, not one.** A briefing is streamed with Anthropic's search-result citations: the
  sources go in as numbered documents, and the model's text comes back with citations that point at a document and
  quote it. A question is read with a second, non-streamed call that returns structured output (`messages.parse`
  with a schema). The brief's `ModelClient` covers only the first.
- **Citations are a feature of one provider.** An interface that just renames Anthropic's stream would not survive
  the swap it exists for. The interface has to say what a citation *is* for this family: a document's number and the
  words quoted from it. How a provider produces that is the adapter's business.

## Options

**For storage (`StateStore`, `Cache`, `Limiter`):**

1. *One generic `StateStore` port* (get, put, query) with SQLite behind it, as the brief sketches. Every shared
   module would talk to storage through it. A generic store over SQL is either too thin to be useful (key and value
   only) or a query language of its own.
2. *No ports: the modules use SQLite directly.* Simple, and a different database would mean editing every module.
3. *A port per need (recommended).* Each module that stores something defines the few operations it needs as its
   own small interface (`SpendingRecord`: add an entry, sum since a time, count for a visitor today; `AnswerCache`:
   get, put, purge), with one SQLite implementation of each sharing a connection helper. A different database, or
   several processes, means writing those small classes again, and each has a contract test.

**For the model:**

1. *One `stream()` method that mirrors the SDK.* The least work now; fails goal 1.
2. *A neutral request and neutral events (recommended):* the caller hands over instructions, documents, the
   question and options; the adapter returns text, citations and a final message in the family's own terms.
3. *A third-party abstraction layer.* Another dependency whose releases the checks would then depend on, and none
   models search-result citations the way the verifier needs.

## Decision

Ports live in one module, `wts_core.ports`, so "what can be swapped" is one page. Each is a `typing.Protocol`.

| Port | The interface, in short | Today's adapter | What it must survive |
|---|---|---|---|
| `ModelClient` | `stream(request) -> Iterator[ModelEvent]` for a briefing; `structured(request, schema) -> (data, Usage)` for reading a question; `provider` and `supports` (caching, extended cache lifetime, fallbacks, effort) | `adapters.anthropic` on SDK 2.x | a new model (settings only); an SDK major version (the adapter only); another provider (a new adapter) |
| `Pricing` | `price_for(model) -> Price`; `cost(usage, model) -> float`; raises `UnknownModel` | a table read from settings | new models and prices in settings; a provider with different usage fields |
| `Embedder` | `embed(texts) -> vectors`; `id`, `dimension` | `adapters.fastembed` (and the dependency-free hashing embedder for tests) | another local or hosted model |
| `VectorIndex` | `open`, `add`, `search`, `rebuild`, `tidy`; `meta` (embedder id, dimension, schema version) | `adapters.lancedb` | another vector store |
| `SpendingRecord`, `AnswerCache`, `BriefingLog`, `ReplyStore`, `KeyValue` | a handful of operations each | SQLite, in `wts_core.state` | another database; several processes |
| `Limiter`, `InProgress` | `allow(key)`; `start(key)`, `finish(key)`, `pending()` | in memory, one process | several processes (a shared implementation) |
| `OffsiteStore` | `put`, `list`, `delete`, `get` | `adapters.b2` | another S3-compatible store |
| `Clock` | `now()`, `monotonic()` | the system's | a fixed clock in tests |
| `Random` | `choice`, `token` | the system's | fixed choices in tests (experiments, briefing ids) |

Rules:

- **Shared logic depends on ports, never on an SDK.** No module outside `wts_core/adapters/` imports `anthropic`,
  `fastembed`, `lancedb`, `duckdb` or a B2 library. A test reads the imports and fails otherwise.
- **`Usage` is a value, not a port:** four counts with unambiguous names (`input_uncached`, `cache_write`,
  `cache_read`, `output`). Today "input tokens" means two different things depending on who is speaking (the SDK
  leaves cache writes out; the sites' own form includes them), and each site's cost code works out which it has
  been given. `Usage.from_mapping()` accepts both of today's forms, so stored and cached data still read correctly;
  inside the package the ambiguity is gone.
- **Provider and model are chosen in settings** (`[answer] provider`, `model`, `query_parse_model`), with prices in
  a `[pricing]` table. Start-up checks that every model named anywhere in settings (including an experiment's
  versions) has a price, and stops with a clear message if one hasn't. Today an unknown model is priced silently at
  the site's default prices.
- **A model change forces a rebuild of the index.** `VectorIndex.open` compares the stored embedder id, dimension
  and schema version with the embedder it is given and raises `IndexOutOfDate` on any difference. Search by meaning
  is then off (the site falls back to search by words, as it does today when no index exists) until a rebuild.
  Vectors from two models are never mixed.
- **Each adapter passes a contract suite** in `wts_core.testing` (`ModelClientContract`, `EmbedderContract`,
  `VectorIndexContract`, `OffsiteStoreContract`, and one for each storage class), using recorded fixtures, never
  live calls. A new adapter is accepted when it passes.

## Consequences

- The storage interfaces are more numerous than the brief's one `StateStore`, and each is five lines. Swapping
  the database is still one file per store, with tests that say when it is done.
- A provider without native citations needs an adapter that makes them (for example by instructing the model to
  mark quotations and parsing the marks). That is real work, but it is contained: the verifier checks every
  citation against its source whatever produced it, so a weak adapter shows up as invalid citations in the
  evaluation harness, not as unchecked text reaching readers.
- `structured()` takes any schema class with `model_json_schema()` and `model_validate()` (Pydantic's two methods),
  so `ports` needn't import Pydantic.
