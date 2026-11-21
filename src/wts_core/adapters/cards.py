"""Share cards for saved briefings, drawn with Pillow: the link preview that shows the checking.

A card (1200 by 630 pixels, PNG) carries the site's band in its cloth with its name and "A Where They Stand
project", what the briefing is ("Briefing written by AI, checked against Hansard"), its title, the three counts of
the family's check strip in words, the day it was prepared and the site's address. It is drawn once, with no AI.

The title is the site's to choose: each site's rule is that a reader's question never becomes the headline (a
saved briefing's neutral title, "Briefing from Hansard, 18 November 2026"); a curated topic's own question may be.
The family's account of the strip is ``family/BRIEFINGS.md`` in the charity's repository (the review plan's B5).

Install with the ``cards`` extra. Fonts are the site's own files (Source Serif 4 and Source Sans 3, TrueType or
OpenType); with none given, Pillow's own is used, which is only fit for tests.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wts_core.checks.display import CheckCounts

__all__ = ["CardStyle", "briefing_card", "card_count_lines"]

W, H = 1200, 630
LEFT, RIGHT = 80, 1120
BAND = 140
WHITE = (255, 255, 255)
PANEL = (242, 244, 244)
INK = (28, 36, 39)
MUTED = (79, 90, 94)
WARN = (138, 75, 0)


@dataclass(frozen=True)
class CardStyle:
    """What makes a card a site's own."""

    site_name: str                     # "Where MPs Stand"
    domain: str                        # "wherempsstand.com"
    cloth: tuple[int, int, int]        # the site's cloth, as on its band: Commons green is (29, 69, 53)
    record: str                        # what the briefing is checked against: "Hansard", "the UN record"
    serif: Path | None = None          # Source Serif 4, semibold
    sans: Path | None = None           # Source Sans 3, regular
    sans_bold: Path | None = None      # Source Sans 3, semibold or bold
    icon: Path | None = None           # the site's square icon, drawn on the band


def card_count_lines(counts: CheckCounts) -> list[tuple[str, str, bool]]:
    """The strip's counts as the card says them: (number, words, a point to check)."""
    return [
        (f"{counts.citations_matched} of {counts.citations_total}", "citations matched to the record",
         counts.citations_matched < counts.citations_total),
        (f"{counts.quotes_found} of {counts.quotes_total}", "quotations found word for word",
         counts.quotes_found < counts.quotes_total),
        (str(counts.no_source), "sentence without a source" if counts.no_source == 1 else "sentences without a source",
         counts.no_source > 0),
    ]


def _font(path: Path | None, size: int) -> Any:
    from PIL import ImageFont

    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size)


def _wrap(draw: Any, text: str, font: Any, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= width:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    return lines


def _fit(draw: Any, text: str, path: Path | None, width: int, max_lines: int, sizes: Sequence[int]) -> tuple[Any, list[str]]:
    for size in sizes:
        font = _font(path, size)
        lines = _wrap(draw, text, font, width)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(path, sizes[-1])
    lines = _wrap(draw, text, font, width)[:max_lines]
    lines[-1] = lines[-1].rstrip(".,;:") + "…"
    return font, lines


def _tick(draw: Any, x: int, y: int, size: int, colour: tuple[int, int, int]) -> None:
    """A tick drawn as lines, so no font need have the character."""
    w = max(3, size // 7)
    draw.line([(x, y + size * 0.55), (x + size * 0.38, y + size * 0.9), (x + size, y + size * 0.15)], fill=colour,
              width=w, joint="curve")


def _bang(draw: Any, x: int, y: int, size: int, colour: tuple[int, int, int]) -> None:
    """An exclamation mark in a circle, for a count with a point to check."""
    draw.ellipse((x, y, x + size, y + size), outline=colour, width=max(3, size // 9))
    cx = x + size / 2
    draw.line([(cx, y + size * 0.22), (cx, y + size * 0.6)], fill=colour, width=max(3, size // 8))
    r = size * 0.07
    draw.ellipse((cx - r, y + size * 0.72 - r, cx + r, y + size * 0.72 + r), fill=colour)


def briefing_card(style: CardStyle, *, title: str, counts: CheckCounts, prepared: str) -> bytes:
    """The card, as PNG bytes. ``title`` is the site's chosen headline; ``prepared`` is the day it was written, as
    the site writes dates ("17 November 2026")."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, BAND), fill=style.cloth)
    x = LEFT
    if style.icon and style.icon.is_file():
        icon = Image.open(style.icon).convert("RGBA").resize((72, 72), Image.Resampling.LANCZOS)
        img.paste(icon, (LEFT, 34), icon)
        x = LEFT + 96
    d.text((x, 36), style.site_name, font=_font(style.serif, 38), fill=WHITE)
    d.text((x, 86), "A Where They Stand project", font=_font(style.sans, 23), fill=WHITE)

    d.text((LEFT, 168), f"Briefing written by AI, checked against {style.record}", font=_font(style.sans_bold, 24),
           fill=MUTED)
    font, lines = _fit(d, title, style.serif, RIGHT - LEFT, 2, (50, 44, 38))
    y = 206
    for line in lines:
        d.text((LEFT, y), line, font=font, fill=INK)
        y += int(font.size * 1.2)

    # the three counts, as on the strip: a number above its words, a tick or a mark beside the number
    top, col = 362, (RIGHT - LEFT) // 3
    num_font, words_font = _font(style.serif, 54), _font(style.sans, 24)
    for i, (number, words, problem) in enumerate(card_count_lines(counts)):
        cx = LEFT + i * col
        d.line([(cx, top), (cx + col - 32, top)], fill=style.cloth, width=3)
        (_bang if problem else _tick)(d, cx, top + 26, 34, WARN if problem else style.cloth)
        d.text((cx + 50, top + 12), number, font=num_font, fill=INK)
        for j, line in enumerate(_wrap(d, words, words_font, col - 40)[:2]):
            d.text((cx, top + 84 + j * 30), line, font=words_font, fill=MUTED)

    d.rectangle((0, 548, W, H), fill=PANEL)
    small = _font(style.sans, 23)
    d.text((LEFT, 574), f"Prepared {prepared}", font=small, fill=MUTED)
    bold = _font(style.sans_bold, 23)
    d.text((RIGHT - d.textlength(style.domain, font=bold), 574), style.domain, font=bold, fill=style.cloth)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
