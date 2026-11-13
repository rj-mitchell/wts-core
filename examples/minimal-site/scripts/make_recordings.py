"""Write the recorded briefings the example's scripted model replays (``data_static/recordings/``).

A recording is what a model sent back for one question: text and citations in the order they arrived, then the
finished message (``wts_core.testing.models``). These three are written by hand, in the shape real recordings have
(a citation arrives before the text it supports, and that text is the model's own wording), because the example
must run with no key. Every quotation is taken from ``data_static/minutes.json`` by its place there, so a
recording cannot quote words the record does not hold. Run it again whenever the minutes change::

    uv run python scripts/make_recordings.py

A site with a key records real ones instead: ``record_stream(path, client.stream(request), documents=…)``.
"""

from __future__ import annotations

from pathlib import Path

from wts_core.events import Block, Citation, CitationDelta, Completed, ModelEvent, TextDelta
from wts_core.ports import Usage
from wts_core.testing.models import record_stream

from parks.pipeline import Reading, _source, load_minutes

ROOT = Path(__file__).resolve().parents[1]
MINUTES = {m.id: m for m in load_minutes(ROOT / "data_static" / "minutes.json")}

# A briefing is a list of pieces: plain words, or (words, minute, passage) for words that cite a passage.
type Piece = str | tuple[str, str, int]

BRIEFINGS: dict[str, tuple[str, Reading, list[str], list[Piece], Usage]] = {
    # name: the question it was made for, how the model read it, the minutes it was given (oldest first, as the
    # pipeline gives them), what it wrote, and what the briefing cost
    "dogs": (
        "What have park committees decided about dogs?",
        Reading(topic="dogs leads"),
        ["m04", "m01", "m08"],
        ["**Dogs on leads**\n\n- Alder Park: ",
         ("the Committee agreed that dogs must be kept on leads in the walled garden from 1 April 2026", "m01", 0),
         ", while ",
         ("dogs may still run free on the main field", "m01", 1),
         ".\n- Canal Gardens: ",
         ("the Committee agreed that dogs must be on leads along the towpath, which cyclists and walkers share",
          "m08", 0),
         ", and ",
         ("the rule will be reviewed after twelve months", "m08", 1),
         ".\n\n**No change**\n\n- Birchfield Common: ",
         ("the Committee resolved to make no change to its rules, under which dogs may be off the lead across the "
          "common", "m04", 0),
         ".\n"],
        Usage(input_uncached=612, cache_write=0, cache_read=540, output=148),
    ),
    # one sentence here has no citation and uses a word on the site's own loaded list: the checks mark both
    "opening-hours": (
        "When do the parks open and close?",
        Reading(topic="opening hours gates open close"),
        ["m07", "m02", "m09"],
        ["- Alder Park: ",
         ("the gates open at 7am and close at dusk throughout the summer", "m02", 0),
         "; ",
         ("a proposal to leave them open overnight was not supported", "m02", 1),
         ".\n- Canal Gardens: ",
         ("the gardens stay open until 10pm from June to August", "m09", 0),
         ", and ",
         ("the gates are locked at 8pm for the rest of the year", "m09", 1),
         ".\n\nThe shorter winter hours leave Canal Gardens neglected after dark.\n"],
        Usage(input_uncached=598, cache_write=0, cache_read=540, output=121),
    ),
    # the one minute found does not answer the question, and the model says so in the words it was told to use
    "parking": (
        "Have any committees decided to charge for parking?",
        Reading(topic="parking charge cost"),
        ["m06"],
        ["The minutes hold no record of this."],
        Usage(input_uncached=231, cache_write=0, cache_read=540, output=11),
    ),
}


def _events(pieces: list[Piece], given: list[str], usage: Usage) -> list[ModelEvent]:
    events: list[ModelEvent] = []
    blocks: list[Block] = []
    for piece in pieces:
        if isinstance(piece, str):
            words, citations = piece, ()
        else:
            words, minute, passage = piece
            citation = Citation(document=given.index(minute), quoted=MINUTES[minute].passages[passage])
            citations = (citation,)
            events.append(CitationDelta(citation.document, citation.quoted))  # before the text it supports
        half = len(words) // 2
        events += [TextDelta(part) for part in (words[:half], words[half:]) if part]  # text arrives in pieces
        blocks.append(Block(words, citations))
    return [*events, Completed(tuple(blocks), "recorded-briefing", "end_turn", usage)]


def main() -> None:
    for name, (question, reading, given, pieces, usage) in BRIEFINGS.items():
        documents = [_source(n, MINUTES[m]).document() for n, m in enumerate(given, start=1)]
        path = record_stream(
            ROOT / "data_static" / "recordings" / f"{name}.jsonl", _events(pieces, given, usage),
            documents=documents, synthetic=True, question=question,
            about="written by hand for the example site, in the shape real recordings have; not a recording",
            reading=reading.model_dump(), reading_usage={"input_uncached": 96, "output": 14})
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
