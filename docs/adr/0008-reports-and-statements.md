# ADR 0008: Reports, corrections and the right of reply: where the shared rules end

Status: accepted by the owner on 13 November 2026.
check first. 13 November 2026.

## Context

On 12 November 2026 all four sites built the same feature separately, from the impartiality policy's section 7:
readers' reports, a corrections log, and a statement a named person or body can have shown beside what a site says
about them. The four builds were compared line by line ([`../study/reports-statements.md`](../study/reports-statements.md)).
They agree on the essentials: the same four statuses, a 150-word limit counted the same way, the same email
pattern, the glossary's heading and disclaimer, and the confirming address deleted three calendar months after a
statement is withdrawn or declined.

They differ in about forty smaller ways, and each build has something the others lack:

| The best copy has | Which | The others |
|---|---|---|
| A log of every action on a statement, readable by one command, and a required note of how the sender was confirmed | Landlords | MPs has no log; Countries and Councils log actions but not how the sender was confirmed |
| A public corrections log fed by withdrawn briefings and by public notes on closed reports; an outcome recorded for every report | MPs | Councils has no public log; Countries lists withdrawn briefings only; neither records a report's outcome |
| A trap field for automated senders and a daily limit per visitor | MPs | none on Countries and Councils |
| A check that the item a statement sits beside exists and has not been withdrawn | Countries | MPs checks only the address's shape; Councils lets a withdrawn briefing through |
| Refusing a statement that is too long | Countries, Councils | Landlords cuts it at 2,000 characters and keeps it, against "never edited" |
| Takedown requests listed first; forms that work without scripts | Landlords | not the others |

Three things are missing from all four:

- **Hiding an item while a concern is decided** (policy 7.3). All four "If you're named" pages promise it. Only
  briefings can be withdrawn, and withdrawal is permanent and public.
- **A status for a statement the site removes** for breaking the rules. MPs marks it "declined", which elsewhere
  means it was never shown; the others mark it "withdrawn", which elsewhere means its author asked.
- **A clock on waiting.** Only Landlords alerts the owner, weekly, which can't keep a five-working-day promise.

## Options for the boundary

1. **Share only the storage** (tables and queries); each site keeps its rules. The rules are where the builds
   disagree and where the policy lives, so this shares the easy part.
2. **Share everything, pages included.** The pages follow each site's record and look; the brief's Musts keep web
   routes and display in the sites.
3. **The package owns the rules and the data; the site owns addresses, pages and wording (recommended).**

## Decision: option 3

**`wts_core.replies` owns:**

- the tables (`wts_reports`, `wts_statements`, `wts_statement_log`, `wts_hidden`, `wts_reply_counts`; the
  corrections log is worked out from closed reports and removed statements, so it has no table of its own);
- **a statement's life:** received → published, or declined (never shown); published → withdrawn (its author
  asked) or **removed** (the site took it down for breaking the rules); updated while waiting or shown. Five
  statuses, so the log always says what happened. A reason is required to decline or remove, and is recorded
  for a withdrawal;
- **what a statement may be:** up to the site's word limit (150 everywhere today; the policy leaves the number to
  the trustees, so it is a setting), counted as words between spaces; refused, never cut, when over the site's
  character limit; line endings tidied and nothing else changed; a name and a role that aren't blank; a link that is
  a full web address with no quotes, brackets or spaces; an address for confirming the sender;
