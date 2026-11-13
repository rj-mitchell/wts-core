# Recorded model streams

**Every file here is synthetic.** No API key was available when the package was built, so these four streams were
written by hand in the fixture format, shaped as the SDK's events arrive for a briefing with citations. The
councils, minutes and addresses in them are invented. They are to be replaced by real recordings (made once, with
a working key, from each site's evaluation questions: `docs/MIGRATION.md`, 1.5) as soon as one can be made; each
file's header says `"synthetic": true` until then.

| File | What it is |
|---|---|
| `cited_briefing.jsonl` | A briefing in which every claim is cited: text in small pieces, each cited block's citation after its text, one block with two citations, a read from the prompt cache |
| `uncited_claim.jsonl` | A briefing with one sentence the sources do not support, on a first request (the instructions are written to the cache) |
| `refusal.jsonl` | The model declines: no text, a finished message with no blocks, `stop_reason` "refusal" |
| `max_tokens.jsonl` | A briefing cut off at the limit: the last block stops in the middle of a word, `stop_reason` "max_tokens" |

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
one adapter tests everything downstream of any other. `wts_core.testing.ScriptedModel(recorded("cited_briefing"))`
replays one; `ModelClientContract` runs every adapter against all of them.

## What is not known to be exact

- **The order of a citation and its text within a block.** Here the text of a cited block arrives first and its
  citation after, as the three sites' own test fakes have it. Nothing downstream depends on the order.
- **The token counts** are plausible, not measured.
- **Thinking.** A real finished message may hold thinking blocks before the text; the adapter drops them, so a
  recording never shows them.

## Making a real recording

    from wts_core.testing.models import record_stream
    events = list(client.stream(request))            # a real client, a real request from an evaluation question
    record_stream(path, events, documents=request.documents, site="councils", question_id="waste-01")

Never record a reader's question: only the sites' own evaluation questions.
