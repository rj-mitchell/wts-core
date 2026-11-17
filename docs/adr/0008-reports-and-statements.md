# ADR 0008: Reports, corrections and the right of reply: where the shared rules end

Status: accepted, 13 November 2026.

This record decides which parts of readers' reports, the corrections log and the right of reply the package owns,
and which stay with each site.

## Context

The charity's impartiality policy, section 7, asks every site for readers' reports, a public corrections log, and
a statement that a named person or body can have shown beside what a site says about them. On 12 November 2026
all four sites built this separately. Compared line by line, the builds agreed on the essentials (four statuses, a
150-word limit counted the same way, the glossary's heading and disclaimer, and the confirming address deleted
three calendar months after a statement ends) and differed in about forty smaller ways. Each had something the
others lacked: a log of every action on a statement, a public corrections log, a trap for automated senders, a
check that the item a statement sits beside still exists, refusing rather than cutting a statement that is too
long. None could hide an item while a concern about it was decided, which every site's "If you're named" page
promises (policy 7.3).

## Options

1. Share only the storage, and each site keeps its rules. The rules are where the builds disagreed and where the
   policy lives, so this shares the easy part.
2. Share everything, pages included. The pages follow each site's record and look.
3. The package owns the rules and the data; the site owns addresses, pages and wording.

## Decision

Option 3. Where the builds differed, the best behaviour was taken for every site.

`wts_core.replies` owns:

- the tables (`wts_reports`, `wts_statements`, `wts_statement_log`, `wts_hidden`, `wts_reply_counts`);
- a statement's life, in five statuses: received, then published or declined (never shown); once published,
  withdrawn (its author asked) or removed (the site took it down for breaking the rules). A reason is required to
  decline or remove, and recorded for a withdrawal;
- what a statement may be: up to the site's word limit (150 on every site), refused and never cut when over the
  character limit, with only line endings tidied; a name and role that are not blank; a link that is a full web
  address; an address for confirming the sender;
- confirming the sender: publishing needs a note of how the sender was confirmed, kept in the log, never shown,
  and never holding the address itself;
- the log of every action with its time and note, and the previous words when a statement is updated;
- what the public may see: a fixed list of fields, never the address, the notes or the log;
- the confirming address and anything else tied to the sender, deleted three calendar months after a statement
  is declined, withdrawn or removed, by every write, every owner's command and the nightly tidy;
- reports: received with a kind, a page, a message and an optional contact; closed with an outcome, a private
  note and an optional public note; the contact deleted on closing; takedown requests listed first;
- the corrections log, as data a site's page lists: withdrawn briefings, the public notes of closed reports (only
  their date, kind and note, never what a reporter typed), and removed statements' reasons where the site shows
  them;
- hiding: any item can be hidden with a note while a concern is decided, and shown again. A site's pages ask
  `hidden(item)` and show the note instead. The site gives a function, `hideable`, that turns whatever the owner
  typed into the one address it files that item under, and may say which items are hidden with another
  (`hidden_with`). Hiding is separate from withdrawal, which is permanent and public;
- a trap field and a daily limit per visitor for reports and statements, on a site that passes the day's visitor
  code. The count is kept in a table emptied each day, so nothing new is tied to a sender;
- what is waiting: counts and the age of the oldest in working days, for the owner's commands and the nightly
  check;
- the owner's commands, one shape on every site: `reports list|show|close`, `statements
  list|show|publish|decline|update|withdraw|remove|log`, `hide`, `unhide`, `hidden`, `waiting` and `would-lapse`.
  A site may keep its older command names, which say what replaces them.

Each site owns:

- its routes, forms and pages, and how a statement looks beside an item;
- where a statement may sit: an `Items` object that turns what someone pasted into an item's address (or
  refuses in words for the sender), and says whether the item exists and is still shown;
- every word a reader or sender sees, passed in as `ReplyMessages`. The glossary's wording is the single source
  for the heading and disclaimer;
- the HTTP status and shape of a refusal, and its limits where the sites differ (the fewest words, the most
  characters).

Questions the owner asked the maintainer to decide (13 November 2026):

1. Statements and search engines. A statement is shown wherever the site shows the item, including in pages read
   without scripts. It is never part of what a search engine quotes as the site's own words: its markup carries
   `data-nosnippet`, and it is never put in a page's description, title or structured data.
2. A statement or report nobody decides. The nightly check fails once anything has waited four working days.
   If something still waits three calendar months, a statement lapses (declined with the reason "No decision was
   made in time; please send it again") and a report loses its contact address, exactly as if it had been
   closed. `would-lapse` shows what the next tidy would lapse, with numbers and dates and nothing of who sent it.
3. The privacy notices say what the code does, about the confirming address and about backups. The sentences are
   in [`NEW-SITE.md`](../NEW-SITE.md#11-privacy-and-accessibility-statements).

## The rule that statements never reach the model, the index or the record

It is kept by tests at three levels:

1. By structure. `wts_core.replies` imports nothing from `checks`, `briefing`, `observe`, `eval` or `adapters`,
   and they import nothing from it. A model request can only be built from documents and a question.
2. By a contract test every site runs, `testing.assert_statements_stay_out`. It publishes a statement containing
   a marker word, asks a question about that item through the site's real pipeline with recording stand-ins for
   the model, embedder and index, and fails if the marker appears in any request, any embedded text, the index,
   the saved briefing, the answer cache, the record of briefings or a log line.
3. By each site's own tests of its pages.

## Consequences

- Where Councils Stand gained a public corrections log, and every site can hide any item.
- A statement that is too long is refused on every site, and every site checks that the item exists.
- Where Countries Stand and Where Councils Stand have neither the trap nor the daily limit: they never kept a
  visitor code for reports and statements, and adding one would be a change of their own, with their privacy
  notices.