- **confirming the sender:** publishing requires a note of how the sender was confirmed, kept in the log, never
  shown, and never containing the address itself (the commands' help says so, and a test checks the example);
- **the log:** every action with its time and note, and the previous words when a statement is updated;
- **what the public may see:** a fixed list of fields (never the address, the notes or the log), with a test that
  the list is exact;
- **the address used to confirm the sender:** deleted three calendar months after a statement is declined,
  withdrawn or removed, by every write, every owner's command and a daily job, together with anything else tied
  to the sender;
- **reports:** received with a kind, a page, a message and an optional contact; closed with an outcome, a private
  note and an optional public note; the contact deleted on closing; takedown requests listed first;
- **the corrections log:** withdrawn briefings, public notes on closed reports, and removed statements' reasons
  where the site chooses to show them, as data a site's page lists;
- **hiding:** any item address can be hidden with a note and a date, and shown again; a site's pages ask
  `hidden(item)` and show the note instead of the item. This is the "hidden meanwhile, with a note" of policy 7.3,
  for every kind of item, and it is separate from withdrawal;
- **limits:** a trap field and a daily limit per visitor for reports and statements. The count is kept against
  the day's visitor code in a table that is emptied each day, not on the report or statement itself, so nothing new
  is tied to a sender;
- **what is waiting:** counts and the age of the oldest in working days, for the owner's commands, the update
  report and the nightly check;
- **the owner's commands,** one shape on every site: `reports list|close`, `statements
  list|show|publish|decline|update|withdraw|remove|log`, `hide`, `unhide`. Each site's old command names keep
  working for one release and say what replaces them. A command that fails exits 1.

**Each site owns:**

- its routes, forms and pages, and how a statement looks beside an item;
- **where a statement may sit:** a small `Items` object the site passes in. Given what someone pasted, it returns
  the item's address and who it is about (a member, a country, a council, a landlord), or refuses with words for
  the sender, and it says whether the item exists and is still shown;
- every word a reader or sender sees (the refusals, the heading, the disclaimer), passed in as `Messages`; the
  glossary's wording stays the single source for the heading and disclaimer;
- the HTTP status and shape of a refusal (they differ today, and each site's front end expects its own);
- its limits where they differ today (the least words: 5 on MPs, 3 on Landlords, 1 elsewhere; the most characters);
- whether a statement appears in the page text that search engines read. Where MPs Stand keeps it out; Where
  Councils Stand and Where Landlords Stand put it in, after the record. The policy says a statement is "never
  treated as part of the record" and is silent on outside search engines. **A question for the owner; until it is
  answered each site stays as it is.**

## The rule that statements never reach the model, the index or the record

Kept three ways, each a test:

1. **By structure, in the package.** `wts_core.replies` imports nothing from `checks`, `briefing`, `observe`,
   `eval` or `adapters`, and they import nothing from it. A test reads the imports. A model request can only be
   built from documents and a question; there is no path from a statement to either.
2. **By a contract test every site runs,** `wts_core.testing.assert_statements_stay_out(site)`. It publishes a
   statement containing a marker word beside an item, then asks a question about that item through the site's real
   pipeline with a recording model client, a recording embedder and a recording index. It fails if the marker
   appears in any request to the model, any text sent to the embedder, anything added to the index, the saved
   briefing, the answer cache, the briefing log or a log line.
3. **By each site's own test of its pages,** as each has today (Where MPs Stand's is the widest, and is the model
   for the others).

## What changes for readers and named people (each listed in MIGRATION.md, by site)

The brief allows two: Where Councils Stand gains the public corrections log, and every site can hide any item. The
rest follow from "the best behaviour wins": every site refuses rather than cuts; every site checks the item
exists; Countries and Councils gain the trap and the daily limit; a statement the site removes is called removed.
Wording, limits and pages stay each site's own.

## The four questions, decided

The owner asked the maintainer to decide these (13 November 2026). Each can be changed with a new record.

1. **Statements and search engines.** A statement is shown where the site shows it today, including in pages read
   without scripts, so that every reader sees the reply beside the item. But it is never part of what a search
   engine quotes as the site's own words: the package's markup for a statement carries `data-nosnippet`, and a
   statement is never put in a page's description, title or structured data. Where MPs Stand, which keeps
   statements out of its server-sent text altogether, stays as it is. A test in each site checks the three places.
2. **A statement or report nobody decides.** The nightly check fails once anything has waited four working days,
   so this should not happen. If it does: after three calendar months of waiting, a statement lapses (it is
   declined with the reason "No decision was made in time; please send it again", which its sender is told if they
   ask), and a report's contact address is deleted, exactly as if it had been closed. Nothing sent to the charity
   keeps a person's address for longer than three months without a decision.
3. **The privacy notices** say what the code does: the confirming address "is kept while the statement is waiting
   or shown, and deleted three months after it is withdrawn, declined or removed". The owner has accepted the
   notice changes; they go in with each site's adoption.
4. **Backups.** Each notice gains one sentence, with the adoption: "Backups of the site's database are kept for up
   to two months, so a deleted address can remain in a backup until then." (Each site keeps 60 off-site copies; a
   daily backup makes that about two months. Where Landlords Stand's backups are named by the minute, and its
   adoption checks the figure before the sentence is used.)
