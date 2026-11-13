"""Flag loaded or judgemental words in the model's own voice (a safety net behind the sites' instructions).

Briefings must report in neutral words; loaded words may appear only inside a quotation from the record. Flags are
shown to the reader, like unsupported text: the words stay, highlighted, so nothing is silently rewritten.
Ambiguous words with common neutral senses ("claims" for benefits, "extreme weather", "lie ahead") are deliberately
not on the list, and "claimed" counts only as a verb of saying.

The mechanism is the same in all three sites. The list is each site's own, on purpose, and is passed in whole as a
compiled pattern: ``COMMON_LOADED_WORDS`` is the part every site shares, for a site to build its pattern on, and
what a site adds (Where Countries Stand's labels for governments and blocs, Where Councils Stand's words about a
council's competence or conduct) stays in that site. A site with nothing to add writes::

    LOADED = re.compile(rf"\\b({COMMON_LOADED_WORDS})\\b", re.IGNORECASE)

and one with more puts its words inside the group (``rf"\\b({COMMON_LOADED_WORDS}|shambles|fiasco)\\b"``) or adds
an alternative of its own after it. A word added to the common part reaches every site, which can only add flags.
"""

from __future__ import annotations

import re
from typing import Any, cast

from wts_core.checks.british import outside_quotes
from wts_core.checks.verify import Segment
from wts_core.events import Answer

__all__ = ["COMMON_LOADED_WORDS", "LoadedWords"]

# The alternatives every site's pattern has, to go inside a group between word boundaries, matched without regard
# to case.
COMMON_LOADED_WORDS = (
    r"lied|liar|liars|misled|misleading|dishonest|dishonesty|hypocrisy|hypocrite|hypocrites|hypocritical|"
    r"u-turn|u-turns|u-turned|backtracked|backtracking|flip-flopped|flip-flop|flip-flops|admitted|conceded|"
    # "claimed" only as a verb of saying ("claimed that", "claimed the plan had failed"), not of benefits or
    # savings claimed for something, which is neutral
    r"claimed(?=\s*(?:that|to|the|a|an|it|there|this|these|he|she|they|we)\b|\s*[,:\"“]|\s*$)|"
    r"attacked|slammed|blasted|dodged|evaded|evasive|refused to answer|gaffe|gaffes|scandal|scandals|"
    r"scandalous|disgraceful|shameful|incompetent|incompetence"
)


class LoadedWords:
    """The loaded-words check with one site's list. Not for subclassing."""

    def __init__(self, pattern: re.Pattern[str]) -> None:
        self._pattern = pattern

    def flag(self, segments: list[Segment]) -> int:
        """Set ``segment.loaded`` to the [start, end] spans of loaded words outside quotations; return the count."""
        total = 0
        for i, start, text in outside_quotes(segments):
            seg = segments[i]
            for m in self._pattern.finditer(text):
                seg.loaded.append({"start": start + m.start(), "end": start + m.end(), "word": m.group(0)})
                total += 1
        return total

    def still_loaded(self, answer: Answer | None) -> Answer | None:
        """A saved briefing's judgemental-word marks, judged again by the current list (a word since recognised as
        neutral in its use, such as "the benefits claimed", is no longer marked). Nothing is ever newly marked."""
        if not answer:
            return answer
        segs = answer.get("segments")
        if not segs or not any(x.get("loaded") for x in segs):
            return answer

        def keep(seg: dict[str, Any], mark: dict[str, Any]) -> bool:
            m = self._pattern.match(seg["text"], mark["start"])
            return m is not None and m.end() == mark["end"]

        segs = [{**x, "loaded": [m for m in x["loaded"] if keep(x, m)]} if x.get("loaded") else x for x in segs]
        return cast(Answer, {**answer, "segments": segs,
                             "loaded_words": sum(len(x.get("loaded") or []) for x in segs)})
