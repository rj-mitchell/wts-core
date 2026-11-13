# Usage, state database and briefing stream: the four copies compared

Study for `wts-core`, 12 November 2026. Read-only: nothing in the four sites was changed.

**How to read the references.** A reference such as "MPs `api/usage.py:140`" is a path under that site's package:

| Short name | Root of the reference |
|---|---|
| MPs | `/home/user/wherempsstand/src/hansard/` |
| Countries | `/home/user/wherecountriesstand/src/wcs/` |
| Councils | `/home/user/wherecouncilsstand/src/councils/` |
| Landlords | `/home/user/wherelandlordsstand/src/landlords/` |

Tests are under each repository's `tests/`, settings under `config/settings.toml`.

**What was read in full:** the three `api/usage.py`; MPs `store/state.py`; Councils `api/state.py`; Landlords `api.py`;
Countries and Councils `api/app.py`; the three `rag/pipeline.py`; Countries `rag/answer.py` (MPs' and Councils' by
normalised diff against it); the three `rag/neutral.py`; MPs `api/briefings.py`, `api/reports.py`, `api/auth.py`; the
four `config.py` and `settings.toml`; MPs `tests/test_api.py`, `tests/test_sse.py`; Countries `tests/test_api.py`,
`tests/test_pipeline.py`; Councils `tests/test_api.py`, `tests/test_pipeline.py`.

