# Extending wts-core: every hook a site has

13 November 2026. This page lists every place where a site plugs its own parts into the package, with a real
example of each. The design behind it is [ADR 0004](adr/0004-how-sites-plug-in.md).

Every example is quoted from the example site, [`examples/minimal-site/`](../examples/minimal-site/), an invented
site called Where Parks Stand. CI runs that site end to end, and a test
(`tests/test_docs.py`) fails if a quotation here is no longer in the file it names. So an example on this page is
code that runs.

The rule from ADR 0004: an extension point that the example site does not use is not a supported one. One hook is
the exception today, and it is marked: `Hooks.usages` (section 4.5).

## The hooks at a glance

| What a site supplies | Form | Section |
|---|---|---|
| Its name, package, prefix, hosts and versions | one `Site` object | 1.1 |
| Its own settings | a subclass of `Settings` | 1.2 |
| Limits, prices and models | keys in `config/settings.toml` | 1.3, 4.2 |
| Every word a reader is shown in the briefing flow | a `Messages` object | 2.1 |
| Every word of reports and the right of reply | a `ReplyMessages` object | 2.2 |
| Words for the owner: alerts and commands | `AlertWording`, `OpsWording`, `RepliesWording` | 2.3 |
| Its loaded-words list | `LoadedWords(pattern)` | 3.1 |
| The verifier's site-specific patterns | arguments to `Verifier(...)` | 3.2 |
| Its pipeline and its sources-only search | two functions on an `Ask` | 4.3 |
| What goes in the answer cache's key | `Ask.cache_key` | 4.4 |
| How sources are grouped for the balance figures | `group_of` | 4.4 |
| Steps only this site has in the flow | a subclass of `Hooks` | 4.5 |
| Stage timings inside the pipeline | `current_stages()` | 4.6 |
| Where a statement may sit | an `Items` object | 5 |
| Its limits for statements and reports | a `ReplyRules` object | 5 |
| The package's tables, and rows from its old ones | `migrations()`, `Import` | 6 |
| A model, an embedder, an index, an off-site store | an adapter behind a port | 7 |
| Its test questions | an `EvalSite` object | 8 |
| What the owner is alerted to | `[alerts]` in settings | 9 |
| The names and words of the owner's commands | arguments to the command groups | 10 |

## 1. The site and its settings

### 1.1 `Site`: the facts fixed in code

A site builds one frozen `Site` and passes it wherever the package needs to know which site it is serving. The
package cannot find a site's root folder from its own path, so the site gives it.

From `examples/minimal-site/src/parks/site.py`:

```python
SITE = Site(
    name="Where Parks Stand",
    package="parks",
    env_prefix="PARKS",  # PARKS_DATA_DIR, PARKS_CONFIG, PARKS_ANTHROPIC_API_KEY, PARKS_CHECK_TOKEN, PARKS_B2_BUCKET…
    root=ROOT,
    hosts=("whereparksstand.example", "www.whereparksstand.example"),
    state_file="state.db",
    version=__version__,
    # Raise this whenever INSTRUCTIONS in parks/pipeline.py change: it is part of the answer cache's key, so a
    # briefing written under the old instructions is never served as if written under the new.
    instructions_version="2026-11-13",
    # settings an environment variable may override: PARKS_PROVIDER sets [answer] provider, and so on
    env_settings=(
        EnvSetting("PROVIDER", "answer", "provider"),
        EnvSetting("BEHIND_PROXY", "server", "behind_proxy", "flag"),
    ),
)
```

- **`env_prefix`** names every environment variable the site reads. The package reads these itself:
  `<PREFIX>_CONFIG` (another settings file), `<PREFIX>_DATA_DIR` (another data folder),
  `<PREFIX>_ANTHROPIC_API_KEY` and `<PREFIX>_ANTHROPIC_BASE_URL` (the model adapter), and `<PREFIX>_B2_BUCKET`,
  `<PREFIX>_B2_KEY_ID` and `<PREFIX>_B2_APPLICATION_KEY` (off-site copies). A site reads `<PREFIX>_CHECK_TOKEN`
  with `SITE.env("CHECK_TOKEN")` and passes it to the check route.
- **`env_settings`** declares any further variable that may override a setting. `PARKS_PROVIDER=anthropic` sets
  `[answer] provider` on the example.
- **`instructions_version`** is the site's to raise when its instructions to the model change. The site puts it
  in the cache key (section 4.4) and in the configuration (section 9).

### 1.2 The `Settings` subclass and the prefix

`Settings` is the one class of the package a site may subclass. The base holds the loading rules and the shared
accessors (`section`, `answer`, `usage`, `data_dir`, `state_db`). The site adds a property for each thing of its
own.

From `examples/minimal-site/src/parks/site.py`:

```python
class ParksSettings(Settings):
    """The package's settings, with this site's own accessors. ``Settings`` is the one class of the package a site
    may subclass."""

    @property
    def minutes_file(self) -> Path:
        """The record itself: the minutes this site's briefings are drawn from."""
        path = Path(self.section("record")["minutes"])
        return path if path.is_absolute() else self.site.root / path
```

Settings are read in layers: `config/settings.toml`, then `<data>/settings.local.toml` on that installation, then
the declared environment variables, then keyword overrides (`**{"usage.requests_per_minute": 2}`, which is how
tests change one setting).

### 1.3 What must be in `settings.toml`

The package has no limit, price or model of its own. The package checks the keys it reads itself; a site checks
the rest, so that a missing key stops the site at start-up and names the file and the key.

From `examples/minimal-site/src/parks/site.py`:

