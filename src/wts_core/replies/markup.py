"""The one piece of markup the package offers: a statement, set apart from the site's own words.

A site may use it or its own (Where MPs Stand draws statements in the browser; Where Landlords Stand writes them
into built pages). Whichever it uses, the rules this markup keeps are the family's (ADR 0008, and its first
question):

* the heading and the disclaimer are the glossary's, from the site's ``ReplyMessages``: "Statement from [name],
  [date]", and last, "In their own words. Not checked or endorsed by [site].";
* the whole statement is inside an element carrying ``data-nosnippet``, so a search engine never quotes it as the
  site's own words (search engines honour the attribute on ``div``, ``span`` and ``section``, hence a ``div``);
* the words are shown as text, never as markup: every value is escaped, paragraphs and line breaks kept;
* the link to the record is made a link only if it is still an ordinary web address when shown (checked again, as
  Where MPs Stand's pages do), and carries ``rel="nofollow ugc noopener noreferrer"``.

A statement is never put in a page's title, description or structured data: that is each site's page to keep, and
each site's test to check.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape
from typing import Any

from wts_core.dates import long_date  # the family's date format: exported from here too, as it always was
from wts_core.replies.rules import ReplyMessages, safe_link

__all__ = ["long_date", "statement_html"]

LINK_REL = "nofollow ugc noopener noreferrer"


def statement_html(statement: Mapping[str, Any], messages: ReplyMessages, *, level: int = 2) -> str:
    """One published statement (as ``Replies.published`` returns it) as HTML. ``level`` is its heading's level,
    to suit where on the page it sits."""
    sid = f"statement-{escape(str(statement['id']), quote=True)}"
    h = f"h{min(max(int(level), 1), 6)}"
    heading = messages.heading.format(name=statement["name"], date=long_date(statement["date"]))
    words = "".join("<p>" + "<br>".join(escape(line.strip()) for line in para.strip().split("\n")) + "</p>"
                    for para in re.split(r"\n\s*\n", str(statement["text"])) if para.strip())
    out = [f'<div class="statement" role="note" id="{sid}" aria-labelledby="{sid}-h" data-nosnippet>',
           f'<{h} class="statement-head" id="{sid}-h">{escape(heading)}</{h}>',
           f'<p class="statement-role">{escape(str(statement["role"]))}</p>',
           f'<blockquote class="statement-text">{words}</blockquote>']
    link = safe_link(statement.get("link"))
    if link:
        out.append(f'<p class="statement-link"><a href="{escape(link, quote=True)}" rel="{LINK_REL}">'
                   f"{escape(messages.record_link.format(link=link))}</a></p>")
    out.append(f'<p class="statement-note">{escape(messages.disclaimer.format(site=messages.site))}</p></div>')
    return "".join(out)
