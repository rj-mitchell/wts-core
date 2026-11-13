# An independent review of the package, and what was done about it

On 13 November 2026, before the package's pull request, a reviewer with no knowledge of how the package was built
was given the code and the brief's hard rules, and asked to find where the rules could break. It wrote its own
tests and ran them. This note keeps what it found, because several findings are about habits worth keeping.

## What it confirmed

- **The checks are not weaker.** Its own generator, 86,500 briefings for each site (honorifics, six kinds of quote
  marks, lists, headings, odd citations, Unicode): the package, set up as each site, gave the same result as the
  site's own code every time. On a briefing judged again later the package never showed fewer flags; in about 7
  in 1,000 the site's own code cleared one, which the package's rules stamp now prevents (stricter; MIGRATION 1.4).
- **The briefing flow is the same.** Thirty more cases for each site, and eight ways of a reader leaving: the same
  bytes, spending, cache and saved rows, and the place in progress released each time.
- No statement can reach the model, the index or the record: `wts_core.replies` imports only `ports` and `state`,
  and no other module names its tables. `published()` returns the public fields only.
- SQL is built with fixed column names only; the limiter and the in-progress count hold under 16 threads; costs
  match each site's own over 60,000 random usages.

## What it found, and the fix

| Finding | Fix |
|---|---|
| **The new record of each briefing could be tied to a visitor.** It holds no code, but its time and token counts match rows of the spending record, which did hold the day's code, for good | `Spending.forget_visitors`: a code is kept on a row for its own day only, then replaced by an empty text; each day's number of visitors is kept in `wts_visitor_days` so the owner's reports are unchanged. Run with the first call of each day |
| **Starting two processes together could crash**, and a migration that failed part-way left half of itself behind (Python's `sqlite3` commits a statement that makes a table on its own) | Migrations and imports take the write lock first and are kept or undone whole |
| **A log line could carry an address or a visitor's code** in the `event`, `stage` or `briefing` field, despite the claim that it could not | `event` and `stage` are from fixed lists (a site lists its own events in code); the id must be exactly the desk's shape. The desk now writes the lines ADR 0012 describes, which nothing did |
| `wts_reply_counts` was emptied only by the next accepted statement, so a code could sit for weeks on a quiet site | Emptied by every tidy and by the nightly check's question |
| A declined statement with no closing time kept its sender's address for ever | Judged by when it was sent |
| A restore lost the newest writes of a database with a write-ahead log unless the spec said so | A log that is there is always kept with the copy |
| The wall tests ignored relative imports, used a list of forbidden libraries rather than of allowed ones, and did not cover `cli` | Rewritten: only the standard library outside the adapters; a short list of files that may import the right of reply; and a check in a fresh interpreter of what loading each module really loads |
| The search adapter logged an error's message, which can hold a reader's words | The error's class only |
| A plan event with an empty `parse_error` lost the key; the sites pass it on | As the sites do |
| The day's visitor secret could be read back as nothing if midnight fell between two steps | Made again; never hashed with nothing |
| Weekly report files (which quote questions that found no records) were readable by anyone on the server | Mode 0600, like a backup |

## Left as it is, and why

- **Three event shapes no pipeline sends today** where the desk and one site differ: a `citation` after `final`
  (Where Countries Stand caches it), a `final` with no `usage` key (the sites store `usage: null`), an `error`
  event with extra keys (Where Countries Stand strips them). Each site's adoption tests its real pipeline.
- **A sister site's backup is accepted by a restore** if it has the tables the spec names. Each site's spec
  should name one table only it has (AS-BUILT, operations).
- **A site still running keeps writing to the replaced file during a restore.** As today: "stop the site first".
- Not reviewed: `eval`, the statistics' arithmetic, the Backblaze, DuckDB and embedding adapters, `settings.py`.

## Habits

- A privacy claim in a docstring is a claim to test with the thing it forbids (an address, a code, a one-word
  question), not with a sentence.
- "No column for it" is not "cannot be joined to it": look at what two tables share (times, counts).
- Anything deleted "each day" needs a path that runs on a day when nobody does anything.
- A parity harness proves the hooks are enough; the adopted site's own tests prove the site matches.
