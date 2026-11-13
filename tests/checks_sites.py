"""For the tests of wts_core.checks: each site's own inputs, its own copy of the checks loaded from its checkout,
and briefings generated from the kinds of fragments the sites' tests use.

The inputs are written here as each site will write them when it adopts the package. The parity tests prove them
against the site's code where its checkout is present (beside this repository, or under ``WTS_SITES_DIR``), and are
skipped with a reason where it is not, so the suite passes anywhere.
"""

from __future__ import annotations

import ast
import importlib
import os
import random
import re
import sys
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from wts_core.checks import (
    COMMON_HONORIFICS,
    COMMON_LOADED_WORDS,
    EVIDENCE_NOTES_STRICT,
    EVIDENCE_NOTES_WIDE,
    LoadedWords,
    Segment,
    Verifier,
    britishise_segments,
    curl_answer,
)


@dataclass
class Source:
    """The sites' ``Source``, field for field (rag/sources.py in each): what the checks are given."""

    n: int
    kind: str
    title: str
    url: str
    blocks: list[str]
    meta: dict[str, Any] = field(default_factory=dict)


def src(n: int, *blocks: str, title: str | None = None, heading: str | None = None) -> Source:
    return Source(n, "record", title or f"Source {n}", f"https://example/{n}", list(blocks),
                  {"heading": heading} if heading else {})


@dataclass(frozen=True)
class SiteChecks:
    """What one site passes to the checks."""

    name: str
    repo: str  # its checkout's folder
    package: str  # its Python package
    no_records: str
    honorifics: tuple[str, ...]
    evidence_notes: re.Pattern[str]
    loaded: re.Pattern[str]
    curled: bool  # shows its briefings with curly quotes

    @property
    def verifier(self) -> Verifier:
        return Verifier(no_records=self.no_records, honorifics=self.honorifics, evidence_notes=self.evidence_notes)

    @property
    def loaded_words(self) -> LoadedWords:
        return LoadedWords(self.loaded)

    def check(self, blocks: list[dict[str, Any]], sources: list[Source]) -> dict[str, Any]:
        """A briefing's blocks through every check, in the order all three pipelines run them; the answer as sent."""
        v = self.verifier
        report = v.verify(blocks, sources)
        v.drop_preambles(report.segments)
        britishise_segments(report.segments)
        self.loaded_words.flag(report.segments)
        v.check_quotes(report, sources)
        answer = report.to_dict()
        return dict(curl_answer(answer) if self.curled else answer)

    def shown_again(self, answer: dict[str, Any] | None) -> dict[str, Any] | None:
        """A saved briefing as the site shows it: its flags and marks judged again."""
        return self.loaded_words.still_loaded(self.verifier.recheck(answer, curled=self.curled))


MPS = SiteChecks(
    "mps", "wherempsstand", "hansard", no_records="No records found.", honorifics=COMMON_HONORIFICS,
    evidence_notes=EVIDENCE_NOTES_WIDE, loaded=re.compile(rf"\b({COMMON_LOADED_WORDS})\b", re.IGNORECASE),
    curled=False)
COUNTRIES = SiteChecks(
    "countries", "wherecountriesstand", "wcs", no_records="No records found.", honorifics=COMMON_HONORIFICS,
    evidence_notes=EVIDENCE_NOTES_WIDE,
    loaded=re.compile(
        rf"\b({COMMON_LOADED_WORDS}|"
        r"regime|regimes|rogue state|rogue states|puppet government|puppet governments|puppet state|puppet states)\b"
        # the West as a bloc, only with its capital letter
        r"|\b(?-i:the West)\b", re.IGNORECASE),
    curled=True)
