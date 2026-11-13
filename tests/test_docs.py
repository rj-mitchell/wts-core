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
