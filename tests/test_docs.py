"""The guides quote the example site, and a quotation that is no longer in the file it names fails here.

``docs/EXTENDING.md``, ``docs/NEW-SITE.md`` and ``README.md`` introduce each quotation with a line of the form
``From `examples/minimal-site/<path>`:`` and then a fenced block. The block must be a run of whole lines of that
file, exactly as they stand there. So an example in the guides is always code that CI runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUIDES = ("README.md", "docs/EXTENDING.md", "docs/NEW-SITE.md")
QUOTATION = re.compile(r"^From `(examples/minimal-site/[^`]+)`[^\n]*:\n\n```\w*\n(.*?)^```$", re.M | re.S)


def quotations() -> list[tuple[str, str, str]]:
    found = []
    for guide in GUIDES:
        path = ROOT / guide
        if path.exists():
            found += [(guide, m.group(1), m.group(2)) for m in QUOTATION.finditer(path.read_text(encoding="utf-8"))]
    return found


def test_the_guides_quote_the_example():
    assert "docs/EXTENDING.md" in {guide for guide, _, _ in quotations()}
    assert len(quotations()) >= 20, "the guides should quote the example site, hook by hook"


@pytest.mark.parametrize("guide, source, quoted", quotations(),
                         ids=[f"{guide}:{source.rsplit('/', 1)[-1]}:{n}" for n, (guide, source, _) in
                              enumerate(quotations())])
def test_every_quotation_is_in_the_file_it_names(guide: str, source: str, quoted: str):
    path = ROOT / source
    assert path.exists(), f"{guide} quotes {source}, which is not there"
    wanted = [line.rstrip() for line in quoted.rstrip("\n").split("\n")]
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").split("\n")]
    starts = [i for i, line in enumerate(lines) if line == wanted[0]]
    assert any(lines[i:i + len(wanted)] == wanted for i in starts), (
        f"{guide} quotes these lines from {source}, and they are no longer there as quoted:\n\n{quoted}")


def slug(heading: str) -> str:
    """A heading's anchor as GitHub makes it: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_every_link_into_a_guide_points_at_a_heading_that_is_there():
    for guide in GUIDES:
        text = (ROOT / guide).read_text(encoding="utf-8")
        for target, anchor in re.findall(r"\]\(((?:docs/)?[A-Z-]+\.md)#([^)]+)\)", text):
            linked = (ROOT / guide).parent / target
            anchors = {slug(h) for h in re.findall(r"^#+ (.+)$", linked.read_text(encoding="utf-8"), re.M)}
            assert anchor in anchors, f"{guide} links to {target}#{anchor}, and there is no such heading"


def test_every_file_a_guide_links_to_is_there():
    for guide in GUIDES:
        text = (ROOT / guide).read_text(encoding="utf-8")
        for target in re.findall(r"\]\((?!https?:)([^)#]+)(?:#[^)]*)?\)", text):
            assert ((ROOT / guide).parent / target).exists(), f"{guide} links to {target}, which is not there"


def test_the_improving_guide_explains_every_statistic_the_report_holds():
    """``docs/IMPROVING.md`` says how to read each number in the weekly report. Its names are taken from the
    code, so that a figure added to the statistics and not explained there fails here."""
    import dataclasses

    from wts_core.observe import ALERTS, PROPORTIONS, REASONS
    from wts_core.observe.figures import MARKS, Figures, Headline, PromptCache, Rate, Spread, Stats
    from wts_core.observe.log import KINDS, OUTCOMES

    guide = (ROOT / "docs" / "IMPROVING.md").read_text(encoding="utf-8")
    names = {f.name for cls in (Stats, Figures, Headline, PromptCache, Spread, Rate) for f in dataclasses.fields(cls)}
    names -= {"period", "earlier", "count", "of", "rate"}  # the two periods and a rate's parts: said in prose
    names |= {*MARKS, *PROPORTIONS, *ALERTS, *OUTCOMES, *KINDS, "too_few", "no_difference", "different"}
    missing = sorted(name for name in names if f"`{name}`" not in guide)
    assert not missing, f"docs/IMPROVING.md does not explain: {', '.join(missing)}"
    assert len(REASONS) == 3  # the three kinds of question proposed, each said in the guide's own words:
    for said in ("found no records", "not useful", "flagged most"):  # why a question is proposed
        assert said in guide
    for never in ("Never weaken a check", "Never collect anything new about readers",
                  "Never spend past the evaluation budget"):
        assert never in guide