COUNCILS = SiteChecks(
    "councils", "wherecouncilsstand", "councils", no_records="No records found.",
    honorifics=(*COMMON_HONORIFICS, "Cllr", "Rev", "Revd", "Hon"), evidence_notes=EVIDENCE_NOTES_STRICT,
    loaded=re.compile(
        rf"\b({COMMON_LOADED_WORDS}|shambles|shambolic|chaos|chaotic|fiasco|"
        r"spiteful|vindictive|racist|racism|bigoted|extremist|extremists|far-right|far-left|hard-left|hard-right|"
        r"loony|cronyism|cronies|wasteful|reckless|botched)\b", re.IGNORECASE),
    curled=False)
SITES = (MPS, COUNTRIES, COUNCILS)
WIDE = (MPS, COUNTRIES)  # the sites whose "note about the evidence" rule is the wide one

# ---- the sites' own copies -------------------------------------------------------------------------------------


def _checkouts() -> Path | None:
    """The folder that holds the sites' checkouts: ``WTS_SITES_DIR``, or the nearest folder above this repository
    that has them."""
    named = os.environ.get("WTS_SITES_DIR")
    places = [Path(named)] if named else list(Path(__file__).resolve().parents[1].parents)
    return next((p for p in places if (p / MPS.repo / "src" / MPS.package).is_dir()), None)


