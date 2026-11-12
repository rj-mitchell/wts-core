# Reports, corrections and the right of reply: the four builds compared

Study for `wts-core`, 12 November 2026. Read-only: nothing in the four repositories was changed. Policy: `/home/user/wheretheystand-charity/policies/impartiality.md` section 7 (lines 84-148). Shared wording: `/home/user/wheretheystand-charity/family/GLOSSARY.md` lines 52-62.

## How to read the references

Repository roots: **M** = `/home/user/wherempsstand`, **C** = `/home/user/wherecountriesstand`, **K** = `/home/user/wherecouncilsstand` (K for councils, so C is free for countries), **L** = `/home/user/wherelandlordsstand`.

| Short name | File |
|---|---|
| `M:statements` | `M/src/hansard/api/statements.py` |
| `M:reports` | `M/src/hansard/api/reports.py` |
| `M:state` | `M/src/hansard/store/state.py` |
| `M:app` | `M/src/hansard/api/app.py` |
| `M:cli` | `M/src/hansard/cli.py` |
| `M:ts` | `M/web/src/statements.ts` |
| `C:statements` | `C/src/wcs/api/statements.py` |
| `C:usage` | `C/src/wcs/api/usage.py` |
| `C:app` | `C/src/wcs/api/app.py` |
| `C:cli` | `C/src/wcs/cli.py` |
| `K:statements` | `K/src/councils/api/statements.py` |
| `K:state` | `K/src/councils/api/state.py` |
| `K:app` | `K/src/councils/api/app.py` |
| `K:cli` | `K/src/councils/cli.py` |
| `L:statements` | `L/src/landlords/statements.py` |
| `L:api` | `L/src/landlords/api.py` |
| `L:cli` | `L/src/landlords/cli.py` |
| `L:pages` | `L/src/landlords/site_pages.py` |
| `L:wording` | `L/config/wording.toml` |

### What was not read

