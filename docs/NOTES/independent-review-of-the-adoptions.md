# Independent reviews of the sites' adoptions, and what was done

Each AI site's adoption is reviewed by someone with no knowledge of how it was done, given the old code, the new
code and the brief's hard rules. This note keeps what each found. The first, of Where Countries Stand, was made
after its pull request was merged and before the owner deployed it, so everything below reaches readers fixed.

## Where Countries Stand (rj-mitchell/wherecountriesstand#37), 14 November 2026

**Confirmed.** The question flow: both `ask` routes read branch by branch, and 20 further scenarios played on the
old code and the new (limits reached by real briefings, caps reached by real spending, follow-ups, a pipeline
raising before its first event, a reader leaving before the first event, a withdrawn briefing against the cache):
19 identical in every byte, row and pipeline call, the 20th differing only in listed changes. The checks: the
site's patterns and word lists identical character for character; a second fuzzer, 27,000 cases: no difference
on fresh answers, none on old saved answers shown again, never a case where the new path flags less. The import: a
visitor's count for the day, spending today and this month, saved briefings, published statements and cache hits
equal before and after on an awkward old database; a second start changes nothing; a failure half-way rolls
everything back.

**Found.** F marks a fix in the package (0.2.1), S in the site.

| # | Finding | Applies to | Fix |
|---|---|---|---|
| 1 | **The old tables freeze personal data.** Left "as they were for a release", they keep senders' addresses the package has since deleted from its own, reports' contacts, failed questions past 90 days, and the adoption day's visitor secret beside that day's codes; and so do every night's backups. The privacy page's "two months" was then untrue | every adopted site | F: a site declares how its old tables are kept within its promises, run nightly; S: each site declares it, and drops the old tables on a stated date |
| 2 | **A backup from before a table existed restores, then the import is silently skipped**: no spending, no saved briefings shown | Countries (its `statements` table arrived on 12 November); check each site | F: a skipped import says so; S: `needs` names only tables every accepted backup has |
| 3 | `hide` says "hidden" for spellings that hide nothing (a full address, a trailing slash, a thing that does not exist) | every site with `hide` | F: `Replies(hideable=…)`; S: each site gives it |
| 4 | A hidden record's words are still served by briefings written before it was hidden | Countries, Councils | S: a saved or cached briefing that cites a hidden item is itself shown as hidden, with the note |
| 5 | `/api/corrections` published what a reporter typed in the "page" box, and a reported briefing's id | Countries (Councils filtered it itself) | F: `corrections()` gives only the date, kind and public note for a report |
| 6 | The corrections log stopped at 100 entries | Countries | S: no limit that can bite |
| 7 | `eval run` on the server would spend, then fail to save (`/app` is read-only in the container) | every AI site | S: runs kept on the data volume; F: said in NEW-SITE |
| 8 | **The record of each briefing kept the question of every ask**, including sources-only requests and refusals, which were stored nowhere before | every AI site | F: the question is kept only where a briefing was written, replayed, answered "no records" or failed |
| 9 | A model with no price entry is costed at the base prices, so a dearer one undercounts and the caps bite late | Countries (Councils asks for strict prices) | S: strict prices on every AI site, with an entry for each model its settings may name |
| 10 | `update.sh` installed the new timers before the image was built: after a failed build they would run commands the old image lacks | every site with new timers | S: timers installed after the new image is up |
| 11 | Smaller: a malformed `follows` is refused where unknown fields were ignored, and any caller could mark a briefing "followed up"; a withdrawn briefing is still served from the answer cache for up to a week (old code too) | Countries | S: `follows` and `website` taken out of the API again (nothing sends them); a withdrawn briefing is not replayed from the cache |

## Where Councils Stand (before its pull request), 14 November 2026

**Confirmed.** The question flow: both routes read branch by branch; 300 seeded random scenarios (2,411 asks:
two visitors, random limits and caps, cache hours of 0, 1 and 168, clock jumps across days and a month,
sources-only, follow-ups, the pipeline raising, the model declining, no records, no key, a second briefing in
progress) through the old app and the new: every byte, each visitor's count, the day's and month's spending and
the saved briefings identical, but for the one listed difference. The checks: 27,000 cases, no report differs.
The import: a visitor at the limit is still refused; spending equal to the cent; `undo-wts-core.sql` followed by
the old code gives the old figures back. A hidden vote or council cannot be reached by its API, page, list,
sitemap, search, sources or what the model is given, and unhide restores each byte for byte.

**Found.**

| # | Finding | Fix |
|---|---|---|
| 1 | The same as Where Countries Stand's first: the old tables keep senders' addresses and reports' contacts for good, and so does every backup (seven addresses in a backup made 125 days on) | as there |
| 2 | **A `[usage.models."…"]` table in the server's local settings replaces the repository's whole table** (settings are laid over one level deep), and with strict prices the site then refuses to start; the deploy notes told the owner to write one | F: the local layer merges `[usage.models]` by model; the error names the local file. S: the deploy note reworded |
| 3 | The public corrections log linked a saved briefing's address when a report about it was closed with a public note; saved briefings "aren't listed anywhere" | F: a report's entry carries no page |
| 4 | **The one-off import runs on whichever command first opens the database**, not only when the site starts: a timer's command on the new image, in the gap before the site restarts, imports while the old site is still writing, and what it writes afterwards is never brought across | S: `update.sh` brings the new site up before it touches the timers; the deploy notes say not to deploy in the timers' hours nor to run a command before the restart |
| 5 | The record kept the question of asks that got no briefing | as Where Countries Stand's eighth |
| 6 | Smaller: lapsing happens at the first write or listing after the deploy, not "the first night"; the tidy run after the backup has systemd's 90-second stop timeout, not the unit's 30 minutes; a malformed old row stops the site from starting until mended by hand (it fails closed) | S |

## Habits

- "Left untouched for the way back" is also "kept": anything left behind needs its own retention and its own end
  date.
- A justification written for one case ("the question is already kept with the saved briefing") must be checked
  against every case the code covers (a question that got no briefing).
- A command that takes an address must refuse what it cannot find, or it reports success for nothing.
- Review after the merge is still worth it when the deploy is a separate, later act.
