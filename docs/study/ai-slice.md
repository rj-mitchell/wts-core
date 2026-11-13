# The AI slice: an exact comparison of the three copies

Study for `wts-core`, 12 November 2026. Read-only: nothing in any site repository was changed.

**Shorthand for paths**

| Short | Means |
|---|---|
| `M:` | `/home/user/wherempsstand/src/hansard/` (Where MPs Stand, `HANSARD_`) |
| `C:` | `/home/user/wherecountriesstand/src/wcs/` (Where Countries Stand, `WCS_`) |
| `L:` | `/home/user/wherecouncilsstand/src/councils/` (Where Councils Stand, `COUNCILS_`) |
| `Mt:` `Ct:` `Lt:` | each repository's `tests/` folder |

**Marks on differences:** (a) a fix one copy has and the others lack; (b) deliberate and site-specific;
(c) incidental (wording, names, order).

**How alike the copies are today** (difflib ratio on lines, after making package names and prefixes the same):

| Module | MPs–Countries | MPs–Councils | Countries–Councils |
|---|---|---|---|
| `rag/verify.py` | 0.99 | 0.97 | 0.98 |
| `rag/neutral.py` | 0.92 | 0.82 | 0.76 |
| `rag/british.py` | 1.00 | 0.99 | 0.99 |
| `rag/answer.py` | 0.94 | 0.92 | 0.93 |
| `embed/base.py` | 0.99 | 0.99 | 0.99 |
| `index/lance.py` | 0.57 | 0.61 | 0.70 |
| `index/build.py` | 0.26 | 0.23 | 0.39 |
| `rank/evidence.py` | 0.30 | 0.31 | 0.46 |
| `rank/composite.py` | 0.67 | 0.64 | 0.81 |
| `rag/pipeline.py` | 0.21 | 0.20 | 0.73 |
| `engine.py` | 0.35 | 0.31 | 0.62 |
| `evaluate.py` | 0.10 | 0.10 | 0.74 |
| `rag/query_parse.py` | 0.22 | 0.18 | 0.42 |

**What was run, and what was not read**

- Run: the `ndiff.sh` helper; difflib; two probes against the SDKs already installed in
  `/home/user/wt/mps-1b/.venv` (anthropic 1.12.1, duckdb 1.5.6, lancedb 0.40.0) and
  `/home/user/wt/councils-1b/.venv` (anthropic 2.3.0, duckdb 2.0.0, lancedb 0.40.0); and one probe that imported
  each site's own `rag/verify.py` and `rag/neutral.py` from the main checkouts (no bytecode written) to confirm
  the behaviours marked "probe" below. No `uv sync` was needed. No call was made to the Anthropic API.
- Read in full, every copy: `rag/verify.py`, `rag/neutral.py`, `rag/british.py`, `rag/typography.py`,
  `rag/answer.py`, `embed/base.py`, `index/lance.py`, `rank/evidence.py`, `rank/composite.py`, `evaluate.py`;
  `index/build.py` (MPs and Countries in full; Councils lines 150–222 and the diff against Countries);
  `rag/pipeline.py` (Countries in full; Councils 55–158; MPs 1–58, 150–230, 545–680).
- **Not read:** MPs `rag/pipeline.py` 59–149 and 231–544 (finding the evidence, comparisons); MPs `engine.py`
  apart from 85–96, 165–182 and 425–466; `Engine.__init__` in every site; MPs `index/float16.py`,
  `index/retune.py`, `index/evidence.py`, `rank/rerank.py`, `rag/blend.py`; `rag/interests.py` apart from
  `check` (255–296); `api/usage.py` in every site; `store/parquet.py` beyond a grep; Councils `index/build.py`
  75–150; the web pages' JavaScript that consumes the events; and most test bodies (test names are listed for all,
  bodies were read only where quoted).

---

## 1. `rag/verify.py`: the citation verifier

### What it does

Takes the text blocks of the model's final message (each `{"text", "citations"}`) and the numbered sources it was
given; checks every citation against the site's own copy of the source; labels every uncited stretch; and returns a
report the page shows to the reader. Later steps mutate the report's segments in place.