```python
def load(config_path: str | Path | None = None, env: Mapping[str, str] | None = None,
         **overrides: Any) -> ParksSettings:
    """The site's settings, with the keys the site reads itself checked: a missing one stops the site here, naming
    it and the file."""
    settings = load_settings(ParksSettings, SITE, config_path, env, **overrides)
    for section, keys in REQUIRED.items():
        require(settings, section, keys)
    return settings
```

The keys the package reads itself. Those of the briefing flow are checked together when the site builds its desk
(section 4.1): everything missing or wrong is named in one error, with the settings file.

| Key | Read by | Needed |
|---|---|---|
| `[paths] data_dir` | `load_settings` | no: `data` if absent |
| `[answer] provider` | `adapters.model_client` | no: `anthropic` if absent |
| `[usage] per_visitor_daily_questions`, `daily_spend_cap_usd`, `monthly_spend_cap_usd` | `Limits.from_settings` | yes |
| `[usage] per_user_daily_questions` | `Limits.from_settings` | only on a site with signed-in accounts |
| `[usage] price_input_per_mtok`, `price_output_per_mtok`, `price_cache_read_per_mtok`, `cache_write_multiplier` | `PriceTable.from_settings` | yes |
| `[usage.models."<name>"]` | `PriceTable.from_settings` | no: a model with no table takes the base prices |
| `[usage] cache_write_long_multiplier` | `PriceTable.from_settings` | no |
| `[usage] requests_per_minute`, `answer_cache_hours`, `briefing_estimate_usd`, `briefings_at_once` | `briefing.desk_parts` | yes, on a site that builds its desk with it |
| two more, under the site's own names: how many briefings one visitor may have in progress, and how many idle visitors the per-minute limiter holds | `briefing.desk_parts`, told the names | yes, unless the site gives the numbers |

Every other key is read by the site and handed to the package as an argument. The example's
[`config/settings.toml`](../examples/minimal-site/config/settings.toml) is the full list for a site with
briefings, each key with a comment.

## 2. Wording

The package holds no wording a reader or sender can be shown. Each site supplies all of it, in objects whose
fields have no defaults. A new message in a later release fails loudly until each site supplies its own.

### 2.1 `Messages`: the briefing flow

One field for each refusal, limit and error in the flow of a briefing.

From `examples/minimal-site/src/parks/site.py`:

```python
MESSAGES = Messages(
    too_many_requests="Too many requests. Please wait a minute and try again.",
    visitor_daily_limit="You have asked a lot of questions today, so new briefings are paused until tomorrow.",
    daily_cap="The site has reached its budget for new briefings today. They start again tomorrow.",
    monthly_cap="The site has reached its budget for new briefings this month. They start again next month.",
    busy_visitor="Two of your briefings are still being written. Please wait for one to finish.",
    busy_site="A lot of briefings are being written just now. Please try again in a minute.",
    sources_follow="{reason} The minutes found are shown below.",
    sources_only="These are the minutes found for your question. No briefing was written.",
    briefing_failed="Something went wrong while this briefing was being written. Please try again.",
    model_declined="The model declined to answer this question.",
)
```

- `sources_follow` is a template: `{reason}` is the refusal's own message.
- `account_daily_limit` is a further field, for a site with signed-in accounts only.
- The package never sends `model_declined` itself. The site's pipeline sends it, in an `error` event, when the
  model declines (see `parks/pipeline.py`).

### 2.2 `ReplyMessages`: reports and the right of reply

Every refusal a sender can be shown, then the words a statement is shown with. Placeholders are `{max}`, `{n}`,
`{words}`, `{name}`, `{date}`, `{site}` and `{link}`. A template that asks for anything else stops the site when
it starts, naming the field. The heading and the disclaimer are the family glossary's.

From `examples/minimal-site/src/parks/site.py`:

```python
    # the family glossary's heading and disclaimer
    heading="Statement from {name}, {date}",
    disclaimer="In their own words. Not checked or endorsed by {site}.",
    record_link="Their link to the record",
    site=SITE.name,
)
```

### 2.3 Words for the owner

Three more objects hold words only the owner sees. Each site supplies all their fields.

- `ops.AlertWording`: what the backup check says when backups or off-site copies have stopped.
- `cli.OpsWording` (with `BackupWords`, `RestoreWords`, `BackupCheckWords`): every line the backup commands print.
- `cli.RepliesWording`: every line the report and statement commands print.

The example's are in `parks/site.py` (`BACKUP_ALERTS`) and `parks/cli.py` (`OPS_WORDING`, `REPLIES_WORDING`).
Section 10 shows how they are passed.

## 3. The checks: word lists and the verifier's patterns

The checks on briefings are the package's and never weaken. Three things about them are a site's own.

### 3.1 The loaded-words list

Each site's list is its own on purpose. The package exports the part every site shares, `COMMON_LOADED_WORDS`,
for a site to build its pattern on. A word added to the common part reaches every site.

From `examples/minimal-site/src/parks/site.py`:

```python
# The family's common list, and two words of this site's own: judgements on the state of a park, which a briefing
# may quote from the minutes but never say in its own voice.
LOADED_WORDS = LoadedWords(re.compile(rf"\b({COMMON_LOADED_WORDS}|eyesore|neglected)\b", re.IGNORECASE))
```

### 3.2 The verifier's site-specific patterns

`Verifier` takes three things, and none has a default except the honorifics:

- `no_records`: the words a "no records" answer opens with. The site's instructions tell the model to use them.
  An empty value is refused.
