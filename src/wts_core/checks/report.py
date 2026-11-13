"""Every check on a briefing, in the one order they run: the function a site's pipeline calls when the model has
finished writing.

The three sites each carried these five lines in their own pipeline, in the same order. The order matters (the
spelling is made British before loaded words are looked for; quotations are checked last, against the text as it
will be shown), so it is kept in one place rather than in each site.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from wts_core.checks.british import britishise_segments
from wts_core.checks.neutral import LoadedWords
from wts_core.checks.typography import curl_answer
from wts_core.checks.verify import TitledSource, Verifier
from wts_core.events import Answer

__all__ = ["check_briefing"]


def check_briefing(blocks: Sequence[Mapping[str, Any]], sources: Sequence[TitledSource], verifier: Verifier,
                   loaded_words: LoadedWords, *, curled: bool = False) -> Answer:
    """The model's finished blocks (``events.blocks_as_today``) through every check: the report as it is sent to a
    reader and saved. ``sources`` are the site's own, as the model was given them; ``curled`` is for a site that
    shows its briefings with curly quotes."""
    report = verifier.verify(blocks, sources)
    verifier.drop_preambles(report.segments)  # "Across the records retrieved, ..." openers
    britishise_segments(report.segments)  # the model's own words only; quotations stay verbatim
    loaded_words.flag(report.segments)  # judgemental words in its own voice are highlighted, not hidden
    verifier.check_quotes(report, sources)  # quotations not found word for word in their sources are marked
    answer = report.to_dict()
    return cast(Answer, curl_answer(answer)) if curled else answer