@cache
def _load(site: SiteChecks) -> SimpleNamespace | None:
    home = _checkouts()
    root = home / site.repo / "src" if home else None
    if root is None or not (root / site.package / "rag" / "verify.py").is_file():
        return None
    pkg = site.package
    # what the site's checks and ranking import from the rest of the site, and never call in what is tested here:
    # its Source type (an annotation only) and two functions that name parties. The real modules read the site's
    # record and its settings.
    stubs = {f"{pkg}.rag.sources": {"Source": Source}, "hansard.sources.elections": {"runner_up_name": str},
             "councils.reference.people": {"party_name": str}}
    wanted = {"verify": "rag.verify", "neutral": "rag.neutral", "british": "rag.british", "prompts": "rag.prompts",
              "composite": "rank.composite", "evidence": "rank.evidence"}
    if (root / pkg / "rag" / "typography.py").is_file():
        wanted["typography"] = "rag.typography"
    before, bytecode = set(sys.modules), sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # nothing is written into the site's checkout
    sys.path.insert(0, str(root))
    try:
        for name, names in stubs.items():
            if name.startswith(pkg + "."):
                stub = ModuleType(name)
                stub.__dict__.update(names)
                sys.modules[name] = stub
        found = {short: importlib.import_module(f"{pkg}.{dotted}") for short, dotted in wanted.items()}
    finally:
        sys.path.remove(str(root))
        sys.dont_write_bytecode = bytecode
        for name in set(sys.modules) - before:  # the site's package is not left importable by anything else
            del sys.modules[name]
    assert all(Path(m.__file__ or "").is_relative_to(root) for m in found.values())
    theirs = SimpleNamespace(**found, root=root / pkg, shown_again=None)
    recheck = theirs.verify.recheck_flags
    if site.curled:
        # Where Countries Stand rechecks through a wrapper in its api/app.py, which cannot be imported without the
        # whole site: the function and its table are taken from the file as they are written
        tree = ast.parse((root / pkg / "api" / "app.py").read_text())
        parts = [n for n in tree.body
                 if (isinstance(n, ast.FunctionDef) and n.name == "_recheck_straight")
                 or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_STRAIGHT" for t in n.targets))]
        assert len(parts) == 2, "api/app.py no longer has _recheck_straight and _STRAIGHT"
        scope: dict[str, Any] = {"recheck_flags": recheck, "Any": Any}
        exec(compile(ast.Module(parts, []), str(root / pkg / "api" / "app.py"), "exec"), scope)
        recheck = scope["_recheck_straight"]

    def site_check(blocks: list[dict[str, Any]], sources: list[Source]) -> dict[str, Any]:
        report = theirs.verify.verify(blocks, sources)
        theirs.verify.drop_preambles(report.segments)
        theirs.british.britishise_segments(report.segments)
        n = theirs.neutral.flag_loaded(report.segments)
        theirs.verify.check_quotes(report, sources)
        answer = report.to_dict()
        assert answer["loaded_words"] == n  # two of the pipelines set it from the count; it is the same number
        return theirs.typography.curl_answer(answer) if site.curled else answer

    def site_shown_again(answer: dict[str, Any] | None) -> dict[str, Any] | None:
        if site.curled and not isinstance(answer, dict):  # its app only rechecks an answer that is a dictionary
            return answer
        return theirs.neutral.still_loaded(recheck(answer))

    theirs.check, theirs.recheck, theirs.shown_again = site_check, recheck, site_shown_again
    return theirs


def theirs(site: SiteChecks) -> SimpleNamespace:
    """The site's own modules, from its checkout; the test is skipped where there is none."""
    found = _load(site)
    if found is None:
        pytest.skip(f"no checkout of {site.repo} beside this repository or under WTS_SITES_DIR: parity with the "
                    f"site's own copy cannot be shown here")
    return found


# ---- generated briefings ---------------------------------------------------------------------------------------

RECORDS = (
    "The line to Crewe is delayed by two years.",
    "Costs rose sharply.",
    "We will deliver the line to Manchester.",
    "The line to Manchester will be delivered in full.",
    "I very much support renewable energy, but we now have our fair share of onshore wind. I warmly welcome the "
    "hon. and learned Gentleman's point.",
    "but more with the positioning of of that company, where its profits are made",
    "The use of force is not justified at this time.",
    "Our action is self-defence.",
    "The council agreed to restore weekly bin collections from April.",
    "(3) The assessment must estimate the cost of—",
    "(a) implementation of this Act, and",
    "(b) the cap.",
    "We will prioritize the program and organize the center; it’s “a modernization program” for the neighbors.",
    "Climate finance is slow, and the regime knows it.",
)
LEAD_INS = (
    "- Louise Haigh (Sheffield Heeley, Lab), 4 October 2023, said ",
    "Jane Smith said on 4 May that ",
    "- Keir Mather (Selby), 10 August 2026, said ",
    "- Giving evidence to the Transport Committee on the northern legs, Mr. Smith said ",
    "Dr. Jones told the committee that ",
    "Mr. Smith, the portfolio holder, said ",
    "- Members differed, as when France's Mr. ",
    "- Witnesses from the industry differed sharply on the timetable, as when its chief executive, Mr. ",
    "Galouzeau De Villepin said ",
    "Stephens said ",
    "Delattre said ",
    "Jones said ",
    "- Members differed on how often bins should be collected, as when the Leader, Cllr. ",
    "- Speaking for the administration at the budget meeting in February, Cllr. Jones said ",
    "Cllr. ",
    "Cllr Jones said on 4 May that ",
    "France's representative said ",
    "the hon. Member said ",
    "Rev. Green and Hon. Alderman Price said ",
    "Revd. Brown told the meeting that ",
    'He said "no." Mr Smith said ',
    "He said “no.” Mr Smith said ",
    "Lamont said ",
    "Ministers said ",
    "Kenya said ",
)
CLAIMS = (
    "Shadow ministers attacked the decision to cancel the northern legs.\n",
    "Labour MPs criticised the government. ",
    "Witnesses doubted the figures. ",
    "The vote was close. ",
    ". The project was also cancelled in 2023 because of a scandal.",
    " The project was then cancelled in 2023 because of a scandal. ",
    "The company had overspent on the northern section by more than a billion pounds. ",
    " The United States then voted against every resolution on the subject since 1992. ",
    " The opposition then voted against every budget since 2019. ",
    "The council has cut every library budget since 2019 and closed six branches. ",
    "Prices rose by 4% in the year to March, the fastest rise since 1992.",
    "- Spending on the scheme rose by 40% under the last administration\n",
    "Was the funding cut by 40% in real terms? ",
    "The scheme was cut by 40% in real terms! ",
    "Gas was supplied to two million homes by the company in that year alone, they found. ",
    "The funding gap between northern and southern councils has widened sharply over the decade. ",
    "Several delegations criticised the draft. ",
    "Opposition councillors criticised the budget. ",
    "\nAbout the evidence: Jane Smith said the policy had failed families across the country.\n",
    "Ministers emphasized the program and its defense, analyzing labor costs of 5 percent toward the center. ",
    ", while the regime in question ignored the West.",
    "The regime admitted the scheme was a fiasco; the West claimed that it was reckless and far-right. ",
    "He questioned the benefits claimed for the trial and the claimed savings. ",
    " (16 September 2025), when it rose by 4%.\n",
    "Troops moved to the west of the country. ",
    "The minister admitted the delay and ",
    " before benefit claims rose; MPs attacked it.",
    "Labor shortages grew. Organizations objected. ",
    "The World Health Organization and the Australian Labor Party were cited. ",
    ' He also said "wind farms are a blight on the landscape".',
    " He called it ‘a blight on the whole landscape’ twice. ",
    " It’s claimed, they said, that the council’s plan was a shambles. ",
)
NOTES = (
    ".\n\nNo division records were supplied, so votes cannot be reported.\n",
    "- The retrieved records contain no revised opening date.\n",
    "- Two results on prison building were not relevant and have been excluded.\n",
    "- The records are dominated by compensation. Little was found on the system itself.",
    "\n**About the evidence:** the records span 2013 to 2026 and include no divisions.\n",
    "\nAbout the evidence: the records show what was said, but nothing said by Hilary Benn before 2026.\n",
    "No recorded-vote data was available for any of the debates on this subject. ",
    "Division lists for the debates in the Lords in this period were not supplied. ",
    "The votes on the second reading were not supplied, so how members voted is unknown. ",
    "These bodies decide many of these subjects for their own nations. ",
    "These bodies decide many matters for their own nations and are not the UK Parliament. ",
    "The Senedd is a separate parliament that decides education for Wales. ",
    "These bodies decide different matters from Westminster. ",
    "The Senedd decides many subjects for Wales, so this was a decision on consent. ",
)
JOINS = (
    ". ", " and ", ", while ", ".\n\n", "\n", " ", "", " (16 September 2025).\n", " (March 2024)", " (2019),\n",
    " on 12 November 2025.\n", " (written answer, 12 October 2026).\n", "## Labour MPs\n\n",
    "**Shadow ministers**\n\n", "**In brief**\n- ", "Across the records retrieved, ", "- In the records supplied, ",
    "According to the evidence, ", ' The term "net zero" is not a quotation.', "No records found. ", '"', "“", "”",
    "### Councils controlled by Labour\n", "1. ", "- ",
)
# what a cited block says, and the words it cites for it (a record above, or part of one, or words in none)
CITED = (
    ("the Crewe line is delayed by two years", RECORDS[0]),
    ('"The line to Manchester will be delivered in full."', RECORDS[3]),
    ("“The use of force is not justified at this time.”", RECORDS[6]),
    ('and "we now have our fair share … onshore wind."', RECORDS[4]),
    (' He "warmly welcome[d] the hon. and learned Gentleman".', RECORDS[4]),
    (' He also said "wind farms are a blight on the landscape".', RECORDS[4]),
    ('"more with the positioning of that company"', RECORDS[5]),
    ("the line to Manchester would be delivered", RECORDS[2]),
    ("France said its action was self-defence", RECORDS[7]),
    ("we will organize the center", RECORDS[12]),
    ('said "this was a scandal', RECORDS[1]),
    ("It sought a cost estimate", "the cost of—(a) implementation of this Act, and(b) the cap."),
    ("Opponents disagreed", "Text not in source"),
    ("it has failed", "the costs of—(a) implementation"),
    ("finance is slow\"", RECORDS[13]),
    ("In the records supplied, weekly collections were restored", RECORDS[8]),
    ("‘Climate finance is slow’, it said, and the regime knew", "Climate finance is slow"),
)


def briefing(rng: random.Random) -> tuple[list[dict[str, Any]], list[Source]]:
    """One generated briefing: the model's blocks and the sources it was given."""
    texts = rng.sample(RECORDS, rng.randint(2, 9))
    sources, at = [], 0
    while at < len(texts):  # one to three passages to a source
        take = rng.randint(1, 3)
        sources.append(src(len(sources) + 1, *texts[at:at + take],
                           title=rng.choice(("Jane Smith (Selby, Lab)", "Full Council", "France")),
                           heading=rng.choice((None, "Renewable energy: onshore wind farms are a blight"))))
        at += take
    blocks: list[dict[str, Any]] = []
    for _ in range(rng.randint(1, 9)):
        if rng.random() < 0.4:
            everything = "\n\n".join(b for x in sources for b in x.blocks)
            there = [c for c in CITED if c[1] in everything]  # mostly what the sources given do say
            said, quoted = rng.choice(there if there and rng.random() < 0.8 else CITED)
            cites = []
            for _ in range(rng.choice((1, 1, 1, 2))):
                holders = [x for x in sources if quoted in "\n\n".join(x.blocks)]
                source = rng.choice(holders if holders and rng.random() < 0.9 else sources)
                words = quoted if rng.random() < 0.9 else rng.choice(source.blocks)
                if rng.random() < 0.15:
                    words = "\n\n".join(source.blocks)[rng.randint(0, 9):][:rng.randint(8, 60)]  # part of a passage
                where: dict[str, Any] = {"search_result_index": source.n - 1}
                if rng.random() < 0.08:
                    where = rng.choice(({"search_result_index": 99}, {"search_result_index": None},
                                        {"document_index": source.n - 1}, {}))
                cites.append({"type": "search_result_location", "cited_text": words, **where})
            blocks.append({"text": said, "citations": cites})
            continue
        kinds = rng.choices((LEAD_INS, CLAIMS, NOTES, JOINS), weights=(3, 4, 2, 3), k=rng.randint(1, 3))
        text = "".join(rng.choice(kind) for kind in kinds)
        blocks.append(rng.choice(({"text": text}, {"text": text, "citations": []}, {"text": text, "citations": None})))
    return blocks, sources


def briefings(count: int, seed: int = 20261113) -> list[tuple[list[dict[str, Any]], list[Source]]]:
    """``count`` generated briefings, the same every time."""
    rng = random.Random(seed)
    return [briefing(rng) for _ in range(count)]


def as_saved(answer: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """An answer as one saved under older rules might be: no stamp, some passages flagged that today's rules would
    not flag, and some marks on words that are not on today's list."""
    segs = []
    for s in answer["segments"]:
        s = {**s, "loaded": [dict(m) for m in s.get("loaded") or []]}
        if s["status"] == "connective" and rng.random() < 0.5:
            s["status"] = "unsupported"
        if s["text"] and rng.random() < 0.3:
            a = rng.randrange(len(s["text"]))
            b = min(len(s["text"]), a + rng.randint(1, 9))
            s["loaded"].append({"start": a, "end": b, "word": s["text"][a:b]})
        if s["loaded"] and rng.random() < 0.2:
            s["loaded"][0]["end"] += 1
        segs.append(s)
    saved = {k: v for k, v in answer.items() if k != "rules"}
    return {**saved, "segments": segs, "unsupported_segments": sum(s["status"] == "unsupported" for s in segs),
            "loaded_words": sum(len(s["loaded"]) for s in segs)}


def segments(seg_dicts: list[dict[str, Any]]) -> list[Segment]:
    return [Segment(s["text"], status=s["status"]) for s in seg_dicts]
