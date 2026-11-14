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

## Habits

- "Left untouched for the way back" is also "kept": anything left behind needs its own retention and its own end
  date.
- A justification written for one case ("the question is already kept with the saved briefing") must be checked
  against every case the code covers (a question that got no briefing).
- A command that takes an address must refuse what it cannot find, or it reports success for nothing.
- Review after the merge is still worth it when the deploy is a separate, later act.
