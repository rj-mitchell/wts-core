"""The checks on an AI-written briefing: where the sites' promises to readers are kept.

Every citation is checked against the site's own copy of its source; every quotation is looked for word for word;
every sentence with no citation is classed, and a claim among them is marked as a point to check; loaded words in
the model's own voice are marked; American spellings in the model's own words are made British. Nothing is silently
rewritten or dropped: what fails a check is shown to the reader as such.

These must never be weaker than the strictest site's copy, case for case (CONTRIBUTING.md, rule 2). What is a
site's own is passed in and has no default here: its "no records" words, its honorifics, its form of the "note
about the evidence" rule (``Verifier``), and its whole list of loaded words (``LoadedWords``).

A site's pipeline runs them through ``check_briefing``, which keeps the order all three sites run them in today::

    report = verifier.verify(blocks, sources)
    verifier.drop_preambles(report.segments)
    britishise_segments(report.segments)
    loaded.flag(report.segments)
    verifier.check_quotes(report, sources)
    answer = report.to_dict()            # then curl_answer(answer), for a site with curly quotes

and shows a saved or cached briefing through ``loaded.still_loaded(verifier.recheck(answer))``.

Plain Python over text and lists: nothing here imports an outside library, the model, the index or a site's record.
``wts_core.checks.balance`` holds the three small functions the sites' rankings share.
"""

from __future__ import annotations

from wts_core.checks.balance import blend, recency_factor, round_robin
from wts_core.checks.british import britishise_segments, outside_quotes, to_british
from wts_core.checks.neutral import COMMON_LOADED_WORDS, LoadedWords
from wts_core.checks.report import check_briefing
from wts_core.checks.typography import curl_answer, curl_event, curl_events, curl_quotes
from wts_core.checks.verify import (
    COMMON_HONORIFICS,
    EVIDENCE_NOTES_STRICT,
    EVIDENCE_NOTES_WIDE,
    RULES_VERSION,
    Segment,
    SourceText,
    Status,
    TitledSource,
    Verification,
    Verifier,
)

__all__ = [
    "COMMON_HONORIFICS",
    "COMMON_LOADED_WORDS",
    "EVIDENCE_NOTES_STRICT",
    "EVIDENCE_NOTES_WIDE",
    "RULES_VERSION",
    "LoadedWords",
    "Segment",
    "SourceText",
    "Status",
    "TitledSource",
    "Verification",
    "Verifier",
    "blend",
    "britishise_segments",
    "check_briefing",
    "curl_answer",
    "curl_event",
    "curl_events",
    "curl_quotes",
    "outside_quotes",
    "recency_factor",
    "round_robin",
    "to_british",
]