- `evidence_notes`: what makes a sentence a note about the evidence, not a claim. `EVIDENCE_NOTES_STRICT` is Where
  Councils Stand's form; `EVIDENCE_NOTES_WIDE` is what Where MPs Stand and Where Countries Stand have today. A new
  site should take the strict form.
- `honorifics`: abbreviations whose full stop ends no sentence. `COMMON_HONORIFICS` is the shared part.

From `examples/minimal-site/src/parks/site.py`:

```python
VERIFIER = Verifier(
    no_records=NO_RECORDS,
    # the strict form of the "note about the evidence" rule: a new site has no reason to take the wider one
    evidence_notes=EVIDENCE_NOTES_STRICT,
    # minutes write "Cllr. Okafor": the full stop ends no sentence
    honorifics=(*COMMON_HONORIFICS, "Cllr"),
)
```

A site's pipeline runs every check with one call, which keeps the one order they run in.

From `examples/minimal-site/src/parks/pipeline.py`:

```python
        # every check, in the family's one order: citations, preambles, spelling, loaded words, quotations
        report = check_briefing(blocks_as_today(done), sources, VERIFIER, LOADED_WORDS)
```

`sources` are the site's own objects. The checks need four things of each (`checks.TitledSource`): `n` (its
number, from 1), `blocks` (its citable text), `title` and `meta`. Pass `curled=True` on a site that shows its
briefings with curly quotation marks.

## 4. The briefing flow

The flow of a briefing is the package's: `briefing.BriefingDesk` ([ADR 0009](adr/0009-briefing-desk.md)). The
route, the request body, the pipeline and the pages stay the site's.

### 4.1 Building the desk

A site builds one desk when it starts, in two steps. `briefing.desk_parts` makes everything the desk is made of
from the site's settings: the prices, the limits, the spending record, the caps, the per-minute limiter, the
count of briefings in progress, the answer cache, the saved briefings and the notes of failures. The clock and
the source of chance are given once, there, and every part uses them, so a test can fix both. `DeskParts.desk`
then makes the desk.

From `examples/minimal-site/src/parks/app.py`:

```python
    parts = desk_parts(
        settings, db, MESSAGES,
        new_id=new_briefing_id,
        # this site's names for the two settings the family's sites name differently
        at_once_per_visitor="briefings_at_once_per_visitor", forget_over="forget_idle_visitors_over",
        keep_failures=True,  # a failed briefing is noted for the owner (the privacy notice says for how long)
        # both models must have prices of their own, so a new model is never costed at another's
        require_prices_for=(settings.answer["model"], settings.answer["query_parse_model"]),
        clock=clock, random=random)
```

It is two steps because what a site makes in between needs the parts. The example's pipeline takes the spending
record, and its hooks take the spending record and the limits.

From `examples/minimal-site/src/parks/app.py`:

```python
    desk = parts.desk(
        config,
        log=log,  # the record of each briefing, turned on (docs/adr/0012)
        hooks=ParksHooks(parts.spending, parts.limits, pipeline.records_up_to),
        group_of=lambda card: card.get("park"),  # the record counts each briefing's sources by park
    )
```

- `new_id` makes a saved briefing's id from the source of chance it is given. `usage.token_id(8, random=chance)`
  gives eleven characters; `usage.alphabet_id(alphabet, length, random=chance)` is Where MPs Stand's form.
- `at_once_per_visitor` and `forget_over` are each a number, or the name of the setting in `[usage]` that holds
  it. The family's sites name the first differently (`briefings_at_once_per_reader` on Where MPs Stand) and keep
  the second in their code, so the package reads neither under a name of its own.
- `keep_failures=False` keeps no notes of failed briefings (Where Councils Stand today).
- `log=None` writes no record of each briefing: a site that has not turned the record on. It has no default, so
  a site says which.
- `strict=True` (to `desk`) is for tests: text sent before the sources raises an error there, where a live site
  only logs it.
- The parts are the site's to use: `parts.spending` for a model call the desk cannot see (section 4.6),
  `parts.caps.site_paused()` for a status page, `parts.archive` for the pages of saved briefings, `parts.limits`,
  `parts.cache` and `parts.cache_hours`.

**The start-up check.** `desk_parts` first reads every limit, price and figure the flow needs, and looks at the
site's messages. Whatever is missing or wrong is said together, in one `SettingsError` that names the settings
file and each key:

```text
config/settings.toml: the briefing desk cannot be built: 2 things missing or wrong.
  - [usage] needs monthly_spend_cap_usd: the package has no limits of its own
  - [usage] needs requests_per_minute
```

`briefing.desk_settings` is the check on its own, for a site that wants to run it without a database (in a test
of its settings file, say). It returns what it read.

The pieces stay public: `BriefingDesk` and everything in `wts_core.usage` can still be built by hand, part by
part. `desk_parts` is the short way, not the only one.

### 4.2 Spending caps and prices

Both come from the site's `[usage]` settings, and `desk_parts` reads them. An owner's command that needs the
prices without the desk reads them on its own, naming the file for the error.

From `examples/minimal-site/src/parks/site.py`:

```python
def prices(settings: ParksSettings) -> PriceTable:
    """The site's prices, for the owner's commands that work out a cost."""
    return PriceTable.from_settings(settings.usage, file=settings.config_path)
```

From `examples/minimal-site/config/settings.toml`:

```toml
# A model whose name equals this, or starts with it, has its own prices (package). The site asks at start-up
# that both models named under [answer] have a table here, so a new model is never costed at another's prices.
[usage.models."recorded-briefing"]
price_input_per_mtok = 3.0
price_output_per_mtok = 15.0
price_cache_read_per_mtok = 0.3
```