Public signatures (the same in all three; line numbers are MPs', Countries' and Councils' are within ±4):

```python
@dataclass
class Segment:                                   # M:rag/verify.py:35
    text: str
    sources: list[int] = []                      # 1-based source numbers
    cited: list[dict] = []                       # [{"source": n, "cited_text": str}]
    status: str = "cited"                        # cited | connective | unsupported | invalid
    loaded: list[dict] = []                      # set by neutral.flag_loaded: {"start","end","word"}
    misquotes: list[dict] = []                   # set by check_quotes: {"start","end","text"}
    def to_dict(self) -> dict                    # keys: text, sources, cited, status, loaded, misquotes

@dataclass
class Verification:                              # M:rag/verify.py:49
    segments: list[Segment]; no_records: bool
    citations_total: int; citations_invalid: int
    unsupported_chars: int; cited_chars: int
    quotes_total: int = 0; quotes_unverified: int = 0
    @property grounded_ratio -> float            # cited / (cited + unsupported); 1.0 when both are 0
    def markdown(self) -> str                    # text + " [Source n]..." after each segment with sources
    def to_dict(self) -> dict                    # the stats dict, below

def verify(blocks: list[dict], sources: list[Source]) -> Verification          # M:225 C:221 L:221
def drop_preambles(segments: list[Segment]) -> int                             # M:214 C:210 L:210
def check_quotes(report: Verification, sources: list[Source]) -> int           # M:287 C:283 L:283
def recheck_flags(answer: dict | None) -> dict | None                          # M:105 C:105 L:105
```

`recheck_flags` exists in **all three** copies, not only MPs'. Callers: `M:api/briefings.py:142`,
`C:api/app.py:285–296` (through `_recheck_straight`), `L:api/app.py:153`.

**The stats dict** (`Verification.to_dict`, `M:rag/verify.py:73–85`), identical in all three:

| Key | Value |
|---|---|
| `segments` | `[Segment.to_dict()]` |
| `markdown` | `markdown()` |
| `no_records` | the whole text, stripped, starts with `NO_RECORDS` (`"No records found."` in every site's `rag/prompts.py`) |
| `citations_total` | every citation on every block |
| `citations_invalid` | citations whose source number is unknown or whose text is not in the source |
| `grounded_ratio` | `round(cited_chars / (cited_chars + unsupported_chars), 3)`; `unsupported_chars` counts `unsupported` and `invalid` segments; `connective` text counts on neither side |
| `unsupported_segments` | number of segments with status `unsupported` (not `invalid`) |
| `loaded_words` | `sum(len(s.loaded))` |
| `quotes_total`, `quotes_unverified` | set by `check_quotes` |

**The rules**, in order (identical unless the differences table says otherwise):

1. **A cited block** (`verify`, `M:242–254`): for each citation, the source is found by
   `c.get("search_result_index", c.get("document_index"))` against `{s.n - 1: s}`. The citation is valid when
   `_compact(cited_text) in _compact("\n\n".join(src.blocks))`, where `_compact` straightens curly quotes,
   lower-cases and removes **all** white space (`M:23–31`), so a citation running across two paragraphs is accepted.
   The segment is `cited` if at least one citation is valid, otherwise `invalid`.
2. **An uncited block** goes to `_classify_uncited(text, next_is_cited)` (`M:161–203`), line by line. A line is
   `connective` when any of these holds, otherwise `unsupported`:
   - `_is_connective(line)` (`M:94–102`) and the line is not a sentence split off a lead-in: empty; matches
     `_DATE_ONLY`; starts with `#` or ends with `:`; or, after stripping `^[\s\-*•\d.)]+`, is at most
     `_CONNECTIVE_MAX = 60` characters with no match for `\d{4}|£|%`;
   - `_LABEL` matches (a heading or a bold label on its own line);
   - it is the lead-in: the last line, the next block is cited, the body is at most `_ATTRIBUTION_MAX = 220`
     characters, contains no sentence end and does not end with a full stop;
   - `_EVIDENCE_NOTE` matches and `_SOMEONE_SAID` does not.
3. **Splitting a lead-in off a claim** (`M:176–187`): when the next block is cited and the last line contains a
   sentence end, the text after the last sentence end is the lead-in (if at most 220 characters and not ending in a
   full stop), and what comes before it is recorded in `claims`: "never a mere transition, however short".
4. **Honorifics** (`M:131`, `M:172`): the checks read a copy of the text with the full stop of an honorific
   replaced by U+2024 (same length), so "Mr. Smith said" is not split at "Mr."; the text kept is the original.
5. **A lead-in in pieces** (`verify`, `M:236–239`): for an uncited block, following uncited blocks that are
   `_is_lead_in_piece` (non-empty after removing honorific stops, at most 80 characters, no newline, no sentence end
   inside or at the end; `M:134–138`) are skipped when looking for "the next block is cited".
6. **`drop_preambles`**: removes openers matching `_PREAMBLE` and capitalises the next letter. It changes
   `seg.text` after the character counts were taken.
7. **`check_quotes`**: every quotation matched by `_QUOTE` in the joined segments with at least 3 words is looked
   for, word for word, in the sources cited for it: the sources of every segment the quotation overlaps, or of a
   segment starting within 3 characters after it. If no source is cited there, it is looked for in **all** sources
   (`M:310`). Haystack per source: title, `meta["heading"]` and the blocks, reduced by `_words` (lower case, letters
   and digits only, apostrophes dropped, a word printed twice in a row collapsed). A quotation may contain gaps
   (`_ELLIPSIS`); each part of 2 or more words must be found; a quotation with no such part passes. Not found:
   `{"start","end","text"}` is appended to `misquotes` of every segment it overlaps.
8. **`recheck_flags`**: for a saved answer dict, each `unsupported` segment is classified again on its own; if every
   resulting piece is `connective` it becomes `connective`, and `unsupported_segments` and `grounded_ratio` are
   recomputed from the saved text lengths. "Nothing is ever newly flagged."

**Exact patterns** (MPs' copy; identical in the others except where the differences table says):

```python
_WS = re.compile(r"\s+")                                                                    # M:19
_DATE_ONLY = re.compile(r"^\W*(?:on\s+)?\(?\s*(?:(?:written|oral)\s+(?:answer|question|statement)s?,?\s*)?"
                        r"(?:\d{1,2}\s+)?(?:[A-Z][a-z]+\s+)?\d{4}\s*\)?\W*$")               # M:90
_HONORIFIC_DOT = re.compile(r"\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St)\.")                            # M:131 C:127
_HONORIFIC_DOT = re.compile(r"\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|Cllr|Rev|Revd|Hon)\.")          # L:128
_LABEL = re.compile(r"^\s*(#+ .*|\*\*[^*]+\*\*:?)\s*$")                                     # M:141
_EVIDENCE_NOTE = re.compile(                                                                # M:143 C:139
    r"\b(records? (retrieved|supplied|shown)|(retrieved|supplied) (records|results|sources)|in the records|"
    r"no (division|voting) records|no (recorded[- ]vote|vote|voting) (data|records|tables)|"
    r"(votes?|data) (were|was) (not )?supplied|\b(are|were|is|was) (not )?(supplied|retrieved)\b|evidence (base|is|set)|gaps?\b|caveats?\b|cannot be (reported|attributed)|"
    r"(were|was) not relevant|been excluded|the records (are|were|contain|include|cover)|little (was|is) (found|said)|"
    r"nothing (was|is) found|no stated position|written questions only|"
    r"decides? (many|most|some)? ?(of )?(these |the |such )?(subjects|matters|areas|policies) for ((its|their) own "
    r"nations?|wales|scotland|northern ireland)|(is|are) (a )?separate (parliament|legislature)s?\b|decides? (different|separate|their own) "
    r"(matters|subjects|policies)\b|"
    r"^\W*(about the evidence|notes?)\b\W*:)", re.I)
# Councils (L:140) has the same pattern without the second and third lines' extra alternatives; its second line is:
#     r"no (division|voting) records|evidence (base|is|set)|gaps?\b|caveats?\b|cannot be (reported|attributed)|"
_SOMEONE_SAID = re.compile(r"\b(?:[A-Z][\w'-]+|[Hh]e|[Ss]he|[Tt]hey)\s+(?:also\s+)?"
                           r"(?:said|argued|claimed|stated|told|described|called)\b")       # M:155
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s+\S")                                          # M:157
_PREAMBLE = re.compile(                                                                     # M:207
    r"(^|\n|[.!?] )([-*•]\s+)?(?:across|in|from|based on|on the basis of|according to|within)\s+"
    r"(?:all\s+)?(?:the\s+|these\s+)?(?:retrieved\s+|supplied\s+)?(?:records?|evidence|search results|results|"
    r"sources|contributions)(?:\s+(?:retrieved|supplied|provided|shown|available|here|above))?\s*[,:]\s*"
    r"([a-z]?)", re.I)
_QUOTE = re.compile(r'["“]([^"“”\n]{6,}?)["”]|‘([^‘’\n]{6,}?)’(?![a-z])')   # M:265
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…|\[[^\]]{0,40}\])\s*")                          # M:267
_WORDS = re.compile(r"[^a-z0-9]+")                                                          # M:268
_REPEATED = re.compile(r"\b(\w+)(?: \1\b)+")                                                # M:271
```

### Differences

MPs' and Countries' copies differ in **one place only** (`recheck_flags`). ENGINE.md still names Countries as the
upstream "for honorifics, lead-ins split across pieces and a wider note-about-the-evidence pattern"; MPs' copy now
has all three (its tests are headed "ported from Where Countries Stand's verifier", `Mt:test_rag.py:400`) and is
ahead by one fix. ENGINE.md also says Councils' verifier "already matches MPs'": it does not (rows 2–4).

| # | Behaviour | MPs | Countries | Councils | Mark | Best, and the effect on strictness |
|---|---|---|---|---|---|---|
| 1 | `recheck_flags`: is the saved segment followed by a citation? | Skips following non-cited segments that are lead-in pieces, as `verify` does (`M:rag/verify.py:112–118`) | Looks at the next segment only (`C:rag/verify.py:112–114`) | Next segment only (`L:rag/verify.py:112–114`) | (a) MPs | MPs', because it makes a saved briefing match what `verify` gives a new one. Adopting it **removes** flags from saved Countries and Councils briefings (probe: a saved lead-in "…, as when Mr. " + "Stephens said " + citation stays `unsupported` in C and L, is cleared in M). It clears nothing `verify` would flag today. See the hole below before porting |
| 2 | Honorifics whose full stop ends no sentence | `Mr Mrs Ms Dr Prof Sr Jr St` (`M:131`) | the same (`C:127`) | adds `Cllr Rev Revd Hon` (`L:128`) | (a) Councils, in part (b) | Councils'. Probe: "- Speaking for the administration …, Cllr. Jones said " + citation is flagged `unsupported` in M and C (the line is cut at "Cllr."), `connective` in L. Adopting it removes false flags; it weakens the check only where one of these abbreviations really ends a sentence before a lead-in, which is rare. All lists are case-sensitive: Hansard's lower-case "the hon. Member said " is cut at "hon." in every copy (by reading, not run) |
| 3 | `_EVIDENCE_NOTE`: three extra alternatives about vote data and things "supplied"/"retrieved" | present (`M:145–146`) | present (`C:141–142`) | absent (`L:142`) | ENGINE.md treats it as (a) in M and C | **Do not port to Councils as it is: it makes the check weaker.** Probe: "Gas was supplied to two million homes by the company in that year alone, they found." is `connective` (not flagged) in M and C and `unsupported` in L, because `\b(are\|were\|is\|was) (not )?(supplied\|retrieved)\b` matches any such sentence. Councils is the strict one. The cost in Councils is false flags on real notes ("No recorded-vote data was available…", "The votes … were not supplied…": both flagged in L) |
| 4 | Comments and docstring examples ("Delattre", "Jones") | | | | (c) | |

**Weaknesses that all three copies share** (not differences, but a shared implementation inherits them, and "the
checks must never weaken" applies to the first one today):

- **`recheck_flags` clears a real flag.** `verify` marks a sentence split off a lead-in as a claim however short it
  is (the `claims` set, `M:175–187`, used at `M:194`). `recheck_flags` classifies the saved segment alone, with no
  `claims`, so a claim of 60 characters or fewer with no year, £ or % passes `_is_connective`. Probe, same result in
  M, C and L: blocks "Labour MPs criticised the government. Jane Smith said on 4 May that " + citation give
  `unsupported, connective, cited` with `unsupported_segments` 1 and `grounded_ratio` 0.406; `recheck_flags` on that
  answer gives `connective, connective, cited`, 0 and 1.0. Every saved or cached briefing shown again loses such
  flags. A shared `recheck_flags` should clear a flag only for a reason other than shortness (date, label, lead-in,
  note about the evidence), or the segment should record why it was flagged.
- `gaps?\b` and `caveats?\b` in `_EVIDENCE_NOTE` match ordinary claims: "The funding gap between northern and
  southern councils has widened sharply over the decade." is `connective` in all three (probe).
- Any uncited line of 60 characters or fewer without a year, £ or % is `connective` (`M:101–102`).
- `c.get("search_result_index", c.get("document_index"))`: `_block_to_dict` always sets `search_result_index`
  (to `None` when absent), so the `document_index` fallback never applies.
- `cited_chars` and `unsupported_chars` are counted before `drop_preambles`, British spelling and curling change
  the text; `recheck_flags` counts the saved text. The two ratios can differ slightly.
- `_SENTENCE_END` knows `"` `'` `)` `]` after the stop but not `”` or `’`. Countries works round this by
  straightening quotes before `recheck_flags` (`C:api/app.py:281–296`). A shared verifier that may be given curled
  text needs the curly marks in the pattern or the same wrapper.
- A quotation with no citation on or just after it is checked against every source (`M:310`).

### Site-specific inputs a shared implementation must take

| Input | Today |
|---|---|
| The "no records" sentence | `NO_RECORDS = "No records found."`, imported from each site's `rag/prompts.py`; the same string in all three |
| Honorifics | row 2; Councils adds `Cllr\|Rev\|Revd\|Hon` |
| Extra "note about the evidence" phrases | row 3 (vote data: MPs and Countries). The devolution phrases ("decides … for its own nation", "is a separate parliament") are MPs' subject matter but are in all three copies (`Mt:test_rag.py:340` tests them) |
| `_DATE_ONLY`'s "(written\|oral) (answer\|question\|statement)" | parliamentary wording, in all three copies |
| The `Source` shape | needs `.n`, `.blocks`, `.title`, `.meta.get("heading")`; identical dataclass in all three (`M:rag/sources.py:24`, `C:rag/sources.py:28`, `L:rag/sources.py:33`) |
| Limits | `_CONNECTIVE_MAX = 60`, `_ATTRIBUTION_MAX = 220`, lead-in piece 80; the same everywhere, never configured |
| Marker format | `[Source n]` in `markdown()`; the same everywhere |

### Tests

| Site | File and tests | What each asserts |
|---|---|---|
| MPs | `Mt:test_rag.py:46 test_verify_marks_cited_unsupported_and_invalid` | statuses `connective, cited, unsupported, invalid`; totals 2 and 1; `[Source 1]` only; ratio between 0 and 1 |
| | `:64 test_verify_separates_lead_ins_and_evidence_notes_from_uncited_claims` | heading, bold label, bullet lead-in and four evidence notes are not flagged; "attacked the decision" is; `unsupported_segments == 1` |
| | `:89 test_verify_detects_no_records_answer` | `no_records` |
| | `:229 test_quotations_are_checked_word_for_word` | 4 quotations, 1 not found; ellipsis, `[d]` insertion, "Gentleman" from "Gentleman's"; two-word term skipped; exact `misquotes` span |
| | `:247 test_a_word_printed_twice_in_the_record_does_not_make_a_misquote` | `_found` with a doubled word |
| | `:260 test_the_closing_note_about_the_evidence_is_not_a_claim` | "About the evidence:" is connective; with "Jane Smith said" it is unsupported |
| | `:273 test_a_lead_in_after_an_uncited_sentence_is_not_flagged_but_the_sentence_is` | the split, with exact texts |
| | `:282 test_the_date_after_a_citation_is_not_flagged` | five date forms connective; a date followed by a claim with % unsupported |
| | `:292 test_openers_about_the_records_are_dropped` | 2 removed, exact texts |
| | `:326 test_saved_briefings_are_rechecked_by_the_current_rules` | date cleared, long claim kept, counts and ratio recomputed, `None` and empty pass through |
| | `:340 test_the_devolution_note_is_not_a_point_to_check` | five devolution notes connective; ". Jane Smith said that " connective |
| | `:377 test_a_citation_across_two_paragraphs_is_accepted` | joined-paragraph citation valid; a wrong one invalid |
| | `:403 test_an_honorifics_full_stop_ends_no_sentence` | "Mr."/"Dr." do not split; a real claim before is still flagged; text kept as written |
| | `:415 test_a_lead_in_written_in_pieces_is_not_a_claim` | pieces connective; a whole sentence between breaks it |
| | `:429 test_notes_that_data_was_not_supplied_are_not_claims` | three vote-data notes connective (row 3) |
| | `:438 test_saved_briefings_with_a_lead_in_in_pieces_are_cleared` | row 1 |
| | `:255 test_pipeline_reports_checked_quotations` | end to end, `quotes_unverified == 0` |
| Countries | `Ct:test_rag.py:102 test_verification_and_loaded_words` | a valid citation; "regime" and "the West" flagged; "the west of the country" not |
| | `:153 test_lead_ins_in_pieces_are_not_claims` | pieces with "Mr. " connective; following claim unsupported |
| | `Ct:test_typography.py`, `Ct:test_pipeline.py:114` | see section 2 |
| Councils | `Lt:test_verify.py:14 test_a_lead_in_written_in_pieces_is_not_a_claim` | with "Cllr. " |
| | `:23 test_an_honorific_does_not_split_a_lead_in_into_a_claim` | "Mr. Smith, the portfolio holder, said " connective; claim before it flagged; text unchanged |
| | `:32 test_a_long_uncited_piece_still_breaks_the_lead_in` | a long piece between is unsupported |

**Union of cases:** MPs' set covers everything Countries tests; Councils adds "Cllr." and the long-piece case. No
site tests: an `invalid` citation's effect on the ratio in isolation, the `document_index` fallback, single-quoted
quotations, `recheck_flags` on a split-off short claim (the hole above), or curled text.

---

## 2. `rag/neutral.py`, `rag/british.py`, `rag/typography.py`

### `rag/neutral.py`: loaded words

**What it does.** One compiled pattern `LOADED`, applied only to the model's own words (outside double quotation
marks, via `british.outside_quotes`). Nothing is rewritten: spans are recorded on the segment.

```python
def flag_loaded(segments: list[Any]) -> int        # M:43 C:50 L:44; appends {"start","end","word"} to seg.loaded
def still_loaded(answer: dict | None) -> dict | None   # M:28 C:35 L:30; drops saved marks the list no longer matches
```

`still_loaded` keeps a mark only when `LOADED.match(seg["text"], mark["start"])` ends at `mark["end"]`, then
recomputes `loaded_words`. The mechanism (both functions) is **identical** in all three.

**The lists.** The common part, in every copy (`M:17–23`):

```
\b(lied|liar|liars|misled|misleading|dishonest|dishonesty|hypocrisy|hypocrite|hypocrites|hypocritical|
u-turn|u-turns|u-turned|backtracked|backtracking|flip-flopped|flip-flop|flip-flops|admitted|conceded|
claimed(?=\s*(?:that|to|the|a|an|it|there|this|these|he|she|they|we)\b|\s*[,:\"“]|\s*$)|
attacked|slammed|blasted|dodged|evaded|evasive|refused to answer|gaffe|gaffes|scandal|scandals|
scandalous|disgraceful|shameful|incompetent|incompetence ... )\b          flags: re.IGNORECASE
```

| Site | Added to the common list | Where |
|---|---|---|
| MPs | nothing | `M:rag/neutral.py:16–25` |
| Countries | `regime\|regimes\|rogue state\|rogue states\|puppet government\|puppet governments\|puppet state\|puppet states` inside the group, and a second alternative `\|\b(?-i:the West)\b` (capital letter required) | `C:rag/neutral.py:20–32` |
| Councils | `shambles\|shambolic\|chaos\|chaotic\|fiasco\|spiteful\|vindictive\|racist\|racism\|bigoted\|extremist\|extremists\|far-right\|far-left\|hard-left\|hard-right\|loony\|cronyism\|cronies\|wasteful\|reckless\|botched` | `L:rag/neutral.py:18–27` |

All differences are (b). Probe on "The regime admitted the scheme was a fiasco; the West claimed that it was
reckless and far-right.": MPs flags `admitted, claimed`; Countries `regime, admitted, the West, claimed`; Councils
`admitted, fiasco, claimed, reckless, far-right`.

**Inputs for a shared version:** the common words, a site's extra words, and a site's extra raw alternatives (for
Countries' case-sensitive "the West"). Build the pattern once per site. Sharing the common list means a word added
for one site reaches all three, which can only add flags.

**Tests:** `Mt:test_british.py:51 test_loaded_words_are_flagged_only_outside_quotations`,
`:64 test_claimed_counts_only_as_a_verb_of_saying`; `Ct:test_rag.py:102` (above);
`Ct:test_pipeline.py:79` asserts `loaded_words == 1` end to end; `Lt:test_pipeline.py:147
test_pipeline_end_to_end_is_grounded` (its fake model adds "fiasco"; body not read beyond the fake). No site tests
`still_loaded` by name.

### `rag/british.py`: British spelling

**What it does.** Converts American spellings in the model's own words; never inside double quotation marks, even
across segments; a capitalised word in mid-sentence is treated as a name and left. Code identical in all three; only
line 3 of the docstring differs in Councils ("quoted from the minutes").

```python
def to_british(text: str) -> str                                   # :158  one piece of text
def britishise_segments(segments: list[Any]) -> None               # :163  in place, quote state carried across
def outside_quotes(segments: list[Any]) -> list[tuple[int, int, str]]   # :133  (segment index, offset, text)
```

- `_WORDS` (`:24–52`) is an explicit map (colour, centre, defence, travelled, programme, "percent" to "per cent",
  "toward" to "towards" and so on); `_IZE = ^([a-z]{2,}?)(i|y)z(e|es|ed|ing|ation|ations|er|ers)$` (`:55`) turns
  -ize into -ise except the words in `_IZE_KEEP` (`:17–22`: size, seize, prize, maize, baize and their forms).
- "program" is left after "computer " (`:88`).
- `outside_quotes` and `_QuoteState` treat `“` and a `"` met outside a quotation as opening, `”` and a `"` met
  inside as closing. **Single quotation marks are not quotations here**, though `check_quotes` does treat
  `‘…’` as one: text inside single quotes is respelt and searched for loaded words. The same in all three.

**Differences:** none in behaviour. **Inputs:** none. **Tests:** `Mt:test_british.py` (8 tests: `:9` converts,
`:15` quotations never changed, `:22` quotation spanning segments, `:31` names and lookalikes, `:39` capitals at
sentence starts, `:46` British text unchanged, plus the two loaded-word tests). Countries and Councils have no test
of `british.py` by name.

### `rag/typography.py`: curly quotes (Countries only)

`C:rag/typography.py` (74 lines). Not in MPs or Councils.

```python
def curl_quotes(text: str) -> str            # :21
def curl_answer(answer: dict | None) -> dict | None     # :46  segments curled as one text; "markdown" curled too
def curl_events(events: list[dict]) -> list[dict]       # :64
def curl_event(e: dict) -> dict              # :69  the final event's answer, and the plan's interpretation
```

Each straight mark becomes exactly one curly mark, so the positions in `loaded` and `misquotes` stay right. Marks in
`_PROTECTED = (?:https?://|www\.)\S+|`[^`\n]*`|<[A-Za-z/!][^<>\n]*>` are left alone. It runs **last**, after every
check has read the straight text (`C:rag/pipeline.py:158–159`), and again when a saved briefing is shown
(`C:api/app.py:277`). Mark: (b) today; a candidate for sharing later, but it forces the `_recheck_straight`
wrapper (`C:api/app.py:281–296`) on any site that adopts it.

**Tests:** `Ct:test_typography.py:6, :17, :22, :37`; `Ct:test_pipeline.py:114
test_briefings_are_written_with_curly_quotes` (asserts `quotes_total == 1`: the quotation was checked before
curling).

---

## 3. `rag/answer.py`, and every call to the model

### What `rag/answer.py` does

```python
FALLBACK_BETA = "server-side-fallback-2026-07-01"          # :17 in all three
KEY_FILE = "anthropic_api_key"                             # :18, a file in the data folder

def api_key() -> str | None            # <PREFIX>_ANTHROPIC_API_KEY, then ANTHROPIC_API_KEY, then data_dir/KEY_FILE
def make_client()                      # anthropic.Anthropic(...)
def cached_system(text: str) -> list[dict]     # [{"type":"text","text":text,"cache_control":{"type":"ephemeral"}}]
def usage_dict(usage: Any) -> dict[str, int]   # the site's own token counts
class Answerer:
    def __init__(self, settings, client=None)  # use_fallbacks = settings.answer.get("use_fallbacks", True)
    def stream(self, question, sources, mode="summary", plan_note="", history=None, today=None,
               group_by=<site default>[, compare=None]) -> Iterator[dict]
    def _run(self, kwargs, fallbacks: bool) -> Iterator[dict]
```

- **`make_client`** (`M:39–49`, `C:48–56`, `L:48–56`): `base_url` from `<PREFIX>_ANTHROPIC_BASE_URL`, default
  `https://api.anthropic.com` (an inherited `ANTHROPIC_BASE_URL` is never followed);
  `timeout=anthropic.Timeout(300.0, connect=10.0)`; `max_retries=2`; `api_key=key` only when a key was found,
  otherwise `anthropic.Anthropic(**options)` so the SDK's own credentials apply.
- **`usage_dict`** (`M:61–71`): `input_tokens` = the API's `input_tokens` + `cache_creation_input_tokens`;
  `output_tokens`; `cache_read_tokens` = `cache_read_input_tokens`; `cache_write_tokens` =
  `cache_creation_input_tokens`. `None` gives four zeros. All read with `getattr(..., 0) or 0`.
- **`stream`** (`M:94–127`): the user message is the sources as `search_result` blocks (each
  `{"type":"search_result","source":url,"title":title,"content":[{"type":"text","text":b}],"citations":{"enabled":True}}`)
  followed by one text block from `user_instruction(...)`. `history`, if given, becomes a note of the last 3
  exchanges, each answer cut to 600 characters. Request: `model` (`settings.answer["model"]`, code default
  `"claude-sonnet-5-5"`), `max_tokens` (default 16000), `system=cached_system(system_prompt(today))`, `messages`,
  `output_config={"effort": ...}` where the effort is `comprehensive_effort` or `summary_effort` (code default
  `"medium"` for both). No `thinking`, no sampling parameters, no tools.
- **The fallback beta** (`_run`, `M:129–133`): with fallbacks,
  `client.beta.messages.stream(**kwargs, betas=[FALLBACK_BETA], fallbacks="default")`; without,
  `client.messages.stream(**kwargs)`. If the first raises `anthropic.BadRequestError` whose text contains
  "fallback", it logs, sets `self.use_fallbacks = False` and runs again without (`M:117–127`). Every pipeline makes
  a new `Answerer` for each briefing (`M:rag/pipeline.py:623`, `C:rag/pipeline.py:144`, `L:rag/pipeline.py:135`), so
  the switch-off is forgotten at once: on an account without the beta every briefing makes a refused request first.
- **Events yielded** (`M:134–153`): from the stream only `content_block_delta` events are read. `text_delta` gives
  `{"type":"text","text"}`; `citations_delta` gives `{"type":"citation","search_result_index","cited_text"}`. Then
  `stream.get_final_message()` gives `{"type":"final","blocks","stop_reason","model","usage"}`, where `blocks` are
  the message's `text` blocks only (`_block_to_dict`, `M:74–85`: `{"text","citations":[{"type","cited_text",
  "search_result_index","source"}]}`); thinking blocks are dropped.

### Differences

| # | Behaviour | MPs | Countries | Councils | Mark | Note |
|---|---|---|---|---|---|---|
| 1 | Timeout and retries written as constants | literals in `make_client` (`M:47`) | `TIMEOUT_SECONDS = 300.0`, `CONNECT_SECONDS = 10.0`, `MAX_RETRIES = 2` (`C:43–45`) | the same but `RETRIES = 2` (`L:43–45`) | (c) | Same values. Countries' comment says the SDK refuses `httpx.Timeout` "from version 2": 1.12.1 refuses it too (probe, section 8) |
| 2 | Default `group_by` of `stream` | `"role"` (`M:96`) | `"region"` (`C:103`) | `"control"` (`L:103`) | (b) | Callers always pass the plan's value |
| 3 | `compare` argument | yes, passed to `user_instruction` (`M:96, :107`) | accepted and passed (`C:103, :114`), but `C:rag/pipeline.py:144–146` never passes one | absent (`L:103, :114`) | (b) MPs; dead in Countries | |
| 4 | `KEY_FILE` comment | "written by `hansard set-key`" | "written by hand" | "written by hand" | (b) | Only MPs has a `set-key` command (`M:cli.py:675–692`) |
| 5 | Order of `key = api_key()` and `options` | | | | (c) | |

No copy has a fix the others lack inside `answer.py`.

### How each site's `rag/query_parse.py` calls the model

The same call in all three:

```python
resp = client.messages.parse(
    model=<query_parse_model or model or "claude-sonnet-5-5">,
    max_tokens=2000,
    system=cached_system(system_prompt(...site arguments...)),
    messages=[{"role": "user", "content": f"{convo}Question: {question}"}],   # convo: MPs only
    output_config={"effort": settings.answer.get("query_parse_effort", "low")},
    output_format=ParsedQuery,                    # a pydantic model, each site's own
)
if resp.stop_reason == "refusal" or resp.parsed_output is None:
    raise RuntimeError(f"query parser returned no output (stop_reason={resp.stop_reason})")
...
return plan, resp.usage                           # the SDK's raw usage object
```

| | MPs | Countries | Councils |
|---|---|---|---|
| Where | `M:rag/query_parse.py:502–556` (call at `:518`) | `C:rag/query_parse.py:314–348` (call at `:320`) | `L:rag/query_parse.py:247–275` (call at `:252`) |
| Model chosen by | `parse_model(settings)` (`:498`) | `parse_model(settings)` (`:310`) | the same expression written inline (`:253`); no `parse_model` |
| Conversation in the message | last 4 questions with what each searched for, and the first 800 characters of the last answer (`:508–517`) | none | none |
| `system_prompt` arguments | regions, parties, today, archive start, party groups | today, start date, archive start, default years (10) | today, start date, default years (4) |
| The fallback beta | not used | not used | not used |
| Usage reported | `usage_dict(u)` on the `plan` event (`M:rag/pipeline.py:212–214`) | the same (`C:rag/pipeline.py:94–98`) | the same (`L:rag/pipeline.py:95–99`) |
| Failure | any exception: offline rules, `plan.parse_error` set (`M:rag/pipeline.py:215–218`) | the same (`C:99–102`) | the same (`L:100–103`) |
| Model named when the cost is recorded | `parse_model(settings)` (`M:api/app.py:550`) | `settings.answer.get("query_parse_model")` (`C:api/app.py:562`) | `settings.answer.get("query_parse_model")` (`L:api/app.py:288`) |

The last row is an (a) for MPs: if `query_parse_model` is unset, Countries and Councils call the briefing model but
record the cost under `None`. Today all three settings files set it (`claude-haiku-5-5`), so nothing is wrong yet.

### Every other place that touches the Anthropic SDK

`import anthropic` appears only in `rag/answer.py` (all three) and `M:cli.py:687`. Calls through a client:

| Where | Call | Parameters |
|---|---|---|
| `M:rag/interests.py:269–271` (`check`) | `client.messages.parse` | `model=parse_model(settings)`, `max_tokens=6000`, `system=cached_system(SYSTEM)`, `output_config={"effort": query_parse_effort}`, `output_format=Matches`; returns `resp.usage` raw; reported as `interests_usage` (`M:rag/pipeline.py:653`) |
| `M:evaluate.py:342–345` (`judge_sources`) | `client.messages.parse` | `model` from `--judge` (default `claude-haiku-5-5`), `max_tokens=4000`, `system=JUDGE_SYSTEM` (a plain string, not cached), `output_config={"effort":"low"}`, `output_format=Grades` |
| `M:evaluate.py:478–482` (`compare_briefings`) | `client.messages.parse` | `model` from `--judge` (default `claude-opus-5-5`), `max_tokens=3000`, `system=COMPARE_SYSTEM`, `output_config={"effort":"medium"}`, `output_format=Verdict` |
| `M:cli.py:691–692` (`set-key`) | `make_client().models.list(limit=1)`, catching `anthropic.AuthenticationError` | |
| `M:cli.py:919–922`, `M:rag/pipeline.py:170–172`, `C:rag/pipeline.py:71–73`, `L:rag/pipeline.py:72–74` | `make_client()` | |
| `M:topics.py` | goes through `Pipeline` (not read) | |

Countries and Councils make no model call outside `rag/answer.py` and `rag/query_parse.py`.

### Site-specific inputs a shared client must take

| Input | MPs | Countries | Councils |
|---|---|---|---|
| Environment prefix | `HANSARD_` | `WCS_` | `COUNCILS_` |
| `[answer] model` | `claude-sonnet-5-5` | the same | the same |
| `[answer] query_parse_model` | `claude-haiku-5-5` | the same | the same |
| `summary_effort` / `comprehensive_effort` / `query_parse_effort` | `medium` / `high` / `low` | the same | the same |
| `max_tokens` (briefing) | 16000 | 16000 | 16000 |
| `use_fallbacks` | true | true | true |
| `summary_sources` / `comprehensive_sources` | 24 / 40 (and `side_sources` 10, `comprehensive_side_sources` 15) | 24 / 40 | 24 / 40 |
| `interests_check` | true | none | none |
| Prompt functions | `system_prompt(today)`, `user_instruction(question, mode, plan_note, history_note, group_by="role", compare=None)` (`M:rag/prompts.py:152, :196`) | `…group_by="region", compare=None` (`C:rag/prompts.py:137, :141`) | `…group_by="control"` (`L:rag/prompts.py:119, :123`) |
| Fixed in code, the same everywhere | parse `max_tokens=2000`; history 3 exchanges of 600 characters; timeout 300 s, connect 10 s, 2 retries |

All values from each `config/settings.toml`, `[answer]`.

### Tests

| Site | Test | Asserts |
|---|---|---|
| MPs | `Mt:test_rag.py:150 test_pipeline_end_to_end_is_grounded` | sources sent as `search_result` blocks; the system block has `cache_control == {"type":"ephemeral"}`; `call["fallbacks"] == "default"`; `call["model"] == "claude-sonnet-5-5"` |
| | `:206 test_api_key_falls_back_to_the_key_file_in_the_data_folder` | name only read |
| | `:391 test_client_has_an_explicit_timeout` | `client.timeout.connect == 10.0`, `.read == 300.0`, `max_retries == 2` |
| | `:353 test_a_follow_up_is_read_with_the_earlier_answer` | name only read |
| Countries | `Ct:test_rag.py:208 test_model_client_gives_up_on_a_dead_connection` | the same three values, and `base_url` starts `https://api.anthropic.com` |
| Councils | `Lt:test_pipeline.py:210 test_the_claude_client_gives_up_after_five_minutes` | name only read |

**Recorded model responses: none in any repository.** Every test uses a hand-written `FakeClient` and
`FakeStream` (`Mt:test_rag.py:95–142`, `Ct:test_pipeline.py:19–61`, `Lt:test_pipeline.py:21–62`; also
`Mt:test_topics.py:38`, `Ct:test_api.py:299`) that yields `content_block_delta` events and a final message built
from `SimpleNamespace`. `messages.parse` is made to raise, so tests always use the offline question rules. No test
exercises the fallback retry, a `max_tokens` stop, or a thinking block in the content.

---

## 4. `embed/base.py`, `index/lance.py`, `index/build.py`

### `embed/base.py`: the embedder

Identical in all three but for one docstring word (line 6).

```python
QUERY_PREFIXES: dict[str, str]     # :21  BAAI/bge-small-en-v1.5, bge-base-en-v1.5, snowflake-arctic-embed-xs and -s:
                                   #      "Represent this sentence for searching relevant passages: "; nomic: "search_query: "
DOC_PREFIXES = {"nomic-ai/nomic-embed-text-v1.5": "search_document: "}     # :28

class Embedder(Protocol):          # :31
    name: str; dim: int; similarity_range: tuple[float, float]
    def embed_documents(self, texts: list[str]) -> np.ndarray
    def embed_query(self, text: str) -> np.ndarray

class HashingEmbedder:             # :48  __init__(dim=256); name "hashing-<dim>"; similarity_range (0.0, 0.6)
class FastEmbedEmbedder:           # :75  __init__(model, cache_dir, threads=None, batch_size=64); similarity_range (0.5, 0.85)
def model_fingerprint(cache_dir: Path) -> str     # :104  SHA-256 over every *.onnx under cache_dir (names and bytes)
def get_embedder(settings) -> Embedder            # :115  settings.embedding: backend, model, dim, threads, batch_size
```

- All vectors are L2-normalised float32 (`_normalise`, `:42`).
- `FastEmbedEmbedder` sets `HF_HUB_OFFLINE=1` when any `*.onnx` is already under the cache folder (`:81–82`), and
  finds `dim` by embedding a probe (`:90`).
- `get_embedder`: `"hashing"` gives `HashingEmbedder(int(cfg.get("dim", 256)))`; `"fastembed"` gives
  `FastEmbedEmbedder(cfg["model"], settings.data_dir / "models", threads=cfg.get("threads"),
  batch_size=int(cfg.get("batch_size", 64)))`.

**Differences:** none. **Inputs:** `[embedding]` (the same in all three settings files: `backend = "fastembed"`,
`model = "snowflake/snowflake-arctic-embed-xs"`, `dim = 384`, `passage_words = 250`, `batch_size = 8`) and the data
folder. **Tests:** no test file is named for it; `HashingEmbedder` is the fixture embedder in `Mt:test_rag.py`,
`Mt:test_search.py`, `Mt:test_blend.py`, `Ct:test_pipeline.py`, `Ct:test_engine.py`, `Ct:test_index.py`,
`Lt:test_pipeline.py`. `model_fingerprint` and the query prefixes are untested (by file and test names; test
bodies were not all read).

### `index/lance.py`: the LanceDB index

Two tables in one LanceDB folder: `passages` (BM25 on `search_text`, the filter columns, the text) and `vectors`
(the filter columns and one vector a passage).

**Generic parts ("vector-index base"): the same code in all three, apart from the table-name attribute.**

| Part | MPs | Countries | Councils |
|---|---|---|---|
| `os.environ.setdefault("LANCEDB_LOG", "error")` before importing lancedb | `:32` | `:26` | `:29` |
| `sanitise_query`, `_QUERY_JUNK = [\"'()\[\]{}:^~*+\-!?\\/<>=\|&]` | `:116–121` | `:71–76` | `:76–81` |
| `sql_str`, `sql_list`, `date_lit` | `:124–129, :362` | `:79–84, :345` | `:84–89, :344` |
| `KEEP_OLD_VERSIONS = timedelta(hours=1)` | `:134` | `:91` | `:96` |
| `SearchIndex.__init__(path, dim)`: `lancedb.connect` | `:138–143` (also `vectors_name`) | `:107–111` | `:105–109` |
| `_names()`: `set(getattr(db.list_tables(), "tables", res))` | `:146–148` | `:114–116` | `:112–114` |
| `passages()`, `vectors()`: open, or create from the schema | `:150–158` | `:118–126` | `:116–124` |
| `has_data()` | `:160` | `:128` | `:126` |
| `replace_keys(keys, rows)`: delete by `source_key`, add | `:164–173` | `:132–141` | `:130–139` |
| `delete_copies(pairs)` | `:175–186` | `:159–170` | `:141–152` |
| `add_vectors(keys, rows, vectors)` | `:188–198` | `:172–180` | `:154–162` |
| `build_indices`: FTS `FTS(with_position=False, stem=True, remove_stop_words=True)`, scalar indices, `passage_id` BTree on vectors, IVF-PQ `IvfPq(distance_type="cosine", num_sub_vectors=max(1, dim // 8))` at 10,000 vectors | `:200–215` | `:182–207` | `:164–180` |
| `ensure_vector_ids()` | `:217–226` | `:213–222` | `:228–237` |
| `unmerged()` | `:252–261` | `:235–247` | `:250–259` |
| `optimize()`: `table.optimize(cleanup_older_than=KEEP_OLD_VERSIONS)` on both tables | `:263–267` | `:249–253` | `:261–265` |
| `bm25(query, where, limit)`: `search(q, query_type="fts").where(where, prefilter=True).limit().to_list()` | `:270–277` | `:256–263` | `:268–275` |
| `vector(vec, where, limit, nprobes, refine_factor, columns, exact)`: cosine, `bypass_vector_index()` when exact, prefilter, selects the filter columns and `_distance` | `:279–306` | `:265–285` | `:277–297` |
| `rebuild_vector_index(rows_per_partition=8192)`: `IvfPq(..., target_partition_size=...)` | `:326–336` | `:287–297` | `:299–310` |
| `passages_for(ids)`, `rows_for_keys(keys)`, `stats()` | `:338–359` | `:299–304, :328–342` | `:312–317, :327–341` |

**The site's own parts:** `FILTER_FIELDS` and `PASSAGE_SCHEMA` (`M:44–77`, `C:38–64`, `L:41–69`); the columns
named in `build_scalar_indices` (`M:240–250`, `C:224–233`, `L:239–248`); and:

| Site | Own methods |
|---|---|
| MPs | `PORTFOLIO_COLUMNS` and `ensure_portfolio_indices` (LabelList indices, `:64, :228–238`); `similarities(vec, passage_ids)` (`:308–324`) |
| Countries | `group_rows`, `set_groups` (rewrite one list column by `merge_insert("passage_id").when_matched_update_all()`, `:143–157`) |
| Councils | none beyond the schema |

A base class therefore needs: the two schemas (or the filter fields and the extra passage columns), the scalar-index
plan (BTree, Bitmap and LabelList columns), and the columns `rows_for_keys` returns (`heading`, `search_text`).

**Differences in the generic parts**

| # | Behaviour | MPs | Countries | Councils | Mark | Note |
|---|---|---|---|---|---|---|
| 1 | Number type of stored vectors | `float16` for new tables, either type read and written (`VECTOR_TYPE`, `vector_schema`, `vector_value_type`, `vector_array`, `query_vector`, `:80–103`, used at `:195–198, :291`) | `float32` (`:67–68, :179`) | `float32` (`:72–73, :161`) | (a) MPs (half the disk; measured in `docs/EVALUATION.md`) | A base should read the type from the table, as MPs does, so each site converts when it chooses |
| 2 | A search that fails once is tried again | `retry_once` (`:106–113`) around `vector` and `similarities` | no | no | (a) MPs, needed only because a conversion swaps the table's folder | Goes with row 1 |
| 3 | A second name for the vectors table | `vectors_name` (`:138–142`) | no | no | (b) MPs' conversion tool | |
| 4 | `unmerged()` counts | BM25 only (`:252–261`) | BM25 and the vector index (`:235–247`) | BM25 only (`:250–259`) | (a) Countries | |
| 5 | When the IVF-PQ index is trained again | never by itself: `build_indices` at 10,000 or more (`:211`), called after every `hansard embed` that added passages (`M:cli.py:238–239`); `rebuild_vector_index` by hand or `index/retune.py` (not read) | `vector_index_due(vectors, trained_on, has_index)` with `MIN_VECTOR_INDEX_ROWS = 10_000`, `VECTOR_INDEX_GROWTH = 1.2` (`:95–103`); the count is kept in `index/state.json` (`C:index/build.py:164–171`); `refresh_indices` (`C:index/build.py:174–192`) | `needs_build()` and `refresh()` with `MIN_VECTORS_FOR_INDEX = 10_000`, `RETRAIN_GROWTH = 1.2` (`:99–100, :195–226`); the count is kept in `index/vector_index.json` (`TRAINED`, `:101, :186–193`) | (a) Countries and Councils have the policy; (c) between them (the same rule written twice, with different names, storage and comparison: `>` in Countries, `>=` in Councils) | One implementation for the base |
| 6 | `build_indices` signature | `() -> None` | `(vectors: bool = True) -> int \| None`, with `build_vector_index()` and `has_index(name, column)` split out (`:182–211`) | `() -> None`, plus `has_keyword_index()` | (c) | Countries' split is the cleanest |
| 7 | `rebuild_vector_index` records the count | no | no (caller does) | yes, `_note_trained` (`:310`) | (c) | |
| 8 | `vectors_for_keys(keys)` | absent | straight from Arrow: `flatten().to_numpy()` reshaped (`:306–314`) | through `to_pylist()` (`:319–325`) | (a) Countries (its comment: "a year's vectors as Python floats would take seconds and hundreds of MB") | Port to Councils |
| 9 | `embedded_ids(keys)`, `versions()` | absent | present (`:316–326`) | absent | (a) Countries: lets `embed_pending` resume inside a source-year, and lets tests see that nothing was written | |

### `index/build.py`: how the embedder's identity is recorded, and whether a change is noticed

| | MPs | Countries | Councils |
|---|---|---|---|
| Where the index's `dim` comes from | `int(settings.embedding.get("dim", 384))` at every `SearchIndex(...)` (`M:cli.py:197, 225, 260, 313, 409`; `M:sync.py:281`; `M:engine.py:143–144`) | the same (`C:index/build.py:201, 245`; `C:cli.py:570, 595, 614`; `C:engine.py:90`) | the same (`L:index/build.py:181`; `L:cli.py:426, 441`; `L:engine.py:81`) |
| Is `dim` compared with the embedder's or the table's? | no | no | no |
| Embedder name recorded | `state.set("embedding_model", embedder.name)` in the state database (`M:cli.py:234`), shown by the status command (`M:cli.py:417`) | not recorded | not recorded |
| Weights recorded | `state.set("embedding_model_sha256", model_fingerprint(data_dir / "models"))` (`M:cli.py:227–233`), fastembed only | not recorded | not recorded |
| Change noticed | **Only in `hansard embed` and the bootstrap** (`embed_pending_cmd`, `M:cli.py:218–241`; `M:bootstrap.py:95`): if the stored hash differs it stops with "embedding model weights changed since the index was built; rebuild vectors or restore the pinned model". The twice-daily update calls `embed_pending` directly (`M:sync.py:517`) and **does not check** | never. `wcs index --re-embed` (`C:cli.py:549–559`, `Indexer(keep_vectors=False)`, `C:index/build.py:197–200`) embeds everything again when the operator says the model changed | never; no re-embed option found |
| What a silent change would do | new vectors from the new model join old ones in one table; nothing fails if the dimension is the same | the same; and unchanged passages keep their old vectors by design (`unchanged_vectors`, `C:index/build.py:220–227`) | the same; a council-year whose passages are all unchanged keeps its vectors (`L:index/build.py:184–213`) |
| What a different dimension would do | `pa.Table.from_pydict(..., schema=vector_schema(self.dim, ...))` fails when vectors are added (by reading; not run) | the same | the same |

So: **no site stores the embedder's identity in or beside the index in a way every writer checks.** `model_fingerprint`
hashes every `*.onnx` under `data/models`, so downloading a second model changes the hash even if the first is
still the one in use.

Other points at this level:

- **What is embedded.** MPs: `f"{heading}: {search_text after its first line}"`, or `search_text` when there is no
  heading (`M:index/build.py:351–352`). Countries: `embedding_text(r)` = `f"{heading}: {search_text after its second
  newline}"` (`C:index/build.py:128–131`). Councils: the same expression inline in `embed_pending`
  (`L:index/build.py:261–`). The text format is the site's own because `search_text` is.
- **Progress.** MPs keeps it in the state database by file (`state.unembedded`, `state.mark_embedded`,
  `M:index/build.py:340–362`). Countries and Councils keep `index/state.json` by source-year or council-year
  (`State`, `C:index/build.py:137–171`, `L:index/build.py:151–175`); Countries' also holds the trained count.
- **`chunk_text`** (`M:34–67`, `C:37–70`, `L:39–`): the same algorithm (paragraphs up to `max_words`, long
  paragraphs split at `(?<=[.!?])\s+`). Paragraphs are split on `"\n\n"` in MPs (`:46`), on `\n\s*\n` in Countries
  (`:49`, an (a): blank lines holding spaces), and on `"\n"` and joined with `"\n"` in Councils ((b): minutes are
  line-based).
- MPs alone uses DuckDB here (`duckdb.connect()`, `:121`); Countries and Councils read through their store modules.

**Tests:** MPs `Mt:test_float16.py` (14 tests: `:49` new tables store 16-bit and find the same, `:61` an old
32-bit table still read and written, `:166` a failed search tried again, the rest on the conversion tool),
`Mt:test_lance_logs.py:24, :28`, `Mt:test_retune.py` (6), `Mt:test_search.py:60
test_where_clause_escapes_values`. Countries `Ct:test_index.py:45 test_a_new_meeting_embeds_only_its_own_passages`,
`:69 test_an_update_with_no_changes_writes_no_new_version`, `:79 test_an_update_merges_new_rows_and_cleans_up`,
`:94 test_the_meaning_index_is_trained_again_only_when_vectors_grow_by_a_fifth`, `:112 test_vector_index_due`;
`Ct:test_engine.py:86 test_where_clause_quotes_values`, `:92 test_chunking`, `:98 test_regroup_updates_groups_in_place`.
Councils `Lt:test_pipeline.py:162 test_reindex_keeps_embeddings_of_unchanged_passages_and_updates_tags`,
`:218 test_an_update_with_no_changes_writes_nothing_to_the_index`,
`:241 test_meaning_search_is_trained_again_once_it_has_grown_by_a_fifth`,
`:267 test_lancedb_logs_only_errors_unless_told_otherwise`. Only names were read for these. No site tests a changed
embedding model.

---

## 5. Balanced selection: `rank/evidence.py` and `rank/composite.py`

### How alike they really are

`rank/evidence.py`: 0.30 (MPs–Countries), 0.31 (MPs–Councils), 0.46 (Countries–Councils).
`rank/composite.py`: 0.67, 0.64, 0.81. The low numbers hide a small core that is the same line for line.

**`select_evidence`**

```python
# MPs        M:rank/evidence.py:117
def select_evidence(scored, profiles, k, *, max_per_speaker=2, min_relevance_ratio=0.25, group_by="role",
                    min_occasions=3, max_persistent=4, only_groups=None) -> list[Scored]
# Countries  C:rank/evidence.py:90
def select_evidence(scored, k, *, group_by="region", max_per_speaker=2, max_per_country=2,
                    min_relevance_ratio=0.25) -> list[Scored]
# Councils   L:rank/evidence.py:71
def select_evidence(scored, k, *, group_by="control", max_per_council=2, max_per_meeting=1,
                    min_relevance_ratio=0.25) -> list[Scored]
```

| Step | Generic? | MPs | Countries | Councils |
|---|---|---|---|---|
| 1. Pool: keep `rel >= best * min_relevance_ratio` | generic | `:122–126`; `rel` is `base_relevance` when re-ranking set one | `:94–95`; `relevance` | `:75–76`; `relevance` |
| 2. Group the pool, in score order | generic loop, site's key | `speaker_group(profile)` or `demographic_group(profile, group_by, only_groups)` on speaker profiles looked up by record (`:128–131`) | `evidence_group(candidate.data, group_by)` (`:96–98`) | `evidence_group(candidate.data, group_by)` (`:77–79`) |
| 3. Order groups by their best score | generic, identical | `:132` | `:99` | `:80` |
| 4. `take(s)`: refuse a record already taken or over a cap | generic shape, site's caps | one cap: per speaker (person id, else the record) (`:136–145`) | two caps: per speaker (`country\|speaker name`) and per country (`on_behalf_of` or country) (`:105–116`) | two caps: per council (`gss`) and per meeting (the record id without its last `:` part) (`:86–97`) |
| 5. Seeds taken before the round-robin | MPs only | members who raised the subject on `min_occasions` separate days, not as ministers, up to `max_persistent` (`:147–161`); `candidate.data["occasions"]` set afterwards (`:177–180`) | none | none |
| 6. Round-robin: best remaining record from each group in turn until `k` or no progress | generic, **identical** | `:163–172` | `:118–127` | `:99–108` |
| 7. Fill by score | generic, identical | `:173–176` | `:128–131` | `:109–112` |
| 8. Sort by `(-score, record_id)` | generic, identical | `:181` | `:132` | `:113` |

Steps 3 and 6–8 are the same 20 lines in every copy. Everything else in `rank/evidence.py` follows the record:
the group keys and labels (`GROUPS`, `GROUP_LABELS`, `TYPE_LABELS`, `group_label`), seat types, runner-up labels,
and `evidence_summary`, whose keys differ entirely (section 6).

Callers pass the best `max(limit * 8, 150)` scored records (`M:engine.py:451`, `C:engine.py:208`, `L:engine.py:154`).
Countries raises its caps when the question names countries (`C:engine.py:201–207`).

**`rank/composite.py`**

| Part | Generic? | Where |
|---|---|---|
| `recency_factor(d, p)`: `1.0` if `p.recency <= 0`, else `floor + (1 - floor) * 0.5 ** (age_years / (min_half_life_years / recency))`, age in days / 365.25, never negative | **identical** | `M:114–119`, `C:88–93`, `L:70–75` |
| Relevance inside `rank`: `bm_max`, `has_sem`, `w = bm25_weight if both else (1.0 if bm_max else 0.0)`, `kw = bm25 / bm_max`, `sem = clamp((cosine - floor) / max(ceiling - floor, 1e-6), 0, 1)`, `rel = w * kw + (1 - w) * sem` | **identical** | `M:146–154`, `C:106–114`, `L:81–89` |
| Sort by `(-score, -relevance, record_id)` | identical | `M:160`, `C:119`, `L:92` |
| `RankParams.from_settings` (copy known keys, `default_recency`, overrides that are not `None`, clamp `recency` to 0–1) | same shape | `M:52–64`, `C:40–52`, `L:31–40` (Councils has no `role_weight`) |
| Authority | the site's | MPs: offices and portfolios, `authority_m(c, query_portfolios, p)` (`:122–139`); Countries: the speaker's role, `m_head 1.0`, `m_minister 0.7`, `m_representative 0.3` (`:96–100`); Councils: none |
| Locality | MPs only | `local_factor 0.7` (`:158`) |
| `Candidate`, `Scored` | the site's fields | MPs adds office flags, portfolios, `local`, `rerank`, `base_relevance` |
| `rank` signature | differs | `rank(candidates, query_portfolios, p)` (MPs); `rank(candidates, p)` (others) |

**Defaults that differ** (each a (b)):

| | MPs | Countries | Councils |
|---|---|---|---|
| `recency` (`default_recency`) | 0.25 | 0.4 | 0.4 |
| `min_half_life_years` | 0.5 | 3.0 | 3.0 |
| `role_weight` (`default_role_weight`) | 1.5 | 1.3 | none |
| `bm25_weight`, `recency_floor`, `semantic_floor`, `semantic_ceiling` | 0.5, 0.35, 0.5, 0.85 | the same | the same |
| Default `group_by` | `"role"` | `"region"` | `"control"` |
| `GROUP_BY` values | `("role", "gender", "age", "tenure", "majority", "runner_up", "group")` (`M:engine.py:35`) | `("region", "council", "bloc")` (`C:rank/evidence.py:65`) | `("control", "region", "type", "council")` (`L:rank/evidence.py:31`) |
| Caps in settings | `max_per_speaker 2`, `min_occasions 3`, `max_persistent 4` | `max_per_speaker 2`, `max_per_country 2` | `max_per_council 2`, `max_per_meeting 1` |
| `min_relevance_ratio` | 0.25 | 0.25 | 0.25 |

### Recommendation

Share **three small functions and nothing else**; about 45 lines in all:

1. `recency_factor(d, today, recency, floor, min_half_life_years) -> float`.
2. `hybrid_relevance(bm25s, cosines, bm25_weight, semantic_floor, semantic_ceiling) -> list[float]` (the blend
   above).
3. `select_balanced(scored, k, *, group_of, caps, min_relevance_ratio=0.25, relevance=None, seeds=()) ->
   list`, where `group_of(s) -> str`, `caps` is a list of `(key_of, maximum)` pairs, `relevance(s)` defaults to
   `s.relevance` (MPs passes its `base_relevance` rule) and `seeds` are records tried first (MPs' persistent
   members).

Keep in each site: `Candidate`, `Scored`, `RankParams`, authority, locality, the group keys and labels,
`evidence_summary`, and the settings names. Sharing more would mean a generic record type, which the sites do not
have. The gain is modest in lines but real in behaviour: the round-robin and the relevance floor decide which
voices a briefing hears, and today a fix to that loop has to be made three times.

**Tests:** MPs `Mt:test_scoring.py` (13: recency properties `:20–49`, role weight `:58–83`, hybrid relevance `:90`,
weak semantic matches not inflated `:100`, sliders clamped `:111`, committee member boost `:116`,
`:127 test_members_who_keep_raising_a_subject_are_included`), `Mt:test_evaluate.py:68
test_rerank_promotes_the_closer_match`, `Mt:test_search.py:48`. Countries `Ct:test_engine.py:47
test_default_search_is_states_and_group_statements`, `:72 test_groups_on_the_day_and_council_place`,
`:114 test_a_named_country_is_not_capped_at_two`. Councils `Lt:test_pipeline.py:128
test_search_is_balanced_and_filters`. Only MPs tests the recency and relevance arithmetic directly; a shared
function should take those tests. No site tests the round-robin in isolation (ties, a group running dry, `k`
larger than the pool).

---

## 6. The event flow: `rag/pipeline.py` and `engine.py`

### What the pipeline consumes and yields

`Pipeline.run(req)` (`M:rag/pipeline.py:584–653`, `C:rag/pipeline.py:122–160`, `L:rag/pipeline.py:113–150`):

1. `make_plan` (the parse call of section 3, or offline rules, or the reader's edited plan).
2. `find` calls `Engine.search(...)`, which returns a `SearchResult` (`M:engine.py:85–94`, `C:engine.py:50–59`,
   `L:engine.py:50–57`): `scored`, `records`, `no_records`, `candidates`, `semantic_available`, `where`, `evidence`
   (and `timings` in MPs and Countries). Sources are numbered from the records by `build_sources`.
3. If there is evidence and a model: `Answerer(...).stream(...)`. `text` and `citation` events are passed on as they
   come; the `final` event is kept back.
4. The checks, on the final event's `blocks`, in this order in all three (`M:644–648`, `C:153–157`, `L:144–148`):
   `verify` → `drop_preambles` → `britishise_segments` → `flag_loaded` → `check_quotes`. Countries then curls
   (`curl_answer`, `C:159`). `to_british` is also applied to the plan's `interpretation` (`M:211`, `C:97`, `L:98`).
5. The pipeline's own `final` event.

### Every event, from the SDK stream to the final answer

**SDK stream → `Answerer`** (identical in all three; `M:rag/answer.py:134–153`)

| SDK | Fields read | Becomes |
|---|---|---|
| stream event `content_block_delta`, `delta.type == "text_delta"` | `delta.text` | `{"type":"text","text"}` |
| stream event `content_block_delta`, `delta.type == "citations_delta"` | `delta.citation.search_result_index`, `.cited_text` | `{"type":"citation","search_result_index","cited_text"}` |
| any other stream event (`message_start`, `content_block_start`/`stop`, `message_delta`, `message_stop`, thinking deltas) | ignored | nothing |
| `stream.get_final_message()` | `content` (text blocks only: `text`, and each citation's `type`, `cited_text`, `search_result_index`, `source`), `stop_reason`, `model`, `usage` | `{"type":"final","blocks":[{"text","citations":[…]}],"stop_reason","model","usage":usage_dict}` |

**`Pipeline.run` → the web layer**

| Event `type` | Fields | MPs | Countries | Councils |
|---|---|---|---|---|
| `progress` | `step: "reading"`, `passages: int`; later `step: "checking"` | yes (`:586`, `:637`) | no | no |
| `plan` | `plan` (`QueryPlan.to_dict()`), `usage` (the parse call's `usage_dict` or `None`), `parse_error` (only when the model call failed) | `:588–591` | `:124–127`; `interpretation` curled | `:115–118` |
| `sources` | `sources` (`[Source.card()]`: `n`, `kind`, `title`, `url`, and the source's `meta`), `candidates`, `semantic`, `evidence` | `:597–602` | `:129–130` | `:120–121` |
| `text` | `text` | passed on | passed on | passed on |
| `citation` | `search_result_index`, `cited_text` | passed on | passed on | passed on |
| `interests` | `interests: [...]` | yes (`:630–633`, `:638–641`) | no | no |
| `error` | `message: "The model declined to answer this question."` | yes, on a refusal or no final event (`:634–636`) | no: a missing final raises `RuntimeError("the model returned no answer")` (`:151–152`); a refusal is **not** checked | the same (`:142–143`) |
| `final` | below | `:651–653` | `:159–160` | `:149–150` |

**`evidence` on the `sources` event**

| Site | Keys |
|---|---|
| MPs | from `evidence_summary` (`M:rank/evidence.py:221–241`): `records`, `speakers`, `divisions`, `date_from`, `date_to`, `groups`, `parties`, `seat_types`, `genders`, `age_bands`, `tenure`, `majority_bands`, `runner_ups`, `party_groups`, `imbalance`, `raised_most`; added by the pipeline (`:599–602`): `devolution`, `edms`, `devolved`, `committee_evidence` |
| Countries | `records`, `countries`, `meetings`, `date_from`, `date_to`, `groups`, `bodies`, `translated`, `ocr` (`C:rank/evidence.py:152–162`); added: `votes` (`C:rag/pipeline.py:130`) |
| Councils | `records`, `councils`, `meetings`, `date_from`, `date_to`, `groups`, `kinds` (`L:rank/evidence.py:130–138`) |

**The `final` event**

| Case | Top-level keys | MPs | Countries | Councils |
|---|---|---|---|---|
| A briefing was written | `type`, `answer`, `usage`, `model`, `stop_reason` | plus `interests` (list) and `interests_usage` (`usage_dict` or `None`) | exactly these; `answer` curled | exactly these |
| No records | `type`, `answer` (below), `usage: None` | condition `not sources or (result.no_records and not divisions)` (`:604`) | `not result.records and not votes` (`:131`) | `not result.records` (`:122`) |
| No API key | `type`, `answer: None`, `usage: None`, `note` | "Showing the evidence set only (no Anthropic API key on the server)." | "Showing the evidence only (no Anthropic API key set)." | the same as Countries |

**Every key of the final `answer` dict when a briefing was written** (the same in all three):

| Key | From |
|---|---|
| `segments` | list of `{"text","sources","cited","status","loaded","misquotes"}`; `cited` items `{"source","cited_text"}`; `loaded` items `{"start","end","word"}`; `misquotes` items `{"start","end","text"}` |
| `markdown` | text with `[Source n]` markers |
| `no_records` | bool |
| `citations_total`, `citations_invalid` | ints |
| `grounded_ratio` | float, 3 places |
| `unsupported_segments` | int |
| `loaded_words` | int. MPs takes it from `to_dict()`; Countries and Councils overwrite it with `flag_loaded`'s return value (`{**report.to_dict(), "loaded_words": loaded}`), which is the same number |
| `quotes_total`, `quotes_unverified` | ints |

**The `answer` dict for "no records"** (built by hand, not by `Verification`): `segments` (one segment with only
`text`, `sources: []`, `cited: []`, `status: "connective"`; no `loaded` or `misquotes`), `markdown: NO_RECORDS`,
`no_records: True`, `citations_total: 0`, `citations_invalid: 0`, `grounded_ratio: 1.0`; MPs adds
`unsupported_segments: 0` (`M:608`). No `loaded_words`, `quotes_total` or `quotes_unverified`. The segment text is
`NO_RECORDS + " The archive contains no records matching this question and these filters."` in MPs and Countries,
`" The minutes contain no records matching…"` in Councils; `markdown` is the bare `NO_RECORDS` in all three.

**What the web layer adds or removes** (read only at `M:api/app.py:536–585`, `C:api/app.py:552–592`,
`L:api/app.py:278–318`):

| | MPs | Countries | Councils |
|---|---|---|---|
| `plan.usage`, `plan.parse_error` | cost recorded; `parse_error` popped and logged; `usage` sent on | the same | both removed before sending |
| `final.usage` | cost recorded; sent on | the same | cost recorded; removed before sending |
| `final.interests_usage` | cost recorded; removed | n/a | n/a |
| Added to `final` | `briefing_key`; the keys `keep_briefing` returns (not read); `support_reminder` for this reader only | `briefing_id` | `briefing_id` |
| `citation` events | sent; kept in memory but not in saved or cached copies | sent; not kept | sent; kept in memory but not in saved or cached copies |
| Saved and cached copy | `plan`, `sources`, one `text` event with the whole text, `final` with `usage: None`, `cached: True` | the same | the same, `usage` already removed |
| On re-display | `still_loaded(recheck_flags(answer))` (`M:api/briefings.py:142`) | `curl_events(still_loaded(_recheck_straight(answer)))` (`C:api/app.py:272–296`) | `still_loaded(recheck_flags(answer))` (`L:api/app.py:149–154`) |
| An exception in the pipeline | an `error` event with a fixed message | the same | the same |

The raw `blocks` from the API are **not kept anywhere**: saved briefings hold the verified `answer`, so `verify`
cannot be run again on a saved briefing; only `recheck_flags` can.

### Differences in the flow

| # | Behaviour | MPs | Countries | Councils | Mark | Note |
|---|---|---|---|---|---|---|
| 1 | A refusal (`stop_reason == "refusal"`) | an `error` event, nothing saved (`M:rag/pipeline.py:634–636`; test `Mt:test_rag.py:178`) | not checked: the empty `blocks` are verified, giving `segments: []`, `markdown: ""`, `grounded_ratio: 1.0`; `answer` is a non-empty dict, so the web layer saves and caches it (`C:api/app.py:568–574, :587–590`) | the same (`L:api/app.py:295–299, :312–315`) | (a) MPs | Port. Stricter: an empty refusal is no longer shown as a fully grounded briefing. (By reading; the refusal path was not run in Countries or Councils) |
| 2 | `stop_reason == "max_tokens"` | not handled | not handled | not handled | shared gap | A briefing cut off at 16000 tokens (which include the model's thinking) is verified and shown as it is |
| 3 | `progress` events | yes | no | no | (b) so far | |
| 4 | `unsupported_segments` in the no-records answer | yes | no | no | (c) | |
| 5 | `loaded_words` set twice | no | yes | yes | (c) | |
| 6 | Curly quotes | no | yes | no | (b) | |
| 7 | Parse order | model first, offline on failure (`:203–226`) | offline first, then the model (`:85–102`) | as Countries | (c) | Same result |
| 8 | `answer_once` collects | `text` joined, and `plan`, `sources`, `final`, `error` (`:656–664`) | `plan`, `sources`, `final` (`:163–169`) | the same (`:153–158`) | (c) | |

**Tests:** `Mt:test_rag.py:150, :169, :178, :183, :255`; `Mt:test_sse.py:11, :23, :34` (the streamer: other slice);
`Ct:test_pipeline.py:79, :114`; `Ct:test_rag.py:144 test_pipeline_without_a_model_shows_the_evidence` (an empty
data folder gives the no-records final); `Lt:test_pipeline.py:147`. Only MPs tests a refusal.

---

## 7. Evaluation

### Where MPs Stand: `hansard eval …`

`M:evaluate.py` (497 lines), commands at `M:cli.py:25–26, :909–1033`, results in `docs/EVALUATION.md`. Three
stages and one free check:

| Command | What it does | Model calls | Writes |
|---|---|---|---|
| `hansard eval plans [--model M \| --model offline] [--effort E] [--only ids]` | `run_plans` (`:131–166`): reads each question, compares each of `PLAN_FIELDS` (`:44–45`) with `expect` (`score_plan`, `:119–128`); dates within `DATE_SLACK_DAYS = 45`; `<field>_any` lists alternatives; `portfolios` scored apart (any overlap) | one `messages.parse` a question (none with `offline`) | `eval/runs/<stamp>-plans-<model>.json` |
| `hansard eval sources --plans FILE [--variant baseline \| rerank:<model>[:question\|keywords\|both[:weight[:top]]]] [--judge claude-haiku-5-5]` | `run_sources` (`:212–255`): `engine.search` with the saved plans, 24 sources each; `judge_sources` (`:321–355`) grades each ungraded source 0, 1 or 2 in batches of 20; `summarise_sources` (`:358–379`) | grading only, for sources not already in `judgments.jsonl` | `eval/runs/<stamp>-sources-<variant>.json` (not committed), `…-sources-summary.json`, appends to `eval/judgments.jsonl` |
| `hansard eval retrieval [--plans FILE] [--compare RUN] [--meaning 300]` | `run_sources` with `meaning`, then `compare_retrieval` (`:258–284`) | none | `eval/runs/<stamp>-retrieval.json`, `…-retrieval-compare.json` |
| `hansard eval briefings --plans FILE [--model claude-opus-5-5 …] [--judge claude-opus-5-5]` | `run_briefings` (`:407–444`): the whole pipeline for each question with the saved plan; `compare_briefings` (`:464–497`): blind side-by-side verdicts, order shuffled with seed 7 | one briefing a question a model ("about $0.06–0.15 each"), plus one judgement a question for each extra model | `eval/runs/<stamp>-briefings-<model>.json` (not committed), `…-compare-<a>-<b>.json` |

**What `briefings` measures** for each question (`:429–441`): `grounded_ratio`, `citations_total`,
`citations_invalid`, `unsupported_segments`, `loaded_words`, `quotes_total`, `quotes_unverified`, `sources_given`,
`sources_cited`, `seconds`, `usage`, `cost`, the `markdown`, and the source texts given to the judge (8000
characters each). The summary (`:447–461`) averages or sums them. **This is the only evaluation in the three sites
that runs the verifier, the loaded-words check and the quotation check**, so it is the only one that can show a
change in those checks.

**Questions file** `eval/questions.toml`: `today = "2026-10-11"`, then 66 `[[q]]` tables (docs/EVALUATION.md
describes the 62 of the first run; the saved runs have 62 rows). Categories: topic 12, demographic 14, party 7,
dates 5, region 5, awkward 4, office 4, combination 3, loaded 3, speaker 3, votes 3, follow-up 2, house 1. One
record:

```toml
[[q]]
id = "wind"
question = "Where do rural and city MPs differ on onshore wind?"
category = "topic"
expect = { houses_any = [[], ["commons"]], portfolios = ["energy_climate"] }
```

Follow-up questions add `history = ["What have MPs said about the assisted dying bill?"]`. Filters not listed are
expected empty (`DEFAULTS`, `:46`: `group_by` "role", `wants_votes` false).

**Judgments** `eval/judgments.jsonl`: 2,649 lines, all graded by `claude-haiku-5-5`. One record:

```json
{"id": "wind", "record_id": "uk.org.publicwhip/wrans/2026-05-20.3564.r0", "grade": 1, "judge": "claude-haiku-5-5"}
```

**Runs** in `eval/runs/` (11 files). A plans run (`20261011-125429-plans-claude-sonnet-5-5.json`) has top-level
`stage`, `model`, `effort`, `today`, `rows`, `summary`; one row, shortened:

```json
{"id": "wind", "category": "topic", "question": "Where do rural and city MPs differ on onshore wind?",
 "got": {"date_from": "", "date_to": "", "houses": ["commons"], "regions": [], "parties": [], "…": "…",
         "group_by": "role", "wants_votes": false, "portfolios": ["energy_climate", "environment", "…"]},
 "fields": {"date_from": true, "date_to": true, "houses": true, "…": true, "portfolios": true},
 "filters_ok": true, "error": null, "seconds": 1.91,
 "usage": {"input_tokens": 3599, "output_tokens": 215, "cache_read_tokens": 0, "cache_write_tokens": 3571},
 "cost": 0.011134,
 "plan": {"question": "…", "search_text": "onshore wind, wind farms, wind turbines, …",
          "filters": {"date_from": null, "date_to": null, "houses": ["commons"], "…": []},
          "portfolios": ["…"], "wants_votes": false, "speakers": [], "unresolved_speakers": [],
          "interpretation": "Searches House of Commons debates on onshore wind …", "parser": "model",
          "group_by": "role"},
 "search_text": "onshore wind, wind farms, …"}
```

Its summary: `{"questions": 62, "all_filters_right": 0.984, "by_field": {…}, "by_category": {"topic": "12/12", …},
"errors": 0, "cost_usd": 0.1882, "cost_per_question_usd": 0.00304, "median_seconds": 2.32, "missed":
["votes-rwanda"]}`.

A sources summary (`20261011-132931-sources-summary.json`): `{"summaries": [{"variant": "baseline", "questions":
62, "mean_grade": 0.801, "share_relevant": 0.961, "share_direct": 0.641, "parties": 4.048, "groups": 4.823,
"seconds": 4.593, "ungraded": 0, "per_question": {"wind": 0.646, …}}, …], "grading": {"graded": 2346, "cost_usd":
0.0921}}`.

A comparison (`20261011-142803-compare-opus-sonnet.json`): `{"stage": "compare", "a": "claude-opus-5-5", "b":
"claude-sonnet-5-5", "judge": "claude-opus-5-5", "rows": [{"id": "wind", "accuracy": "claude-sonnet-5-5",
"balance": "claude-opus-5-5", "coverage": "claude-opus-5-5", "clarity": "claude-opus-5-5", "overall":
"claude-opus-5-5", "reason": "…"}, …], "tally": {"overall": {"claude-opus-5-5": 4, "tie": 2, "claude-sonnet-5-5":
4}, …}, "cost_usd": 0.5659}`.

No `briefings` run and no per-variant `sources` run is in the repository (`.gitignore:41–43`). A hand-assembled
`20261106-retrieval-float16.json` is there too.

### Where Countries Stand and Where Councils Stand: `wcs evaluate`, `councils evaluate`

`C:evaluate.py` (137 lines) and `L:evaluate.py` (135 lines; "adapted from Where Countries Stand's"); commands at
`C:cli.py:112–129`, `L:cli.py:195–214`. One command each:

```
uv run wcs evaluate [--with-model] [--only ID …] [--no-save]
uv run councils evaluate [--with-model] [--only ID …] [--no-save]
```

Two scores a question, **no briefing written**:

1. **Reading the question** (`compare`): each of `FIELDS` equal to `expect`, dates by year; `"default"` for
   `date_from` means `today.year - default_years` (Countries, 10 years; Councils `max(…, start.year)`, 4 years);
   `<field>_any` alternatives. Countries' `FIELDS` (`:31`): `sources, countries, groups, date_from, date_to,
   wants_votes`. Councils' (`:33–34`): `councils, nations, council_types, kinds, control, parties, date_from,
   date_to, wants_votes`.
2. **The evidence** (`run`): for `no_records = true`, nothing found (Countries: no records and no votes); for
   `include = [...]`, a source from each (Countries by `country_code`, Councils by `gss`).

With `--with-model` and a key, `Pipeline.make_plan` reads the question (one parse call each); otherwise
`parse_offline`. Printed: a line a question and totals by category. Saved (unless `--no-save`):
`eval/runs/<YYYYMMDDTHHMMSS>[-model].json` holding `{"summary": {...}, "results": [asdict(Result)]}`.

`Result` fields: `id`, `category`, `question`, `fields` (each filter right or wrong), `got`, `records`, `votes`
(Countries only), `evidence_ok` (`true`, `false` or `null`), `problems`. Summary keys: `questions`, `plans_right`,
`fields_right`, `fields`, `evidence_checked`, `evidence_right`, `by_category`.

**No run file exists in either checkout** (`eval/runs/` is ignored: `wherecountriesstand/.gitignore:9`,
`wherecouncilsstand/.gitignore:12`), so no real example record can be shown; the shape above is from
`C:evaluate.py:131–137` and `L:evaluate.py:130–135`. There are no judgments files.

**Questions files.** Countries: `today = "2026-10-25"`, 55 questions (country 10, group 10, topic 10, dates 6,
sparse 6, body 4, combined 3, countries 3, votes 3). Councils: `today = "2026-11-06"`, 31 questions (party 7,
topic 6, council 5, dates 5, nation 4, type 3, outside 1). One record of each:

```toml
# wherecountriesstand/eval/questions.toml
[[q]]
id = "ukraine-grain"
question = "What has Ukraine said about the Black Sea Grain Initiative?"
category = "country"
expect = { countries = ["UKR"], date_from = "default" }
include = ["UKR"]

[[q]]
id = "none-tuvalu-1995"
question = "What did Tuvalu say in the Security Council in 1995?"
category = "sparse"
expect = { countries = ["TUV"], sources = ["sc"], date_from = "1995-01-01", date_to = "1995-12-31" }
no_records = true

# wherecouncilsstand/eval/questions.toml
[[q]]
id = "bins-weekly"
question = "What have councils decided about weekly bin collections?"
category = "topic"
expect = { date_from = "default" }
```

**Documents.** MPs: `docs/EVALUATION.md` (method, results, costs, the 16-bit vectors measurements). Councils:
`docs/EVALUATION.md` (method, how to run, one result: built-in rules on the made-up record, 29 of 31 read right,
277 of 279 filters, evidence 3 of 6). Countries: no `docs/EVALUATION.md`; decision 10 in `docs/DECISIONS.md:17`
and a line in the README.

### Differences

| # | | MPs | Countries | Councils | Mark |
|---|---|---|---|---|---|
| 1 | Stages | plans, sources (graded), retrieval, briefings (checked and judged) | plans and evidence presence | the same as Countries | (b) by age and size; the gap matters (below) |
| 2 | Runs the verifier and the other checks | yes (`briefings`) | no | no | |
| 3 | Dates compared | within 45 days | by year | by year | (c) |
| 4 | "Default" date range | none (no default range) | `today.year - default_years` (`C:evaluate.py:70`) | `max(today.year - default_years, start.year)` (`L:evaluate.py:71`) | (a) Councils, small |
| 5 | Questions path and output folder as arguments | options on every command | fixed (`REPO_ROOT / "eval"`) | `run(..., path=…)`, `save(..., folder=…)` | (a) Councils, small |
| 6 | `encoding="utf-8"` on read and write | yes | no | yes | (a) |
| 7 | Tests | `Mt:test_evaluate.py` (8) | none | `Lt:test_evaluate.py` (3) | |

**Tests.** MPs `Mt:test_evaluate.py:18 test_questions_file_is_valid` (date, at least 50 questions, only known
fields; its list of fields omits `seat_types`), `:36 test_scoring_counts_extra_filters_as_mistakes`,
`:44 test_scoring_dates_and_alternatives`, `:52 test_variants`, `:68 test_rerank_promotes_the_closer_match`,
`:75 test_prices_per_model`, `:83 test_region_groups_are_expanded_not_dropped`,
`:93 test_retrieval_runs_are_compared_without_grading`. Councils `Lt:test_evaluate.py:14
test_the_test_set_is_well_formed` (date, 20–40 questions, known fields, every GSS code exists, categories, at least
one `no_records` and one `include`), `:26 test_compare_reads_defaults_years_and_alternatives`,
`:37 test_evaluate_scores_questions_and_evidence` (a two-question file against the fixture record).

---

## 8. Library versions

Pinned in each `uv.lock`: MPs anthropic 1.12.1, duckdb 1.5.6, fastapi 0.143.0, httpx2 2.13.1; Countries and
Councils anthropic 2.3.0, duckdb 2.0.0, fastapi 0.162.0, httpx2 2.16.0. The same everywhere: lancedb 0.40.0,
pyarrow 26.0.0, httpx 0.28.1; fastembed 0.9.0 (MPs, Countries) and 0.9.1 (Councils).

### Anthropic SDK: every call, and whether its shape differs

**The sites' code is the same shape at every call.** Each call below was checked against both installed SDKs by
reading the method signatures (no request was sent).

| Call | Where | Shape in the sites' code | In 1.12.1 and 2.3.0 |
|---|---|---|---|
| `anthropic.Timeout(300.0, connect=10.0)` | `M:rag/answer.py:47`, `C:…:55`, `L:…:54` | the same | In both, `anthropic.Timeout` is `httpx2.Timeout`, and both refuse an `httpx.Timeout` ("this SDK uses `httpx2`") |
| `anthropic.Anthropic(api_key=…, base_url=…, timeout=…, max_retries=2)` | `M:49`, `C:56`, `L:56` | the same | accepted by both; `client.timeout` and `client.max_retries` read back the same |
| `client.beta.messages.stream(**kwargs, betas=[…], fallbacks="default")` | `M:131`, `C:138`, `L:137` | the same | `betas`, `fallbacks`, `output_config` are parameters in both |
| `client.messages.stream(model, max_tokens, system, messages, output_config)` | `M:133`, `C:140`, `L:139` | the same | parameters in both |
| iterating the stream: `event.type`, `event.delta.type`, `.text`, `.citation.search_result_index`, `.citation.cited_text` | `M:135–144` | the same | `TextDelta`, `CitationsDelta`, `CitationsSearchResultLocation` (and the beta type) have the same fields in both: `cited_text`, `end_block_index`, `search_result_index`, `source`, `start_block_index`, `title`, `type` |
| `stream.get_final_message()`; `msg.content`, `.stop_reason`, `.model`, `.usage` | `M:145–153` | the same | present in both |
| `anthropic.BadRequestError` | `M:122`, `C:129`, `L:128` | the same | in both |
| `client.messages.parse(model, max_tokens, system, messages, output_config, output_format=<pydantic model>)`; `resp.stop_reason`, `.parsed_output`, `.usage` | `M:rag/query_parse.py:518`, `M:rag/interests.py:269`, `M:evaluate.py:342, :478`, `C:rag/query_parse.py:320`, `L:rag/query_parse.py:252` | the same | `output_format` and `output_config` are parameters of `messages.parse` in both |
| `client.models.list(limit=1)`; `anthropic.AuthenticationError` | `M:cli.py:691–692` only | n/a | 2.3.0 removed `betas` from `models.list`; `limit` remains, so the call is unaffected |
| `usage.input_tokens`, `.output_tokens`, `.cache_read_input_tokens`, `.cache_creation_input_tokens` (through `getattr`) | `usage_dict` | the same | all four on `Usage` and `BetaUsage` in both. `BetaUsage` also has `fallback_credit`, `iterations`, `speed`, which `usage_dict` ignores |

**What does differ is what the SDK sends by default** (probe on both installed SDKs):

| | anthropic 1.12.1 (MPs) | anthropic 2.3.0 (Countries, Councils) |
|---|---|---|
| `anthropic-version` header | `2023-06-01` | `2026-10-21` |
| How an API key is sent | `X-Api-Key: <key>` | `Authorization: Bearer <key>` |
| `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` both set, no explicit key | both headers sent | the API key is used, with a printed warning "both are set. Using ANTHROPIC_API_KEY." |

Consequences for moving MPs to 2.x:

- On API version `2026-10-21` a request with `temperature`, `top_p` or `top_k`, a `document` block in an
  assistant message, or a text block carrying `citations` in a user message is refused. The sites send none of
  these: no sampling parameters; history is passed as plain text inside the instruction; the `search_result`
  blocks carry only the setting `"citations": {"enabled": True}`, which is still accepted. (From the Anthropic
  migration notes bundled with this session's tooling; not tested against the live API.)
- Anything between the sites and the API that reads `X-Api-Key` (a gateway set through
  `<PREFIX>_ANTHROPIC_BASE_URL`) would stop seeing the key. The default is the API itself.
- `Pipeline.has_model()` counts `ANTHROPIC_AUTH_TOKEN` as a credential in all three (`M:rag/pipeline.py:175–182`,
  `C:76–83`, `L:77–84`); which credential is used when both exist differs as in the table.
- The comment at `C:rag/answer.py:39–42` ("from version 2 the SDK has its own copy of httpx") is true of 1.12.1 as
  well, so `anthropic.Timeout` is already right for MPs.

No code change in the modules of this study was found to be needed for the upgrade. That is from signatures and the
migration notes; MPs' test suite was not run under 2.3.0.

### DuckDB (1.5.6 in MPs, 2.0.0 in the others)

Among the modules of this study only `M:index/build.py` calls DuckDB directly; the engines go through
`store/shared.py` (the other slice). Each statement shape below was run on both versions with the same result:

| Call | Where |
|---|---|
| `duckdb.connect()` | `M:index/build.py:121` |
| `con.register(name, <pyarrow table>)`, `con.unregister(name)` | `:141, :157, :164, :277` |
| `con.sql(ENRICH_SQL)`, `.columns`, `.fetchall()` | `:142–144, :282–285` |
| `con.execute(sql).fetchall()` with `arg_max(x, strftime(date, '%Y-%m-%d') \|\| x)`, `list(DISTINCT …)`, `read_parquet([...], union_by_name = true)`, `SEMI JOIN`, `GROUP BY ALL`, `HAVING count(DISTINCT …) > 1` | `:158–163, :204–213` |
| `con.execute("SET enable_object_cache = true")` | `M:engine.py:149` |

`ENRICH_SQL` itself (`M:reference/profiles.py`) was not read or run. Countries' and Councils' `index/build.py` do
not import DuckDB.

### LanceDB (0.40.0 in all three)

One version, so no difference to manage. Calls used in `index/lance.py` and `index/build.py`: `lancedb.connect`;
`db.list_tables()` (returns a `ListTablesResponse` with `.tables`; the code's `getattr(res, "tables", res)` copes
with either form), `db.create_table(name, schema=…)`, `db.open_table(name)`; on a table: `count_rows()`,
`delete(where)`, `add(pa.Table)`, `schema`, `version`, `list_indices()` (`.columns`, `.name`),
`index_stats(name).num_unindexed_rows`, `optimize(cleanup_older_than=timedelta)`,
`create_index(column, config=…, replace=True)` with `FTS(with_position=False, stem=True, remove_stop_words=True)`,
`BTree()`, `Bitmap()`, `LabelList()`, `IvfPq(distance_type="cosine", num_sub_vectors=…[, target_partition_size=…])`,
`merge_insert("passage_id").when_matched_update_all().execute(table)`; on a search:
`search(q, query_type="fts")`, `search(vec, vector_column_name="vector")`, `search()`, `.distance_type("cosine")`,
`.bypass_vector_index()`, `.nprobes(n)`, `.refine_factor(n)`, `.where(sql, prefilter=True)`, `.select([...])`,
`.limit(n | None)`, `.to_list()`, `.to_arrow()`. Results carry `_score` (BM25) and `_distance` (vector). All of
these exist in the installed 0.40.0 (checked for the table methods and the index classes' parameters).

---

## 9. Tests: where each site stands

| Module | MPs | Countries | Councils |
|---|---|---|---|
| `rag/verify.py` | 16 tests in `Mt:test_rag.py` (section 1) | 2 in `Ct:test_rag.py` | 3 in `Lt:test_verify.py` |
| `rag/neutral.py` | 2 in `Mt:test_british.py` | 1 in `Ct:test_rag.py`, 1 end to end | end to end only |
| `rag/british.py` | 6 in `Mt:test_british.py` | none | none |
| `rag/typography.py` | n/a | 4 in `Ct:test_typography.py`, 1 end to end | n/a |
| `rag/answer.py` | timeout, key file, end-to-end request shape | timeout and base URL | timeout |
| `rag/query_parse.py` model call | none (the fake raises) | none | none |
| `embed/base.py` | none by name | none by name | none by name |
| `index/lance.py`, `index/build.py` | `test_float16.py` (14), `test_retune.py` (6), `test_lance_logs.py` (2), `test_search.py` (8) | `test_index.py` (6), `test_engine.py` (8) | 5 in `test_pipeline.py` |
| `rank/*` | `test_scoring.py` (13) | 3 in `test_engine.py` | 1 in `test_pipeline.py` |
| Pipeline and events | 5 in `test_rag.py`, `test_sse.py` (3) | `test_pipeline.py` (2), 1 in `test_rag.py` | 1 in `test_pipeline.py` |
| Evaluation | `test_evaluate.py` (8) | none | `test_evaluate.py` (3) |

A shared package's suite for this slice should be MPs' verifier, spelling, loaded-word and scoring tests, plus
Councils' three verifier tests and Countries' typography and index tests, plus the cases nobody has (listed at the
end of sections 1, 3, 4 and 5).

---

## 10. Ports worth making now

In order of importance for the checks. "New" means no copy has it.

| # | What | Source | Destination | Effect on the checks |
|---|---|---|---|---|
| 1 | **New: `recheck_flags` must not clear a claim only because it is short.** | the hole is `M:rag/verify.py:112–118` with `:194` (`_is_connective` without `claims`) | the same lines in `C:rag/verify.py:112–114`, `L:rag/verify.py:112–114` | Stricter: stops saved and cached briefings losing real flags. Add the probe of section 1 as a test |
| 2 | A refusal is an error, not an empty briefing | `M:rag/pipeline.py:634–636`; test `Mt:test_rag.py:178–180` | `C:rag/pipeline.py:151–152`, `L:rag/pipeline.py:142–143` | Stricter |
| 3 | `recheck_flags` looks past lead-in pieces | `M:rag/verify.py:112–118`; test `Mt:test_rag.py:438–448` | `C:rag/verify.py:112–114`, `L:rag/verify.py:112–114` | Removes stale flags from saved briefings; nothing `verify` would flag. Make port 1 first or together, since both touch `cleared` |
| 4 | Honorifics `Cllr`, `Rev`, `Revd`, `Hon` | `L:rag/verify.py:127–128`; tests `Lt:test_verify.py:14–36` | `M:rag/verify.py:131`, `C:rag/verify.py:127` | Removes false flags; negligible weakening. Decide separately whether MPs needs lower-case "hon." |
| 5 | **Do not port:** the wider `_EVIDENCE_NOTE` | `M:rag/verify.py:145–146`, `C:rag/verify.py:141–142` | not to `L:rag/verify.py:142` | It would weaken Councils. For the shared verifier, narrow `\b(are\|were\|is\|was) (not )?(supplied\|retrieved)\b` first (for example require "records", "data", "votes", "division lists" as its subject) |
| 6 | The model whose cost is recorded for reading a question | `M:rag/query_parse.py:498–499` used at `M:api/app.py:550` | `C:api/app.py:562` (use `parse_model(settings)` from `C:rag/query_parse.py:310`); `L:rag/query_parse.py:253` (make the function) and `L:api/app.py:288` | none; cost accounting |
| 7 | Check the embedding model before every embedding run | `M:cli.py:227–234` | `M:sync.py:517`; `C:cli.py:597`, `C:update.py:520`; `L:cli.py:427`, `L:index/build.py:233` (`update_index`) | none on briefings; protects the index. Better done once in the shared index base, with the name and dimension stored beside the index |
| 8 | `vectors_for_keys` straight from Arrow | `C:index/lance.py:306–314` | `L:index/lance.py:319–325` | none; memory and time |
| 9 | `unmerged()` counts the vector index too | `C:index/lance.py:235–247` | `M:index/lance.py:252–261`, `L:index/lance.py:250–259` | none |
| 10 | Paragraph split tolerant of blank lines with spaces | `C:index/build.py:49` | `M:index/build.py:46` | none; changes passages only for such text (a re-index) |
| 11 | Timeout and retries as named constants, one name | `C:rag/answer.py:39–45` | `M:rag/answer.py:44–47`; `L:rag/answer.py:45` (`RETRIES` → `MAX_RETRIES`) | none |
| 12 | `unsupported_segments: 0` in the no-records answer | `M:rag/pipeline.py:608` | `C:rag/pipeline.py:134–135`, `L:rag/pipeline.py:125–126` | none; a consistent answer dict |
| 13 | `encoding="utf-8"` and path arguments in `evaluate` | `L:evaluate.py:53–55, :80–81, :130–135` | `C:evaluate.py:51–53, :79–82, :131–137` | none |

Worth doing in the package rather than as ports: one retraining rule for the vector index (section 4, row 5); the
`use_fallbacks` memory that is lost with each `Answerer` (section 3); 16-bit vectors read from the table's own type
(section 4, row 1).

---

## 11. What each site's evaluation needs to run

| Run | Site data | Search index | Reference data | API key | Cost | On a machine without the site's data |
|---|---|---|---|---|---|---|
| MPs `hansard eval plans --model offline` | no | no (see note) | regions from settings; party-group aliases | none used, but `_client()` is still built (`M:cli.py:942`) | free | Probably runs if the reference data can be built; not tried |
| MPs `hansard eval plans` | no | no (see note) | parties and memberships (`Pipeline.parties()`, `M:rag/pipeline.py:184–189`), party groups | yes: one small call a question (66) | about $0.01 (Haiku) to $0.3 (Opus) for the set, from the saved runs | Needs the reference tables and a key |
| MPs `hansard eval retrieval` | the Parquet records behind the sources | yes, the real one | speaker profiles | no | free | Runs but finds nothing useful; the saved plans in `eval/runs` are enough to start it |
| MPs `hansard eval sources` | yes | yes | yes | yes, for sources not already in `judgments.jsonl` (a client is built regardless) | first round $0.09 for 2,346 grades | Not meaningful |
| MPs `hansard eval briefings` | yes | yes | yes, and the registers if `interests_check` is on | yes | "about $0.06–0.15" a briefing a model, plus the judge | Not meaningful: this is the one that measures the checks |
| Countries `wcs evaluate` | for the evidence score only | for the evidence score only | the country and group tables in the repository (`data_static`) | no | free | **Yes for the reading score** (55 questions). Evidence: the `no_records` questions pass trivially and every `include` question fails |
| Countries `wcs evaluate --with-model` | as above | as above | as above | yes: 55 small calls | "a fraction of a penny each" | Yes for the reading score, with a key |
| Councils `councils evaluate` | for the evidence score only | for the evidence score only | `councils.csv` and the rest in the repository | no | free | **Yes for the reading score** (31 questions). `scripts/fixture_site.py` makes a made-up record of three councils; on it the documented result is 29 of 31 read right and 3 of 6 evidence checks |
| Councils `councils evaluate --with-model` | as above | as above | as above | yes: 31 small calls; "never run in CI" | a fraction of a penny each | Yes, with a key |

Notes:

- MPs' commands take `--questions` and `--out` and default to the relative folder `eval/` (`EVAL_DIR`,
  `M:cli.py:33`): run from the repository root, or `/app` in the container. Countries and Councils write under the
  repository's `eval/runs/`.
- MPs `eval plans` builds `Pipeline(settings)`, which builds an `Engine`. `Engine.__init__` was not read, so
  whether it needs an index folder with data, or only creates an empty one, is not confirmed.
- That Countries' pipeline runs on an empty data folder is shown by `Ct:test_rag.py:144–150`.
- **No site can replay the checks without the model.** There are no recorded responses, and saved briefings do not
  keep the raw blocks. To test a shared verifier on real output without MPs' data and a key, a set of recorded
  `blocks` and sources would have to be made first.

---

## 12. Open questions

1. **`recheck_flags` and short claims** (section 1): fix by clearing only for a named reason, or by saving on each
   segment why it was flagged? The second changes the saved answer format.
2. **The "note about the evidence" pattern:** which form is the shared default? Councils' is strict but flags real
   notes about vote data; MPs' and Countries' clears ordinary sentences containing "was supplied". `gaps?\b` and
   `caveats?\b` are loose in all three.
3. **Honorifics:** one list for all, or a common list plus a site's additions? Should it be case-insensitive for
   Hansard's "hon."?
4. **`max_tokens`:** should a briefing stopped at the limit be shown, marked, or refused? With thinking always on
   for the current models, 16000 tokens covers thinking and text together.
5. **Fallbacks:** when the server-side fallback answers, `final.model` is whatever the message reports and
   `usage_dict` ignores `fallback_credit` and `iterations`. Is the cost recorded correctly then? Not examined
   (`api/usage.py` is the other slice).
6. **Remembering that the fallback beta is unavailable:** on the client, in the module, or in settings?
7. **Which SDK version does `wts-core` target?** The code is the same shape on 1.12.1 and 2.3.0, so the package
   could serve both for a while; the differences are the API version and the auth header (section 8). Has MPs any
   gateway that reads `X-Api-Key`?
8. **The embedder's identity:** store `{name, dim, weights hash, number type}` beside the index and have every
   writer check it? What should happen on a mismatch: stop, or mark everything for re-embedding as `wcs index
   --re-embed` does?
9. **Vector index retraining:** Countries keeps the trained count in `state.json`, Councils in
   `vector_index.json`, MPs in neither (it has `index/vector-index.json` from `retune.py`, not read). One file and
   one rule?
10. **16-bit vectors** for Countries and Councils: adopt with the base, or leave each site on 32-bit until it
    chooses?
11. **Typography:** does curling move into the shared slice? If so `recheck_flags` and `_SENTENCE_END` must cope
    with curled text everywhere.
12. **Single quotation marks:** `check_quotes` treats `‘…’` as a quotation but British spelling and the
    loaded-words check do not treat it as quoted. Intended?
13. **Evaluating the checks:** should `wts-core` carry a small set of recorded blocks and sources, so a change to
    the verifier can be measured without a site's data or a key? Should saved briefings keep the raw blocks from
    now on?
14. **Balanced selection:** is a 45-line shared core (section 5) wanted, or is it "what stays separate" as
    ENGINE.md's third section suggests? ENGINE.md lists it in the second slice.
15. **ENGINE.md's table is out of date** for the verifier (upstream is now MPs, with Councils ahead on
    honorifics) and its remark that Councils' verifier matches MPs'. Update it with the first port?
