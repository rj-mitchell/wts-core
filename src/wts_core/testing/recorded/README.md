# Recorded model streams

Streams of model events for tests: replayed by `wts_core.testing.models.ScriptedModel`, and run against every model
adapter by `ModelClientContract`. Three files are real recordings; four are written by hand, because what they show
cannot be provoked cheaply. Each file's header says which it is (`"synthetic": true` or `false`).

Every council, minute, address and question in these files is invented. Nothing here came from a site's archive or
from a reader.

## Real recordings

Made on 13 November 2026 through `wts_core.adapters.anthropic.AnthropicClient` with `anthropic` 2.8.0: three
requests in all, each sent once. The briefings used the model the sites use for briefings (`claude-sonnet-5-5`,
effort "medium", `max_tokens` 3000, the fallback beta on, which the API accepted); the structured call used the
model they use for reading questions (`claude-haiku-5-5`, effort "low", `max_tokens` 2000). The instructions and
the question of each request are in its header, so the request can be made again.

| File | What it is |
|---|---|
| `real_cited_briefing.jsonl` | A briefing over three short documents, every claim cited: 46 events. The first request, so the instructions were written to the prompt cache (`cache_write` 946) |
| `real_nothing_relevant.jsonl` | The same documents asked about something they do not mention: the model gives the sentence the instructions tell it to, with no citation. The second request within five minutes, so the instructions were read from the cache (`cache_read` 946) |
| `real_structured.json` | One `ModelClient.structured` call: the schema sent (`schema`), the object that came back (`parsed`) and its `usage`. Not a stream, so not JSON lines |

What they show, which the hand-written files now follow:

- **A citation arrives before the text it supports.** For a cited block the API sends the `citations_delta` first
  and the block's text after it, in pieces. (The three sites' own test fakes have it the other way round. Nothing
  downstream may depend on the order.)
- **The text of a cited block is the model's own wording,** not the quotation: the quotation is in the citation
  (`quoted`), and is the whole passage cited.
- **Blocks alternate:** connecting words with no citation, then a cited block, each cited block with one citation.
- **No thinking reaches the events.** The adapter passes on text and citations only.

## Written by hand (synthetic)

| File | What it is |
|---|---|
| `cited_briefing.jsonl` | A briefing in which every claim is cited, with the text of each cited block being the quotation itself, one block with two citations, and a read from the prompt cache |
| `uncited_claim.jsonl` | A briefing with one sentence the sources do not support, on a first request |
| `refusal.jsonl` | The model declines: no text, a finished message with no blocks, `stop_reason` "refusal" |
| `max_tokens.jsonl` | A briefing cut off at the limit: the last block stops in the middle of a word, `stop_reason` "max_tokens" |

Their token counts are plausible, not measured, and their model is called `synthetic-model`. A refusal and a stop at
the limit should be replaced by real recordings if either is ever met in an evaluation run.

## The format

JSON lines (`wts_core.testing.models`: `record_stream`, `load_stream`, `load_documents`, `load_header`). The first
line is a header: `recording` (the format's version, 1), `documents` (how many documents the request had),
`sources` (the documents themselves: `title`, `source`, `passages`) and anything else worth knowing. Every other
line is one model event, in order:

- `{"event": "text", "text": …}`: a piece of the answer (`events.TextDelta`);
- `{"event": "citation", "document": …, "quoted": …}`: the model cites a document, counted from 0, and the words
  it quotes (`events.CitationDelta`);
- `{"event": "completed", "blocks": […], "model": …, "stop_reason": …, "usage": {…}}`: the finished message, always
  last and always exactly one (`events.Completed`). `usage` has the four counts of `ports.Usage`.

These are the events every model adapter emits, with nothing of one provider in them, so a recording made through
one adapter tests everything downstream of any other.

## Making another

    from wts_core.testing.models import record_stream
    events = list(client.stream(request))            # a real client; a request made up for the purpose
    record_stream(path, events, documents=request.documents, synthetic=False, recorded="2026-11-13",
                  instructions=request.instructions, question=request.question, requested_model=request.model)

Never record a reader's question, and never a key: only requests written for the purpose, or a site's own
evaluation questions.