**What was read only in part** (say so where it matters): MPs `api/app.py` (lines 1-680 and 1815-2015: all of the
briefing flow, feedback, reports, status and admin usage; not the pages in between); MPs `topics.py` (138-226); MPs
`tests/test_rag.py` and `tests/test_topics.py` (the pipeline tests and the budget test); the `statements.py` of every
site (function list and SQL only); Countries `cli.py` and `update.py` (the usage command and the spending warning
only); Landlords `statements.py`, `publish.py`, `status.py`, `cli.py` (their calls on the state database only);
`rag/verify.py` (the `to_dict` fields and Countries' `recheck_flags` only). The live servers' databases were not
seen: everything about "existing data" is deduced from the code and the tests.

**Two corrections to `family/ENGINE.md`** found on the way (its table is from 6 November):

- The three `sse()` functions are now the same code, line for line; only the docstring and one comment differ
  (MPs `api/app.py:296-331`, Countries `api/app.py:140-176`, Councils `api/app.py:92-126`). All three close the
  briefing when the reader leaves.
- Cost accounting: MPs and Countries now have `token_counts`, which Councils lacks. Councils is no longer the most
  advanced copy (section 1.2, row 3).

---

## 1. Usage: cost, caps, limits, visitors, the answer cache

### 1.1 What it does, and the public functions

Every model call is priced and written to a `usage` table. Before a briefing is written the site checks a
per-minute rate limit (in memory), a per-visitor daily limit and two spending caps (from the table), and reserves a
place among the briefings in progress (in memory). Identical questions are answered from an `answer_cache` table. A
visitor is a 24-character code: SHA-256 of a daily salt and the visitor's network.

| Function or class | MPs `api/usage.py` | Countries `api/usage.py` | Councils `api/usage.py` (and `api/state.py`, `api/app.py`) |
|---|---|---|---|
| `prices_for(prices, model) -> dict` | 22-28 | 79-84 | 18-23 |
| `token_counts(usage) -> dict[str, int]` | 31-44 | 87-103 | none |
| `cost_usd(usage, prices, model=None) -> float` | 47-62 | 106-120 | 26-43 |
| `network_of(address) -> str` | 65-78 | 123-137 | 46-59 |
| `visitor_key(...) -> str` | `(state, address, day=None)` 81-95 | `(state, address, day=None)` 140-151 | `(state, address)` 62-73 |
| `record_usage(...) -> float` | `(state, user_id, kind, model, usage, prices, visitor=None)` 98-109 | `(state, kind, model, usage, prices, visitor=None)` 154-163 | `(state, visitor, kind, model, usage, prices)` 76-87 |
| `spent(state, since) -> float` | none (inline SQL, 159-160) | 166-168 (`since`: a day or month prefix compared with `at`) | 90-93 (`since_day` compared with `day`) |
| caps | `check_caps(state, user_id, limits, visitor=None, pending_usd=0.0) -> str \| None` 140-165 | `check_caps(state, limits, visitor=None, pending_usd=0.0)` 171-188 | `blocked(state, visitor, cfg, pending_usd=0.0)` 112-117; `site_paused(state, cfg, pending_usd=0.0)` 120-126 |
| per-visitor count | `new_briefings_today(state, visitor)` 112-116 (counts `usage` rows) | inline in `check_caps` 179-180 (counts `usage` rows) | `count_question(state, visitor) -> int` 96-103, `questions_today(state, visitor)` 106-109 (a `questions` table) |
| `InFlight(per_key=2, total=8, estimate_usd=…)` with `start(key)`, `finish(key)`, `pending_usd(besides=0)` | 168-197, estimate 0.15 | 191-221, estimate 0.10 | 129-158, estimate 0.15 |
| `RateLimiter(per_minute)` with `allow(key) -> bool` | 200-220 | 224-244 | 161-181 |
| `cache_key(parts) -> str` | 225-226 (64 hex) | 249-250 (64 hex) | `api/app.py:157-158` (32 hex) |
| read the cache | `cached_events(state, key, hours)` 229-233 | 253-257 | `StateDB.cached(key, max_hours)` `api/state.py:95-101` |
| write the cache | `store_events(state, key, events, hours)` 236-241 | 260-265 | `StateDB.store_cached(key, events, max_hours)` `api/state.py:103-110` |
| `record_failure(state, kind, question, error)` | 253-258 | 268-274 | none |
| operator's reports | `alerts(state, usage_settings)` 261-282, `recent_failures` 285-289, `summary(state)` 388-401 | `summary(state, limits, now=None, days=7)` 282-301, `warnings(report, hours=24)` 304-318 | none |
| only in MPs | `mark_supporter` 123-128, `support_reminder_due` 131-137, `record_feedback` 246-250, `count_question(state, question)` 292-296 (a different function from Councils' of the same name), `popular_questions` 299-305, `record_visit` 308-321, `EVENTS`/`record_event` 325-338, `task_summary` 341-360, `visit_summary` 363-385 | | |
| only in Countries (in `usage.py`; Councils has them as `StateDB` methods) | | `StateDB` 49-74, `new_briefing_id` 323, `save_briefing` 327, `saved_briefing` 336, `withdraw_briefing` 347, `withdrawn_briefings` 353, `add_report` 361, `reports` 368, `close_report` 375 | |

**Landlords** has only `Limiter(per_minute=10)` with `allow(who) -> bool` (`api.py:222-238`), made once with the
default (`api.py:283`) and used on four routes (`api.py:305`, `330`, `381`, `404`). No cost, caps, visitors or cache.

Other callers of these functions outside the web app: MPs `topics.py:171-211` (`check_caps`, `record_usage` with kind
`"topic"`, `record_failure` with kind `"topic"`) and `evaluate.py:161`, `346`, `431`, `483` (`cost_usd`); Countries
`cli.py:254-279` (`wcs usage`: `summary`, `warnings`, exit 1 on any warning) and `update.py:470-487` (warnings added
to the update report).

### 1.2 Differences

Kinds: **(a)** a fix one copy has and others lack; **(b)** deliberate, the site's own; **(c)** incidental.

| # | What | MPs | Countries | Councils | Landlords | Kind, and which is best |
|---|---|---|---|---|---|---|
| 1 | `InFlight.start` for a refused visitor | `self.running[key]` on a `defaultdict` (`usage.py:181`): a visitor refused because the site is full is left behind as a key with 0 for ever | `self.running.get(key, 0)` (`usage.py:205`, comment "a refused visitor leaves nothing behind"); tested (`tests/test_api.py:287`, `flight.running == {}`) | as MPs (`usage.py:142`) | n/a | **(a)** Countries. The others grow by one entry per refused key until restart. Totals are unaffected |
| 2 | Default `estimate_usd` | 0.15 (`usage.py:173`, `api/app.py:343`) | 0.10 (`usage.py:197`, `api/app.py:367`, settings 104) | 0.15 (`usage.py:134`, `api/app.py:169`, settings 81) | n/a | **(b)** |
| 3 | Token counts in the SDK's own names | `token_counts` (31-44) normalises both forms; `record_usage` stores the normalised counts (101-108) | the same idea, written differently (87-103): `int()` everywhere, and `cache_read_tokens` is preferred when present even if 0 | `cost_usd` copes with both (31-39) but `record_usage` stores `input_tokens` as given (83): with the SDK's names the stored input leaves out cache writes. `usage.get("input_tokens", 0) - writes` (35) raises `TypeError` if the value is `None` | n/a | **(a)** MPs/Countries. In practice every caller passes `usage_dict`'s form, so the stored data is the same today. Countries' is the safest with `None` values (tested `tests/test_api.py:511`) |
| 4 | `record_usage` with no usage | writes a row of zeros (callers guard: `api/app.py:549`, `557`) | the same (callers guard: `api/app.py:563`, `566`) | returns 0.0 and writes nothing (`usage.py:78-79`); callers do not guard (`api/app.py:288`) | n/a | **(c)**; a shared function should write nothing when there is no usage |
| 5 | Argument order of `record_usage` | `user_id` second, `visitor` last | no `user_id`, `visitor` last | `visitor` second | n/a | **(c)** but every call site changes on adoption |
| 6 | Code fallback prices (when a key is missing from settings) | input 4.0, output 20.0, cache read 0.2, write multiplier 1.25 (53-60) | 4.0, 20.0, 0.2, 1.25 (112-118) | **2.0, 10.0**, 0.2, 1.25 (30-43) | n/a | **(b)/(c)**. MPs' tests rely on the 4.0 fallback with `{}` prices (`tests/test_api.py:203`, `278`). The fallback must be a parameter |
| 7 | Per-visitor daily limit: how counted | `usage` rows with `kind = 'answer'` for the visitor since midnight UTC (154-155) | the same (179-180) | a `questions` table, one row a visitor a day, incremented when a briefing finishes with usage (`usage.py:96-103`, `api/app.py:294`); earlier days deleted on each count | n/a | **(b)**. Same effect. Councils' needs no index on `usage.visitor` (it has none); MPs has `usage_visitor_at` |
| 8 | Signed-in users | `user_id` branch: `per_user_daily_questions` (148-152); visitor is `None` for a signed-in user (`api/app.py:418`) | none | none | n/a | **(b)** MPs only |
| 9 | Messages for caps | see 1.3: "budget" wording | the same as MPs' (no per-user message) | different: "limit … keeps its costs down" | n/a | **(b)**; tests match on words ("budget", "limit", "today's limit") |
| 10 | Month cap query | `at >= 'YYYY-MM'` (146, 160) | the same (176, 186) | `day >= 'YYYY-MM-01'` on the `day` column (`usage.py:124`) | n/a | **(c)** |
| 11 | `visitor_key`: a fixed day for tests | `day` argument (81) | `day` argument (140) | none (uses `today()`, 66) | n/a | **(c)**; keep the argument |
| 12 | `visitor_key`: old salts | also deletes the one un-dated key `visitor_salt` (92) | deletes dated ones only (149) | dated ones only (71) | n/a | **(b)** MPs once had a permanent salt (tested `tests/test_api.py:449-457`) |
| 13 | Where the visitor's address comes from | `request.client.host`; uvicorn `proxy_headers` when `--behind-proxy` (`api/app.py:418`, `cli.py:712-714`) | first entry of `X-Forwarded-For` read by the app when `behind_proxy`, on top of uvicorn `proxy_headers` (`api/app.py:387-392`, `cli.py:53-54`) | `request.client.host`; uvicorn `proxy_headers` (`api/app.py:195`, `cli.py:368-369`); comment: a header the visitor could set is never trusted | first entry of `X-Forwarded-For` read by the app; uvicorn's `proxy_headers` not used (`api.py:285-288`, `cli.py:137`) | **(b)/(a)?** Open question 4: the first entry is the client's only if the proxy overwrites the header |
| 14 | Rate-limit key | `user:<id>` or `visitor:<code>` (`api/app.py:419`); the same string is the `InFlight` key | the visitor code | the visitor code | SHA-256 of the address, first 16 hex (`api.py:230`) | **(b)** |
| 15 | `RateLimiter`: lock, forgetting idle keys | lock; over 50,000 keys, idle ones dropped (206-219) | the same (230-243) | lock; over **10,000** (178) | **no lock, never forgets a key** (`api.py:227-238`) | **(a)** for Landlords (ENGINE.md says so too). 10,000 against 50,000 is **(c)** |
| 16 | `RateLimiter` default | none: `requests_per_minute`, fallback 20 (`api/app.py:345`) | the same (`api/app.py:364`) | the same (`api/app.py:167`) | 10, fixed in code (`api.py:225`, `283`) | **(b)** |
| 17 | Second limiter | `hit_limiter = RateLimiter(120)` for page counts; over it the hit is dropped with 204, no error (`api/app.py:346`, `1910-1911`) | none | none | none | **(b)** |
| 18 | Cache key length | 64 hex | 64 hex | 32 hex (`api/app.py:158`) | n/a | **(c)**, but a shared function must give each site its own length or the existing cache is simply missed for a week (harmless) |
| 19 | Cache expiry test | SQL: `created_at >= since` (232) | the same (256) | Python: `age < max_hours` from the row's `at` (`api/state.py:100-101`) | n/a | **(c)**; the same but for the boundary second |
| 20 | Old cache rows deleted when a new one is stored | yes (239) | yes (263) | yes (`api/state.py:108`), tested (`tests/test_api.py:154`) | n/a | same |
| 21 | Failures kept | newest 500 (258) | newest 500 **and** 90 days (`FAILURE_DAYS`, 42, 273-274; "the privacy notice … says these are deleted after 90 days") | no failures table: a failed briefing is only logged (`api/app.py:306-307`) and a question the model could not read is dropped silently (`api/app.py:290`) | n/a | **(a)** Councils lacks it. Whether MPs needs the 90 days depends on its privacy notice (open question 6) |
| 22 | Operator's report | `summary` by user/visitor for the month, `alerts` at 50% (warning) and 80% (error) of a cap and for failures in 24 hours (261-282) | `summary` of today/month/by day/failures; `warnings` at 80% (`WARN_AT`, 279) and for failures in 24 hours | none | n/a | **(b)**: different shapes for different consumers (MPs' admin page; Countries' command line and update report) |
| 23 | `check_caps` connections | one connection for all the queries (147-160) | up to three (178, 184, 186 through `spent`) | up to three | n/a | **(c)** |
| 24 | Model the question-reading cost is priced as | `parse_model(settings)`: `query_parse_model`, else `model`, else `"claude-sonnet-5-5"` (`rag/query_parse.py:498-499`; `api/app.py:550`) | `settings.answer.get("query_parse_model")`, which may be `None` and then takes the base prices (`api/app.py:564`) | the same as Countries (`api/app.py:288`) | n/a | **(a)** small: MPs' is right when the key is unset |

### 1.3 Reader-visible strings and numbers

**Shared by MPs, Countries and Councils, word for word:**

| What | Text | Where |
|---|---|---|
| Per-minute limit, HTTP **429** (JSON `{"detail": …}`) | `Too many requests. Please wait a minute and try again.` | MPs `api/app.py:421`; Countries `api/app.py:394`; Councils `api/app.py:197` |
| Too many at once, this visitor | `A briefing is already being written for you; please wait for it to finish.` | MPs `usage.py:182`; Countries `usage.py:206`; Councils `usage.py:143` |
| Too many at once, the whole site | `Many briefings are being written at the moment; please try again in a minute.` | MPs `usage.py:184`; Countries `usage.py:208`; Councils `usage.py:145` |
| Suffix added to a cap or at-once reason, in the final event's `note` | `{reason} The sources found are shown below.` | MPs `api/app.py:537`, `592`, `597`; Countries `api/app.py:554`, `600`, `605`; Councils `api/app.py:281`, `326`, `331` |

The cap and at-once messages are never an HTTP error: they arrive inside a 200 stream, in `final.note`, after the
`plan` and `sources` events.

**Cap messages (differ):**

| Case | MPs (`usage.py`) | Countries (`usage.py`) | Councils (`usage.py`) |
|---|---|---|---|
| Signed-in user's daily limit | `You have reached today's question limit. It resets at midnight UTC.` (152) | none | none |
| Visitor's daily limit | `You have reached today's limit for new briefings. It resets at midnight UTC; briefings others have already asked for still load.` (157-158) | the same text (182-183) | `You have asked a lot of questions today, so new briefings are paused until tomorrow.` (116) |
| Daily spending cap | `Today's budget for new briefings has been used up. It resets at midnight UTC.` (162) | the same (185) | `The site has reached today's limit on new briefings, which keeps its costs down.` (123) |
| Monthly spending cap | `This month's budget for new briefings has been used up.` (164) | the same (187) | `The site has reached this month's limit on new briefings, which keeps its costs down.` (125) |

The same strings are shown on each status page as `briefings_note` (MPs `api/app.py:1926`, `1940`; Countries
`api/app.py:482-485`; Councils `api/app.py:233`, `245`), with `briefings` one of `"unavailable"`, `"paused"`,
`"available"`.

**Comparisons are `>=`** in every copy: a visitor with a limit of 40 gets 40 briefings; spending *equal to* the cap
stops briefings; a cap of 0 stops them all (used by tests: Countries `tests/test_api.py:96`, Councils
`tests/test_api.py:56`).

**Landlords' limiter messages** (all HTTP **429**):

| Route | Body | Where |
|---|---|---|
| `POST /api/corrections` | JSON `{"ok": false, "error": "too many reports; try again in a minute"}` | `api.py:306` |
| `POST /api/statements` | JSON `{"ok": false, "error": "too many tries; try again in a minute"}` | `api.py:331` |
| `POST /api/missed` | JSON `{"ok": false}` | `api.py:382` |
| the approval pages | an HTML page titled `Too many tries` with `<p>Try again in a minute.</p>` | `api.py:405` |

**Other limits in MPs that use the visitor code** (outside the briefing flow, listed because a shared limiter may be
asked to serve them): reports, 10 a visitor a day, HTTP 429 `Thank you, we have your reports. Please email us if
there is more to add.` (`api/reports.py:23`, `api/app.py:1831-1832`); statements, 5 a day, 429 `Thank you, we have
your statements. Please email us if there is more to add.` (`api/app.py:1849-1850`); sign-in, 5 failures per address
and email and 20 per address in 900 seconds, 429 `Too many failed sign-in attempts. Try again in 15 minutes.`
(`api/auth.py:83`, `api/app.py:339-340`, `431`).

**Default numbers** (file value; code fallback when the key is absent):

| Setting (`[usage]`) | MPs file / code | Countries file / code | Councils file / code |
|---|---|---|---|
| `requests_per_minute` | 20 / 20 | 20 / 20 | 20 / 20 |
| `per_visitor_daily_questions` | 40 / 40 | 40 / 40 | 30 / 30 |
| `per_user_daily_questions` | 60 / 60 | not read | not read |
| `daily_spend_cap_usd` | 10.0 / 10.0 | 3.0 / 3.0 | 3.0 / 3.0 |
| `monthly_spend_cap_usd` | 150.0 / 150.0 | 50.0 / 50.0 | 50.0 / 50.0 |
| `answer_cache_hours` | 168 / **24** (`api/app.py:347`) | 168 / 168 | 168 / 168 |
| briefings at once, per visitor | **absent** / 2, key `briefings_at_once_per_reader` (`api/app.py:342`) | 2 / 2, key `briefings_at_once_per_visitor` | 2 / 2, key `briefings_at_once_per_visitor` |
| `briefings_at_once` | absent / 8 | 8 / 8 | 8 / 8 |
| `briefing_estimate_usd` | absent / 0.15 | 0.10 / 0.10 | 0.15 / 0.15 |
| `support_reminder_every` | 10 / 10 (`api/app.py:561`) | not read | not read |
| `price_input_per_mtok` | 4.0 / 4.0 | 2.0 / 4.0 | 2.0 / 2.0 |
| `price_output_per_mtok` | 20.0 / 20.0 | 10.0 / 20.0 | 10.0 / 10.0 |
| `price_cache_read_per_mtok` | 0.2 / 0.2 | 0.2 / 0.2 | 0.2 / 0.2 |
| `cache_write_multiplier` | 1.25 / 1.25 | 1.25 / 1.25 | 1.25 / 1.25 |
| `[usage.models."claude-sonnet-5-5"]` | input 2.0, output 10.0, cache read 0.2 | none (the base prices are Sonnet's) | none (the same) |
| `[usage.models."claude-haiku-5-5"]` | input 0.1, output 0.5, cache read 0.01 | the same | the same |

Lines: MPs settings 120-148; Countries settings 93-116; Councils settings 72-93. Landlords has no `[usage]` section.

**How a price is chosen** (the same in all three): the first `[usage.models."<name>"]` whose name equals the model's
id or is a prefix of it is laid over the base prices; with no match, or no model, the base prices are used. So in
MPs any model that is not Sonnet or Haiku is priced at 4.0 and 20.0 (its settings call these Opus's, line 138), and
in Countries and Councils any model that is not Haiku is priced at 2.0 and 10.0. These are the sites' own figures
for spend tracking; this study did not check them against the provider's price list.

**The cost formula** (the same in all three; `input` here includes cache writes, as `rag/answer.usage_dict` gives
it): `(input - writes) / 1e6 × price_in + writes / 1e6 × price_in × multiplier + output / 1e6 × price_out + reads /
1e6 × price_cache_read`, rounded to 6 places.

**Fixed in code, not in settings:** the limiter's window, 60 seconds (an entry exactly 60 seconds old still counts:
`now - q[0] > 60`); the limiter forgets idle keys over 50,000 keys (MPs, Countries) or 10,000 (Councils); the
visitor code is 24 hex characters; the salt is `secrets.token_hex(16)`, kept in `kv` as `visitor_salt:YYYY-MM-DD`;
questions and errors in `failures` are cut to 500 characters; failures kept: 500 (MPs), 500 and 90 days (Countries);
MPs' page-count limiter, 120 a minute; Countries' warning threshold `WARN_AT = 0.8`; MPs' alert thresholds 0.5 and
0.8; Landlords' limiter, 10 a minute.

**Operator-only strings** (admin page, command line, update report; not shown to readers). MPs `alerts`
(`usage.py:270-281`): `{n} briefing{s} failed in the last 24 hours (latest: {kind}, {error}). See Recent failures.`
(level `error` from 3 failures, else `warning`); `Spending {today|this month} is ${spent:.2f}, {pct} of the
${cap:.0f} cap. New briefings pause at the cap.` (from 80%, `error`); the same without the last sentence (from 50%,
`warning`). Countries `warnings` (`usage.py:310-317`): `spending: {today's|this month's} cap of ${cap:.2f}
{reached: new briefings are paused | NN% used} (${spent:.2f} spent)`; `{n} briefing(s) failed in the last {hours}
hours; the latest: {error} (wcs usage lists them)`.

### 1.4 The stored data

See section 2.4: the tables are described once there, with the state database.

### 1.5 Tests

See section 4.

### 1.6 What a shared implementation must take as parameters

- **Prices:** the `[usage]` mapping as it is, plus the **fallback prices** (4.0/20.0 for MPs and Countries, 2.0/10.0
  for Councils). MPs' tests pass `{}` and expect 4.0.
- **Cap messages:** four strings a site (signed-in user, visitor, day, month), and the `InFlight` messages if a site
  ever wants its own.
- **Limits and their settings keys:** `per_visitor_daily_questions` fallback (40 or 30); MPs' extra
  `per_user_daily_questions`; the per-visitor at-once key name (`briefings_at_once_per_reader` in MPs,
  `briefings_at_once_per_visitor` elsewhere); `briefing_estimate_usd` fallback (0.15 or 0.10); `answer_cache_hours`
  fallback (24 in MPs' code, 168 elsewhere).
- **How the per-visitor count is kept:** from `usage` rows (MPs, Countries) or a `questions` table (Councils); a
  strategy, or a decision to move Councils to the first (its `usage` table has the `visitor` and `day` columns
  needed, but no index on `visitor`).
- **The store's shape:** the `usage` column list (with or without `id`, `user_id`, `day`), the cache's date column
  (`created_at` or `at`), whether there is a `failures` table, the failures' retention (500; 500 and 90 days).
- **Kinds:** `usage.kind` is `"parse"`, `"answer"` everywhere, plus `"interests"` and `"topic"` in MPs; `failures.kind`
  is `"question reading"`, `"briefing"`, plus `"topic"` in MPs. Only `"answer"` rows count towards the per-visitor
  limit; all rows count towards spending.
- **Cache key:** the digest length (64 or 32) and the parts (section 3.3).
- **The limiter:** requests a minute, and the size at which idle keys are dropped. Landlords needs the key hashed
  (or not: a hash of the address in memory adds nothing once the visitor code is used) and a default of 10.
- **The visitor's address:** who reads it (`request.client.host`, or the first `X-Forwarded-For` entry), decided by
  the site.
- **The legacy salt:** MPs' deletion of the un-dated `visitor_salt` key (harmless everywhere; keep it).

---

## 2. The state database

### 2.1 What it is, per site

| | MPs | Countries | Councils | Landlords |
|---|---|---|---|---|
| File | `data/state.sqlite` (`config.py:83-85`) | `data/state.db` (`api/app.py:362`) | `data/state.db` (`api/app.py:164`) | `data/state.db` (`api.py:282`) |
| Class | `StateDB(path)` `store/state.py:226` | `StateDB(path)` `api/usage.py:49` | `StateDB(path)` `api/state.py:64` | `State(path)` `api.py:66` |
| Schema | `SCHEMA` `store/state.py:18-212`, 20 tables | `SCHEMA` `api/usage.py:23-40`, 7 tables | `SCHEMA` `api/state.py:19-40`, 7 tables | `SCHEMA` `api.py:43-56`, 5 tables (lower-case SQL) |
| Who writes | the web app **and** the twice-daily sync, two processes (`store/state.py:3-5`); also `topics.py`, `ingest.py`, `cli.py` | the web app; the nightly update reads spending and clears old statement emails (`update.py:482-485`); command-line commands | the web app; command-line commands (`cli.py:242`) | the web app; `publish.py:120`, `133`; `cli.py:190`, `222`, `305`; `status.py:64` reads it with its own connection |
| What else is in it beyond usage | the ingest manifest, sync log, users, sessions, briefings, reports, statements, topics, featured, feedback, visit counts | briefings, reports, statements | briefings, reports, statements | reports, statements and their log, missed searches, approval links |

Public methods:

- **MPs** `StateDB`: `connect()` (248), `latest_record_date()` (258), `manifest()` (266), `upsert_manifest(row)`
  (270), `mark_indexed(keys)` (281), `mark_embedded(keys)` (288), `unembedded(newest_first=True)` (294),
  `unindexed()` (301), `start_run(kind) -> int` (308), `close_unfinished_runs() -> int` (313), `finish_run(run_id,
  stats, error=None)` (321), `runs(limit=20)` (326), `get(key, default=None)` (337), `set(key, value)` (342). Module:
  `utcnow()` (222), `MIGRATIONS` (215-219). Everything else (usage, cache, briefings, reports, statements, topics,
  auth) is functions in other modules that take the `StateDB` and write SQL through `state.connect()`.
- **Countries** `StateDB`: `connect()` (62), `get(key)` (71). **No `set`.** Module functions as in section 1.1.
- **Councils** `StateDB`: `connect()` (72), `get(key)` (84), `set(key, value)` (89), `cached`, `store_cached`,
  `new_briefing_id()` (static, 113), `save_briefing(bid, question, options, events)` (117), `briefing(bid)` (123),
  `withdraw_briefing(bid, reason)` (130), `add_report(kind, page, message, contact)` (137), `reports(open_only=True)`
  (143), `close_report(report_id)` (149), and the statements methods (156-240). Module: `utcnow()` (49), `today()`
  (53), `months_before(when, months)` (57).
- **Landlords** `State`: `connect()` (75), `add_report(page, message, email, kind="")` (78), `open_reports()` (85),
  `close_report(rid, outcome)` (91), `missed(query)` (98), `open_report_count()` (103), the statements methods
  (111-158), `add_approval(build, days) -> str` (161), `approval(token)` (173), `mark(token, field)` (182),
  `top_missed(days=28, limit=50)` (188). **No key-value table.**

### 2.2 Connection handling, migrations, key-value helpers

| | MPs | Countries | Councils | Landlords |
|---|---|---|---|---|
| Connection | one per thread, kept open for the thread's life (`threading.local`, `store/state.py:230`, `238-246`); `check_same_thread=False` | a new one for every `with state.connect()`, closed after (`api/usage.py:62-69`) | a new one each time, closed after (`api/state.py:72-81`) | a new one each time, **not closed**: `connect()` returns the raw connection and `with` on a `sqlite3.Connection` only commits or rolls back (`api.py:75-76`, `79`) |
| Lock | none (SQLite's own, WAL) | none | **one `threading.Lock` for the whole process, held for the whole `with` block** (`api/state.py:68`, `74`). Not re-entrant: a `connect()` inside a `connect()` on one thread would hang. No such nesting was found in the code read | none |
| Busy timeout | 30 s | 30 s | 30 s | 10 s |
| Row factory | `sqlite3.Row` (242) | none: plain tuples | `sqlite3.Row` (76) | none: plain tuples |
| Pragmas | `journal_mode=WAL`, `foreign_keys=ON`, on each new connection (243-244) | none | none | none |
| Commit and rollback | commit on leaving the block; **explicit rollback** on an exception (251-256) | commit on leaving; on an exception the connection is closed without commit | the same as Countries | commit or rollback by `sqlite3`'s own context manager |
| At start-up | `executescript(SCHEMA)`; then each `MIGRATIONS` column added if `PRAGMA table_info` lacks it: `usage.visitor TEXT`, `usage.cache_write_tokens INTEGER NOT NULL DEFAULT 0`, `reports.page TEXT`; then `CREATE INDEX IF NOT EXISTS usage_visitor_at ON usage(visitor, at)` (231-236) | `executescript(SCHEMA)`; then `usage.cache_write_tokens INTEGER DEFAULT 0` added if missing (56-60) | `executescript(SCHEMA)` only: **no migrations** (69-70) | `executescript(SCHEMA)`; then `reports.kind text` added if missing (70-73) |
| `kv` table | `key TEXT PRIMARY KEY, value TEXT NOT NULL` (41-44) | `key TEXT PRIMARY KEY, value TEXT` (28) | the same as Countries (20) | none |
| `get` | `get(key, default=None)`, reads `row[0]` (337-340) | `get(key)`, `row[0]` (71-74) | `get(key)`, `row["value"]` (84-87) | none |
| `set` | upsert (342-345) | **none** | upsert (89-92) | none |
| Keys kept in `kv` | `visitor_salt:<day>`; `supporter:<day>:<visitor>` (value `'1'`, earlier days deleted, `api/usage.py:119-128`); others may exist in modules not read | `visitor_salt:<day>` | `visitor_salt:<day>` | n/a |

Differences worth a decision:

| # | What | Kind | Best |
|---|---|---|---|
| 1 | MPs uses WAL and a connection per thread; the others open and close per call with the default journal | **(b)** for MPs (two writing processes); for the others **(c)** | MPs' for a shared store: WAL lets the nightly update and the web app write together. WAL is a property of the file, so turning it on for Countries or Councils is a one-way change that adds `-wal` and `-shm` files beside the database: backups already use `sqlite3`'s backup call (Countries `backup.py:29`, Councils `backup.py:28`, Landlords `cli.py:270`), which copes |
| 2 | Councils' process-wide lock | **(c)**: it makes every database call in the process wait its turn, including the cached-answer read on every question | drop it in a shared store (SQLite locks the file itself; the 30 s timeout covers contention) |
| 3 | Landlords never closes its connections | **(a)** missing: connections are left to the garbage collector | close after use |
| 4 | Explicit rollback | **(c)**: closing without commit rolls back too | either |
| 5 | Countries has no `kv.set`; Landlords no `kv` at all | **(c)** | give all four `get`/`set` |
| 6 | Each sse worker thread in MPs opens its own thread-local connection, since each briefing is worked out in a new thread (`api/app.py:317`); it is dropped with the thread | **(c)** | a shared store that opens per call avoids it; one that keeps a connection per thread must expect short-lived threads |

### 2.3 Rows or tuples

A shared store must choose one row type. What each site's code needs:

| Site | Type today | Code that needs **names** (`sqlite3.Row`) | Code that uses **positions or unpacking** (works with both) | Code or tests that need a real **tuple** |
|---|---|---|---|---|
| MPs | `Row` | `dict(r)`: `api/usage.py:289`, `api/briefings.py:107`, `124`, `api/reports.py:51`, `api/auth.py:51`, `71`, `store/state.py:331`; `r["…"]`: `api/briefings.py:93-96`, `api/reports.py:70-73`, `api/auth.py:46`, `store/state.py:268` | `[0]`: `api/usage.py:116`, `150`, `155`, `159-160`, `233`; unpacking: `api/usage.py:266`, `305`, `380-384`; `dict(rows)`: `350`, `369` | test: `tuple(con.execute(…).fetchone()) == (…)` (`tests/test_api.py:244`, `518`) converts first, so either works |
| Countries | tuple | none | `dict(zip(keys, row, strict=True))`: `api/usage.py:343`, `358`, `372`; unpacking: `290-299`; `row[0]`: `74`, `168`, `180`, `257`; `api/statements.py:183-185` (`row[0]`, `row[1]`) | tests compare a row with a tuple: `tests/test_api.py:516` (`row == (1500, 3000, 500)`), `532` (`fetchone() == (0, 0.5)`). A `sqlite3.Row` is not equal to a tuple, so these tests fail with `Row` unless changed |
| Councils | `Row` | `row["c"]` `api/usage.py:93`; `["n"]` `103`, `109`; `row["value"]` `api/state.py:87`; `row["at"]`, `row["events"]` `100-101`; `dict(row)`, `dict(r)` with `SELECT *`: `125-128`, `145-147`, `169-170`, `175-178`, `193`; `row["status"]`, `row["log"]` `198-201` | tests: `r[0]` | none |
| Landlords | tuple | none | `dict(zip(STATEMENT_FIELDS, r, strict=True))` `api.py:127`; unpacking in callers: `cli.py:225` (`for at, action, note in …`), `305`; `status.py:70` (`for (build,) in rows`); `row[2]` `api.py:178` | `open_reports()` and `statement_log()` return lists of tuples to callers; a test unpacks one (`tests/test_api.py:37`), which works with `Row` |

`sqlite3.Row` satisfies every site's code; only Countries' two tuple comparisons in tests need rewriting.

**`SELECT *` and column order.** `SELECT *` is used with names only (MPs `api/briefings.py:104`, `api/auth.py:41`,
`68`; Councils `api/state.py:125`, `145`, `169`, `175`; Countries `api/statements.py:147`, `156`, read with the
cursor's column names), so order does not matter there. **The one place that relies on column order** is Councils'
`INSERT INTO usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)` (`api/usage.py:82`): ten values in the order `at, day,
visitor, kind, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd`. Adding a column
to that table, or creating it in another order, breaks every write. A shared store must name the columns.

### 2.4 The stored data, table by table

Types and defaults are quoted from each `SCHEMA`. "—" means the site has no such table.

**`usage`** (one row a model call)

| Column | MPs (`store/state.py:59-70`, `216-217`) | Countries (`api/usage.py:24-26`) | Councils (`api/state.py:21-24`) |
|---|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | `INTEGER PRIMARY KEY` | **none** (rowid only) |
| `user_id` | `INTEGER` | none | none |
| `at` | `TEXT NOT NULL` | `TEXT` | `TEXT NOT NULL` |
| `day` | none | none | `TEXT NOT NULL` (`YYYY-MM-DD`, UTC) |
| `visitor` | `TEXT`, **added by migration**, so it is the last column of a new database | `TEXT` (second column) | `TEXT` (third) |
| `kind` | `TEXT NOT NULL` | `TEXT` | `TEXT NOT NULL` |
| `model` | `TEXT` | `TEXT` | `TEXT` |
| `input_tokens` | `INTEGER NOT NULL DEFAULT 0` | `INTEGER` | `INTEGER` |
| `output_tokens` | `INTEGER NOT NULL DEFAULT 0` | `INTEGER` | `INTEGER` |
| `cache_read_tokens` | `INTEGER NOT NULL DEFAULT 0` | `INTEGER` | `INTEGER` |
| `cache_write_tokens` | `INTEGER NOT NULL DEFAULT 0` (in `SCHEMA` and in `MIGRATIONS`) | `INTEGER DEFAULT 0`, **last column** in `SCHEMA` and when migrated | `INTEGER` (no default) |
| `cost_usd` | `REAL NOT NULL DEFAULT 0` | `REAL` | `REAL NOT NULL` |
| Indexes | `usage_user_at (user_id, at)`, `usage_visitor_at (visitor, at)` | `usage_at (at)` | `usage_day (day)` |

Column order on a live server depends on when the database was made:

- MPs, new: `id, user_id, at, kind, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
  cost_usd, visitor`. MPs, made before cache writes were recorded (the shape in `tests/test_api.py:530-533`): `…,
  cache_read_tokens, cost_usd, visitor, cache_write_tokens`. All MPs code names its columns (`api/usage.py:104-106`).
- Countries: `id, visitor, at, kind, model, input_tokens, output_tokens, cache_read_tokens, cost_usd,
  cache_write_tokens` either way (the schema was written to match a migrated database). Named inserts
  (`api/usage.py:159-160`).
- Councils: as its `SCHEMA`; positional insert (above). **If the live Councils database was created before
  `cache_write_tokens` was in the schema, its table has nine columns and every insert fails; there is no migration.**
  Not checked: see open question 1.

Meaning of `input_tokens`: in all three, as written through `usage_dict`, it **includes cache writes** (MPs
`rag/answer.py:61`, Countries `rag/answer.py:68-78`, Councils `rag/answer.py:68`). Rows written before cache writes
were recorded have `cache_write_tokens` 0 (MPs, Countries) and cannot be told apart.

`at` is `datetime.now(UTC).isoformat(timespec="seconds")`, for example `2026-11-12T09:30:00+00:00`, in all three.
Day and month sums compare this text with `YYYY-MM-DD` or `YYYY-MM` (MPs, Countries) or use `day` (Councils).

**`answer_cache`**

| Column | MPs (`store/state.py:72-76`) | Countries (`api/usage.py:29`) | Councils (`api/state.py:28`) |
|---|---|---|---|
| `key` | `TEXT PRIMARY KEY` (64 hex) | `TEXT PRIMARY KEY` (64 hex) | `TEXT PRIMARY KEY` (32 hex) |
| date | `created_at TEXT NOT NULL` | `created_at TEXT` | **`at`** `TEXT NOT NULL` |
| `events` | `TEXT NOT NULL` (JSON list) | `TEXT` | `TEXT NOT NULL` |

A cache can be thrown away at any release (it only costs rewrites), so a shared store may rename `at` to
`created_at` for Councils by recreating the table.

**`failures`**: MPs `id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, question TEXT, error
TEXT NOT NULL` (`store/state.py:160-166`); Countries `id INTEGER PRIMARY KEY, at TEXT, kind TEXT, question TEXT,
error TEXT` (`api/usage.py:30`); Councils and Landlords —.

**`questions`** (Councils only, `api/state.py:26-27`): `day TEXT NOT NULL, visitor TEXT NOT NULL, n INTEGER NOT NULL,
PRIMARY KEY (day, visitor)`. Only today's rows are kept.

**`briefings`**

| Column | MPs (`store/state.py:78-89`) | Countries (`api/usage.py:31-32`) | Councils (`api/state.py:29-31`) |
|---|---|---|---|
| `id` | `TEXT PRIMARY KEY`; 10 characters from `abcdefghijkmnpqrstuvwxyz23456789`; pattern `^[a-km-z2-9]{10}$` (`api/briefings.py:25-26`); five tries on a clash (38-49) | `TEXT PRIMARY KEY`; `secrets.token_urlsafe(8)`, 11 characters (`api/usage.py:323-324`); the page route accepts `[A-Za-z0-9_-]{6,20}` (`api/app.py:662`); no retry | the same as Countries (`api/state.py:113-115`); no pattern check on the API |
| when | `created_at TEXT NOT NULL` | `at TEXT NOT NULL` | `at TEXT NOT NULL` |
| `question` | `TEXT NOT NULL` | `TEXT NOT NULL` | `TEXT NOT NULL` |
| the request's options | `settings TEXT NOT NULL` (JSON) | `options TEXT NOT NULL` (JSON) | `options TEXT NOT NULL` (JSON) |
| `events` | `TEXT NOT NULL` (JSON) | the same | the same |
| `records_up_to` | `TEXT` | none | none |
| `model` | `TEXT` | none | none |
| `withdrawn_at`, `withdrawn_reason` | `TEXT`, `TEXT` | the same | the same |
| Index | `briefings_created (created_at)` | none | none |

What `events` holds differs by site: section 3.4. These rows are the record of what each site published (MPs
`api/briefings.py:3-6`) and must be kept and readable for ever.

**`reports`**

| Column | MPs (`store/state.py:93-107`) | Countries (`api/usage.py:33-34`) | Councils (`api/state.py:32-34`) | Landlords (`api.py:44-45`, `72-73`) |
|---|---|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | the same | the same | `integer primary key` (no autoincrement) |
| `at` | `TEXT NOT NULL` | the same | the same | `text not null` |
| `kind` | `TEXT NOT NULL`: `correction`, `complaint`, `takedown`, `general` (`api/app.py:169`) | `TEXT NOT NULL`: `error`, `unfair`, `problem`, `takedown`, `other`; default `error` (`api/app.py:123`) | `TEXT NOT NULL`: `error`, `unfair`, `takedown`, `other`; default `error` (`api/app.py:74`) | `text`, nullable, **added by migration (last column)**: `wrong`, `unfair`, `takedown`, `other`, or null; aliases `correction`/`error`/`mistake` → `wrong`, `complaint` → `unfair`, `general` → `other` (`api.py:39-42`) |
| `briefing_id` | `TEXT` | none | none | none |
| `page` | `TEXT` (in `SCHEMA` and `MIGRATIONS`) | `TEXT` | `TEXT` | `text` |
| `message` | `TEXT NOT NULL` | the same | the same | `text not null` |
| contact | `contact TEXT`; set to `NULL` on closing (`api/reports.py:57-58`) | `contact TEXT`; set to `''` on closing (`api/usage.py:378`) | `contact TEXT`; set to `''` (`api/state.py:152`) | **`email`** `text`; set to `null` on closing (`api.py:94`) |
| `visitor` | `TEXT`; set to `NULL` on closing | none | none | none |
| `status` | `TEXT NOT NULL DEFAULT 'open'`; `resolved`, `dismissed` | none (open means `closed_at IS NULL`) | none | none |
| `closed_at` | `TEXT` | `TEXT` | `TEXT` | `text` |
| outcome | `resolution TEXT` (private), `public_note TEXT` (shown on the corrections page) | none | none | `outcome text` |
| Index | `reports_status (status, at)` | none | none | none |

**`statements`** (the right of reply; the four are four different designs)

| | MPs (`store/state.py:111-130`) | Countries (`api/usage.py:35-39`) | Councils (`api/state.py:35-39`) | Landlords (`api.py:46-51`) |
|---|---|---|---|---|
| Columns | `id` (autoincrement), `at`, `name`, `role`, `item_path`, `person INTEGER`, `text`, `link`, `email`, `visitor`, `status DEFAULT 'pending'`, `published_at`, `updated_at`, `closed_at`, `reason`, `checked` | `id` (autoincrement), `at`, `page`, `country`, `name`, `role`, `text`, `link NOT NULL DEFAULT ''`, `email NOT NULL DEFAULT ''`, `status DEFAULT 'pending'`, `shown_on`, `ended_at`, `reason`, `log NOT NULL DEFAULT '[]'` | the same as Countries with `council` in place of `country` | `id`, `at`, `name`, `role`, `page`, `part not null default ''`, `text`, `link`, `email`, `status default 'pending'`, `landlord`, `checked`, `reason`, `published_at`, `updated_at`, `closed_at` |
| The log of decisions | none in the table | JSON in the `log` column | JSON in the `log` column | a table, `statement_log (id, statement, at, action, note)` |
| Email forgotten after three months | set to `NULL`, with `visitor` (`api/statements.py:145`) | set to `''` (`api/statements.py:226`) | set to `''` (`api/state.py:239`) | set to `null` (`api.py:153`) |
| Indexes | `statements_item (status, item_path)`, `statements_person (status, person)` | `statements_page (status, page)` | `statements_page (status, page)` | none |

Countries' and Councils' differ only in the name of one column (`country`, `council`). The `statements.py` modules
were not read in full: this table is from the schemas and the SQL in them.

**Tables only one site has**

| Site | Tables |
|---|---|
| MPs | `manifest (source, key, revision, file_name, size, mtime_ns, rows, parsed_at, indexed_at, embedded_at; PK source, key)` 19-31; `sync_log (run_id AUTOINCREMENT, kind, started_at, finished_at, status DEFAULT 'running', stats, error)` 32-40; `users (user_id AUTOINCREMENT, email UNIQUE, password_hash, is_admin DEFAULT 0, created_at, disabled DEFAULT 0)` 45-52; `sessions (token_hash PK, user_id REFERENCES users, created_at, expires_at)` 53-58; `question_counts (day, question, n; PK day, question)` 132-137; `topic_versions (slug, briefing_id, prepared_at, records_up_to; PK slug, briefing_id)` 139-145; `topic_checks (slug PK, checked_at, outcome)` 147-151; `featured (briefing_id PK, title, blurb, featured_at)` 153-158; `feedback (id AUTOINCREMENT, at, briefing_key, question, useful INTEGER, visitor)` 167-174; `page_views (day, path, views DEFAULT 0; PK day, path)` 177-182; `referrers (day, host, views DEFAULT 0; PK day, host)` 183-188; `day_visitors (day, visitor; PK both)` 189-193; `day_totals (day PK, visitors)` 194-197; `day_events (day, event, visitor; PK all three)` 200-205; `event_totals (day, event, visitors; PK day, event)` 206-211 |
| Councils | `questions` (above) |
| Landlords | `statement_log` (above); `missed (day, query, count default 0; primary key day, query)` 52-53; `approvals (token_hash primary key, build, created, expires, published_at, rolled_back_at)` 54-55 |

In MPs, `sync_log.run_id` is part of the answer cache's key (section 3.3), so the briefing flow depends on the sync
log.

**Reading every site's existing database without losing data.** A shared store should (1) create only the tables a
site asks for, with that site's column list, and never alter or drop a table it did not create in that shape;
(2) keep each site's migrations and run them the same way (`PRAGMA table_info`, then `ALTER TABLE … ADD COLUMN`);
(3) name columns in every insert; (4) leave `briefings`, `reports`, `statements`, `feedback`, `users`, `sessions`,
`manifest`, `sync_log`, `approvals` and the count tables exactly as they are, since their rows cannot be rebuilt;
(5) treat `answer_cache`, `questions`, `day_visitors`, `day_events` and the `kv` salts as disposable. Unifying the
`usage` table (adding `id`, `user_id`, `day` where missing) is possible by `ALTER TABLE` for nullable columns only;
Councils' missing `id` would need the table rebuilt.

### 2.5 What a shared store must take as parameters

The file's path and name (`state.sqlite` or `state.db`); the schema for the site (tables and columns as above) and
its list of migrations; whether to use WAL (MPs must; the others may); the busy timeout (30 s, or Landlords' 10 s);
the row type (`sqlite3.Row` serves all); table and column names where they differ (`answer_cache.at` or
`created_at`; `briefings.at`/`options` or `created_at`/`settings`; `reports.contact` or `email`); whether there is a
`kv` table (Landlords has none; adding one is harmless).

---

## 3. The briefing stream

### 3.1 `sse()`

`sse(events: Iterator[dict], keep_alive: float = KEEP_ALIVE_SECONDS) -> Iterator[bytes]`, with `KEEP_ALIVE_SECONDS =
15` in all three (MPs `api/app.py:293`, `296-331`; Countries `94`, `140-176`; Councils `49`, `92-126`). The code is
identical.

- The events are worked out in a new daemon thread named `sse`, which puts each on a queue.
- The response thread takes from the queue and writes `event: {type}\ndata: {json}\n\n`, with `json.dumps(ev,
  default=str)` (so dates become text). After 15 seconds with nothing to send it writes the comment line `: still
  working\n\n`.
- An exception in the events is put on the queue and raised in the response thread: the connection is cut, with no
  `error` event. (Errors while the briefing is written never get this far: the route catches them, 3.2 step 9.)
- When the response generator is closed (the reader has gone), `gone` is set; the worker stops **after the next
  event it produces** and calls `events.close()` in its own thread. That raises `GeneratorExit` down through the
  route's generators and the pipeline to the model client's `with … stream` block, which closes the model's stream.
  During a long silence from the model the worker does not notice until the next event arrives.
- The response is `StreamingResponse(sse(guarded()), media_type="text/event-stream", headers={"Cache-Control":
  "no-cache", "X-Accel-Buffering": "no"})` in all three (MPs `api/app.py:603-604`; Countries `611-612`; Councils
  `337-338`).

No site sends a `done` event: the stream simply ends after `final` or `error`.

### 3.2 The request flow, in order

`POST /api/ask`: MPs `api/app.py:498-604`; Countries `api/app.py:533-612`; Councils `api/app.py:249-338`. Steps 1 to
7 run before the response starts, so their errors are real HTTP statuses. From step 8 everything is inside a 200
stream.

| Step | MPs | Countries | Councils |
|---|---|---|---|
| 1. Body checked (HTTP **422** on failure) | `AskBody` (249-274): `question` 3 to 2,000 characters; `mode` `summary`\|`comprehensive`; `recency` 0 to 1; `role_weight` 1 to 2; `scope` six booleans; `plan` at most 20,000 characters as JSON (`the search plan is too large`); `history` at most 10 items, each part cut to 2,000/1,000/500/1,000 characters (230-245); `sources_only`; `follows` at most 2,000; `compare` at most 3 sides, trimmed | `AskBody` (108-115): `question` 3 to 500; `mode`; `plan` (no size limit); `recency`; `role_weight`; `history` at most 4 `Turn`s (`question` ≤ 500, `answer` ≤ 4,000); `sources_only` | `AskBody` (62-67): `question` 3 to 500; `mode`; `plan` (no size limit); `history` at most 6 items of `dict[str, str]`, **no limit on their length**; `sources_only` |
| 2. Sign-in | `current_user`: HTTP **401** `Please sign in.` when `[auth] required` (402-406) | none | none |
| 3. Visitor code, then rate limit (HTTP **429**) | `requester` (416-422): code is `None` for a signed-in user | `visitor` (387-395) | `visitor` (191-198) |
| 4. Counting before anything else | `count_question` (the question's text, per day), `record_event "ask"`, and `"follow_up"` if there is history (513-516): on every request, cached or not | none | none |
| 5. Cache key made | only if a model is available and `cache_hours > 0` (508-512) | only if a model is available, `cache_hours > 0` **and there is no history** (539-542) | always (255-256) |
| 6. Cache looked up | if there is a key and not `sources_only` (517) | the same (543) | if a model is available and not `sources_only` (257) |
| 7. First caps check | `check_caps(state, uid, settings.usage, visitor)` if a model is available, no hit, not `sources_only` (518-519) | `check_caps(state, limits, who)`, same conditions (544) | `blocked(state, v, usage_cfg)`, same conditions (258) |
| 8. `guarded()`: reserve a place | skipped for a hit, `sources_only`, a first-check refusal or no model. Else `inflight.start(who)`; refused → the sources with the reason; then caps again with `inflight.pending_usd(besides=1)`; refused → the sources with the reason; `finally: inflight.finish(who)` (584-601) | the same (592-609) | the same (317-335) |
| 9. `events()` | see below | | |

**`events()`, case by case:**

| Case | MPs | Countries | Councils |
|---|---|---|---|
| Cache hit | interests cleaned (`without_public_office`); a hit saved before shareable addresses gets a briefing saved now and the cache row rewritten, **which restarts its age** (522-531); events replayed **as stored, not rechecked** | replayed through `rechecked()`: flags and loaded words judged again by today's rules, quotes curled (547-549, 272-278) | replayed through `rechecked()` (273-275, 149-154) |
| `sources_only` | question read **by the model if the site's own budget is not used up**, else by the built-in rules; parse usage and a parse failure recorded (532-535, 606-645) | question read by the built-in rules: no model call, no cost (550-552, 502-520) | question read **by the model whenever there is one, with no caps check**; parse usage recorded (276-279, 260-270, `free=False`) |
| Refused by a cap or by `InFlight` | as `sources_only` above: the model still reads the question while the site's budget lasts, even for a visitor over their own limit (536-538, 642) | built-in rules, free | built-in rules, free (`free=True`, 261-262) |
| Written | loop over `p.run(req)` (543-571) | (559-579) | (286-305) |
| – question could not be read by the model (`parse_error` on the plan) | `record_failure("question reading", …)`; the field is removed before sending (544-546) | the same (561-562) | the field is removed; **nothing recorded** (290) |
| – parse usage | `record_usage(uid, "parse", parse_model(settings), …)` (549-551) | `record_usage("parse", query_parse_model, …)` (563-565) | the same, unguarded (288-289) |
| – `error` event from the pipeline (the model declined) | `record_failure("briefing", question, message)` (547-548); the refused call's tokens are **not** recorded | the pipeline has no such event | the pipeline has no such event |
| – `final`: usage | `interests_usage` recorded as kind `"interests"` and removed (552-556); `usage` recorded as `"answer"` (557-558); the support reminder worked out (559-561) | `usage` recorded as `"answer"` (566-567) | `usage` recorded as `"answer"`, then `count_question(state, v)` (292-294); `usage` removed from the event (295) |
| – `final`: saved as a briefing, if there is an answer and it is not "no records" | `keep_briefing` → `briefings.keep` (564-565, 655-656; `api/briefings.py:52-59`); adds `briefing_id`, `prepared_at`, `records_up_to` | `save_briefing`; adds `briefing_id` (568-574) | `state.save_briefing`; adds `briefing_id` (296-300) |
| – `final`: other additions | `briefing_key` (the cache key) when there is one (562-563); `support_reminder` on this reader's copy only (571) | none | none |
| – an exception while writing | `log.exception`; `record_failure("briefing", question, "{Type}: {message}")`; an `error` event (572-577) | the same (580-585) | `log.exception`; an `error` event; **nothing recorded** (306-310) |
| After the last event: cached, if there is a key, the last kept event is a `final` and it has an answer | `store_events` (578-582) | (586-590) | `state.store_cached` (311-315) |

Things that follow from the code and are the same in all three:

- **A "no records" answer is cached but not saved** as a briefing; it has no usage, so it does not count towards
  the visitor's limit (the question-reading call is still recorded, as `"parse"`).
- **Without an API key** the pipeline sends `plan`, `sources` and a `final` with `answer: null` and a note; nothing
  is cached or saved.
- **When the reader leaves part-way**: the model's stream is closed, the `InFlight` place is released (`finally`),
  and **no answer usage is recorded** (it is only known from the model's final message), no briefing is saved and
  nothing is cached. The question-reading usage has already been recorded. The tokens written before the stream
  closed are spent but appear nowhere in `usage`.
- **When writing fails part-way**: the same, plus the `error` event; the answer's tokens are not recorded.
- The caps are checked twice (step 7 and step 8), the second time counting the others in progress at the estimate.
- An exception in the sources-only path (the search itself failing) is not caught by the route: `sse()` raises it
  and the connection is cut.

**Feedback.** Only MPs: `POST /api/feedback` (`api/app.py:1820-1824`), body `FeedbackBody` (160-163: `question` 1 to
2,000, `useful` boolean, `briefing_key` at most 128); it passes the rate limiter, then `record_feedback` writes
`question[:500]`, `useful` and the visitor code (`api/usage.py:246-250`); the reply is `{"ok": true}`. The
`briefing_key` is the cache key sent on `final`. Countries and Councils have no feedback route or table.

**Other routes that use the same pieces.** Status: `check_caps`/`site_paused` without a visitor (MPs
`api/app.py:1926`; Countries `482`, remembered for 60 seconds, `486`; Councils `233`). Search (`POST /api/search`):
rate-limited, never calls the model (MPs `647-653`; Countries `522-531`; Councils `340-348`). MPs' topic refresh
(`topics.py:138-224`) runs the same pipeline outside the web app with `check_caps(state, None, …)`, kind `"topic"`.

### 3.3 The cache key, part by part

`sha256(json.dumps(parts, sort_keys=True, default=str))`.

| Part | MPs (`api/app.py:510-512`) | Countries (`api/app.py:540-542`) | Councils (`api/app.py:254-256`) |
|---|---|---|---|
| `q` | the question, lower-cased, runs of white space made one space | the same | the same |
| `mode` | yes | yes | yes |
| `plan` | yes | yes | yes |
| `recency` | yes | yes | not in the body |
| `role_weight` | yes | yes | not in the body |
| `scope` | `{written, pbc, votes, edms, devolved, evidence}` | not in the body | not in the body |
| `history` | yes: the list of `{question, answer, topic, scope}` | present but always `[]` (no key is made for a follow-up) | yes: the list as sent |
| `sources_only` | present, always `false` when used | the same | the same |
| `follows` | yes | not in the body | not in the body |
| `compare` | yes | not in the body | not in the body |
| `model` | `[answer] model` | `[answer] model` | `[answer] model` |
| data stamp | `data`: the newest `sync_log.run_id`, of any kind and status, or `None` (509-511) | `data`: the modification time of `index/state.json` as whole seconds, or `"none"` (300-303) | `data`: the newest modification time among `parquet/meetings/*.parquet`, a float, or 0.0 (`api/data.py:172-175`) |
| instructions | `instructions`: 12 hex of a SHA-256 of the answer prompt, the mode and grouping instructions and the question-reading prompt, worked out at import (130-133) | `instructions`: the constant `INSTRUCTIONS_VERSION = 3`, raised by hand (96) | **`v`**: the constant `INSTRUCTIONS_VERSION = "2"` (51) |
| Digest | 64 hex | 64 hex | 32 hex |

Differences: MPs' automatic instructions hash is a **(a)** over the hand-raised constants (it cannot be forgotten);
follow-ups are cached in MPs and Councils and not in Countries **(b)/(c)**; the data stamps are each site's own
**(b)**; MPs' stamp changes when a sync *starts*, even one that then fails **(c)**.

### 3.4 The events

**From the model client** (`Answerer._run`; the same code in all three: MPs `rag/answer.py:129-153`, Countries
`136-160`, Councils `135-159`):

| Event | Fields |
|---|---|
| `text` | `text` (a piece as it arrives) |
| `citation` | `search_result_index`, `cited_text` |
| `final` | `blocks` (each `{text, citations: [{type, cited_text, search_result_index, source}]}`), `stop_reason`, `model`, `usage` (`{input_tokens, output_tokens, cache_read_tokens, cache_write_tokens}`, input including cache writes) |

The client's `final` never leaves the pipeline: the pipeline verifies it and sends its own.

**From the pipeline** (`Pipeline.run`: MPs `rag/pipeline.py:584-653`; Countries `122-160`; Councils `113-150`):

| Event | MPs | Countries | Councils |
|---|---|---|---|
| `progress` | `{step: "reading", passages}` first of all (586); `{step: "checking"}` after the writing (637) | none | none |
| `plan` | `{plan, usage}` and `parse_error` if the model could not read the question (588-591) | the same, with the plan's interpretation in curly quotes (124-127) | the same as MPs, no curling (115-118) |
| `sources` | `{sources, candidates, semantic, evidence}`; `evidence` also has `devolution`, `edms`, `devolved`, `committee_evidence` (597-602) | `evidence` also has `votes` (129-130) | `evidence` as the search gave it (120-121) |
| `text`, `citation` | passed on | passed on | passed on |
| `interests` | `{interests}` when the register check finds something, during or after the writing (630-633, 638-641) | none | none |
| `error` | `{message: "The model declined to answer this question."}` when there is no final message or `stop_reason == "refusal"`; the run ends there (634-636) | none: no final message raises `RuntimeError("the model returned no answer")` (151-152); a refusal with a final message is verified and sent like any answer | the same as Countries (142-143) |
| `final`, no records | `{answer: {segments: [one, status "connective"], markdown: "No records found.", no_records: true, citations_total: 0, citations_invalid: 0, grounded_ratio: 1.0, unsupported_segments: 0}, usage: null}` (604-609) | the same without `unsupported_segments` (131-136) | the same as Countries (122-127) |
| `final`, no API key | `{answer: null, usage: null, note}` (610-613) | (137-140) | (128-131) |
| `final`, written | `{answer, usage, model, stop_reason, interests, interests_usage}` (651-653) | `{answer, usage, model, stop_reason}`, answer curled (159-160) | `{answer, usage, model, stop_reason}` (149-150) |

`answer` is `Verification.to_dict()`: `segments` (each `{text, sources, cited, status, loaded, misquotes}`),
`markdown`, `no_records`, `citations_total`, `citations_invalid`, `grounded_ratio`, `unsupported_segments`,
`loaded_words`, `quotes_total`, `quotes_unverified` (`rag/verify.py:43-45`, `73-85`, the same in all three).

**Where the checks run** (after the model's stream has ended, before the pipeline's `final`; the same order in all
three): `verify(final["blocks"], sources)`, `drop_preambles`, `britishise_segments`, `flag_loaded` (the
loaded-words check, each site's own word list in `rag/neutral.py`), `check_quotes` (MPs `rag/pipeline.py:644-648`;
Countries `153-157`; Councils `144-148`). Countries then curls quotes, last (`158-159`). Countries and Councils
write `"loaded_words": loaded` over the same number `to_dict()` already gives; MPs does not: no difference in the
result. The text events the reader saw while it was written are unchecked; the `final` replaces them.

**Notes and error texts in the stream:**

| What | MPs | Countries | Councils |
|---|---|---|---|
| No records (the one segment's text) | `No records found. The archive contains no records matching this question and these filters.` (`rag/pipeline.py:605-606`) | the same (`rag/pipeline.py:132-133`) | `No records found. The minutes contain no records matching this question and these filters.` (`rag/pipeline.py:123-124`) |
| No API key (`final.note`) | `Showing the evidence set only (no Anthropic API key on the server).` (612) | `Showing the evidence only (no Anthropic API key set).` (139) | `Showing the evidence only (no Anthropic API key set).` (130) |
| Sources only (`final.note`) | `Sources only: no briefing was written. Ask again without 'Sources only' for a written briefing.` (`api/app.py:533-534`) | `Sources only: no briefing was written.` (`api/app.py:551`) | as MPs (`api/app.py:277-278`) |
| Writing failed (`error.message`) | `The briefing could not be written just now. The sources found are shown above; please try again later.` (`api/app.py:575-576`) | the same (`api/app.py:583-584`) | `The briefing could not be written just now. Any sources found are shown above; please try again later.` (`api/app.py:308-309`) |
| The model declined (`error.message`) | `The model declined to answer this question.` (`rag/pipeline.py:635`) | none | none |

**Saved briefings' HTTP texts:** 404 `There is no briefing at this address.` in all three (MPs `api/app.py:662`;
Countries `414`; Councils `354`). 410: MPs `This briefing has been withdrawn.` (664, no reason shown); Countries
`This briefing has been withdrawn: {reason}` (416); Councils `This briefing has been withdrawn: {reason}`, or `This
briefing has been withdrawn.` when the reason is empty (356-357).

**What the browser receives, what is cached, what is saved:**

| | MPs | Countries | Councils |
|---|---|---|---|
| `progress` to the browser | yes | — | — |
| `plan` to the browser | `{plan, usage}` (the question-reading token counts are sent) | `{plan, usage}` | `{plan}`: `usage` and `parse_error` removed (`api/app.py:290`) |
| `sources`, `text`, `citation` | as the pipeline sent them | the same | the same |
| `interests` | yes | — | — |
| `final` to the browser, written | `answer`, `usage`, `model`, `stop_reason`, `interests`; `briefing_key` (if cached at all); `briefing_id`, `prepared_at`, `records_up_to` (if saved); `support_reminder` (a count, this reader only) | `answer`, `usage`, `model`, `stop_reason`; `briefing_id` | `answer`, `model`, `stop_reason`; `briefing_id`. **No `usage`** (tested `tests/test_api.py:43`) |
| `final` to the browser, sources only | `{answer: null, usage: null, note}` | the same | the same (here `usage: null` is present, as is `plan.usage: null`) |
| `error` | `{message}` | `{message}` | `{message}` |
| Kept while streaming (`kept`) | every event but `text`, so also `progress`, `citation`, `interests`, `error` (566-569) | every event but `text` and `citation` (575-578) | every event but `text` (301-304) |
| **Cached** | `[plan, sources, {type: "text", text: whole text}, final + {usage: null, cached: true}]` (580-582); the `plan` keeps its `usage`; the `final` keeps `briefing_key`, `briefing_id`, `prepared_at`, `records_up_to`, `interests`; never `support_reminder` | the same four; `final + {usage: null, cached: true}` with `briefing_id` (588-590) | the same four; `final + {cached: true}`, no `usage` key (313-315) |
| A cached answer as replayed | `plan`, `sources`, `text`, `final` (tested `tests/test_api.py:182`); no `progress`, no `citation` | the same, rechecked | the same, rechecked |
| **Saved** (`briefings.events`) | `[plan, sources, final]` with `usage`, `briefing_key`, `support_reminder` removed from the final; **no `text` event**, no `briefing_id` in the final (`api/briefings.py:56-58`); also the columns `records_up_to`, `model` | `[plan, sources, text, final + {usage: null}]` with `briefing_id` in the final (571-574) | `[plan, sources, text, final]` with `briefing_id`, no `usage` (297-300) |
| Saved options | `body.model_dump(exclude={"question", "history"})` → `settings` (656) | the same exclusion → `options` (574) | `body.model_dump(exclude={"question"})`: **the follow-up history is saved and served** (254, 300, 358) |
| A saved briefing as served (`GET /api/briefings/{id}`) | a flat object, not events: `id, question, created_at, records_up_to, settings, plan, sources, candidates, semantic, evidence, answer, interests`; answer rechecked (`api/briefings.py:127-144`) | `{id, at, question, options, events}`, events rechecked and curled (417) | `{id, at, question, options, events}`, events rechecked (358-359) |

### 3.5 Differences

| # | What | MPs | Countries | Councils | Kind, and which is best |
|---|---|---|---|---|---|
| 1 | Cached answers rechecked when replayed | no (`api/app.py:530`); only saved briefings are (`api/briefings.py:142`) | yes (548) | yes (274) | **(a)** Countries/Councils. A mark since found wrong stays on MPs' cached answers for up to a week |
| 2 | A question the model could not read | recorded | recorded | dropped | **(a)** Councils lacks it |
| 3 | A failed briefing | recorded | recorded | logged only | **(a)** Councils lacks it |
| 4 | The model declines | its own `error` event and a recorded failure; the call's usage dropped (`rag/pipeline.py:634-636`) | no branch: sent as an answer, or a generic error if there is no final message | as Countries | **(a)** MPs, with one gap of its own: the refused call's tokens should be recorded |
| 5 | Follow-up history: bounded | each part cut (`api/app.py:230-245`), tested (`tests/test_api.py:576`) | bounded by `Turn` (103-105) | **unbounded strings** (66) | **(a)** MPs/Countries. A request to Councils can inflate the prompt (the question part is not cut in `rag/answer.py`; only the answer part is, to 600 characters, and only the last three turns are used) |
| 6 | Follow-up history saved with the briefing | no | no | yes, and served | **(a)** MPs/Countries: a shared page should not carry an earlier conversation |
| 7 | "Sources only" and over-limit: who reads the question | the model while the site's budget lasts | the rules, free | "Sources only": the model, **with no check of the caps**; over a limit: the rules | **(a)** Councils' "Sources only" spends (a little) past the cap; MPs' check (`api/app.py:642`) is the fix. Whether an over-limit visitor should still get a paid reading (MPs) is **(b)** |
| 8 | Token counts sent to the browser | yes (`plan.usage`, `final.usage`) | yes | no | **(b)/(c)**: Councils' is tidier; MPs' and Countries' tests and pages may read them (not checked in the browser code) |
| 9 | Plan size limit | 20,000 characters (246, 261-266) | none | none | **(a)** MPs |
| 10 | Briefing id clash | five tries (`api/briefings.py:38-49`) | none: the reader would get the error event after the answer was paid for | none | **(a)** MPs, of small importance (64 random bits) |
| 11 | What `kept` holds | all but `text` | all but `text`, `citation` | all but `text` | **(c)**: only `plan`, `sources` and the last event are used. Countries' saves memory |
| 12 | `text` event in the saved briefing | no | yes | yes | **(b)**: MPs serves saved briefings as an object. A shared save must write each site's shape, and read both |
| 13 | Old cached answers given an address on a hit | yes (526-529) | no | no | **(b)** MPs' history |
| 14 | `progress`, `interests`, `support_reminder`, `briefing_key`, `prepared_at`, `records_up_to` | yes | no | no | **(b)** |
| 15 | Curly quotes | no | yes, in the pipeline and on replay | no | **(b)** |
| 16 | Pipeline's `find` returns | `(result, divisions, sources)` | `(result, votes, sources)` | `(result, sources)` | **(b)** |

### 3.6 What a shared implementation must take as parameters

`sse()` needs nothing: it can move as it is. A shared `ask` flow would need, from the site:

- the request body and how to turn it into the pipeline's request; the cache key's parts (3.3), digest length and
  the rule for when to make a key (follow-ups or not);
- the visitor and rate-limit key (with or without signed-in users) and the `InFlight` key;
- the caps function and its messages; the note texts (sources only; the suffix; the error text, which differs by
  one word in Councils);
- how the question is read on the sources-only and refused paths (model if the budget allows; rules; model always);
- hooks on events: before sending (strip `usage`/`parse_error`, add `briefing_key`, `support_reminder`), on `plan`
  (record parse usage and failure), on `final` (record usage kinds, count the question, save the briefing), on
  `error`;
- what to keep, what to cache (with or without `usage: null`), what to save and under which column names, and the
  saved options' exclusions;
- how a cached hit is prepared (recheck; curl; MPs' interests cleaning and late saving);
- the model names used for pricing (`parse_model`), and MPs' extra counting at the start (`count_question`,
  `record_event`).

---

## 4. Tests

### 4.1 MPs

`tests/test_api.py` (fixture `make_app`, 23-33: per-user and per-visitor limits set to 2):

| Line | Test | What it asserts |
|---|---|---|
| 98 | `test_ask_streams_plan_sources_text_and_verified_answer` | 200 and `text/event-stream`; first event `progress`/`reading`; then `plan`, `sources`, some `text`, `progress` second from last, `final` last; one `usage` row of kind `answer` |
| 121 | `test_sources_only_needs_no_model` | `sources_only` gives sources and a note with "Sources only"; the answer model is not called |
| 128 | `test_daily_question_cap` | a signed-in user's third question gets sources and a note containing "limit" |
| 147 | `test_admin_usage_is_admin_only` | 403 for a non-admin; `total_usd > 0` after a recorded call |
| 157 | `test_cost_calculation` | 1M input and 100k output at 4.0/20.0 cost 6.0 |
| 165 | `test_public_site_needs_no_sign_in` | the stored visitor is a code, not the address |
| 176 | `test_repeat_questions_come_from_the_cache_and_cost_nothing` | the same question in other case and spacing is a hit (`cached: true`, same answer, events `plan, sources, text, final`); another `mode` is not |
| 190 | `test_each_visitor_has_a_daily_limit_but_cached_answers_still_load` | third new question refused with "limit"; an earlier one still loads; another address is not limited |
| 201 | `test_site_wide_daily_budget` | 3M input tokens at the fallback price stop briefings with "budget" |
| 208 | `test_requests_per_minute_limit` | with 3 a minute, the fourth search is 429 |
| 224 | `test_feedback_refers_to_the_briefing_and_shows_in_admin_usage` | `briefing_key` on the final and on the replay; feedback stored and listed |
| 238, 253 | visit and event counts | daily totals only; yesterday's codes rolled up and deleted |
| 274 | `test_public_status` | `available`, then `paused` with "budget" in the note |
| 327 | `test_every_briefing_gets_a_permanent_shareable_address` | 10-character id, `prepared_at`; replay keeps the id; the saved view has no `usage` or `briefing_key`; withdrawal gives 410 |
| 445 | `test_visitor_codes_change_daily_and_old_secrets_are_deleted` | same day same code; other address, other day differ; only the day's salt is left (the un-dated one too is deleted) |
| 460 | `test_failures_and_spending_show_as_alerts` | alert texts for one failure and for 80% of the daily cap |
| 475 | `test_failed_briefing_is_logged_and_readers_see_plain_words` | an `error` event with "could not be written" and no exception name; the failure and the question count are listed |
| 494 | `test_cache_writes_and_reads_are_priced` | 1M cache writes at 4.0 cost 5.0; 1M cache reads cost 0.2 |
| 500 | `test_raw_sdk_token_names_are_priced_and_cache_writes_recorded` | the SDK's names and `usage_dict`'s cost the same and store the same row |
| 523 | `test_a_usage_table_from_before_cache_writes_were_recorded_gains_the_column` | the migration; old row reads 0 |
| 541 | `test_support_reminder_every_n_new_briefings` | every second new briefing; never on a cached one or a saved copy; stops after `/api/support-clicked` |
| 576 | `test_oversized_follow_up_history_and_plans_are_bounded` | history parts cut to 2000/1000/500/1000; a huge plan is 422 |
| 592 | `test_briefings_in_progress_count_against_the_caps` | `InFlight` alone: per-key and total refusals, `pending_usd` |
| 604 | `test_an_ipv6_connection_counts_as_one_visitor` | `network_of` for /64, IPv4, IPv4-mapped, `None` |

`tests/test_sse.py`: 11 `test_a_silence_is_filled_with_comment_lines_and_events_arrive_in_order`; 23
`test_an_error_is_raised_where_the_response_is_sent`; 34 `test_the_work_stops_once_the_reader_has_gone` (the events'
`finally` runs within 2 seconds of closing the stream).

`tests/test_rag.py` (pipeline; read in part): 150 `test_pipeline_end_to_end_is_grounded`; 169
`test_pipeline_returns_no_records_without_calling_the_model`; 178 `test_pipeline_reports_refusals_instead_of_answering`
(`error`, no `final`); 255 `test_pipeline_reports_checked_quotations`; 326
`test_saved_briefings_are_rechecked_by_the_current_rules`; 391 `test_client_has_an_explicit_timeout`.
`tests/test_topics.py:102` `test_topics_stop_at_the_budget_and_without_a_key` (a daily cap of 0 skips topics).

### 4.2 Countries

`tests/test_api.py`:

| Line | Test | What it asserts |
|---|---|---|
| 80 | `test_ask_streams_records_spend_and_caches` | `plan`, `sources`, `text`, `final`; one `usage` row costed as Sonnet; the repeat is `cached` with one model call |
| 94 | `test_caps_fall_back_to_sources` | a daily cap of 0: `answer` null, "budget" in the note, sources shown, no model call |
| 102 | `test_rate_limit` | with 2 a minute, the third search is 429 |
| 107 | `test_without_an_api_key` | "no Anthropic API key" in the note |
| 115, 131 | visitor codes | change daily; never contain the address; one /64 is one visitor |
| 121 | `test_ipv6_visitors_are_counted_by_their_64` | `network_of`, including `::1` and a non-address (`"testclient"`) |
| 138 | `test_question_length_is_checked` | 501 characters is 422 |
| 164 | `test_failures_are_kept_for_90_days` | an old failure is deleted when a new one is recorded |
| 175 | `test_usage_report_warns_near_a_cap` | the exact warning text at 80% (`spending: today's cap of $1.00 80% used ($0.80 spent)`), "reached: new briefings are paused", the failure warning, visitors counted |
| 194 | `test_briefings_are_saved_shared_and_withdrawn` | saved events end in `final` with `briefing_id` and `usage` null; the cached answer keeps the id; 404, 410 with the reason; report closing empties `contact` |
| 244 | `test_stream_stops_when_the_reader_leaves` | after close, the events' `finally` runs **and nothing more is produced** |
| 274 | `test_briefings_in_progress_count_against_the_caps` | `InFlight` with `check_caps`: under the cap alone, over it with pending; **`running == {}` afterwards** |
| 290 | `test_a_second_briefing_at_once_waits_its_turn` | over HTTP with a slow model: the second question gets the "already being written for you" note; the third, afterwards, is written |
| 321, 338, 351 | saved briefings rechecked and curled | marks cleared by today's rules; quotes curled with marks in place; a curled saved briefing keeps its points to check |
| 499 | `test_cost_copes_with_the_sdks_own_names_and_records_cache_writes` | `token_counts`; `None` for a count is safe; the stored row |
| 519 | `test_an_older_state_database_gains_the_cache_writes_column` | the migration |
| 535 | `test_status_says_when_briefings_are_paused_or_unavailable` | `paused` with "Today's budget"; `unavailable` without a key |

`tests/test_pipeline.py`: 79 `test_pipeline_end_to_end_is_grounded` (`loaded_words == 1` for "regime"); 114
`test_briefings_are_written_with_curly_quotes`.

### 4.3 Councils

`tests/test_api.py`:

| Line | Test | What it asserts |
|---|---|---|
| 36 | `test_ask_streams_a_briefing_saves_it_and_answers_again_from_the_cache` | `plan`, `sources`, `final`; **no `usage` in the final**; saved with its id; the repeat (other case and spacing) is `cached`; one `usage` row of kind `answer` |
| 54 | `test_over_the_daily_cap_the_sources_are_still_shown` | a cap of 0: sources, `answer` null, "limit" in the note, no model call |
| 87 | `test_rate_limit` | with 2 a minute, the third report is 429 |
| 96 | `test_briefings_in_progress_count_against_the_daily_cap` | over HTTP: with cap and estimate both 0.15, a second question while the first is written gets "today's limit" |
| 124 | `test_in_flight_reservations` | `InFlight` alone |
| 136 | `test_a_saved_briefing_is_checked_again_when_shown` | recheck of flags and loaded words |
| 154 | `test_old_answers_are_deleted_from_the_cache` | storing deletes rows older than the window |
| 188 | `test_an_ipv6_visitor_is_counted_by_their_slash_64` | `network_of` and `visitor_key` |
| 201 | `test_status` | `available`; `paused` with "today's limit" |
| 218 | `test_cost_counts_cache_writes_once_whichever_names_the_usage_uses` | both name forms cost 0.0921 |

`tests/test_pipeline.py`: 147 `test_pipeline_end_to_end_is_grounded` (`unsupported_segments == 1`, `loaded_words ==
1` for "fiasco"); 210 `test_the_claude_client_gives_up_after_five_minutes`. `tests/test_cli.py:12`
`test_reports_are_listed_closed_and_briefings_withdrawn` (the state methods through the command line; 410 text
`This briefing has been withdrawn: It named the wrong council.`).

### 4.4 Landlords

`tests/test_api.py`: 30 `test_a_report_from_the_form_is_kept_and_its_email_deleted_on_closing` (303 redirect; the
row; email null after closing; an empty message is 400); 44 `test_a_missed_search_keeps_only_the_words` (the
`missed` table's columns are exactly `day, query, count`). **No test touches `Limiter`**: no test file mentions 429.
`tests/test_approve.py` and `tests/test_statements.py` use the state database; they were not read.

### 4.5 Cases one site tests and others do not

| Case | Tested in | Missing from |
|---|---|---|
| Keep-alive comment lines; an error raised in the response | MPs `test_sse.py:11`, `23` | Countries, Councils |
| After the reader leaves, nothing more is produced | Countries `test_api.py:244` (MPs `test_sse.py:34` checks only that the events are closed) | Councils (no sse test at all) |
| A refused visitor leaves nothing in `InFlight` | Countries `test_api.py:287` | MPs, Councils (and their code would fail it) |
| At-once limit over HTTP | Countries `test_api.py:290` (per visitor); Councils `test_api.py:96` (pending cost against the cap) | MPs (only `InFlight` alone, `test_api.py:592`) |
| Per-visitor daily limit over HTTP | MPs `test_api.py:128`, `190` | Countries, Councils |
| Old cache rows deleted | Councils `test_api.py:154` | MPs, Countries |
| Failures' 90 days | Countries `test_api.py:164` | MPs (no such rule), Councils (no table) |
| A `None` token count | Countries `test_api.py:511` | MPs, Councils |
| The `usage` migration | MPs `test_api.py:523`; Countries `test_api.py:519` | Councils (no migration) |
| The old un-dated salt deleted | MPs `test_api.py:449-457` | Countries, Councils (no such rule) |
| The model declining | MPs `test_rag.py:178` | Countries, Councils (no such branch) |
| A failed briefing recorded and shown in plain words | MPs `test_api.py:475` | Countries (the recording is used in 175-190 but not through `/api/ask`), Councils |
| Bounded history and plan | MPs `test_api.py:576` | Countries, Councils |
| No `usage` in the browser's final | Councils `test_api.py:43` | (the others send it) |

**Tested nowhere** (in the files read): the monthly cap; a cached answer expiring by age; the limiter's window
rolling over or forgetting idle keys; the `InFlight` place being released when the reader leaves; the answer's
usage when the reader leaves; Councils' positional insert against an older table; Landlords' `Limiter`.

---

## 5. Ports worth making now

Each is a fix in one copy that another lacks. Source first, then where it goes.

1. **A refused visitor leaves nothing behind in `InFlight`.** From Countries `api/usage.py:205` (`self.running.get(key,
   0)`) to MPs `api/usage.py:181` and Councils `api/usage.py:142`; with the assertion from Countries
   `tests/test_api.py:287`.
2. **Failures recorded in Councils.** From MPs `api/usage.py:253-258` and Countries `api/usage.py:268-274` (table:
   Countries `api/usage.py:30`) to Councils: a `failures` table in `api/state.py:19-40`, and calls at
   `api/app.py:290` (the dropped `parse_error`) and `api/app.py:306-310` (the caught exception).
3. **Councils' "Sources only" must respect the caps.** From MPs `api/app.py:642` (read with the model only while
   `check_caps(state, None, …)` is `None`) to Councils `api/app.py:263-265`, `277-278`.
4. **Councils' follow-up history: bound it and do not save it.** From MPs `api/app.py:230-245` (or Countries
   `api/app.py:103-105`) to Councils `api/app.py:66`; and from MPs `api/app.py:656` / Countries `api/app.py:574`
   (`exclude={"question", "history"}`) to Councils `api/app.py:254`, `300`. Briefings already saved keep their
   history in `options`: decide whether to clear it (open question 5).
5. **Cached answers rechecked on replay in MPs.** From Countries `api/app.py:548`, `272-278` and Councils
   `api/app.py:274`, `149-154` to MPs `api/app.py:522-531` (apply `still_loaded(recheck_flags(…))`, as
   `api/briefings.py:142` does for saved briefings).
6. **`token_counts` in Councils, and name the columns.** From MPs `api/usage.py:31-44`, `98-109` (or Countries
   `87-103`) to Councils `api/usage.py:26-43`, `76-87`; replace `INSERT INTO usage VALUES (…)` (`api/usage.py:82`)
   with a named column list. Update `family/ENGINE.md`: Councils is no longer upstream for cost accounting.
7. **The model declining, in Countries and Councils.** From MPs `rag/pipeline.py:634-636` to Countries
   `rag/pipeline.py:151-152` and Councils `rag/pipeline.py:142-143`. In all three, record the declined call's
   usage (MPs drops it at the same lines).
8. **A lock and forgetting idle keys in Landlords' limiter.** From MPs `api/usage.py:200-220` to Landlords
   `api.py:222-238`; and close connections after use (`api.py:75-76`).
9. **MPs' settings and code out of step.** `answer_cache_hours` falls back to 24 in code (`api/app.py:347`) while
   the file and the other sites say 168; the three at-once keys are absent from MPs' file (settings 120-136) and
   the per-visitor one has a different name (`briefings_at_once_per_reader`, `api/app.py:342`). Write the keys into
   MPs' settings and settle one name before the shared package reads them.
10. **Plan size limit.** From MPs `api/app.py:246`, `261-266` to Countries `api/app.py:111` and Councils
    `api/app.py:65`.
11. **Lesser:** the briefing-id retry (MPs `api/briefings.py:38-49` to Countries `api/usage.py:327-333`, Councils
    `api/state.py:117-121`); `parse_model`'s fallback (MPs `rag/query_parse.py:498-499` to Countries
    `api/app.py:564`, Councils `api/app.py:288`); the 90-day rule for failures in MPs if its privacy notice needs it
    (Countries `api/usage.py:273-274` to MPs `api/usage.py:258`); the sse tests (MPs `tests/test_sse.py` and
    Countries `tests/test_api.py:244`) into Councils, which has none.

## 6. Open questions

1. **Councils' live `usage` table.** Does it have ten columns in the schema's order? If it was created before
   `cache_write_tokens` was added, every `record_usage` fails today (the insert is positional and there is no
   migration). `PRAGMA table_info(usage)` on the server answers it. This study could not see the server.
2. **Usage when the reader leaves or the stream fails.** No site records the answer's tokens then, though they are
   paid for. Should the shared flow record an estimate (or whatever the stream reports on closing)? A reader who
   opens and abandons briefings is otherwise invisible to the caps, apart from the `InFlight` estimate while each
   runs.
3. **One `usage` table or three?** A single shape (with `id`, `user_id`, `day`) means rebuilding Councils' table;
   keeping three means the shared code takes a column list. The same question for `answer_cache.at`/`created_at`
   and `briefings.at`/`created_at`, `options`/`settings`.
4. **The visitor's address behind the proxy.** Countries and Landlords take the first `X-Forwarded-For` entry in the
   app; MPs and Councils leave it to uvicorn's `proxy_headers` with `forwarded_allow_ips="*"`. Both are right only
   if the proxy replaces the header (Councils' comment says its Caddy does, `api/app.py:193-194`). Were the Caddy
   files of the other three checked? Not read here. If a visitor can set the header, they can dodge every limit.
5. **Councils' saved briefings already holding history in `options`:** clear it in place, or leave it?
6. **MPs' failures and its privacy notice:** does the notice promise a deletion period, as Countries' does (90
   days)? Not read.
7. **Should an over-limit visitor still have the question read by the model** (MPs) or by the rules (Countries,
   Councils)? MPs' way costs a little for each refused request, limited only by the 20-a-minute rate limit and the
   site's caps.
8. **Token counts in the browser** (`plan.usage`, `final.usage` in MPs and Countries): does either front end use
   them? Not checked. If not, strip them as Councils does.
9. **WAL for Countries, Councils and Landlords:** wanted? It is a lasting change to the file, and the backup and
   off-site copy scripts should be checked against the extra `-wal` file (they use SQLite's backup call in the code
   read, which is safe).
10. **Councils' process-wide lock:** was it added for a reason (a "database is locked" error seen live), or by
    caution? If the first, keep a write lock until WAL is on.
11. **MPs' cache stamp is the newest sync run of any status:** intended, or should it be the newest successful one?
12. **The prices** are the sites' own figures and differ in their fallbacks; this study did not check any of them
    against the provider's current price list. Someone should, once, before they are written into a shared default.
13. **`settings.local.toml` is merged one level deep** in MPs, Countries and Councils (`config.py`: MPs 103-107,
    Countries 95-99, Councils 85-89): a `[usage.models]` table in the local file replaces the whole table from the
    main file. Intended?