`require_prices_for` is the strict start-up check: every model named must have a table of its own
(`PriceTable.require(models, base_counts=False)` is the same check on its own). Left out, a model with no table
takes the base prices, which is today's rule on the three older sites.

### 4.3 `Ask`: one question, as the route describes it

The site's route counts the request, builds an `Ask` and streams what the desk gives back.

From `examples/minimal-site/src/parks/app.py`:

```python
        events = desk.handle(Ask(
            question=question,
            visitor=visitor,
            write=lambda: pipeline.write(question, mode=body.mode, park=body.park),
            sources_only=lambda note, free: pipeline.sources_only(question, note, free=free, mode=body.mode,
                                                                 park=body.park, visitor=visitor),
            cache_key=None if check else key,
            only_sources=body.sources_only,
            model_available=pipeline.has_model,
            mode=body.mode,
            filters_set=("park",) if body.park else (),  # which filters were set, never their values
            kind="check" if check else "reader",
            options={"mode": body.mode, "park": body.park},  # saved with the briefing: what the reader chose
        ))
        return StreamingResponse(sse(events), media_type="text/event-stream", headers=STREAM_HEADERS)
```

| Field | What it is |
|---|---|
| `write()` | runs the site's pipeline and yields the events a reader is sent |
| `sources_only(note, free)` | finds the sources and writes no briefing, ending in a final event that carries `note`. `free` is true when the question must cost nothing to read |
| `visitor` | the day's visitor code (`usage.visitor_code`), for the daily limit and the spending record |
| `account` | a signed-in account's number, on a site with accounts |
| `limiter_key` | what this reader is counted by among the briefings in progress, if not the visitor's code |
| `cache_key` | the site's key for this question, or `None` for an answer that must not be cached or looked for |
| `only_sources` | the reader asked for the sources only |
| `model_available` | false when there is no model: the pipeline then shows the evidence only |
| `follow_up`, `mode`, `filters_set`, `kind` | for the record of the briefing. `kind` is `reader`, `check` or `eval` |
| `options` | what the reader chose, saved with the briefing |
| `save(final, kept, text)` | for a site whose saved briefings have a shape of their own (Where MPs Stand) |

The route calls `desk.allow(key)` first, for every route it limits, and answers 429 with the site's words when it
raises `TooManyRequests`.

### 4.4 Briefing defaults: the cache key, the instructions version, `group_of`

**The cache key is the site's.** It is `usage.cache_key(parts, length=…)`: a hash of whatever the site says an
answer depends on. The desk adds only the experiment's arm. So the site must put in everything that would make
an old answer wrong: the question, the reader's choices, the model, the instructions' version and a stamp of the
record.

From `examples/minimal-site/src/parks/app.py`:

```python
        key = cache_key({"question": question.lower(), "mode": body.mode, "park": body.park,
                         "model": settings.answer["model"], "instructions": SITE.instructions_version,
                         "data": data_stamp(settings.minutes_file)}, length=64)
```

`length` has no default: Where MPs Stand and Where Countries Stand keep 64 characters and Where Councils Stand 32,
and a site that passed the wrong length would miss every answer it had cached. A new site says 64.

**`group_of`** tells the desk which group a source card belongs to: a party, a region, a body, or on the example a
park. The record of each briefing then holds how many sources came from each group, which is the spread the
impartiality policy asks a site to be able to show.

**The configuration** (`config`) is what the site says of the settings a briefing ran with: a
`ports.BriefingConfig`, whose fields go into each briefing's record as they are. Its `parse_model` is the model
the reading of a question is priced as, and in an experiment its `arm` is part of the answer cache's key. A site
does not build one by hand: section 9 shows how the example makes it.

### 4.5 `Hooks`: the steps only some sites have

A site subclasses `briefing.Hooks` and overrides what it needs. Each default does nothing. The hooks run only
while a briefing is being written by `write()`, except `on_cached`. They do not run on a sources-only stream.

| Hook | When it runs | What it may change | Used by |
|---|---|---|---|
| `on_cached(ask, events)` | before a cached answer is replayed | the whole list of events to send | Where Countries Stand and Where Councils Stand judge the flags again by today's rules. Where MPs Stand gives an answer cached before briefings had addresses one now |
| `usages(ask, event)` | for each event, before its own cost is recorded | nothing: it names further model calls to record, each as a kind, a model and token counts | Where MPs Stand's final event carries what matching registered interests cost |
| `on_event(ask, event)` | for each event, after its cost and any failure are recorded, before it is kept or sent | the event, or `None` to drop it. What is taken out here is in no copy | Where Councils Stand takes the token counts out. Where MPs Stand takes out a key that is only for the spending record |
| `finish(ask, final, kept)` | for the final event, before it is saved or cached | the final event: what is added reaches every copy | Where MPs Stand's `briefing_key` |
| `for_this_reader(ask, final)` | after the briefing is saved and cached | this reader's copy only: never saved, never cached | Where MPs Stand's reminder of what briefings cost |

The example fills four of the five.

From `examples/minimal-site/src/parks/app.py`:

```python
    def on_cached(self, ask: Ask, events: list[Event]) -> list[Event]:
        """A cached briefing is judged again by today's rules before it is shown: a flag the rules no longer make
        is cleared. Nothing is ever newly flagged."""
        return [{**e, "answer": LOADED_WORDS.still_loaded(VERIFIER.recheck(e.get("answer")))}
                if e.get("type") == "final" else e for e in events]

    def on_event(self, ask: Ask, event: Event) -> Event | None:
        """Token counts are for the spending record, which has them by now. A reader has no use for them, so they
        are in no copy: not sent, not saved, not cached."""
        return {k: v for k, v in event.items() if k != "usage"}

    def finish(self, ask: Ask, final: Event, kept: list[Event]) -> Event:
        """Every copy of a briefing says how far the record ran when it was written. (This hook is given every
        final event of the pipeline, so one with no briefing in it is passed on as it is.)"""
        return {**final, "records_up_to": self._records_up_to} if final.get("answer") else final

    def for_this_reader(self, ask: Ask, final: Event) -> Event:
        """How many briefings this reader may still have today. It is about one reader, so it goes to that reader
        only: what is added here is never saved or cached."""
        if ask.visitor is None or not final.get("answer"):
            return final
        left = self._limits.per_visitor_daily - self._spending.briefings_today(visitor=ask.visitor)
        return {**final, "briefings_left_today": max(left, 0)}
```

**`usages` is not used by the example.** The example makes no model call beyond reading the question and writing
the briefing, which the desk records by itself. The package's own tests cover the hook
(`tests/test_briefing_desk.py`, `tests/test_briefing_parity.py`). It should be treated as provisional until Where
MPs Stand adopts the desk.

### 4.6 Stage timings and spending the desk cannot see

The desk times what it can see: the question read, the sources sent, the first words, the checks done. What
happens inside a pipeline only the pipeline knows, so it marks those stages itself: `searched`, `ranked` and
`written`.

From `examples/minimal-site/src/parks/pipeline.py`:

```python
def _reached(stage: Stage) -> None:
    """A stage of the briefing being written has just been reached. The briefing desk can see for itself when the
    question was read, the sources sent and the first words written; the search, the ranking and the model
    finishing happen in here, so the pipeline marks them. The desk times them, puts them in the briefing's record
    and writes them to the structured log."""
    current_stages().mark(stage)
```

A sources-only stream carries no token counts. If the site's sources-only function asks the model to read the
question, the site records that spending itself and tells the briefing's record what it cost.

From `examples/minimal-site/src/parks/pipeline.py`:

```python
        if read_usage is not None and self.spending is not None:
            # These events carry no token counts, so the desk cannot see this call. The site records the spending
            # itself, and tells the briefing's record what it cost.
            cost = self.spending.add("parse", self.settings.answer["query_parse_model"], read_usage, visitor=visitor)
            current_stages().spent(read_usage, cost)
```

### 4.7 What a pipeline must send

The events are today's JSON (`wts_core.events`). The desk relies on these rules:

- a `plan` event first, with `usage` (the cost of reading the question, or `None`) and, if the model failed to
  read it, `parse_error`;