Say so rather than guess: `M/web/src/admin.ts` outside lines 100-235 (the report card and the page's loading code); `M/web/src/components/ReportProblem.tsx`; `M/src/hansard/backup.py` beyond its docstring; `K/web/src/corrections.tsx`, `council.tsx`, `vote.tsx`, `ask.tsx` beyond the lines that mount `<Statements>`; `K/src/councils/registry.py` (`get`, used by `publish-statement --council`); `L/src/landlords/site.py` beyond the lines that place slots (350, 386, 403, 421, 426, 561-564); `L/src/landlords/status.py`; `L/tests/test_api.py` beyond lines 30-41; the footers' partials on each site; the stylesheets, beyond the rules quoted; the charity's `policies/privacy.md`; the existing files in `wts-core/docs` (`adr/`, `NOTES`, `study/drift-2026-11-13.txt`). No test suite was run: every statement about tests is from reading them. How often each site's update runs (twice daily, nightly, weekly) is taken from each site's own documents, not from its timers.

---

## 1. Per site, end to end

### 1.1 Where MPs Stand (`hansard`, decision 31: `M/docs/DECISIONS.md:65`)

**Data model** (`M:state`, SQLite, WAL).

- `reports` (`M:state:93-107`): `id` autoincrement, `at`, `kind`, `briefing_id`, `page` (added by migration, `M:state:218`), `message`, `contact`, `visitor`, `status` default `'open'`, `closed_at`, `resolution`, `public_note`. Index `reports_status(status, at)`.
- `statements` (`M:state:111-130`): `id`, `at`, `name`, `role`, `item_path`, `person` INTEGER, `text`, `link`, `email`, `visitor`, `status` default `'pending'`, `published_at`, `updated_at`, `closed_at`, `reason`, `checked`. Indexes `statements_item(status, item_path)`, `statements_person(status, person)`.
- `briefings.withdrawn_at`, `withdrawn_reason` (`M:state:86-87`).
- Statuses: `STATUSES = ("pending", "published", "declined", "withdrawn")` (`M:statements:30`); reports `open`, `resolved`, `dismissed` (`M:reports:22`).
- Transitions: pending → published (`publish_statement`, only from pending, `M:statements:194-204`); pending **or published** → declined (`M:statements:207-215`: "Decline a pending statement, or take down a published one that breaks the rules"); pending or published → withdrawn (`M:statements:237-243`); update allowed while pending or published (`M:statements:218-234`). Nothing leaves declined or withdrawn.
- **Audit log: none.** There is no log table or column. What survives is `checked` (how the sender was confirmed), `reason` (one column shared by decline and withdraw; withdraw's default is `"Withdrawn by the author."`, `M:statements:242`), and the timestamps. An update overwrites text, name, role and link with no trace but `updated_at`.

**Validation** (`M:statements:90-101`, plus pydantic in `M:app:183-190`).

- Words: `len(text.split())` (`M:statements:45-46`). Fewer than 5: `"Please write the statement: a sentence or more."`. More than `MAX_WORDS = 150`: `f"A statement can be up to {MAX_WORDS} words. This one is {words}."`. Exactly 150 passes.
- Characters: pydantic `text` max 2000, `name` 2-120, `role` 2-200, `item` 1-300, `link` ≤500, `email` 3-200 (`M:app:183-190`). A breach is FastAPI's 422 with a list in `detail`, not words for the reader.
- Text cleaning: `\r\n` and `\r` to `\n`, strip, three or more newlines closed to two (`M:statements:84-87`).
- Name: `len(name.strip()) < 2` → `"Please give the name the statement is from."`. Role: `"Please give their role, for example \"MP for Leeds Central\" or \"Chief of staff to …\"."`.
- Email: `^[^@\s]+@[^@\s]+\.[^@\s]+$` (`M:statements:32`) → `"Please give an email address, so we can confirm who the statement is from."`.
- Link (`M:statements:74-81`): optional; scheme `http`/`https`, a netloc, and none of `"'<>` or space → else `"The link to the record should be a full web address, starting https://."`. Stored as NULL when empty.
- All `StatementError`s become **HTTP 400** with the message in `detail` (`M:app:1854-1855`).
- Spam trap: a filled `website` field returns `{"ok": true}` and keeps nothing (`M:app:1847-1848`, reports `1829-1830`).
- Report kinds: `Literal["correction", "complaint", "takedown", "general"]`; `message` 10-4000; `briefing_id` ≤20; `page` ≤300; `contact` ≤200 (`M:app:166-174`). Labels in `M:reports:20-21`.

**Item address** (`M:statements:35-66`). A path with a leading slash, kept in `item_path`. Accepted: a full address on `SITE_HOSTS = ("wherempsstand.com", "www.wherempsstand.com")`, a host-first address, or a path. Query and fragment are dropped, trailing slashes removed, `/people/<n>/<name>` shortened to `/people/<n>`. It must match:

```
^/(people/\d+|b/[a-km-z2-9]{10}|topics/[\w-]+|debates/\d{4}-\d{2}-\d{2}/[\w-]+/[\w-]+|bills/[\w-]+|groups/[\w-]+/[\w-]+|edms/\d+|committees/\d+|inquiries/\d+|evidence/\d+|devolved/[\w-]+/[\w.-]+)$
```

`person` is set from `/people/<n>` at once, otherwise by the owner at publishing. **There is no check that the item exists** (a statement about `/people/99999999` or an unknown briefing is accepted). The host list is fixed, so a full address on a test host is refused.

**Public routes.**

| Route | Request | Response |
|---|---|---|
| `POST /api/report` (`M:app:1826-1840`) | JSON `kind`, `message`, `briefing_id?`, `page?`, `contact?`, `website?` | `{"ok": true}`. `page` kept only as a path on this site, cut to 200 |
| `POST /api/statements` (`M:app:1844-1856`) | JSON `name`, `role`, `item`, `text`, `link?`, `email`, `website?` | `{"ok": true}` (no id) |
| `GET /api/statements?path=…&path=…&person=N` (`M:app:1858-1860`) | up to 5 paths of ≤300 characters; bad paths are skipped silently | `{"statements": [{id, name, role, item, person, text, link, date}]}`; empty list when nothing is asked |
| `GET /api/corrections` (`M:app:1891-1893`) | none | `{"corrections": [{date, kind, briefing_id, question, note}]}` |
| `GET /feeds/corrections.xml` (`M:app:1779-1787`) | none | RSS of the same |

Public fields are fixed by the SELECT at `M:statements:187-191`; `date` is `published_at[:10]`. Ordered `published_at, id`.

**Display.** Fetched by the browser on its own (`M:ts:91-105`), never with a briefing. Heading `` `Statement from ${s.name}, ${fmtDate(s.date)}` `` (`M:ts:50`); disclaimer `"In their own words. Not checked or endorsed by Where MPs Stand."` (`M:ts:21`); an `<aside class="statement">` labelled by its heading, role, a `<blockquote>` of paragraphs set as text, a link (only if it matches `^https?:\/\/[^\s"'<>]+$`, `rel="nofollow ugc noopener noreferrer"`, text "The record they point to"), an "About …" line when shown away from its item, then the disclaimer (`M:ts:110-155`, `M/web/src/components/Statements.tsx:18-58`). Places: beside the member's first source card in a briefing, with a pointer under the briefing (`Statements.tsx:83-140`); the member's page (`M/web/src/person.tsx:391-401`); the end of other item pages (`M:ts:166-187`).

**Owner's commands.** CLI `hansard statements …` (`M:cli:787-870`):

- `list [--status pending|published|declined|withdrawn|all]` (default `pending`), newest first, limit 200. Output per statement: `#{id}  {status}  received {date}` (+ `  published {date}`, `  closed {date}`), `  From: {name}, {role}  <{email or 'email deleted'}>`, `  About: {item_path}  (member N)` or `  (no member set)`, optional `  Link:`, `  Checked:`, `  Reason:`, then the text.
- `publish SID --checked TEXT [--person N]` → `published #N`. `--checked` is required on the CLI.
- `decline SID --reason TEXT` → `declined #N: tell the author why; their email address is deleted in three months`.
- `update SID [--text-file F] [--name] [--role] [--link ""]` → `updated #N`.
- `withdraw SID [--note TEXT]` → `withdrawn #N; the email address is deleted in three months`.
- Failure: ``No such statement, or it can't be changed in that way now (see `hansard statements list`).``, exit 1.
- The same over HTTP for the admin page: `GET /api/admin/statements`, `POST /api/admin/statements/{sid}/publish|decline|update|withdraw` (`M:app:1862-1889`); `checked` is **optional** there (`M:app:193-195`).
- Reports have **no CLI**: `GET /api/admin/reports`, `POST /api/admin/reports/{id}/close` with `status` (`resolved`/`dismissed`), `resolution` (private, 3-2000), `public_note?` (≤1000) (`M:app:177-180, 1895-1903`).
- Briefings: `POST /api/admin/briefings/{bid}/withdraw` with `reason` 3-500 (`M:app:700-705`).
- Fault: `decline_statement` raises `StatementError` for a reason under 3 characters after stripping (`M:statements:210-211`), which neither the CLI (`M:cli:836-842`) nor the route (`M:app:1875-1877`) catches. Pydantic stops a short reason on the route, but three spaces pass it.

**Deleting the confirming address** (`M:statements:129-147`):

```python
def months_ago(now, months):
    y, m = divmod(now.year * 12 + now.month - 1 - months, 12)
    m += 1
    for day in range(now.day, 27, -1):
        try: return now.replace(year=y, month=m, day=day)
        except ValueError: continue
    return now.replace(year=y, month=m, day=min(now.day, 28))

cutoff = months_ago(now or datetime.now(UTC), EMAIL_KEPT_MONTHS).isoformat(timespec="seconds")
"UPDATE statements SET email = NULL, visitor = NULL WHERE email IS NOT NULL "
"AND status IN ('withdrawn', 'declined') AND closed_at < ?"
```

Run after each new statement (`M:statements:125`), before each owner's listing (`M:statements:152`) and at the start of each update (`M/src/hansard/sync.py:253-255`; twice daily per `M/docs/OPERATIONS.md:183-184`). Report contacts: `contact = NULL, visitor = NULL` on closing (`M:reports:57-58`).

**Corrections log** (`M:reports:63-75`): every withdrawn briefing (date, question, reason) and every closed report with a `public_note`, newest first, limit 200. Statements never feed it.

**Hiding an item while a concern is decided: not built.** A briefing can be withdrawn (410 `"This briefing has been withdrawn."`, `M:app:658-664`), which is permanent and public. There is no hide-with-a-note for a briefing, label or page, though `M/web/named.html:196-197` says "we can hide the item meanwhile, with a note saying so".

**Alerts to the owner:** none found beyond the admin page listing them. **Limits:** 20 requests a minute per visitor code (`M:app:345, 416-422`; `M/config/settings.toml:128`), plus per visitor 5 statements (`M:statements:29, 104-110`; `M:app:1849-1850`) and 10 reports (`M:reports:23`; `M:app:1831-1832`), counted by the stored `visitor` code over the last 24 hours (the code itself changes at midnight UTC, so the count in effect starts again then).

**Never the model, the index or the record.** Statements live only in the state database. Guarantees: a run-time test with a marker word through `/api/ask`, `/api/briefings/{id}`, `/api/search`, `/api/v1/search`, the member page's readable text and `/api/people/{n}` (`M/tests/test_statements.py:204-229`); and a source scan that only `api/statements.py`, `api/app.py`, `cli.py`, `sync.py` and `store/state.py` may name the module or the table, with exactly three call sites in `app.py` (`M/tests/test_statements.py:232-248`). MPs is the only site that also keeps statements **out of the server-rendered readable text** of pages.

### 1.2 Where Countries Stand (`wcs`, decision 16: `C/docs/DECISIONS.md:23`)

**Data model** (`C:usage:33-39`).

- `reports`: `id`, `at`, `kind`, `page`, `message`, `contact`, `closed_at`. No outcome, no status column, no public note.
- `statements`: `id`, `at`, `page`, `country`, `name`, `role`, `text`, `link` (NOT NULL default `''`), `email` (NOT NULL default `''`), `status` default `'pending'`, `shown_on`, `ended_at`, `reason`, `log` (JSON, default `'[]'`). Index `statements_page(status, page)`.
- `briefings.withdrawn_at`, `withdrawn_reason`.
- Transitions (`C:statements:192-218`): pending → published; **pending only** → declined; pending or published → withdrawn (author's request, or removal by the site, the reason saying which); update while pending or published.
- **Audit log:** the `log` column, a JSON list of `{"at", "action", "note"?}` written by `_change` (`C:statements:178-189`). Actions: `received`, `published` (no note), `declined` (note: the reason), `updated` (note: the changed field names, sorted and comma-joined, e.g. `shown_on, text`), `withdrawn` (note: the reason). Not printed by any command. **How the sender was confirmed is not recorded.**

**Validation** (`C:statements:49-111`; handler `C:app:435-453`). Every refusal is **HTTP 422** with a string `detail`.

- Words: `len(text.split())`; over 150 → `"A statement can be up to 150 words; this one is {n}."`. Empty → `"Write the statement."`. **No minimum** beyond one character. Over `MAX_CHARS = 1500` → `"A statement can be up to 150 words (1,500 characters)."`. Text is stripped, otherwise unchanged. Pydantic allows 1,600 so the friendly message is reached (`C:app:135`).
- Name and role: `check_line` joins whitespace to single spaces, needs 2-200 characters (`C:statements:80-87`). Messages: `"Give your name, as it should be shown."`, `"Give your role, such as Permanent Representative of Kenya to the United Nations."`, and for length `"Your name, as it should be shown can be up to 200 characters."` (awkward: the phrase was written for the first message).
- Link: scheme `http`/`https`, a hostname, no space (quotes and angle brackets are allowed) → `"The link to the record must be a web address starting https:// (or leave it empty)."`.
- Email: same pattern → `"Give an email address we can use to confirm who you are."`.
- Country (owner's side and `GET`): `^[A-Z]{3}$` after upper-casing → `"A country is given by its three-letter code, such as KEN."`.
- The briefing must exist and not be withdrawn → `"There is no briefing at that address. Check the address of the briefing the statement is about."` (`C:app:449-452`).
- No spam trap. Report kinds: `Literal["error", "unfair", "problem", "takedown", "other"]`, default `error`; `message` 5-4000; `page` ≤300; `contact` ≤200 (`C:app:118-126`). `problem` is the form's old value.

**Item address** (`C:statements:42, 53-65`): only a saved briefing, `/b/<id>` with `^/b/([A-Za-z0-9_-]{6,20})$`. Hosts: the two site hosts, plus the configured site address and the request's own host (`C:app:431-433`), so test servers work. Messages: `"Give the address of the briefing the statement is about."`, `"The address must be a briefing on wherecountriesstand.com."`, `"The address must be a briefing on this site, such as https://wherecountriesstand.com/b/…"`.

**Public routes.**

| Route | Request | Response |
|---|---|---|
| `POST /api/report` (`C:app:423-427`) | JSON `kind?`, `page?`, `message`, `contact?` | `{"ok": true, "id": n}` |
| `POST /api/statements` (`C:app:435-453`) | JSON `page`, `name`, `role`, `text`, `link?`, `email` | `{"ok": true, "id": n}` |
| `GET /api/statements?page=/b/<id>` or `?country=KEN` (`C:app:455-465`) | one is required, else 422 `"Give the address of a briefing (page) or a country's code (country)."` | `{"statements": [{id, page, country, name, role, text, link, shown_on}], "note": "In their own words. Not checked or endorsed by Where Countries Stand."}` |
| `GET /api/corrections` (`C:app:419-421`) | none | a bare list `[{id, at, question, withdrawn_at, reason}]`, remembered for 60 seconds |

Public fields: `PUBLIC` (`C:statements:40`). Ordered `shown_on, id`.

**Display** (`C/web/site/app.js:14, 239-257`): a `<section class="statement">` after the briefing's notes, heading `` `Statement from ${s.name}, ${fmtDate(s.shown_on)}` `` (an `h2`), role, paragraphs as text (`white-space: pre-line`, `C/web/site/styles.css:531`), then, if the link starts `http(s)://`, `"The record it points to: "` followed by **the address itself as the link's words** (`rel="ugc nofollow noopener"`), then the disclaimer. `?country=` has no page using it yet.

**Owner's commands** (`C:cli:283-421`):

- `wcs reports [--all]`: `#{id}  {at}  {kind}  {page or '-'}` (+ `  (closed)`), the message, `    reply to: {contact}`.
- `wcs close-report ID` → `closed` or `no open report with that number`. No outcome is asked for.
- `wcs statements [--all]` (alias `list-statements`, hidden): per statement `#{id}  {at}  {status}  {page}` (+ `  (speaks for KEN)`), `    from: {name}, {role}`, `    confirm with: {email}`, `    record: {link}`, the text, `    ({n} words; shown from {date}; {status}: {reason})`. Default: pending and published, newest first.
- `wcs publish-statement ID [--country KEN]` → `published` / `no waiting statement with that number`.
- `wcs decline-statement ID --reason TEXT` → `declined` / `no waiting statement with that number`.
- `wcs update-statement ID [--text | --text-file] [--name] [--role] [--link ''] [--country]` → `updated` / `nothing changed: no waiting or published statement with that number, or no change`; a rule broken prints `error: …`, exit 1.
- `wcs withdraw-statement ID [--reason "Withdrawn by its author."]` → `withdrawn` / `no waiting or published statement with that number`.
- `wcs withdraw BRIEFING_ID --reason TEXT` → `withdrawn` / `no briefing with that id`.
- A failed command prints a line and exits 0 (only validation errors exit 1).

**Deleting the confirming address** (`C:statements:120-124, 221-227`):

```python
def months_before(when, months):
    y, m = divmod(when.month - 1 - months, 12)
    year, month = when.year + y, m + 1
    return when.replace(year=year, month=month, day=min(when.day, calendar.monthrange(year, month)[1]))

"UPDATE statements SET email = '' WHERE status IN ('withdrawn', 'declined') AND email != '' AND ended_at < ?"
```

Run before each new statement is stored (`C:statements:136`), by every statement command (`C:cli:321-329`) and by `wcs update` inside `spending()` (`C/src/wcs/update.py:472-487`, called at 558; skipped silently if the spending summary raises first, since both share one `try`). Report contacts: `contact = ''` on closing (`C:usage:375-379`).

**Corrections log:** withdrawn briefings only (`C:usage:353-358`). A corrected label or grouping has nowhere to be recorded: closing a report takes no note.

**Hiding: not built**, though `C/web/site/named.html` says "we may hide the briefing meanwhile, with a note". A withdrawn briefing answers 410 `f"This briefing has been withdrawn: {reason}"` (`C:app:415-416`).

**Alerts:** none for reports or statements (the update report warns only of spending and failed briefings). **Limits:** 20 requests a minute per visitor code, shared with every other endpoint (`C:app:364, 387-395`); no daily limit on reports or statements.

**Never the model or the index.** Run-time test: the model's calls, the answer, `/api/search`, `/api/briefings/{id}`, and the saved and cached events (`C/tests/test_statements.py`, `test_statements_never_reach_the_model_the_index_or_a_briefing`). Source scan: nothing in `rag/`, `index/`, `rank/`, `embed/`, `sources/`, `store/`, `engine.py`, `evaluate.py` contains `wcs.api`, `FROM statements` or `state.db` (same file, `test_the_code_that_builds_the_record_and_briefings_never_reads_statements`).

### 1.3 Where Councils Stand (`councils`, decision 22: `K/docs/DECISIONS.md:29`)

**Data model** (`K:state:32-39`): the same as Countries', with `council` in place of `country`. `reports`: `id`, `at`, `kind`, `page`, `message`, `contact`, `closed_at`. `statements`: `id`, `at`, `page`, `council`, `name`, `role`, `text`, `link`, `email`, `status`, `shown_on`, `ended_at`, `reason`, `log`. The methods live on `StateDB` (`K:state:156-240`). Transitions and the JSON `log` are as Countries' (`K:state:195-231`). One difference: an update of a published statement always renews `shown_on` (`K:state:224-225`), where Countries renews it only when text, name, role or link change (`C:statements:210-211`).

**Validation** (`K:statements:26-77`; handler `K:app:418-436`). Refusals are **HTTP 422**.

- Text, link and email: the same functions and messages as Countries' (`K:statements:54-77`).
- Name and role: only pydantic `min_length=2, max_length=200` on the raw value, then `.strip()` (`K:app:84-85, 435`). **A name of two or more spaces is accepted and stored empty.** `update-statement --name/--role` has no check at all (`K:cli:335`).
- A box that must be ticked: `acting: bool = False`; unticked → `"Please confirm that you are the person or organisation the item is about, or act for them."` (`K:app:89, 422-424`). Only this site has it.
- The item must exist (`K:app:392-398, 432-434`) → `"There's no page at that address on this site. Copy the address from the page the statement is about."`. **A withdrawn briefing still counts as existing** (`state.briefing(key) is not None`).
- No spam trap. Report kinds: `Literal["error", "unfair", "takedown", "other"]`, default `error`; `message` 5-5000; `page` ≤500; `contact` ≤300 (`K:app:70-77`). Email ≤300 (`K:app:88`).

**Item address** (`K:statements:21, 30-51`): `^/(councils|votes|b)/([^/\s]+)$`, returned as `(page, council)`: `/councils/<GSS>` (upper-cased; its own council), `/votes/<GSS>:<rest>` (GSS upper-cased; that council), `/b/<id>` (no council until the owner gives one). Hosts: the site's, the configured address with and without `www.`, and the request's host (`K:app:388-390`). Messages: `"Give the address of the page the statement is about."`, `"The address must be a page on wherecouncilsstand.com."`, `"The address must be a council's page, a named vote or a briefing on this site, such as https://wherecouncilsstand.com/votes/…"`.

**Public routes.**

| Route | Request | Response |
|---|---|---|
| `POST /api/report` (`K:app:381-385`) | JSON `kind?`, `page?`, `message`, `contact?` (stored unstripped) | `{"ok": true, "id": n}` |
| `POST /api/statements` (`K:app:418-436`) | JSON `page`, `name`, `role`, `text`, `link?`, `email`, `acting` | `{"ok": true, "id": n}` |
| `GET /api/statements?page=…` or `?council=GSS` (`K:app:438-449`) | one is required, else 422 `"Give a page or a council."`; `council` is upper-cased, not checked | `{"statements": [{id, page, council, name, role, text, link, shown_on, about?}], "note": "In their own words. Not checked or endorsed by Where Councils Stand."}`; `about` (the item's name) only with `council` |

There is **no `/api/corrections` and no public corrections log** on this site.

**Display.** In the browser: `<article class="statement">`, heading `Statement from {name}, {longDate(shown_on)}`, role, `About: <link>` when on a council's page and about another item, paragraphs, link "The record they point to" (`rel="nofollow ugc"`; shown whenever `s.link` is non-empty, with no check of its scheme), disclaimer (`K/web/src/components/Statements.tsx:10-41`). On a council's page they are gathered under `Statements in their own words` (`Statements.tsx:57-68`). **Also written into the page the server sends** (for readers without scripts, and so for search engines): `K/src/councils/api/plaintext.py:336-352`, after the record's text, never in the description or structured data (`K:app:530-533, 549-552`).

**Owner's commands** (`K:cli:245-345`): `councils list-reports [--all]`, `close-report ID`, `withdraw BRIEFING_ID --reason`, `list-statements [--all]`, `publish-statement ID [--council GSS-or-name]`, `decline-statement ID --reason`, `update-statement ID [--text | --text-file] [--name] [--role] [--link '']`, `withdraw-statement ID [--reason "Withdrawn by its author."]`. Outputs are word for word Countries' (`closed`, `published`, `declined`, `updated`, `withdrawn`, and the same "no … with that number" lines), except the listing's first line ends `  (on {council}'s page)` or `  (on no council's page: --council)` (`K:cli:271-272`). A council cannot be set after publishing (Countries' `update-statement --country` can).

**Deleting the confirming address:** `months_before` identical to Countries' (`K:state:57-61`); the same SQL (`K:state:233-240`). Run before each new statement (`K:state:159`), by every statement command (`K:cli:285-288`) and at the end of `councils update` (`K:cli:162-163`, reported as `statement_emails_deleted`; not reached if the update raises earlier). Report contacts: `contact = ''` on closing (`K:state:149-153`).

**Hiding: not built**, though `K/web/named.html:82` says "we may hide the item meanwhile, with a note". A withdrawn briefing answers 410 `"This briefing has been withdrawn: {why}"` or `"This briefing has been withdrawn."` (`K:app:355-357`).

**Alerts:** none. **Limits:** 20 a minute per visitor code (`K:app:167, 191-198`); no daily limit; no trap.

**Never the model or the index.** Run-time: the model's calls, the events and `/api/search` (`K/tests/test_statements.py:237-246`). Source scan by parsing imports: nothing in `rag/`, `index/`, `embed/`, `rank/`, `engine.py`, `extract.py`, `load.py`, `ingest.py` imports a name containing `state` or `statements` (`K/tests/test_statements.py:252-262`).

### 1.4 Where Landlords Stand (`landlords`, decision 15: `L/docs/DECISIONS.md:26`)

**Data model** (`L:api:43-56`).

- `reports`: `id`, `at`, `page`, `message`, `email`, `closed_at`, `outcome`, and `kind` added by migration (`L:api:72-73`).
- `statements`: `id`, `at`, `name`, `role`, `page`, `part` (default `''`), `text`, `link`, `email`, `status` default `'pending'`, `landlord`, `checked`, `reason`, `published_at`, `updated_at`, `closed_at`.
- `statement_log`: `id`, `statement`, `at`, `action`, `note`.
- Transitions (`L:statements:154-204`): pending → published (needs `checked` and a landlord whose page exists); **pending only** → declined (reason required); pending or published → withdrawn (reason required); update while pending or published.
- **Audit log:** `statement_log`, a row per action from `change_statement` (`L:api:132-142`): `received`; `published` (note: how the sender was confirmed); `declined` (note: reason); `updated` (note: `--reason`); `withdrawn` (note: reason). Read with `landlords statements --log N`. The best of the four.

**Validation** (`L:statements:68-135`). Refusals are **HTTP 400** as `{"ok": false, "error": "…"}` for JSON, or a page titled "Your statement wasn't sent" that gives the words back to copy, for a form post (`L:api:342-352`).

- Words: `len(text.split())`; fewer than **3** → `"Please write the statement: a sentence or more."`; over 150 → `"A statement can be up to 150 words. This one is {n}."`.
- Lengths: `LIMITS = {"name": 120, "role": 200, "page": 300, "part": 20, "text": 2000, "link": 300, "email": 200}` (`L:statements:43`), applied by **cutting** (`L:statements:127-128`). A statement over 2,000 characters but within 150 words is silently shortened and kept, against "never edited"; a long link is cut and may break. The form's `maxlength` stops browsers; a direct post is not stopped.
- Text cleaning as MPs' (`L:statements:72-75`). Name: `"Please give the name the statement is from."`. Role: `"Please give your role and the landlord you speak for, for example \"Chief executive, Example Housing\"."`. Email: same pattern, `"Please give an email address, so we can confirm who the statement is from."`. Link: scheme, netloc, no whitespace or `"'<>` → `"The link to the record should be a full web address, starting https://."` (`L:statements:78-85`).
- The page must exist in the live pages (`L:api:341`) → `"We couldn't find that page on the site. Please copy its address from your browser."`.
- Spam trap `website` on statements only (`L:api:337-339`); the report form has none.
- Report kinds: `KINDS = ("wrong", "unfair", "takedown", "other")`; aliases `correction`, `error`, `mistake` → `wrong`; `complaint` → `unfair`; `general` → `other` (`L:api:39-42`); anything else is stored as NULL. `message` required (cut to 4,000) → 400 `{"ok": false, "error": "please say what is wrong"}`; an email without `@` is dropped silently (`L:api:313-317`).
- Fault: a JSON body that does not parse raises (`json.loads`, `L:api:310, 334`), which would be a 500.

**Item address** (`L:statements:47-50, 88-105`): no leading slash, a trailing slash: `landlords/<slug>/` or `areas/<slug>/` (`^(landlords|areas)/([a-z0-9][a-z0-9-]*)/?(?:index\.html)?$`), plus a `part` of a landlord's page from `PARTS = ("grade", "bands", "ombudsman", "safety")`, taken from the form's field or the address's `#fragment`. Returned as `(page, part, landlord)`; the landlord is known for its own page and given by the owner (`--landlord`) for an area's page. Fixed hosts. Message: `"Please give the address of a page on wherelandlordsstand.com that names your landlord: its own page (with /landlords/ in it), or a council area's page (with /areas/ in it)."`.

**Public routes.**

| Route | Request | Response |
|---|---|---|
| `POST /api/corrections` (`L:api:303-321`) | form or JSON: `kind?`, `page?`, `message`, `email?` | JSON: `{"ok": true, "id": n}`; form: 303 to `/corrections/thanks.html` |
| `POST /api/statements` (`L:api:323-355`) | form or JSON: `name`, `role`, `page`, `part?`, `text`, `link?`, `email`, `website?` | JSON: `{"ok": true, "id": n}`; form: 303 to `/named/thanks.html` |
| `GET /corrections/`, `/named/` with `?kind=&page=&part=` (`L:api:360-377`) | none | the built page with the choice made (`prefill`, `L:api:205-219`), so no script is needed |

There is **no route that returns statements**: pages are static.

**Display** (`L:statements:234-329`). Each landlord's page has slots `<!--statements:KEY--><!--/statements:KEY-->` for `grade`, `bands`, `ombudsman`, `safety` and `page`; each area's page has `page` (`L/src/landlords/site.py:350-426`; `L:pages:116`). `write_into` fills them: beside the part it is about (heading level 4), or after the card (level 2), and also on the landlord's own page when the item is elsewhere, with `This statement is about <link>.`. Markup: `<div class="statement" role="note" id="statement-N" aria-labelledby="statement-N-h">`, heading from `L:wording:242` (`"Statement from {name}, {date}"`), role, a `<blockquote>` (escaped; single line breaks kept as `<br>`), the link (`rel="nofollow"`, "The record they point to"), then `L:wording:243` (`"In their own words. Not checked or endorsed by {site}."`). The date is that of `updated_at` if set, else `published_at`. Every owner's command rewrites the live pages, every kept build and `data/site` at once (`refresh`, `L:statements:317-329`; also after a publish or an undo, `L/src/landlords/publish.py:203-215`), each file replaced whole (`L:statements:310-312`).

**Owner's commands** (`L:cli:184-247`): one command with options.

- `landlords reports` → a JSON line per open report (`id, at, kind, page, message, email`), **takedown requests first** (`order by kind is not 'takedown', id`, `L:api:88-89`). `landlords reports --close N [--outcome TEXT]` → `{"closed": true|false}`.
- `landlords statements` (pending) / `--all` → a JSON line per statement with every column and `words`.
- `--publish N --checked TEXT [--landlord SLUG]`, `--decline N --reason TEXT`, `--update N [--text-file F] [--name] [--role] [--link ""] [--reason TEXT]`, `--withdraw N --reason TEXT`, `--log N`.
- Success prints `{"id", "status", "name", "page", "part", "landlord", "email", "pages_changed", "shown"}`. Failure prints `Not done: …` and exits 1, with: `no statement N`; `statement N is {status}, not pending`; `say how you confirmed who sent it (--checked), for the log`; `statement N is about {page}: say which landlord it speaks for (--landlord)`; `no landlord's page landlords/{slug}/ on the site`; `give the reasons (--reason): the sender is told why`; `nothing to change: give --text-file, --name, --role or --link`; `say why (--reason): "withdrawn by the author", or the rule it broke`.

**Deleting the confirming address** (`L:statements:207-218`; `L:api:149-154`):

```python
y, m = divmod(now.year * 12 + now.month - 1 - months, 12)
return now.replace(year=y, month=m + 1, day=min(now.day, calendar.monthrange(y, m + 1)[1]))

"update statements set email = null where email is not null and status in ('withdrawn', 'declined') and closed_at < ?"
```

Run after each new statement (`L:statements:134`), by every `landlords statements` command (`L:cli:223`) and by the **weekly** update (`L/src/landlords/publish.py:136`). Report emails: `email = null` on closing (`L:api:91-96`).

**Corrections log:** a hand-kept file, `L/data_static/corrections.csv` (`date,page,what_was_wrong,what_we_did`; header only today), built into the corrections page under "Mistakes we have fixed" (`L:pages:281-291`). A report's `outcome` is private and does not feed it.

**Hiding: not built**, though `L/config/pages.toml:180` says "we can hide the item meanwhile, with a note saying so". The site has no briefings to withdraw.

**Alerts:** the weekly email carries `Readers' reports of mistakes waiting: {n} (landlords reports)` and `Statements from landlords waiting for a decision: {n} (landlords statements). We reply within 5 working days, and decide within 20 working days.` (`L/src/landlords/notify.py:163-167`), and is sent when either count is above zero (`publish.py:141-142`). A weekly email is slower than the 5-day reply; `L/docs/OPERATIONS.md:180-182` says to look twice a week.

**Limits:** 10 posts a minute per address, in memory (`L:api:222-238, 285-288`); no daily limit. The limiter never forgets an address it has seen (the other three prune).

**Never part of the figures.** No model and no search index of text; search is `names.json`. Tests: writing statements into pages changes no file that is not HTML (`L/tests/test_statements.py:267-274`); a source scan that only `api.py` touches the table, only `statements.py`, `cli.py`, `api.py` read statements, only `statements.py` and `site.py` call `statements.published`, and the scoring and download code never mention the word (`L/tests/test_statements.py:277-295`). The statement's words are in the static HTML, so outside search engines can index them, as on Councils.

---

## 2. Differences

Marks: **(a)** a fix or feature one build has and others lack (the best is named); **(b)** deliberate and site-specific; **(c)** incidental.

| Behaviour | MPs | Countries | Councils | Landlords | Mark |
|---|---|---|---|---|---|
| Statuses | pending, published, declined, withdrawn (`M:statements:30`) | same | same | same (`L:statements:51`) | same |
| Decline from | pending or published (`M:statements:214`) | pending only (`C:statements:200`) | pending only (`K:state:214`) | pending only (`L:statements:173`) | (c). Best: pending only, with withdraw-with-reason for a removal, so "declined" always means never shown |
| Removal by the site | `decline` on a published one | `withdraw --reason` | `withdraw --reason` | `--withdraw --reason` (required) | (c). No build has a status of its own for "removed by the site" |
| Withdraw reason | optional note, default "Withdrawn by the author." | default "Withdrawn by its author." | same as Countries | required (`L:statements:201-202`) | (c). Best: Landlords (a reason every time) |
| Audit log | none | JSON `log` column (`C:statements:178-189`) | JSON `log` column (`K:state:195-205`) | `statement_log` table and `--log` (`L:api:50-51, 132-147`) | (a). Best: Landlords |
| How the sender was confirmed | `checked`; required on CLI (`M:cli:825`), optional on the route (`M:app:195`) | not recorded | not recorded | required and logged (`L:statements:158-159`) | (a). Best: Landlords |
| Old words kept after an update | no | no | no | no | gap in all four |
| Minimum words | 5 (`M:statements:96`) | 1 | 1 | 3 (`L:statements:116`) | (c) |
| Word count | `len(text.split())` | same | same | same | same |
| Over-long text | pydantic 2000 → 422 list (`M:app:187`) | 1,500 characters, friendly 422 (`C:statements:75-76`) | same (`K:statements:61-62`) | cut at 2,000 and kept (`L:statements:128`) | (a). Best: Countries/Councils. Landlords' cutting is a fault |
| Text cleaning | line endings, blank runs (`M:statements:84-87`) | strip only | strip only | as MPs | (c). Best: MPs/Landlords |
| Name and role check | ≥2 after strip, 120/200 | joined to one line, 2-200 (`C:statements:80-87`) | raw length only; blank accepted (`K:app:84-85, 435`) | ≥2 after strip, cut to 120/200 | (a). Best: Countries. Councils' is a fault |
| Link check | no `"'<>` or space (`M:statements:79`) | no space only (`C:statements:92`) | no space only | no whitespace or `"'<>` (`L:statements:83`) | (a). Best: MPs/Landlords |
| Link length | 500 | 500 | 500 | 300, cut | (c) |
| Email pattern | `^[^@\s]+@[^@\s]+\.[^@\s]+$` | same | same | same | same |
| "I act for them" box | no | no | required (`K:app:422-424`) | no | (a) or (b): see open questions |
| Item must exist | no | yes, and not withdrawn (`C:app:449-452`) | yes, withdrawn briefing passes (`K:app:392-398`) | yes (`L:api:341`) | (a). Best: Countries. MPs lacks it |
| Hosts accepted | fixed two | site, configured, request (`C:app:431-433`) | same plus `www.` (`K:app:388-390`) | fixed two | (a). Best: Councils |
| Item address shape | `/people/<n>`, `/b/<id>` and nine more kinds | `/b/<id>` only | `/councils/<GSS>`, `/votes/<id>`, `/b/<id>` | `landlords/<slug>/`, `areas/<slug>/` + part | (b) |
| "About whom" key | `person` (int) | `country` (alpha-3) | `council` (GSS) | `landlord` (slug) | (b) |
| Key can be set later | at publish only | at publish or update | at publish only | at publish only | (c). Best: Countries |
| Refusal code and shape | 400 `detail` string; 422 for pydantic | 422 `detail` string | 422 `detail` string | 400 `{"ok": false, "error"}` or a page | (c). One code and one shape are needed |
| Success shape | `{"ok": true}` | `{"ok": true, "id"}` | `{"ok": true, "id"}` | `{"ok": true, "id"}` or 303 | (c). Best: with id (Councils shows it as a reference) |
| Works without scripts | no | no | no (noscript says email) | yes (`L:api:336-355`) | (a). Best: Landlords |
| Spam trap | statements and reports (`M:app:1829, 1847`) | none | none | statements only (`L:api:337`) | (a). Best: MPs |
| Daily limit | 5 statements, 10 reports (`M:statements:29`, `M:reports:23`) | none | none | none | (a). Best: MPs |
| Per-minute limit | 20, visitor code | 20, visitor code | 20, visitor code | 10, address in memory, never pruned (`L:api:222-238`) | (c) |
| Fetching published | `GET ?path=&person=` | `GET ?page=&country=` + `note` | `GET ?page=&council=` + `note`, `about` | none: written into pages | (b) |
| Nothing asked for | 200, empty list | 422 | 422 | n/a | (c) |
| Date in heading | `published_at`, reset on any update (`M:statements:232`) | `shown_on`, reset when words, name, role or link change | `shown_on`, reset on any update | `updated_at` or `published_at` (`L:statements:242`) | (c). Best: Landlords (both dates kept) |
| Link's words | "The record they point to" | "The record it points to: " + the address | "The record they point to" | "The record they point to" | (c). Countries is the odd one |
| Link `rel` | `nofollow ugc noopener noreferrer` | `ugc nofollow noopener` | `nofollow ugc` | `nofollow` | (c). Best: MPs |
| Link scheme checked again when shown | yes (`M:ts:62`) | yes (`app.js:254`) | no (`Statements.tsx:32`) | no (trusts storage) | (a). Best: MPs |
| In server-sent page text | never (`M/tests/test_statements.py:228`) | n/a (no item pages) | yes, after the record (`plaintext.py:336-352`) | yes (static pages) | (b), but see open questions |
| Admin over HTTP | yes (`M:app:1862-1903`) | no | no | no | (b) |
| CLI shape | `hansard statements list\|publish\|…` | `wcs statements`, `publish-statement`, … | `councils list-statements`, `publish-statement`, … | `landlords statements --publish N` | (c) |
| CLI failure exit code | 1 | 0 with a line | 0 with a line | 1 | (c). Best: 1 |
| Report kinds stored | correction, complaint, takedown, general | error, unfair, problem, takedown, other | error, unfair, takedown, other | wrong, unfair, takedown, other | (c): history, not design |
| `?kind=` aliases | wrong, unfair, privacy (`M:ts:27-35`) | problem (`corrections.js`) | none | correction, error, mistake, complaint, general (`L:api:41-42`) | (a). Best: Landlords (takes the sisters' words) |
| Report outcome recorded | status, private resolution, public note (`M:reports:54-60`) | none (`C:usage:375-379`) | none (`K:state:149-153`) | private outcome, optional (`L:api:91-96`) | (a). Best: MPs. Policy 7.4 needs it |
| Takedown requests listed first | no | no | no | yes (`L:api:88-89`) | (a). Best: Landlords |
| Report commands | admin route and page only | `reports`, `close-report` | `list-reports`, `close-report` | `reports [--close]` | (c) |
| Public corrections log | withdrawn briefings + public notes, with RSS (`M:reports:63-75`) | withdrawn briefings only | **none** | hand-kept CSV | (a). Best: MPs. Policy 7.1 needs one on every site |
| Email deleted: when | new statement, listing, twice-daily update | new statement, every command, twice-daily update | new statement, every command, nightly update | new statement, every command, **weekly** update | (c). Landlords can be up to a week late |
| Email deleted: to | NULL, with `visitor` | `''` | `''` | NULL | (c) |
| Three-months sum | loop over days (`M:statements:129-138`) | `calendar.monthrange` | same | same | (c): all give 31 May → 28 February |
| Alert to the owner | none | none | none | weekly email (`notify.py:163-167`) | (a). Best: Landlords, though weekly is too slow for 5 days |
| Hide while deciding | no | no | no | no | gap in all four; all four pages promise it |
| Guard tests | marker + table/module scan | marker + text scan | marker + import scan | bytes unchanged + scan | (a). Best: MPs (widest surfaces, and counts call sites) |

---

## 3. The best of the four, rule by rule

What a shared `wts-core` module should adopt, and where from.

| Rule | Adopt | Why |
|---|---|---|
| Statuses and transitions | pending → published; pending → declined; pending or published → withdrawn; update while pending or published (`C:statements:192-218`) | three builds agree; "declined" then never describes something that was shown. Consider a fifth status for removal by the site |
| Reasons | required for decline and for withdraw (`L:statements:174-175, 201-202`) | policy 7.2: "says why" |
| Sender confirmed | a required `checked` note at publishing, in function and CLI alike (`L:statements:158-159`) | policy 7.2 "Who is checked"; MPs' route lets it be empty |
| Audit log | a log table with action, time and note, and a command to read it (`L:api:50-51, 132-147`; `L:cli:224-227`) | policy 7.4; easier to review than a JSON column. Add the old words on update |
| Word limit | `MAX_WORDS = 150`, `len(text.split())`, message with the count (all four) | already the same |
| Minimum | choose one (MPs 5, Landlords 3, others 1) | open question |
| Characters | refuse over 1,500 with words for the reader (`C:statements:75-76`); never cut | Landlords cuts; MPs gives an unfriendly 422 |
| Text cleaning | line endings and blank runs only (`M:statements:84-87`) | keeps the words; makes display the same everywhere |
| Name and role | `check_line` (`C:statements:80-87`), with a `what` phrase written to suit both messages | Councils accepts blanks |
| Link | MPs' rule (`M:statements:74-81`), 500 characters, and checked again when shown (`M:ts:62`) | strictest; Countries/Councils allow quotes |
| Email | the shared pattern | already the same |
| Item | a per-site function returning (address, key) plus an existence check that refuses withdrawn items (`C:app:449-452`) | MPs has none; Councils lets a withdrawn briefing through |
| Hosts | site hosts + configured + `www.` + request host (`K:app:388-390`) | test and staging servers work |
| Refusals | one exception type whose message is for the reader (`M:statements:41`, `L:statements:56`), one HTTP code, one shape | four shapes today |
| Spam and limits | trap field on both forms, and a daily limit per visitor code (`M:app:1829-1832, 1847-1850`; `M:statements:104-110`) | only MPs has both |
| Public fields | an explicit tuple (`C:statements:40`; `K:state:46`) and a test that the set is exact (`M/tests/test_statements.py:125`) | the address can then never leak by `SELECT *` |
| Heading and disclaimer | from one constant per site, as `L:wording:242-243` | the glossary's words (`GLOSSARY.md:60`) |
| Dates | keep `published_at` and `updated_at`; show the later (`L:statements:242`) | the first date is otherwise lost |
| Deleting the address | Countries/Councils/Landlords' `monthrange` sum; MPs' SQL (clears the visitor code too); run on every write, every command and a **daily** job | simplest and correct; Landlords' weekly run is too slow |
| Reports | MPs' closing with status, private resolution and public note (`M:reports:54-60`), Landlords' takedown-first order (`L:api:88-89`) and alias table (`L:api:41-42`) | policy 7.1 and 7.4 |
| Corrections log | MPs' function over closed reports and withdrawn items (`M:reports:63-75`), with the feed | Councils has no log; Countries' cannot record a corrected label |
| Owner's alert | Landlords' counts (`L:api:103-105, 156-158`), sent daily | 5 working days |
| Guard test | MPs' pair (`M/tests/test_statements.py:204-248`), with Councils' import parsing for the record-building code | catches both a read and an import |

**What each site must keep as its own.**

- **MPs:** the eleven kinds of item and the `/people/<n>` shortening; `person`; placing a statement beside the member's first source card; the admin page and its routes; keeping statements out of the readable text.
- **Countries:** `/b/<id>` only; `country` and its three-letter check; the single place after a briefing's notes.
- **Councils:** `/councils`, `/votes`, `/b`; `council`; gathering on the council's page with `about`; the text sent to readers without scripts.
- **Landlords:** `landlords/` and `areas/` with a `part`; `landlord`; slots written into static pages, in every kept build; forms that work without scripts; wording held in `wording.toml`.
- All four: the "If you're named" page's own lists of what is covered, the role examples, and where identity is checked (parliament.uk, a mission, a council, a landlord's own address).

---

## 4. Reader-visible strings

Form labels are left out. Messages a reader can be shown, statuses, headings and disclaimers are given exactly.

### 4.1 Where MPs Stand

Statuses: statements `pending`, `published`, `declined`, `withdrawn`; reports `open`, `resolved`, `dismissed`. Report kinds and labels (`M:reports:20-21`): `correction` "Something is wrong"; `complaint` "You've been characterised unfairly"; `takedown` "A private person's name or details to remove"; `general` "Something else".

From the server:

- 400 `Please give the address of the page on wherempsstand.com that the statement is about.`
- 400 `That address isn't a page a statement can sit beside: please give the address of a member's page, a briefing or another page that names them.`
- 400 `The link to the record should be a full web address, starting https://.`
- 400 `Please give the name the statement is from.`
- 400 `Please give their role, for example "MP for Leeds Central" or "Chief of staff to …".`
- 400 `Please write the statement: a sentence or more.`
- 400 `A statement can be up to 150 words. This one is {n}.`
- 400 `Please give an email address, so we can confirm who the statement is from.`
- 429 `Thank you, we have your statements. Please email us if there is more to add.`
- 429 `Thank you, we have your reports. Please email us if there is more to add.`
- 429 `Too many requests. Please wait a minute and try again.`
- 404 `There is no briefing at this address.`; 410 `This briefing has been withdrawn.`
- Page titles `Briefing withdrawn — Where MPs Stand`, `Briefing not found — Where MPs Stand`; descriptions `This briefing is no longer available.`, `There is no briefing at this address.` (`M:app:686-691`).
- Feed: `Corrections`, `Withdrawn briefings and published corrections.`, items `Briefing withdrawn` or `Correction`.
- Owner only: `Please give the reason: it is sent to the author.`; 404 `No such statement, or it can't be changed in that way now.`; 404 `No such report.`; 403 `Admins only.`

From the page's script (`M:ts`, `M/web/src/pages.ts`). Three differ from the server's words for the same fault:

- `Please give your role, for example "MP for Leeds Central".` (server: "their role …")
- `Please give the address of the page the statement is about.`
- `Please give an email address, so we can confirm it's you.` (server: "… confirm who the statement is from.")
- `Please give the name the statement is from.`; `Please write the statement: a sentence or more.`; `A statement can be up to 150 words. This one is {n}.`; `The link to the record should be a full web address, starting https://.`
- Counter: `{n} of 150 words`; `{n} words: {k} over the limit of 150`.
- `The statement could not be sent. Please try again, or email admin@wherempsstand.com.`
- `The report could not be sent. Please try again, or email admin@wherempsstand.com.`
- `Please describe the problem in a sentence or two.`
- `Thank you. We have your statement, and will write to confirm it's from you. We reply within 5 working days.` (`M/web/named.html:190`)
- `Thank you. Your report has been received.` (`M/web/corrections.html:80`)
- Corrections log: `Loading…`; `No corrections so far.`; `The corrections log could not be loaded. Please try again later.`; entries headed `Briefing withdrawn` or `Correction`.

Display:

- `Statement from {name}, {date}`; `In their own words. Not checked or endorsed by Where MPs Stand.`; `The record they point to`.
- `About ` + one of: `their page on this site`, `a briefing`, `a topic briefing`, `a debate`, `a bill`, `a group's page`, `an early day motion`, `a committee`, `a committee inquiry`, `evidence to a committee`, `a day in a devolved parliament`, `a page on this site` (`M:ts:65-80`).
- Member's page: `A statement in their own words` / `Statements in their own words`; `Added by {name} or someone acting for them, beside what this site says about them. If you're named on this site.`
- Under a briefing: `A statement about this briefing` / `Statements about this briefing`; `From people it names, in their own words. If you're named on this site.`; `{heading}, beside their source below`.
- Other pages: `A statement about this page` / `Statements about this page`; `Added by the people or organisations named here, in their own words. If you're named on this site.`
- Pages: `If you're named`; `Corrections and problems`; `Corrections log`; `Report a problem`; `We reply within 5 working days, and decide within 20 working days.`

### 4.2 Where Countries Stand

Statuses as above; a report is open or closed (`closed_at`). Kinds: `error`, `unfair`, `problem`, `takedown`, `other`.

From the server (all 422 unless marked):

- `Give the address of the briefing the statement is about.`
- `The address must be a briefing on wherecountriesstand.com.`
- `The address must be a briefing on this site, such as https://wherecountriesstand.com/b/…`
- `Write the statement.`
- `A statement can be up to 150 words; this one is {n}.`
- `A statement can be up to 150 words (1,500 characters).`
- `Give your name, as it should be shown.`; `Your name, as it should be shown can be up to 200 characters.`
- `Give your role, such as Permanent Representative of Kenya to the United Nations.`; `Your role, such as Permanent Representative of Kenya to the United Nations can be up to 200 characters.`
- `The link to the record must be a web address starting https:// (or leave it empty).`
- `Give an email address we can use to confirm who you are.`
- `There is no briefing at that address. Check the address of the briefing the statement is about.`
- `Give the address of a briefing (page) or a country's code (country).`
- `A country is given by its three-letter code, such as KEN.`
- 429 `Too many requests. Please wait a minute and try again.`
- 404 `There is no briefing at this address.`; 410 `This briefing has been withdrawn: {reason}`

From the page's script (`C/web/site/corrections.js`, `app.js`):

- Counter: `{n} word of 150.` / `{n} words of 150.`; `{n} words: {k} more than the 150 a statement can have.`
- `A statement can be up to 150 words. Please shorten it.`; `Sending…`
- `Thank you: your statement has been sent. We will write to you to confirm who you are before it is shown.`
- `Thank you: your report has been sent.`
- `It could not be sent ({status}). Please email us instead.`
- Hints: `A fact, a quotation, a date, a label, a group or a connection is incorrect, or a briefing misstates the record.`; `The record is right, but the site’s own words, labels or groupings are unfair: a loaded word in the site’s own voice, a connection without published evidence, or a grouping that suggests something the record doesn’t show.`; `The record is accurate and the site has followed its impartiality policy, but you see it differently: add a short statement, shown beside the briefing.`; `Something about you is shown that should not be. These requests are dealt with first.`; `Anything else about the site.`
- Questions: `What is wrong?`; `What is unfair, and why?`; `What would you like removed, and why?`; `Your message`. Button: `Send` / `Send the statement`.
- Withdrawn list: `{question} (written {date}; withdrawn {date}): {reason}` (or `withdrawn`); empty: `None so far.`

Display: `Statement from {name}, {date}`; `The record it points to: ` + the address; `In their own words. Not checked or endorsed by Where Countries Stand.` Pages: `If you’re named`; `Corrections and problems`; `Report a problem`; `Withdrawn briefings`; the routes `Something is wrong`, `You’ve been characterised unfairly`, `Add a statement in your own words`, `Something about you that you want removed`, `Something else`; `We reply within 5 working days, and decide within 20 working days.` (This site sets a curly apostrophe; the others a straight one. Its footer link reads `Corrections`, as its test asserts, where the glossary's words are "Corrections and problems".)

### 4.3 Where Councils Stand

Statuses as Countries'. Kinds: `error`, `unfair`, `takedown`, `other`.

From the server (422 unless marked):

- `Give the address of the page the statement is about.`
- `The address must be a page on wherecouncilsstand.com.`
- `The address must be a council's page, a named vote or a briefing on this site, such as https://wherecouncilsstand.com/votes/…`
- `Write the statement.`; `A statement can be up to 150 words; this one is {n}.`; `A statement can be up to 150 words (1,500 characters).`
- `The link to the record must be a web address starting https:// (or leave it empty).`
- `Give an email address we can use to confirm who you are.`
- `Please confirm that you are the person or organisation the item is about, or act for them.`
- `There's no page at that address on this site. Copy the address from the page the statement is about.`
- `Give a page or a council.`
- 429 `Too many requests. Please wait a minute and try again.`
- 404 `There is no briefing at this address.`; 410 `This briefing has been withdrawn: {why}` or `This briefing has been withdrawn.`

From the page's script (`K/web/src/components/ReportForm.tsx`):

- `Thank you. Your statement has been received (reference {n}). We'll write to you at the address you gave to confirm it's you, then publish it as you wrote it or tell you why not. We reply within 5 working days, and decide within 20 working days.`
- `Thank you. Your report has been received (reference {n}). Takedown requests are dealt with first. We reply within 5 working days, and decide within 20 working days.`
- `The statement couldn't be sent: {error}`; `The report couldn't be sent: {error}`
- Counter: `{n} of 150 words`; `{n} of 150 words: {k} too many`.
- Options: `Something is wrong`; `You've been characterised unfairly`; `Add a statement in your own words`; `A takedown request`; `Something else`.
- Hints: `A fact, a date, a vote, a party, a council's control, a coverage label, a connection between councils or a briefing that is incorrect, or that misstates the minutes.`; `The record is right, but the site's own words, labels or groupings are unfair: a loaded word, a connection without published evidence, or a grouping that suggests something the minutes don't show.`; `For a councillor, a council or someone acting for them: a short statement, shown beside the item, when the record is right but you see it differently.`; `For someone named on the site who isn't a councillor, and wants something removed. Dealt with first.`; `Anything else about the site, such as something hard to use.`
- Questions: `What's wrong?`; `What's unfair, and why?`; `What would you like removed, and why?`; `What's the problem?`
- Rules line: `Up to 150 words, in your own name, about one item on the site. No defamatory or abusive content, nothing about a private individual or another person's conduct, and no appeals for votes, money or support. The rules in full.`

Display: `Statement from {name}, {date}`; `About: {item}`; `The record they point to`; `In their own words. Not checked or endorsed by Where Councils Stand.`; `Statements in their own words`; `From councillors, or people acting for them or the council, about this page or an item on the site. If you're named on this site.` In the server-sent text the same heading, `About: `, link words, and the disclaimer in `<em>` (`plaintext.py:344-351`). Pages: `If you're named`; `Corrections and takedown requests` (the page's own heading; decision 22 calls the footer link "Corrections", where the glossary's words are "Corrections and problems"); `We reply within 5 working days, and decide within 20 working days.`

### 4.4 Where Landlords Stand

Statuses as MPs'. Kinds: `wrong`, `unfair`, `takedown`, `other`, or none.

From the server:

- 400 `Please give the address of a page on wherelandlordsstand.com that names your landlord: its own page (with /landlords/ in it), or a council area's page (with /areas/ in it).`
- 400 `Please give the name the statement is from.`
- 400 `Please give your role and the landlord you speak for, for example "Chief executive, Example Housing".`
- 400 `Please write the statement: a sentence or more.`
- 400 `A statement can be up to 150 words. This one is {n}.`
- 400 `Please give an email address, so we can confirm who the statement is from.`
- 400 `The link to the record should be a full web address, starting https://.`
- 400 `We couldn't find that page on the site. Please copy its address from your browser.`
- 400 `please say what is wrong` (report without a message)
- 429 `too many tries; try again in a minute`; 429 `too many reports; try again in a minute`
- Page for a refused form post: title `Your statement wasn't sent`; `Go back to the form to change it: your browser should still have what you wrote. Here it is too, so you can copy it.`; `Your statement`; `Back to the form` (`L:api:348-352`).
- `Page not found` / `That page isn't on the site.`

From `L:wording` and `L/config/pages.toml`:

- `Statement from {name}, {date}`; `In their own words. Not checked or endorsed by {site}.` (with `Where Landlords Stand`); `The record they point to`; `This statement is about {page}.` with `what we say on the page for {page}`.
- Statement thanks: `Thank you`; `We have your statement. We will write to you to confirm it's from you before it is shown.`
- Report thanks: `Thank you`; `We have your report. We will look at it and put right any mistake of ours.`
- `We reply within 5 working days, and decide within 20 working days.`; `We can only reply if you give your email. A fix goes on the site with the next pages, which a person checks first.`
- Kinds: `Something is wrong`; `You've been characterised unfairly`; `Remove a person's details`; `Something else`, each with its hint (`L:wording:213-216`).
- Log: `Mistakes we have fixed`; `None yet.`; columns `Date`, `Page`, `What was wrong`, `What we did`.
- Pages: `If you're named`; `Corrections and problems`; `Send a statement`; `Your statement is shown with your name and role once we have confirmed it's from you.`

### 4.5 Wording that differs for the same thing

| Thing | MPs | Countries | Councils | Landlords |
|---|---|---|---|---|
| Too many words | "…up to 150 words. This one is N." | "…up to 150 words; this one is N." | as Countries | as MPs |
| No text | "Please write the statement: a sentence or more." | "Write the statement." | as Countries | as MPs |
| Bad email | "Please give an email address, so we can confirm who the statement is from." | "Give an email address we can use to confirm who you are." | as Countries | as MPs |
| Bad link | "The link to the record should be a full web address, starting https://." | "The link to the record must be a web address starting https:// (or leave it empty)." | as Countries | as MPs |
| Link's words | The record they point to | The record it points to: … | The record they point to | The record they point to |
| Statement received | "Thank you. We have your statement, and will write to confirm it's from you. We reply within 5 working days." | "Thank you: your statement has been sent. We will write to you to confirm who you are before it is shown." | "Thank you. Your statement has been received (reference N). …" | "We have your statement. We will write to you to confirm it's from you before it is shown." |
| Third takedown label | A private person's name or details should be removed | Something about you that you want removed | A takedown request | Remove a person's details |

Two families of wording are visible: MPs and Landlords share one, Countries and Councils the other. The heading, the disclaimer, the three routes and the response times are the glossary's on all four.

---

## 5. Tests

### 5.1 What each site's tests assert

**MPs** (`M/tests/test_statements.py`, `M/tests/test_api.py:384-426`, `M/web/src/__tests__/statements.test.tsx`).

- Item addresses: five good forms; six bad ones, including another host, `/about`, `/`, `javascript:` and an empty string (50-58).
- Stored as pending with the member set, and not shown (61-67).
- Seven refusals, each 400 with its words (70-83). Exactly 150 words pass; each of five fields missing gives 422; the link is optional (86-94).
- The trap keeps nothing; the sixth statement in a day is 429 (97-102).
- Owner's routes: 403 without the token; publish, with the member given for a group's page; the public set of fields is exact; no address in the output; publish twice is 404; update with new words, 151 words refused, an empty link removes it; decline needs a reason of three characters; withdraw; nothing can be done to a closed one (107-155).
- CLI: list, `--checked` required, update from a file, withdraw, decline of a withdrawn one exits 1 (158-179).
- The address goes one minute after three months, not one minute before; shown and pending ones keep theirs; 31 May → 28 February (184-199).
- Marker test and source scan (204-248).
- Reports: private until closed, contact deleted on closing, the public note and the withdrawn briefing in the log, the private resolution never public; the eleventh report in a day is 429 (`test_api.py:384-426`).
- Browser tests: heading, disclaimer last, text never as HTML, a `javascript:` link not made a link, the same markup with and without React, beside the first card of its member, the checks before sending, the page path, the named page's routes and fields, the report form's values and `?kind=` names.

**Countries** (`C/tests/test_statements.py`, `C/tests/test_api.py:194-216`).

- Addresses, including a given extra host; six bad ones.
- 150 words kept as written; 151, 1,501 characters and blank refused.
- Name, role, link, email and country each checked, with bad cases.
- Waits and is not shown; the log starts with `received`.
- Refusals with their words; every required field missing or blank; a nonexistent and a **withdrawn** briefing refused.
- The test server's own host and the configured host count as this site.
- Every command and its exact output; the alias; the log's actions in order.
- The address goes between 80 and 93 days on (a loose bound); `wcs update`'s `spending()` deletes one that is due.
- The exact public record; `?country=`; 422 with nothing asked.
- The page's script and styles carry the words (read as text, not run).
- Marker test including saved and cached events; source scan.
- The named page, the footer on four pages, the corrections page, the privacy notice's sentence; the report kinds, and that `statement` is not one.

**Councils** (`K/tests/test_statements.py`, `K/tests/test_api.py:83-93`, `K/tests/test_cli.py:12-29`, `K/web/src/__tests__/statements.test.tsx`).

- Waits with its council set; twelve refusals with their words, including the unticked box and a page that does not exist; each required field missing or a single space.
- Addresses in lower case and with a query; `ftp:` refused.
- Report kinds; an unknown one is 422.
- Every command and its output, the `--council` case, the log's actions.
- The address goes after three months, to the hour (11:00 no, 13:00 yes); kept while shown; two `months_before` cases.
- The exact public set; `about` on the council's listing.
- The server-sent pages: the heading escaped, paragraphs, the disclaimer, after "From the minutes", not in the description or the structured data, gone when withdrawn.
- Marker test; import scan.
- Report commands, contact deleted on closing, the 410 message; three reports with a limit of two a minute.
- Browser tests: the card, the lower heading and `about`, the five options, `?kind=`, the counter, the button disabled until ticked, what is posted, the thanks with the reference.

**Landlords** (`L/tests/test_statements.py`, `L/tests/test_api.py:30-41`).

- A form post is kept as pending, with `received` logged, and redirects to the thanks page.
- 151 words refused with the words given back to copy.
- Eleven refusals, including a page not on the site and a link with a space.
- Five ways of writing the address, a `#bands` fragment, a part given for an area's page ignored.
- The trap.
- Publish needs `--checked`; an area's page needs `--landlord`, which must exist; the statement is in the pages at once; update from a file, 151 words refused; withdraw needs a reason; `--log` in order; `--all`.
- Decline needs a reason.
- The address goes after three months, to the hour; kept while pending; 31 May → 28 February.
- The weekly email's line.
- The rendered markup exactly, escaping, the later date after an update.
- Placement beside a part, after the card when the part is missing, on the area's page and the landlord's page; nothing rewritten when nothing changes; slots emptied.
- Kept through a build, a publish and an undo.
- No non-HTML file changes; source scan.
- Report kinds, `?kind=` and aliases, `?page=` escaped, takedown listed first.
- The named page's words and fields, no script; the footer link.

### 5.2 Cases one site covers that others don't

| Case | Covered by | Missing from |
|---|---|---|
| Daily limit and trap | MPs | Countries, Councils (not built); Landlords tests the trap only |
| Item does not exist | Countries, Councils, Landlords | MPs (not built) |
| Withdrawn briefing refused | Countries | Councils (not built: would be accepted), MPs |
| Test or configured host accepted | Countries | others |
| Address deleted to the minute or hour | MPs, Councils, Landlords | Countries (80 and 93 days only) |
| Scheduled update deletes addresses | Countries | MPs, Councils, Landlords (the calls exist, untested) |
| Blank name or role | Countries (`check_line`), Landlords, MPs | Councils tests a single space only; two spaces would pass |
| Text over the character limit | Countries, Councils | MPs, Landlords (Landlords cuts) |
| Markup escaped | MPs (browser), Councils (server text), Landlords | Countries (asserts only that `innerHTML` is not in the script) |
| `javascript:` link not linked when shown | MPs | Councils, Landlords (rely on the check at storing) |
| Not in description or structured data | Councils | n/a elsewhere |
| Not in the page's readable text | MPs | n/a elsewhere |
| Not in saved or cached briefing events | Countries | MPs, Councils |
| Audit log's actions in order | Countries, Councils, Landlords | MPs (no log) |
| Survives a build, publish and undo | Landlords | n/a elsewhere |
| Report outcome and public log | MPs | Countries (withdrawn list only), Councils, Landlords (the CSV is untested) |
| Takedown requests first | Landlords | others (not built) |
| Owner alerted | Landlords | others (not built) |
| Decline of a published statement | MPs (allowed) | others (refused, tested as "no waiting statement") |

No site tests: an update's old words being kept (none keeps them); a leap-day cutoff; two visitors behind one address; a pending statement never decided.

---

## 6. Privacy check

### 6.1 The sentences

**MPs** (`M/web/privacy.html:63-79, 138-146`):

> If you report a problem, your message is saved, with your email address if you choose to give one. The email address is used only to reply to you and is deleted when the report is dealt with. A short public note may be added to the corrections page; it never includes your name or email address.

> The statement is published with their name and role, as they wrote it. The email address used to confirm who they are, and to let them update or withdraw it, is never shown; it is kept while the statement is shown and deleted three months after it is withdrawn or declined. Statements are never sent to Anthropic or used to write briefings.

> Report contact details are deleted when the report is closed, and the email address given with a statement three months after the statement is withdrawn or declined.

**Countries** (`C/web/site/privacy.html:36-47, 82-87`):

> If you report a problem, your message is saved, with your email address if you choose to give one. The email address is used only to reply to you, and is deleted when the report is dealt with. If a briefing is withdrawn, its question and the reason are listed on the corrections page; your name and address never are.

> The statement is published with their name and role, as they wrote it, and is never sent to the AI model. The email address used to confirm who they are, and to let them update or withdraw it, is kept while the statement is waiting or shown, and deleted three months after it is withdrawn or declined.

**Councils** (`K/web/privacy.html:20-21`):

> A problem report or takedown request is saved, with your email address if you choose to give one. The address is used only to reply, and is deleted when the report is dealt with.

> The statement is published with their name and role, as they wrote it, and is never sent to the AI model. The email address used to confirm who they are, and to let them update or withdraw it, is kept while the statement is shown and deleted three months after it is withdrawn or declined.

**Landlords** (`L:wording:234-235`):

> If you report a mistake, we keep what you wrote and, if you give it, your email address, until we have dealt with it. Then we delete your email address.

> The statement is published with their name and role, as they wrote it. The email address used to confirm who they are, and to let them update or withdraw it, is kept while the statement is shown and deleted three months after it is withdrawn or declined. It is never shown on the site.

### 6.2 Does the code match?

| Promise | MPs | Countries | Councils | Landlords |
|---|---|---|---|---|
| Report contact deleted on closing | yes (`M:reports:57-58`), tested | yes (`C:usage:378`), tested | yes (`K:state:152`), tested | yes (`L:api:94`), tested |
| Statement address never shown | yes: fixed SELECT, exact-set test | yes: `PUBLIC`, exact-record test | yes: `PUBLIC_STATEMENT`, exact-set test | yes: `keep` tuple (`L:statements:230`), not tested as an exact set |
| Kept "while shown" | kept while **pending or shown** | says "waiting or shown": matches | kept while pending or shown | kept while pending or shown |
| Deleted three months after | yes, at the next twice-daily update | yes, at the next twice-daily update | yes, at the next nightly update | **up to a week late** if no command is run and no statement arrives |
| Never sent to the model | tested | tested | tested | no model |
| Published "as they wrote it" | yes | yes | yes | not if cut at a limit (`L:statements:127-128`) |

Findings, in order of weight.

1. **The confirming address can outlive its deletion in the owner's own note.** Landlords' operations guide shows `--checked "reply from j.smith@example-housing.org.uk, 14 Nov"` (`L/docs/OPERATIONS.md:190`) and its test does the same (`L/tests/test_statements.py:137`). That text is kept for good in `statements.checked` and `statement_log.note`, which `forget_statement_emails` does not touch. MPs' `checked` column has the same exposure, though its examples name no address (`M:cli:825-826`). The notices promise deletion of "the email address", without exception.
2. **Three notices say "kept while the statement is shown"; the code also keeps it while the statement waits**, with no limit if the owner never decides. Only Countries says "waiting or shown". MPs' and Landlords' own module notes say "pending or shown" (`M:statements:13-15`, `L:statements:22-24`), so the notices lag the code.
3. **Deletion depends on something running.** No site has a job whose only purpose is this. Landlords' scheduled run is weekly. Countries' sits in a `try` behind the spending summary (`C/src/wcs/update.py:481-487`); Councils' is the last step of an update and is skipped if the update raises (`K:cli:162-163`).
4. **A report that is never closed keeps its address for ever**, on all four. "When the report is dealt with" is then never reached.
5. **Backups.** Each site's backup copies the state database, addresses included; a deleted address stays in older copies until they are pruned. Not checked in detail (see "What was not read"); no notice mentions it.
6. MPs alone stores a visitor code with each report and statement. It is cleared with the report on closing, and with a statement only in the same UPDATE as the address. The code cannot be linked across days, as the notice says.
7. Public notes and withdrawal reasons are free text written by the owner: "it never includes your name or email address" (MPs) and "your name and address never are" (Countries) rest on care, not code.
8. Nobody but the owner sees a pending, declined or withdrawn statement or any report: there is no public route to them on any site. MPs' admin routes need an admin session or the token (`M:app:408-414`).

---

## 7. Ports worth making now, and open questions

### 7.1 Ports

Source → destination. None was made: this is a study.

1. **Spam trap and daily limit.** `M:app:1829-1832, 1847-1850`, `M:statements:104-110`, `M:reports:26-31` → `C:app:423-453`, `K:app:381-436`; the trap also → `L:api:303-321` (reports). Needs a `visitor` column on Countries' and Councils' two tables, or a count in the key-value table.
2. **Record how the sender was confirmed.** `L:statements:154-167` → `C:statements:192-196` + `C:cli:356-364`; `K:state:207-211` + `K:cli:299-307`. Make it required on MPs' route too (`M:app:193-195`).
3. **An audit log for MPs.** `L:api:50-51, 132-147` and `L:cli:224-227` → `M:state:111-130`, `M:statements:194-243`, `M:cli:803-870`.
4. **Check the item exists.** `C:app:449-452` → `M:app:1851-1853` (a briefing by `get_briefing`; a member by the people store). Refuse a withdrawn briefing on Councils: `K:app:398` should also test `withdrawn_at`.
5. **Name and role.** `C:statements:80-87` → `K:app:435` and `K:cli:335`.
6. **Refuse, don't cut.** `C:statements:75-76` → `L:statements:127-128` (and a friendly refusal in place of pydantic's at `M:app:187`).
7. **Stricter link.** `M:statements:79` → `C:statements:92`, `K:statements:68`; and check the scheme when showing: `M:ts:62` → `K/web/src/components/Statements.tsx:32`.
8. **Report outcomes and a public log.** `M:reports:54-75` and `M:app:177-180` → `C:usage:375-379` + `C:cli:295-301`; `K:state:149-153` + `K:cli:255-258`; add `/api/corrections` and a list to `K/web/corrections.html`. Landlords: a public note from `--outcome`, or keep the CSV and test it.
9. **Takedown requests first.** `L:api:88-89` → `M:reports:43-51`, `C:usage:368-372`, `K:state:143-147`.
10. **Accept the sisters' `?kind=` words.** `L:api:41-42` → `M:ts:27-35`, `C/web/site/corrections.js` (KINDS), `K/web/src/components/ReportForm.tsx:8, 137-139`.
11. **Tell the owner.** `L:api:103-105, 156-158` and `L/src/landlords/notify.py:163-167` → the update reports of `M/src/hansard/sync.py`, `C/src/wcs/update.py:472-487`, `K:cli:153-166`. On Landlords, move the count to a daily job.
12. **Privacy wording.** "kept while the statement is waiting or shown" (`C/web/site/privacy.html:45-47`) → `M/web/privacy.html:76-77`, `K/web/privacy.html:21`, `L:wording:235`, and the matching lines on the named pages (`M/web/named.html:218-219`, `K/web/named.html:78`, `L/config/pages.toml:197`).
13. **Keep addresses out of `--checked`.** Change the example at `L/docs/OPERATIONS.md:190` and say so in the help at `L:cli:200`; or have `forget_statement_emails` clear `checked` and the log's note as well.
14. **Small faults.** Catch `StatementError` in `M:cli:836-842` and `M:app:1875-1877`; a JSON body that does not parse at `L:api:310, 334`; prune `L:api:227-238`; `check_line`'s length message at `C:statements:86`; exit 1 on a failed command in `C:cli` and `K:cli`.

### 7.2 Open questions

1. **Hiding while a concern is decided** (policy 7.3) is promised on all four named pages and built on none. What can be hidden on each site (a briefing, a label, a whole page, a statement slot), and what does the note say? Is withdrawal, which is permanent and public, an acceptable stand-in for briefings?
2. **Should a statement be in the text search engines read?** MPs keeps it out; Councils and Landlords put it in. The policy says "never treated as part of the record" and the sites' pages speak of their own search; the policy is silent on outside search engines. One rule, or site by site?
3. **Removal by the site**: its own status (say `removed`), or `withdrawn` with a reason as three sites do? MPs marks it `declined`, which reads as never shown.
4. **Minimum length**: 5 words (MPs), 3 (Landlords) or none?
5. **The "I act for them" box** (Councils only): adopt everywhere, or drop, since the owner confirms the sender anyway?
6. **Report kinds**: four vocabularies are stored. Should `wts-core` store one set (the glossary names no values) and translate, leaving old rows as they are?
7. **Refusal code and shape**: 400 or 422; `detail` or `error`?
8. **Dates**: does the heading's date mean first published or the words now shown? All four show the latter; only Landlords keeps both.
9. **Old words after an update**: keep them in the log (policy 7.4 says decisions and reasons are logged; it does not say versions)?
10. **Pending statements with no decision**: a time limit after which the address is deleted or the statement lapses? The policy gives 20 working days for a decision.
11. **Reports never closed**: a time limit for the contact address?
12. **Backups**: how long does a deleted address survive in them, and should the notices say so?
13. **Self-service**: updates and withdrawals go through the owner by email on all four. Is a signed link for the author wanted, or is the owner's check the point?
14. **Where the shared tables live**: MPs keeps functions over a `StateDB`; Councils puts methods on it; Landlords splits rules (`statements.py`) from storage (`api.py`). The Landlords split (rules that take a store) ports most easily to four different state classes.
15. **Countries' `?country=`** has no page using it. Keep it in the shared interface as the general "about whom" query (`person`, `country`, `council`, `landlord`)?