- a `sources` event before any `text`;
- `text` and `citation` events as the model writes (`events.to_reader` makes them from the model's events);
- one `final` event: `answer` is the checked report, `None` when no briefing was written, with `usage`, `model`
  and `stop_reason`;
- or an `error` event with the site's words when the model declines, carrying `usage` and `model` so the call is
  still recorded. The desk does not send those two keys on.

## 5. `Items` and `ReplyRules`: the right of reply

`replies.Replies` owns the rules and the data of reports and statements
([ADR 0008](adr/0008-reports-and-statements.md)). A site passes three things: `ReplyMessages` (section 2.2), its
limits, and where a statement may sit.

**`Items`** is the one thing about statements that is wholly a site's own. Given what someone pasted, it returns
the item's address, or refuses in the site's words. It also says whether the item exists and is still shown.

From `examples/minimal-site/src/parks/site.py`:

```python
class ParksItems:
    """Where a statement may sit on this site (``replies.Items``): beside a saved briefing, at ``/b/<id>``."""

    def __init__(self, briefings: SavedBriefings) -> None:
        self._briefings = briefings

    def resolve(self, pasted: str) -> Item:
        """The briefing at what someone pasted: a full address on one of the site's hosts, or the path alone."""
        parts = urlsplit((pasted or "").strip())
        if parts.hostname and parts.hostname not in SITE.hosts:
            raise Refused("That address is not on this site. Please paste the address of a briefing.", "bad_item")
        match = _BRIEFING_ADDRESS.fullmatch(parts.path if parts.path.startswith("/") else "/" + parts.path)
        if match is None:
            raise Refused("Please paste the address of a briefing: it looks like /b/ and then some letters.",
                          "bad_item")
        return Item(address=f"/b/{match.group(1)}")

    def shown(self, item: Item) -> bool:
        saved = self._briefings.get(item.address.removeprefix("/b/"))
        return saved is not None and saved.withdrawn_at is None
```

An `Item` may also carry `about` (the member, country, council or landlord it concerns) and `part` (a part of the
page, as on Where Landlords Stand).

**`ReplyRules`** holds the limits where the sites differ. Only `max_words` (150) and `email_kept_months` (3) have
defaults, because they are the policy's.

From `examples/minimal-site/src/parks/site.py`:

```python
REPLY_RULES = ReplyRules(
    min_words=1,
    max_chars=1500,
    name_max=120,
    role_max=160,
    link_max=500,
    email_max=254,
    daily_statements=3,
    daily_reports=10,
    about_required=False,  # a statement sits beside a briefing, which is about no one person
    report_kinds={"error": "error", "takedown": replies.TAKEDOWN, "other": "other"},
    report_kind_required=True,
    report_min=10,
    report_max=4000,
    page_max=300,
    contact_max=254,
)
```

The site's routes turn a refusal into its own HTTP status. `Refused.why` names the rule that was broken.

From `examples/minimal-site/src/parks/app.py`:

```python
    def refused(exc: Refused) -> HTTPException:
        """The site's own status for a refusal: 429 for a daily limit, 422 for a mistake in the form."""
        return HTTPException(429 if exc.why.startswith("daily_") else 422, str(exc))
```

A site shows a published statement with `replies.statement_html`, or with markup of its own that keeps the same
rules. A page asks `replies.hidden(address)` before it shows an item.

From `examples/minimal-site/src/parks/app.py`:

```python
                # Statements under the right of reply, set apart from the site's own words. They are read from
                # their own tables here and nowhere else: never by the pipeline, the index or the model.
                + "".join(statement_html(s, REPLY_MESSAGES) for s in replies.published(items=[address])))
```

## 6. The state database: migrations and a site's one-off `Import`

Each module that stores something exports `migrations()`. The site joins the lists of the modules it uses and
passes them to `StateDB`. The package's tables all have names that start `wts_`. Every other table in the file is
the site's own, and the package never touches one.

From `examples/minimal-site/src/parks/site.py`:

```python
def migrations() -> tuple[Migration, ...]:
    """The tables of every part of the package this site uses. Each module names its own; the site joins them."""
    return (*usage.migrations(), *replies.migrations(), *observe.migrations())
```

An **`Import`** is a site's one-off copy of rows from its old tables into the package's. It runs once, in one
transaction, after the migrations. It waits while any table in `needs` is missing. Before the first import the
package makes a copy of the whole file beside it (`state.pre-wts-core.<date>.db`). The old tables are left as they
were.

From `examples/minimal-site/src/parks/site.py`:

```python
IMPORTS = (
    Import(
        name="parks-briefings",
        statements=(
            "INSERT OR IGNORE INTO wts_briefings (id, created_at, question, options, events) "
            "SELECT id, created_at, question, '{}', events FROM briefings",
        ),
        needs=("briefings",),
    ),
)


def open_state(settings: ParksSettings, clock: Clock = SYSTEM_CLOCK) -> StateDB:
    """The site's state database, with the package's tables made (and any import run) on the way in."""
    return StateDB(settings.state_db, migrations=migrations(), imports=IMPORTS, clock=clock)
```

An import must give every `NOT NULL` column a value. The copy made before an import holds everything the site
deletes on a schedule, as it was that day, so it must not outlive the site's backups. The package's `tidy`
command deletes old copies when the site passes `backup_days` (section 10).

## 7. Adapters, and how to swap one

Shared code depends on the interfaces in `wts_core.ports`, never on an outside library
([ADR 0002](adr/0002-ports-and-adapters.md)). Only the modules under `wts_core.adapters` import one. A site's
pipeline takes the interfaces too, so the same pipeline runs over real adapters or over the fakes in
`wts_core.testing`.

From `examples/minimal-site/src/parks/pipeline.py`:

```python
    def __init__(self, settings: ParksSettings, *, model: ModelClient | None, embedder: Embedder,
                 index: VectorIndex, spending: SpendingRecord | None = None) -> None:
```

| Port | The package's adapters | Fake for tests | Contract test |
|---|---|---|---|
| `ModelClient` | `adapters.anthropic.AnthropicClient`, made by `adapters.model_client(settings, site)` | `testing.models.ScriptedModel` | `ModelClientContract` |
| `Embedder` | `adapters.fastembed.FastEmbedEmbedder`; `adapters.hashing.HashingEmbedder` (no model file) | `testing.index.RecordingEmbedder` | `EmbedderContract` |
| `VectorIndex` | `adapters.lancedb.LanceIndex` | `testing.index.MemoryIndex` | `VectorIndexContract` |
| `OffsiteStore` | `adapters.b2.B2Store`, made by `adapters.b2.configured(site)` | `testing.MemoryOffsiteStore` | `OffsiteStoreContract` |
| `Clock`, `Random` | the system's | `testing.FixedClock`, `testing.FixedRandom` | none |

**A new model** is a settings change: `[answer] model`, and its prices under `[usage.models."<name>"]`.

**A new provider, embedding model, vector store or off-site store** is one new module that implements the port,
and one test class. The contract tests are in `wts_core.testing.contracts` (it needs pytest, so it is imported by
its full name). A new adapter is accepted when its class passes:

```python
import pytest
from wts_core.testing.contracts import OffsiteStoreContract

from mysite.store import MyStore


class TestMyStore(OffsiteStoreContract):
    @pytest.fixture
    def store(self, tmp_path):
        return MyStore(tmp_path)
```

Each contract names the one fixture it needs: `model` (a `ModelFactory`) for `ModelClientContract`, `embedder` for
`EmbedderContract`, `open_index` for `VectorIndexContract`, `store` for `OffsiteStoreContract`. The model's
contract replays the recorded streams that ship with the package, so no test calls a model or the network.

The site chooses its adapters in one place. The example has a provider of its own, "scripted", which replays a
recording so that the site runs with no key. Any other provider goes to the package.

From `examples/minimal-site/src/parks/pipeline.py`:

```python
def model_from_settings(settings: ParksSettings, env: Mapping[str, str] | None = None) -> ModelClient | None:
    """The model ``[answer] provider`` names, or ``None`` when there is nothing to call one with. Made once and
    kept for the life of the process."""
    provider = str(settings.answer["provider"]).strip().lower()
    if provider == "scripted":
        return scripted_model(settings.recordings_dir / f"{settings.answer['recording']}.jsonl")
    if provider == "anthropic" and not anthropic.has_credentials(SITE, settings, env):
        return None  # no key: the site shows the minutes only
    return model_client(settings, SITE, env)
```

Three rules for a site:

- **Keep one model client for the life of the process.** It remembers what the provider refused.
- **Changing the embedding model means rebuilding the index.** An index records the embedder it was built with and
  raises `ports.IndexOutOfDate` when opened with another. Vectors from two models are never mixed.
- **An off-site store other than the default** is passed to the backup commands:
  `ops_commands(SITE, load, BACKUPS, OPS_WORDING, store=lambda: MyStore(...), how_to_set_up="…")`.

## 8. `EvalSite`: the site's test questions

The evaluation harness (`wts_core.eval`) asks a site's test questions of its real pipeline and reports what the
checks found, the spread of sources, the time and the cost. The site gives it three methods: `cases()`,
`ask(case, config)` and `group_of(source)`.

From `examples/minimal-site/src/parks/evaluation.py`:

```python
    def ask(self, case: Case, config: Mapping[str, Any]) -> Iterator[ReaderEvent]:
        """Ask one question of the pipeline itself: never through the briefing desk, so never from the answer
        cache. ``config`` is the configuration this site was built from (``parks.pipeline.configuration``)."""
        pipeline = Pipeline(self.settings, model=self._model_for(case), embedder=self.embedder,
                            index=new_index(self.embedder))
        self._kept.pop(case.id, None)

        def keep(documents: Any, blocks: Any) -> None:
            self._kept[case.id] = Recording(documents, blocks)

        return cast(Iterator[ReaderEvent], pipeline.write(case.question, keep=keep))

    def group_of(self, source: Mapping[str, Any]) -> str:
        """The group a source belongs to on this site: its park."""
        return str(source.get("park") or "")
```

The harness looks for three optional methods. A site has one by defining it; nothing is declared.

- `score(case, plan, sources)`: the site's own expectations of a question, each met or not.
- `recording(case)`: what the model was given and what it wrote, so the briefing can be kept as a fixture for
  the free replay (`eval replay`).
- `judge(case, answer)`: a score for the briefing, where the site's set has judged answers. The example has none.

The questions are in the site's `eval/questions.toml`, read by `eval.load_cases`. The thresholds a run is held to
are the site's too.

From `examples/minimal-site/config/settings.toml`:

```toml
[eval.thresholds]
# What an evaluation run is held to (`parks eval run`). A threshold is min_ or max_ and the name of a figure.
# The set's second question is recorded with one unsupported sentence and one loaded word, on purpose: the
# thresholds allow exactly that and nothing worse.
max_invalid_citations = 0
max_unverified_quotations = 0
max_unsupported = 1
max_loaded_words = 1
min_grounded_ratio = 0.8
max_errors = 0
```

The names a threshold may use are the keys of `eval.FIGURES`. A run that asks the whole set and meets every
threshold is noted in `eval/runs/passed.jsonl`. That file must be committed: it is what the guard on experiments
reads.

## 9. The record of each briefing, and the alert thresholds

With `log=SqliteBriefingLog(db)` the desk writes one record for every question
([ADR 0012](adr/0012-briefing-record-and-statistics.md)). The site supplies two things.

**The configuration.** Everything that could change a briefing, and the short id of it all.
`observe.briefing_config` makes it: it works the id out, adds the package's own version, and keeps the settings
behind the id in `wts_configs`, in one call. Every field is named, so a misspelt one stops the site when it starts.
`also` holds whatever else could change a briefing on this site.

From `examples/minimal-site/src/parks/pipeline.py`:

```python
    answer = settings.answer
    return briefing_config(
        log=log, model=answer["model"], parse_model=answer["query_parse_model"],
        instructions=SITE.instructions_version, site_version=SITE.version,
        also={"provider": answer["provider"], "embedder": embedder.id, "ranking": dict(settings.ranking),
              "sources": {"summary": answer["summary_sources"], "comprehensive": answer["comprehensive_sources"]}})
```

`log` is the site's `SqliteBriefingLog`. A site that has not turned the record on says `log=None`: the
configuration is made and nothing is kept. Never put a key, a password or anything about a reader in it. The
settings behind each id are stored as they are.

**What happened next.** The routes that already receive these signals mark the briefing's record:
`log.mark(briefing_id, reported=True)`, `useful=True` or `False`, `corrected=True`, `followed_up=True`.

**The alert thresholds** are the site's `[alerts]` settings. They start unset. The first weekly report proposes
values from that week's figures, and the owner writes them in. An alert never fires from a number nobody chose.

From `examples/minimal-site/config/settings.toml`:

```toml
[alerts]
# Thresholds start unset: the first weekly report proposes them from that week's figures, and the owner writes
# them here. The names are p95_full_briefing_ms, error_rate, check_failure_rate, not_useful_rate, daily_cost_usd.
```

An unknown name under `[alerts]` stops the statistics commands and names it. A figure trips only when it is over
its threshold.

**The structured log** is turned on by the site, once for each process, by giving the logger `observe.LOGGER` a
handler with the site's own limits. The desk then writes a line for each stage a briefing reaches and one for how
it ended. With no handler nothing is logged.

From `examples/minimal-site/src/parks/app.py`:

```python
    logs = settings.section("logs")
    handler = json_logging(settings.logs_dir / "briefings.jsonl", site=SITE, max_bytes=int(logs["max_bytes"]),
                           keep=int(logs["keep"]), days=int(logs["days"]), clock=clock)
    log = logging.getLogger(LOGGER)
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
```

A line holds a briefing's record id, a stage's name, a time and an error's class name, and nothing else. A line's
`event` must be one of `observe.EVENTS`, and its `stage` one of `observe.STAGE_NAMES`. A site that notes events
of its own with `observe.log_event` lists their names in its code: `json_logging(..., events=("index.rebuilt",))`.
A name that is not listed is left out of the line, so nothing a reader typed can become one.

**Visitor codes are forgotten after their day.** The spending record keeps the day's visitor code on a row for
that day only (`Spending.forget_visitors`, run with the first model call of each day). The package's `tidy`
command does the same on a day with no model call. A site needs to do nothing but run `tidy` nightly.

## 10. The owner's commands and the check route

A site keeps its own Typer app and adds the package's command groups to it (`wts_core.cli`). For backups, reports
and statements every name and every printed line is the site's.

From `examples/minimal-site/src/parks/cli.py`:

```python
app.add_typer(ops_commands(SITE, load, BACKUPS, OPS_WORDING))  # backup, restore, offsite, backup-check
```

From `examples/minimal-site/src/parks/cli.py`:

```python
app.add_typer(replies_commands(_replies, REPLIES_COMMANDS, REPLIES_WORDING))  # reports …, statements …, hide, …
```

| Group | Commands | What a site passes |
|---|---|---|
| `ops_commands` | `backup`, `restore`, `offsite`, `backup-check` | its `BackupSpec` and `OpsWording`; another off-site store if it has one |
| `replies_commands` | `reports list/show/close`, `statements list/show/publish/decline/update/withdraw/remove/log`, `hide`, `unhide`, `hidden`, `waiting` | `RepliesCommands` (what each command is called) and `RepliesWording` |
| `stats_commands` | `stats`, `weekly-report`, `tidy` | its `[alerts]` thresholds, its reports folder, its embedder and the similarity for themes |
| `eval_commands` | `eval run`, `eval compare`, `eval replay` | its `EvalSite`, configuration, prices, thresholds and the most a run may spend |

A **`BackupSpec`** says what the site's backups are called and what a restored database must hold.

From `examples/minimal-site/src/parks/site.py`:

```python
BACKUPS = BackupSpec(
    prefix="parks-state-",  # parks-state-2026-11-13.sqlite.gz: what marks a backup, here and off site, as this site's
    keep=14,  # how many stay on the server; `parks backup --keep` says otherwise for one run
    required_tables=("wts_schema", "wts_spending", "wts_briefings", "wts_reports", "wts_statements"),
)
```

The package's `tidy` applies the retention to the record of briefings and to the weekly reports, forgets old
visitor codes, and deletes copies of the database made before an import once they are older than `backup_days`.
A site passes the days it keeps a backup.

From `examples/minimal-site/src/parks/cli.py`:

```python
    backup_days=BACKUPS_KEPT_DAYS,  # tidy deletes copies of the database older than the backups are kept
```

The housekeeping of reports and statements is not in `tidy`. A site's nightly run calls it too:
`Replies.lapse_undecided`, `Replies.forget_old_emails` and `Replies.forget_old_counts`. The example's own
`parks nightly` command calls all three.

A restore accepts any file that has the tables `required_tables` names. A site with a table of its own should
name it there, so that a sister site's backup is refused. The example has no table of its own, so its list holds
the package's tables only.

**The check route** answers the nightly family check ([ADR 0010](adr/0010-ci-and-nightly-check.md)). `check_route`
returns a plain function; the site's own route calls it.

From `examples/minimal-site/src/parks/app.py`:

```python
    check = check_route(SITE, token=parks.check_token, replies=replies,
                        backups=lambda: backup_ages(settings.backups_dir, BACKUPS, clock=parks.clock),
                        figures=lambda: last_day_figures(parks.log, clock=parks.clock), clock=parks.clock)

    @app.get("/api/check")
    def api_check(authorization: str | None = Header(None)) -> JSONResponse:
        status_code, body = check(authorization)
        return JSONResponse(body, status_code=status_code)
```

The site's ask route must also treat a question that carries the check token as the nightly check's: no cache key,
and `kind="check"`. The example does this in `is_the_nightly_check` in `parks/app.py`.

## 11. The two checks every site's tests must call

Both are in `wts_core.testing`, and both run over the site's real pipeline.

- `assert_statements_stay_out(...)`: a published statement never reaches the model, the embedder, the index, the
  record or a log ([ADR 0008](adr/0008-reports-and-statements.md)). The example calls it in
  `tests/test_replies.py`.
- `assert_no_reader_data(...)`: after a question, nothing kept or logged holds the reader's address; the day's
  visitor code is only where it is counted; the question is only where the privacy notice says a question is
  kept. The example calls it in `tests/test_privacy.py`.

## 12. What a site must never do

These rules are what keep four sites from drifting apart again
([ADR 0007](adr/0007-versioning.md); [`CONTRIBUTING.md`](../CONTRIBUTING.md), rule 7).

- **Never patch the installed copy.** A fix is made in the package, released, and taken by each site in a pull
  request. A fix made in place is how the four copies drifted.
- **Never import a private name.** A name that starts with an underscore is private everywhere, and so is a
  module-level name that is not in its module's `__all__`.
- **Never reach past `__all__`.** The public interface is what `wts_core.__all__` and each submodule's `__all__`
  export. Anything else may change in any release without notice.
- **Never subclass anything but `Settings`** (and `Hooks`, whose methods are the hooks). `Verifier` and
  `LoadedWords` are final. A site that needs a class to behave differently asks for a hook.
- **Never copy a module of the package into the site.** If the package does not fit, the package is changed.

If a hook is missing, the right step is an issue or a pull request on the package, and an amended ADR if the
design has to change.
