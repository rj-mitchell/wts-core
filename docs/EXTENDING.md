# Extending wts-core: every hook a site has

Every place where a site plugs its own parts into the package, with a real example of each, for the maintainer
building or changing a site. The design behind it is [ADR 0004](adr/0004-how-sites-plug-in.md).

An example introduced by "From `examples/minimal-site/…`" is quoted from the example site,
[`examples/minimal-site/`](../examples/minimal-site/), an invented site called Where Parks Stand. CI runs that
site end to end, and a test (`tests/test_docs.py`) fails if such a quotation is no longer in the file it names.
So those examples are code that runs.

The rule from ADR 0004: an extension point that the example site does not use is not a supported one. The
exceptions are hooks that one of the four older sites needs and the example does not. They are covered by the
package's own tests, and each is marked where it is described: `Hooks.usages` (section 4.5), an `Item` made by
the route (section 5), `Replies(hidden_with=…)` and `ReplyRules.form_max` (section 5), an import's statement built
when it runs and `Import(written_at=…)` (section 6), the LanceDB helpers for a site that builds its own table
(section 7), `EvalSite.usages` (section 8), and `changed` and `groups` for the owner's commands (section 10).

## Summary of hooks

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
| An experiment: its arms, and the variant its pipeline reads | `[experiment]` in settings; `current_config()` | 4.8 |
| Where a statement may sit | an `Items` object | 5 |
| Its limits for statements and reports | a `ReplyRules` object | 5 |
| What can be hidden, and the one address each item is filed under | a function, `hideable` | 5 |
| The package's tables, and rows from its old ones | `migrations()`, `Import` | 6 |
| What becomes of its old tables after the import | an `OldTables` object | 6 |
| A model, an embedder, an index, an off-site store | an adapter behind a port | 7 |
| Its test questions | an `EvalSite` object | 8 |
| Test questions proposed from real use | the `propose-questions` command; a person approves each | 9 |
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

- `env_prefix` names every environment variable the site reads. The package reads these itself:
  `<PREFIX>_CONFIG` (another settings file), `<PREFIX>_DATA_DIR` (another data folder),
  `<PREFIX>_ANTHROPIC_API_KEY` and `<PREFIX>_ANTHROPIC_BASE_URL` (the model adapter), and `<PREFIX>_B2_BUCKET`,
  `<PREFIX>_B2_KEY_ID` and `<PREFIX>_B2_APPLICATION_KEY` (off-site copies). A site reads `<PREFIX>_CHECK_TOKEN`
  with `SITE.env("CHECK_TOKEN")` and passes it to the check route.
- `env_settings` declares any further variable that may override a setting. `PARKS_PROVIDER=anthropic` sets
  `[answer] provider` on the example.
- `instructions_version` is the site's to raise when its instructions to the model change. The site puts it
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

The installation's file is laid over the site's two levels deep. A key of a section replaces that key
(`[usage] daily_spend_cap_usd`); where the key is a table in both files, the two tables are merged key by key, so
a server's `[usage.models."claude-opus-5-5"]` adds that one model's prices and leaves the others'. A model's own
table is given whole. An error about the settings names both files when the installation's was read
(`Settings.files`), since what is missing or wrong may be in either.

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
| `[answer] provider` | `adapters.model_client`, `adapters.has_model` | no: `anthropic` if absent |
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
    briefing_failed="The briefing could not be finished. Any minutes found are listed above.",
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

Seven messages may be left out, and nothing else. `item_hidden` is what a sender is told when the item is hidden
while a concern about it is decided, where the site wants to say that and not what it says of an item that is
gone (`item_not_shown`, which is said where `item_hidden` is not given). The six "too long" messages
(`too_many_chars`, `name_too_long`, `role_too_long`, `link_too_long`, `report_too_long`, `contact_too_long`) may
each be left out by a site whose own form cannot send that much: the site says what its form lets through in
`ReplyRules(form_max={"name": 120, …})` (section 5), and the package checks when the site starts that every
message left out is one no sender could be shown. A message left out that a sender could meet stops the site,
naming it. The package still has no wording of its own for a reader
([ADR 0004](adr/0004-how-sites-plug-in.md)): a missing message is allowed only where it is proved unreachable.

### 2.3 Words for the owner

Three more objects hold words only the owner sees. The package has none of its own to put in their place.

- `ops.AlertWording`: what the backup check says when backups or off-site copies have stopped. Every field is
  needed.
- `cli.OpsWording` (with `BackupWords`, `RestoreWords`, `BackupCheckWords`): every line the backup commands print.
  `restore` and `backup_check` are `None` on a site with no such command.
- `cli.RepliesWording`: every line the report and statement commands print. A site gives the lines its own
  commands print. A line for a command it left out (`None` in `RepliesCommands`) need not be given, and a line
  missing for a command it has stops the commands being built, naming the line.

The example's are in `parks/site.py` (`BACKUP_ALERTS`) and `parks/cli.py` (`OPS_WORDING`, `REPLIES_WORDING`).
Section 10 shows how they are passed.

## 3. The checks: word lists and the verifier's patterns

The checks on briefings are the package's and never weaken. A site supplies its loaded-words list, the verifier's
site-specific patterns and the shape of its sources.

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

`Verifier` takes the following; only the honorifics have a default:

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
        experiment=experiment,  # while it runs, the desk gives each briefing a version by chance
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

The start-up check. `desk_parts` first reads every limit, price and figure the flow needs, and looks at the
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
part. `desk_parts` is the shorter way.

### 4.2 Spending caps and prices

Both come from the site's `[usage]` settings, and `desk_parts` reads them. An owner's command that needs the
prices without the desk reads them on its own, naming the file for the error.

From `examples/minimal-site/src/parks/site.py`:

```python
def prices(settings: ParksSettings) -> PriceTable:
    """The site's prices, for the owner's commands that work out a cost."""
    return PriceTable.from_settings(settings.usage, file=settings.files)
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
takes the base prices.

Strict prices are the rule for a site that writes briefings. It passes `require_prices_for=(its answer
model, its question-reading model)` to `desk_parts`, as the example does above, and keeps a table under
`[usage.models]` for every model its settings may name. A site that does not ask costs an unknown model at its
base prices and says nothing: a dearer model named in a server's own settings then undercounts spending, and the
daily and monthly caps bite late. An empty table is enough for a model that really does cost the base prices;
what matters is that someone wrote it down.

A server may price one model in its own settings. `<data>/settings.local.toml` is laid over the site's file
two levels deep, so a local `[usage.models."claude-opus-5-5"]` adds that model's table to the site's and leaves
the rest. The table of one model is given whole: it is laid over the base prices, not
over the site file's table for that model. When a price is missing the error names both files.

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

The cache key is the site's. It is `usage.cache_key(parts, length=…)`: a hash of whatever the site says an
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

`group_of` tells the desk which group a source card belongs to: a party, a region, a body, or on the example a
park. The record of each briefing then holds how many sources came from each group, which is the spread the
impartiality policy asks a site to be able to show.

The configuration (`config`) is what the site says of the settings a briefing ran with: a
`ports.BriefingConfig`, whose fields go into each briefing's record as they are. Its `parse_model` is the model
the reading of a question is priced as, and in an experiment its `arm` is part of the answer cache's key. A site
does not build one by hand: section 9 shows how the example makes it.

### 4.5 `Hooks`: the steps only some sites have

A site subclasses `briefing.Hooks` and overrides what it needs. Each default does nothing. The hooks run only
while a briefing is being written by `write()`, except `on_cached`. They do not run on a sources-only stream.

| Hook | When it runs | What it may change | Used by |
|---|---|---|---|
| `on_cached(ask, events)` | when a cached answer is found, before anything is sent | the whole list of events to send; or `None`, which makes it a miss: the briefing is written afresh in the same request (the caps are asked first) and stored over the copy refused | Where Countries Stand and Where Councils Stand judge the flags again by today's rules. Where MPs Stand gives an answer cached before briefings had addresses one now |
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

A briefing that is withdrawn or hidden is dropped from the answer cache by the site. Saved briefings and the
cache are separate parts, and withdrawing a briefing (`parts.archive.withdraw`) does not touch the cache: the
next reader with the same question would be played the briefing that was taken down, for as long as the cache
keeps it. The command or route that withdraws a briefing, or hides one, calls
`parts.cache.delete_briefing(briefing_id)` straight after, which drops every cached copy of it and says how many.
A site that judges a cached answer in `on_cached` and decides not to play it can drop it there:
`parts.cache.delete(ask.cache_key)`. Both are methods of `usage.SqliteAnswerCache`, which `DeskParts.cache` is;
they are not part of `ports.AnswerCache`, which asks only for what the desk itself uses.

`usages` is not used by the example, which makes no model call beyond reading the question and writing the
briefing, both of which the desk records by itself. Where MPs Stand uses it, and the package's own tests cover it
(`tests/test_briefing_desk.py`, `tests/test_briefing_parity.py`).

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

### 4.8 An experiment

A site may try two versions of its method side by side on real questions, on the conditions the impartiality
policy sets (principle 6; [ADR 0012](adr/0012-briefing-record-and-statistics.md), "Experiments"). When
to run one, and when not to, is in [`IMPROVING.md`](IMPROVING.md#running-an-experiment). This
section is the mechanism.

It is declared in settings, one at a time. The example declares none, and sets one out in comments for an
owner to copy into the site's settings or the installation's own `data/settings.local.toml`.

From `examples/minimal-site/config/settings.toml`:

```toml
#   [experiment]
#   name = "more-effort"            # lower-case letters, digits, hyphens
#   start = 2026-12-01              # the first day it runs (UTC) ...
#   end = 2026-12-14                # ... and the last; outside them it is off
#   decided_by = "any_check"        # the rate that decides it: the share of briefings in which a check found a problem
#
#   [[experiment.arms]]             # the first arm is the control: the site as it stands. It changes nothing
#   name = "control"
#   share = 0.5                     # the shares add up to 1
#
#   [[experiment.arms]]
#   name = "more"
#   share = 0.5
#   variant = "more-effort"         # a word of this site's own: parks/pipeline.py asks the model for more effort
```

The first arm is the control: the site as it stands. Another arm may change only
`model`, `instructions` (the version of the site's instructions) and `variant`, a word of the site's own. Any
other key in an arm is refused; one that names a check, the loaded words, a threshold or the balance of sources
is refused as such, since every version passes the same checks. `decided_by` is one of `observe.PROPORTIONS`.

It is read and checked when the site starts, and the switch is given to the desk.

From `examples/minimal-site/src/parks/app.py`:

```python
    experiment = experiment_switch(settings, config, log=log, runs=settings.runs_dir,
                                   thresholds=settings.section("eval")["thresholds"],
                                   prices=parts.prices)  # an arm that names a model needs that model's own prices
```

`experiment_switch` never stops the site. The experiment does not run if the declaration is wrong; if an arm
names a model with no price table of its own under `[usage.models]`, since its briefings would be costed at the
base prices and the caps would count them wrongly (so `prices=` is needed wherever an arm may name a model); if an
arm that changes anything has no pass noted by the evaluation harness for exactly its configuration under the
site's thresholds as they stand (`eval.has_passed`); or if anything goes wrong in finding these out. The site then
runs on its control alone, an error naming the fault is logged, and `ExperimentSwitch.state(clock)` says so.
Give that state to the check route and to `stats_commands`, as the example does (section 10), and
`stats --check` fails while a declared experiment cannot run, so the owner is told.

While it runs, the desk gives each reader's question a version by chance (`ports.Random`, the arms' shares,
and nothing about the reader), records it with the briefing (`experiment`, `arm` and the arm's own `config_id`),
and adds it to the answer cache's key. The nightly check's question and the evaluation harness's are never in an
experiment. Outside its dates it is off, with no restart.

The pipeline reads its version from the desk. `briefing.current_config()` is the configuration this briefing
is being written with: the arm's, while an experiment runs, and otherwise the site's own; `None` outside a desk.
Read it once, at the top of the pipeline, and take from it what an arm may change. The example's one variant
asks the model for more effort.

From `examples/minimal-site/src/parks/pipeline.py`:

```python
def _version(config: Mapping[str, Any] | None, settings: ParksSettings) -> _Version:
    """The version to write with: from the configuration given, else from the one the briefing desk made current
    for this briefing, else (a test of the pipeline alone, a command) the site's settings."""
    if config is None:
        current = current_config()
        config = current.settings if current is not None else {}
    variant = config.get("variant")
    if variant is not None and variant not in VARIANTS:
        raise ValueError(f"this site's pipeline has no variant {variant!r}: it knows {', '.join(VARIANTS)}")
    return _Version(model=str(config.get("model") or settings.answer["model"]), variant=variant)
```

A variant the pipeline does not know stops the briefing. A version recorded as one thing and written as another
would make the experiment's figures untrue. For the same reason read the configuration in the pipeline's own
code: a thread the pipeline starts for itself does not inherit it, and must be handed what was read.

An arm must pass before it goes live. `eval run --arm <name>` makes the run with the arm's configuration and
files it under the arm's id. The site gives `eval_commands` its arms, and its `EvalSite.ask` hands the
configuration to the pipeline, so that what is measured is what would run.

From `examples/minimal-site/src/parks/cli.py`:

```python
def _arms() -> Mapping[str, Mapping[str, Any]]:
    """The configuration of each arm of the site's experiment, for `parks eval run --arm …`: the run an arm must
    pass before it can go live is made with exactly what the arm would run with, and filed under its id."""
    experiment = Experiment.from_settings(load())
    if experiment is None:
        return {}
    return {name: arm.settings for name, arm in arm_configs(experiment, _site_configuration()).items()}
```

The desk enforces the following while an experiment runs, and a site cannot switch them off. A briefing written in
an arm whose report lacks any check's figure (`briefing.CHECKED`) is not shown: the reader is told it failed, and
it is neither saved nor cached. And a saved briefing is shown as it was sent, whichever version wrote it: nothing
of the experiment is consulted when it is read again.

The example's `tests/test_experiment.py` plays all of this end to end: an arm that has not passed, the pass, both
versions given to one visitor, the cache, the record, the day after the last.

## 5. `Items` and `ReplyRules`: the right of reply

`replies.Replies` owns the rules and the data of reports and statements
([ADR 0008](adr/0008-reports-and-statements.md)). A site passes `ReplyMessages` (section 2.2), its limits, and where a
statement may sit.

`Items` is the one thing about statements that is wholly a site's own. Given what someone pasted, it returns
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

A form with more than one field. `resolve` takes one string: what someone pasted. A site whose form sends the
place in two fields (Where Landlords Stand's sends the page's address and, separately, which part of the page)
does not fold them into one address for `resolve` to take apart again. `Replies.submit(item=…)` takes an `Item`
the site has already made, and the site's route makes it:

```python
    beside = items.resolve(body.page)                      # the page, checked as ever
    if body.part in PARTS and beside.address.startswith("landlords/"):
        beside = dataclasses.replace(beside, part=body.part)   # the form's own field, not a #fragment
    replies.submit(item=beside, name=body.name, role=body.role, text=body.text, link=body.link,
                   email=body.email, visitor=None, trap=body.website)
```

`submit` still asks the site whether the item is shown (`Items.shown`) and refuses a hidden one. So does
`publish`, when the owner decides weeks later: a statement is not published beside an item that has gone.

`ReplyRules` holds the limits where the sites differ. Only `max_words` (150) and `email_kept_months` (3) have
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

`form_max` is what the site's own form lets through for each field (any of `replies.FORM_FIELDS`: `text`, `name`,
`role`, `link`, `report`, `contact`), where the form has a limit of its own that is no greater than the rule's.
It is what lets the matching "too long" message be left out (section 2.2), and it is given only by a site that
leaves one out: Where MPs Stand does, whose request models refuse an over-long field before the package sees it.
The example gives every message, and so no `form_max`.

The day something nobody decided lapses is the package's sum, in `replies.days`, and needs no database:
`has_lapsed(at, now, months)` says whether something sent at `at` has lapsed, `lapses_on(at, months)` is the
first day by the end of which it has, and `lapse_cutoff(now, months)` is the moment that decides. A site's page,
its tests and any script of its own that must agree with the tidy ask there, and work nothing out for
themselves.

The site's routes turn a refusal into its own HTTP status. `Refused.why` names the rule that was broken.

From `examples/minimal-site/src/parks/app.py`:

```python
    def refused(exc: Refused) -> HTTPException:
        """The site's own status for a refusal: 429 for a daily limit, 422 for a mistake in the form."""
        return HTTPException(429 if exc.why.startswith("daily_") else 422, str(exc))
```

### Hiding an item

Any item can be hidden while a concern about it is decided, with a note shown in its place (policy 7.3):
`replies.hide(item, note)`, `replies.unhide(item)`, and `replies.hidden(address)`, which a page asks before it
shows an item. An item is hidden by its address as the site files it, which is what its pages ask about. So
the site says, once, what that address is for whatever an owner might type: it gives its `Replies` a function,
`hideable`. Given what was typed (a full address copied from a browser, a path with a trailing slash, another
case) it returns the one address the site files that item under; or it raises `NotDone`, in words for the owner,
when what was typed is not an item of a kind that can be hidden, or there is no such item.

From `examples/minimal-site/src/parks/site.py`:

```python
def hideable(items: ParksItems) -> Callable[[str], str]:
    """This site's one spelling for an item that can be hidden while a concern about it is decided: a saved
    briefing, filed as ``/b/<id>``, which is what its page asks about. The owner may paste the briefing's full
    address or its path; anything else, and a briefing that is not there, is refused in words for the owner."""

    def filed(typed: str) -> str:
        try:
            item = items.resolve(typed)
        except Refused:
            raise NotDone("only a briefing can be hidden on this site: give its address, which looks like /b/ and "
                          "then some letters") from None
        if not items.shown(item):
            raise NotDone(f"there is no briefing at {item.address}, or it has been withdrawn")
        return item.address

    return filed
```

From `examples/minimal-site/src/parks/site.py`:

```python
    items = ParksItems(open_archive(db, clock))
    return Replies(db, items=items, rules=REPLY_RULES, messages=REPLY_MESSAGES, clock=clock,
                   hideable=hideable(items))
```

- `hide`, `unhide` and `hidden` all pass what they are given through it, so the owner's commands and the site's
  pages agree whatever was typed. The commands need nothing new: the site's `Replies` carries it, and the line
  said (and `changed`) are given the address the item is filed under.
- A site that can hide more kinds of thing than a statement can sit beside (a record, a label, a vote) resolves
  those in `hideable` itself. For an item a statement can sit beside it must return the address `Items.resolve`
  gives, because a statement is hidden with its item by that address.
- `hidden` is asked by a page on every request, so `hideable` should be cheap. What it refuses is simply not
  hidden, unless it is, letter for letter, an address hidden now: an item that has gone from the site since it
  was hidden can still be shown again by its exact address, as the `hidden` command lists it.
- Without `hideable` the site must give the exact address. `hide` then stores whatever it is given: a full
  address or a trailing slash is reported as hidden and hides nothing, because no page asks about that spelling.
- Do not subclass `Replies` for this: a site subclasses nothing but `Settings` and `Hooks` (section 12).
- Where hiding one item hides others, the site says which: `Replies(..., hidden_with=…)`. The package knows
  a hidden item by its address, and cannot know that a briefing cites a record that is hidden (Where Countries
  Stand) or that a named vote belongs to a council whose page is hidden (Where Councils Stand). The function is
  given an `Item` a statement sits beside and says whether it is hidden now for such a reason; `published()`
  asks it once of each item and leaves out the statements beside one that is. The example has no such items and
  gives none. It is not `Items.shown`, which decides only whether a statement may be sent or published beside an
  item: what a site shows of a statement whose briefing was later withdrawn is the site's own to decide.

A site shows a published statement with `replies.statement_html`, or with markup of its own that keeps the same
rules.

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

An `Import` is a site's one-off copy of rows from its old tables into the package's. It runs once, in one
transaction, after the migrations. It waits while any table in `needs` is missing. Before the first import the
package makes a copy of the whole file beside it (`state.pre-wts-core.<date>.db`). The import leaves the old
tables as they were.

From `examples/minimal-site/src/parks/site.py`:

```python
def _old_failures(con: sqlite3.Connection) -> list[str]:
    """The old notes of failed briefings, where there are any. That table came late, so a backup from before it
    has none: it is not among the import's ``needs`` (or the import would never run on a database restored from
    such a backup), and this returns nothing when it is not there."""
    if not columns(con, "failures"):
        return []
    return ["INSERT INTO wts_failures (at, kind, question, error) SELECT at, 'briefing', question, error FROM failures"]


IMPORTS = (
    Import(
        name="parks-briefings",
        statements=(
            "INSERT OR IGNORE INTO wts_briefings (id, created_at, question, options, events) "
            "SELECT id, created_at, question, '{}', events FROM briefings",
            _old_failures,
        ),
        needs=("briefings",),  # only what is in every backup the site's restore accepts
    ),
)
```

`needs` names only tables that are in every backup the site's restore accepts. An import that needs a table
an older backup lacks is skipped on a database restored from that backup, at every start, for ever: nothing it
brings across arrives, and the restored site shows no spending and no saved briefings. When some of an import's
needed tables are there and others are not, the package logs a warning each time the site starts
(`wts_core.state`), naming the import and the missing tables; but the remedy is the one above. A statement for a
table that may be missing is a function, given the connection when the import runs and returning the SQL to run:
it returns nothing when the table is not there (`state.columns(con, table)` is empty), and the table is left out
of `needs`.

The same serves for an old table that is not the same in every copy of the database: Where Landlords Stand's
`reports` gained its `kind` column late, and a backup from before it has none.

```python
def bring_reports(con: sqlite3.Connection) -> list[str]:
    kind = "kind" if "kind" in columns(con, "reports") else "NULL"   # wts_core.state.columns
    return [f"INSERT INTO wts_reports (id, at, kind, page, message, contact) "
            f"SELECT id, at, {kind}, page, message, contact FROM reports"]


IMPORTS = (Import(name="landlords-reports", statements=(bring_reports,), needs=("reports",)),)
```

An import must give every `NOT NULL` column a value. The copy made before an import holds everything the site
deletes on a schedule, as it was that day, so it must not outlive the site's backups. The package's `tidy`
command deletes old copies when the site passes `backup_days` (section 10).

An import that fails says which statement failed. The error is `state.ImportFailed`, an
`sqlite3.OperationalError` that carries the import's `name`, the statement's `number` (from 1) and the
`statement` itself; nothing of the import is kept, and the site does not start.

Going back, and coming forward again. An import runs once. If the site is put back on its old code for a
while without its undo script being run, the old code writes to the old tables again; when the new code comes
back the import is marked as done, and what was written meanwhile would be silently missing from the package's
tables. So an import says, for each old table it copies from, which column holds the time a row was written:

```python
Import(
    name="parks-briefings",
    statements=(…),
    needs=("briefings",),
    written_at={"briefings": "created_at", "failures": "at"},
)
```

Each time the database is opened, while the old tables are still there, a row written after the second the
import ran stops the site with `state.StateError`, which names the tables and the mend: run the site's undo
script (which takes the package's rows back to the old tables and forgets that the import ran), then start the
new code, and the import runs again over everything.

- What is declared is checked. A table named in `written_at` must be among the import's `needs` or the
  site's `OldTables`: any other is a mistyped name, and the database is not opened. A table that is there
  without the column named is refused too, with the columns it does have. A table that is not there is passed
  over (it was dropped on its day, or this copy never had it).
- Times are compared as times, to the second, however the old code wrote them: `+00:00` or `Z`, with or
  without microseconds, another offset, or SQLite's `datetime('now')` (taken as UTC). A value that cannot be
  read as a time never stops the site: it is passed over, and a warning in the log says how many there were.
  A table whose times are kept another way (seconds since 1970, say) gives a function of the connection and the
  time the import ran, returning how many rows are newer.
- It cannot see a row written in the very second the import ran, a row with no time, or what the old code
  changed in a row that was already there. And if the server's clock was put back between the old code's last
  write and the move, it stops a site that lost nothing: the mend is the same, and loses nothing.
- The nightly tidy of the old tables never trips it, since it changes and deletes rows and adds none.

The example declares none; the package's tests cover it. Each of the four older sites' lines is in
[`UPGRADING.md`](UPGRADING.md#going-back-to-the-old-code).

### The old tables, after the import

The old tables stay in the live file after the import, so that the move to the package can be undone. Left alone
they would hold what the package has since deleted from its own tables: the addresses of senders whose
statements ended three months ago, the contacts of reports since closed, the questions of failed briefings past
their 90 days, and the adoption day's visitor secret beside that day's visitor codes. A site promises that
nothing is kept longer than before, so it declares what becomes of them, as `OldTables`, beside its imports.

From `examples/minimal-site/src/parks/site.py`:

```python
OLD_TABLES = OldTables(
    tables=("briefings", "failures"),
    # Dropped by `parks tidy` from this day: no later than the day the copy made before the import is deleted
    # (60 days after it: BACKUPS.keep_offsite), since after that there is nothing left to go back to.
    drop_on=date(2027, 1, 12),
    nightly=(
        # the question of a briefing that failed is kept for 90 days, in the old table as in the package's
        "DELETE FROM failures WHERE substr(at, 1, 10) < date(:today, '-90 days')",
    ),
)


def open_state(settings: ParksSettings, clock: Clock = SYSTEM_CLOCK) -> StateDB:
    """The site's state database, with the package's tables made (and any import run) on the way in. It is marked
    as this site's the first time it is opened, and a file marked as another site's is refused."""
    return StateDB(settings.state_db, migrations=migrations(), imports=IMPORTS, old_tables=OLD_TABLES, clock=clock,
                   site=SITE.package)
```

`site=` marks the file as this site's (section 10 says what the mark is for).

`StateDB.retire_old()` applies the declaration, in one transaction, and is safe to run every night: the package's
`tidy` command calls it (section 10), and a site with a nightly command of its own calls it there. What a site
must declare:

| Promise | What the site declares | For example |
|---|---|---|
| A sender's address is deleted three months after their statement ends | blank the old statement's address wherever the package's row has none | `UPDATE statements SET email = NULL WHERE email IS NOT NULL AND id IN (SELECT id FROM wts_statements WHERE email IS NULL)` |
| A report's contact is deleted when it is closed | the same, for the old reports | `UPDATE reports SET contact = NULL WHERE contact IS NOT NULL AND id IN (SELECT id FROM wts_reports WHERE contact IS NULL)` |
| A failed briefing's question is kept 90 days | delete old notes of failures older than the site's retention | `DELETE FROM failures WHERE substr(at, 1, 10) < date(:today, '-90 days')` |
| A visitor's code cannot be worked back to an address after its day | delete every old visitor secret but today's (and blank old visitor codes from before today, where an old spending table has them) | `DELETE FROM kv WHERE key LIKE 'visitor_salt:%' AND key != 'visitor_salt:' \|\| :today` |
| The old tables do not outlive the way back | their names, and when they are dropped | `tables=(…), drop_after_days=60`, or `drop_on=date(2027, 2, 1)` |

- A statement is SQL, which may use the named values `:now` and `:today` (UTC, as the package stores times and
  dates), or a function of the connection that returns SQL, as for an import. One that names a table no longer
  there is passed over, so the list need not change as tables go.
- The day the old tables are dropped is no later than the day the copy made before the import is deleted
  (the adoption day plus the `backup_days` the site gives `tidy`). From that day `retire_old` drops them; until
  it, the site's script for undoing the adoption (`deploy/undo-….sql`, which rewrites the old tables from the
  package's) still works, and the script and the site's operations page must say it is valid only until then.
- Give the drop as `drop_after_days` unless the day was promised in public. A fixed `drop_on` can only keep
  to the rule above if the deploy day is known when the code is written, and it is not. `drop_after_days` counts
  from the day the site's imports ran (the last of them), so the old tables and the copy go together whatever
  day the owner deploys: give it the days the site keeps a backup, or fewer. Exactly one of the two is given.
  `StateDB.old_tables_due()` is the day that makes, for a page or a script that states it. The example gives a
  fixed date, as the four older sites do (1 February 2027).
- A drop that is due is held back while an import the site declares has not run, since those rows would be
  nowhere else; `tidy` then ends with status 1, so the site's timer fails and the owner is told.
- A site's `BackupSpec.required_tables` must not name a table that is dropped, or every later backup is refused.
  A site that wants its restore to insist on the old tables until the drop, and on the package's from then on,
  says so once: `BackupSpec(required_tables=("wts_spending", …), required_tables_until={date(2027, 2, 1):
  ("usage", "briefings")})`. The day is the day of the restore, so one spec serves on both sides of it.
- `OldTables` cannot name a `wts_` table. The package's tables are never a site's to retire.

### Deleted data in the file

Every connection the package opens sets `PRAGMA secure_delete = ON`, so a row deleted or blanked is overwritten
with zeros where it lay. The nightly `tidy` deals with what that does not reach (section 10):

- a copy of a row left behind in the file's unused space by an earlier, ordinary connection (the site's old
  code, or the `sqlite3` command), and
- in a database that keeps a write-ahead log (`journal_mode = WAL`), earlier copies of changed pages in the log
  until it is next emptied.

`StateDB.compact()` writes the file out afresh (`VACUUM`) and empties the log, and returns whether it did: `False`
when another connection was using the file at that moment, in which case nothing is lost and it is tried again
the next night. It needs free space on the volume for the length of the call: as much again as the file, and
about twice the file where the database keeps a write-ahead log (the rewrite goes through the log).
`retire_old()` calls it after a drop. A site with a nightly command of its own, and no stats group, calls
`compact()` last there, and acts on what it returns. A site's own connections to the state database
(a script's, a test's) should come from `StateDB.connect()`, so that they delete the same way.
[ADR 0005](adr/0005-state-database.md) has what was measured.

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

A new model is a settings change: `[answer] model`, and its prices under `[usage.models."<name>"]`.

A new provider, embedding model, vector store or off-site store is one new module that implements the port,
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
    if not has_model(settings, SITE, env):
        return None  # nothing to call the provider with (no key): the site shows the minutes only
    return model_client(settings, SITE, env)
```

`adapters.has_model` asks whether the provider named in the settings has what it is called with. A site asks
there, beside `adapters.model_client`, and imports no provider's module, so a change of provider stays a change
to its settings.

A pipeline closes the model's stream when it has finished with it, however it finished. `close()` is in the
interface's type (`ports.ModelStream`), and it stops the model if the reader has gone.

From `examples/minimal-site/src/parks/pipeline.py`:

```python
        finally:
            stream.close()  # if the reader has gone, this stops the model: nothing more is written or paid for
```

A site should follow these rules:

- Keep one model client for the life of the process. It remembers what the provider refused.
- Changing the embedding model means rebuilding the index. An index records the embedder it was built with and
  raises `ports.IndexOutOfDate` when opened with another. Vectors from two models are never mixed.
- An off-site store other than the default is passed to the backup commands:
  `ops_commands(SITE, load, BACKUPS, OPS_WORDING, store=lambda: MyStore(...), how_to_set_up="…")`.

What a site that builds its own LanceDB table may use. A site whose index is built by its own code (all four
older sites') shares the adapter's helpers and copies none: `number_type(name)` and `number_name(type)` for the
vectors' number type as the index's record names it, `vector_schema(filter_fields, dimension, value_type)`,
`vector_array(vectors, value_type)` and `vector_value_type(schema)`; `UNKNOWN_EMBEDDER`, the id an index built
before embedders were recorded is given; `LanceIndex(..., number_type=…)`, which is honoured with or without an
`IndexMeta`; and `LanceIndex(..., trained_file="vector-index.json")` for a site whose note of when the vector
index was last trained has another name. `LanceIndex.everything()` gives every row with its vector, which is
what `testing.assert_statements_stay_out` reads (section 11). A search with a vector of the wrong length raises
`ports.IndexOutOfDate`, as opening the index with another embedder does.

One models folder for each model. The fastembed embedder's id is the model's name and the fingerprint of
that model's own files, where the library made the model a folder of its own: another model's files in the
same models folder do not change it. Where the model's files cannot be told from another's (weights lying
loose, or held in more than one place, none of them the folder the library makes for this model),
`adapters.fastembed.model_fingerprint(cache_dir, model)` raises `ModelFilesUnclear`; the embedder itself is
still made, with the whole folder's id, and says so in the log and in its `unclear`: an id that depends on
another model's files puts the index out of date whenever those change. A re-ranker's models go in a folder
beside the embedder's, not inside it. Where the files cannot be told apart, separating them later changes the id,
and the vectors must be made again. (An index stamped by 0.2.x with the whole folder's id, which the embedder
gives as `earlier_ids`, is accepted once and stamped again, until 0.4.0.)

What the index guards, and what it does not. An index records the embedder it was built with
(`wts_index.json` in its folder), and refuses to be opened with another: by id, and by the length of its
vectors. It does not guard the following, and tests document both:

- An index opened without an embedder (`LanceIndex(path, None, …)`, for search by words and for counts)
  cannot tell which model made a vector of the right length. Asked to search by meaning with another model's
  vector of the same dimension, it answers, and the answer means nothing. So search by meaning only through an
  index opened with the site's embedder, as every site's engine does.
- The note is the guard. With `wts_index.json` deleted, the index is taken to have been built with whatever
  next opens it (as an index made before the note existed is), and only the vectors' length can still refuse.
  Back the note up and restore it with the index, and never delete it to get past a refusal: make the vectors
  again (`start_again`).

### A second provider

No site uses a provider other than Anthropic's, and the package ships no working adapter for one.
`adapters/skeleton_provider.py` is a skeleton: it meets `ports.ModelClient` over a made-up HTTP shape, passes
`ModelClientContract` against the recorded streams, and drives the example site's whole pipeline in
`tests/test_swap_provider.py`, with nothing else in the package changed. It is not exported from
`wts_core.adapters`, and `adapters.model_client` does not know it. That proves the interface; it is not a
client for any service. What a real second adapter needs, in the order to do it:

1. A module under `adapters/` that imports the provider's library (or `httpx`) inside its functions, and an
   extra in `pyproject.toml` that brings the library. Start from the skeleton and replace its wire shape, every
   line, with the provider's own.
2. `stream(request)`: `TextDelta` as the words arrive, `CitationDelta` before the words a citation supports,
   and one `Completed` last, with the whole answer as blocks, the model that answered, how it ended and the
   usage. `close()` on the stream must stop the provider's work.
3. `structured(request, schema)`: the parsed object and the usage. Take the provider's answer and its
   usage first, then read the answer (`ports.read_structured(schema, text, usage=…, stop_reason=…)`): it
   raises `ports.NoStructuredAnswer`, carrying the usage and the stop reason, for a refusal, an answer with
   nothing in it, one cut off part-way, one that is not JSON and one that does not fit. Every one of those was
   paid for, and the site records it. Do not let the provider's library read the answer if it throws
   the response away when it cannot, as the Anthropic SDK's `messages.parse` does. The contract has all seven
   ways an answer can come back (`testing.contracts.ANSWERS`).
4. The usage, in the family's four counts: input tokens not read from a cache, tokens written to a cache,
   tokens read from one, output tokens. Most providers report the prompt's tokens as one total with the cached
   part inside it: subtract, as the skeleton's `usage_of` does, or every cached token is charged twice.
5. How an answer ended, in the family's words (`end_turn`, `max_tokens`, `refusal`): the sites' pipelines
   look for `refusal`, and the record of each briefing keeps the word. The skeleton's `FINISH` is the pattern.
6. `supports`: say honestly which of `caching`, `long_cache`, `fallbacks`, `effort` and `citations` the
   provider has. A site asks before it relies on one (`"citations" in model.supports`).
7. Citations, which are the whole difficulty. The family's checks need the document a citation points to and
   the words quoted from it. Where the provider gives both, pass them on as given. Where it gives none, make
   none up: send the text with no citation and leave `citations` out of `supports`. The site then either shows
   every point as "to check" (which is what the checks will do, unprompted) or writes no briefings with that
   provider. An adapter may instead ask the model to mark its quotations and parse the marks into citations:
   that is honest, because the verifier checks each against its source and a weak adapter shows up as invalid
   citations in the evaluation harness. It is real work, and the policy's conditions for a change of method
   apply to it.
8. The contract test: a class that inherits `ModelClientContract`, with a `model` fixture that plays the
   recorded streams through the provider's wire shape (`tests/test_swap_provider.py` shows one way). The
   fixture is also handed an `Answered` (the text the model wrote, how it ended, what it cost) and makes its
   stand-in for the provider say exactly that, in the provider's own shape.
9. Wiring: a branch for the provider's name in `adapters.model_client` and in `adapters.has_model` (which
   says whether the provider has been given its key), and its export from `adapters`. A site then changes
   `[answer] provider` and nothing else.
10. Prices: each model's under `[usage.models."<name>"]` in the site's settings, with the cache rates the
    provider really charges. `usage.Pricing` matches the longest name a model's id starts with. An
    experiment's arm that names a model with no table of its own is not run (section 4.8).
11. Before a site uses it: a full run of the site's test questions under the new configuration, passing the
    site's thresholds as they stand, and then (if the owner wants the comparison on real questions) an
    experiment on the policy's conditions (section 4.8). A change of provider is a change of method like any
    other, and is recorded as one.

A second embedder needs none of this: it is a class that passes `EmbedderContract`, and a rebuilt index.
`tests/test_swap_embedder.py` shows an index made with one embedder refusing to open with another, by name.

## 8. `EvalSite`: the site's test questions

The evaluation harness (`wts_core.eval`) asks a site's test questions of its real pipeline and reports what the
checks found, the spread of sources, the time and the cost. The site gives it three methods: `cases()`,
`ask(case, config)` and `group_of(source)`.

From `examples/minimal-site/src/parks/evaluation.py`:

```python
    def ask(self, case: Case, config: Mapping[str, Any]) -> Iterator[Event]:
        """Ask one question of the pipeline itself: never through the briefing desk, so never from the answer
        cache. ``config`` is the configuration being measured: the site's own (``parks.pipeline.configuration``),
        or an arm's of its experiment (``parks eval run --arm …``). The pipeline is handed it, and writes with
        the model and the variant it names: what is measured is what would run."""
        pipeline = Pipeline(self.settings, model=self._model_for(case), embedder=self.embedder,
                            index=new_index(self.embedder))
        self._kept.pop(case.id, None)

        def keep(documents: Any, blocks: Any) -> None:
            self._kept[case.id] = Recording(documents, blocks)

        return pipeline.write(case.question, keep=keep, config=config)

    def group_of(self, source: Mapping[str, Any]) -> str:
        """The group a source belongs to on this site: its park."""
        return str(source.get("park") or "")
```

The harness looks for four optional methods. A site has one by defining it; nothing is declared.

- `usages(event)`: further model calls an event reports, each a kind, the model it is priced as and its token
  counts: the same shape as `Hooks.usages` (section 4.5), so that a site with a third model call has it counted
  in a run's cost as the desk counts it in a reader's briefing. Only Where MPs Stand needs it; the example has
  none.
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
threshold is noted in `passed.jsonl` in the folder runs are kept in. That note is what the guard on experiments
reads (section 4.8), so the folder must be one the running site can read: `eval/runs/` committed with the code,
or a folder on the data volume.

A run's cost in the site's own spending. `eval_commands(..., spending=…)` gives the site's spending record
when a run starts: each model call the run counts is then added to it, as the kind `eval` and for no visitor, so
that what a run costs shows in the owner's spending figures and counts towards the site's daily and monthly
caps.

From `examples/minimal-site/src/parks/cli.py`:

```python
def _spending() -> Spending:
    """The site's spending record: an evaluation run's model calls are recorded in it (as the kind "eval"), so
    that what a run costs shows in the site's spending and counts towards its caps."""
    settings = load()
    return Spending(open_state(settings), prices(settings))
```

## 9. The record of each briefing, and the alert thresholds

With `log=SqliteBriefingLog(db)` the desk writes one record for every question
([ADR 0012](adr/0012-briefing-record-and-statistics.md)). The site supplies the configuration and, optionally,
alert thresholds.

The configuration. Everything that could change a briefing, and the short id of it all.
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

What happened next. The routes that already receive these signals mark the briefing's record:
`log.mark(briefing_id, reported=True)`, `useful=True` or `False`, `corrected=True`, `followed_up=True`.

The alert thresholds are the site's `[alerts]` settings. They start unset. The first weekly report proposes
values from that week's figures, and the owner writes them in. An alert never fires from a number nobody chose.

From `examples/minimal-site/config/settings.toml`:

```toml
[alerts]
# Thresholds start unset: the first weekly report proposes them from that week's figures, and the owner writes
# them here. The names are p95_full_briefing_ms, error_rate, check_failure_rate, not_useful_rate, daily_cost_usd.
```

An unknown name under `[alerts]` stops the statistics commands and names it. A figure trips only when it is over
its threshold.

The structured log is turned on by the site, once for each process, by giving the logger `observe.LOGGER` a
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

Visitor codes are forgotten after their day. The spending record keeps the day's visitor code on a row for
that day only (`Spending.forget_visitors`, run with the first model call of each day). The package's `tidy`
command does the same on a day with no model call. A site needs to do nothing but run `tidy` nightly.

## 10. The owner's commands and the check route

A site keeps its own Typer app and adds the package's command groups to it (`wts_core.cli`). For backups, reports
and statements every name and every printed line is the site's.

From `examples/minimal-site/src/parks/cli.py`:

```python
app.add_typer(ops_commands(SITE, load, BACKUPS, OPS_WORDING))  # backup, restore, offsite, backup-check
```

A backup forgets before it copies. Every site's timer makes the backup first and tidies after it. So the
backup command first does, in the database it is about to copy, the forgetting the tidy does for the days
before today: who each model call was for and its time of day, and every visitor secret but today's (nothing
the site still serves). Without it each night's backup would hold the whole of the day before as it was while
that day lasted, for as long as the backup is kept. A site gives the command nothing for this: a database that
has the package's tables is the package's to keep to its promises, and is opened for that alone, with no
migration and no import of the site's run. A file with none of the package's spending is copied as it is.
Where the forgetting cannot be done (a database with spending that this version has not opened yet) the backup
is still made and sent, a line on standard error says what it holds, and the command ends with status 1.

From `examples/minimal-site/src/parks/cli.py`:

```python
app.add_typer(replies_commands(_replies, REPLIES_COMMANDS, REPLIES_WORDING))  # reports …, statements …, hide, …
```

| Group | Commands | What a site passes |
|---|---|---|
| `ops_commands` | `backup`, `restore`, `offsite`, `backup-check` | its `BackupSpec` and `OpsWording`; another off-site store if it has one |
| `replies_commands` | `reports list/show/close`, `statements list/show/publish/decline/update/withdraw/remove/log`, `hide`, `unhide`, `hidden`, `waiting`, `would-lapse`, `tidy-replies` | `RepliesCommands` (what each command is called) and `RepliesWording` |
| `stats_commands` | `stats`, `weekly-report`, `tidy`, `propose-questions` | its `[alerts]` thresholds, its reports folder, its embedder and the similarity for themes, its cache hours, its experiment's state |
| `eval_commands` | `eval run` (and `--arm`), `eval compare`, `eval replay` | its `EvalSite`, configuration, prices, thresholds and the most a run may spend; its spending record; its experiment's arms |

Telling the site that a page may have changed. `replies_commands(..., changed=…)` is called after each
change a page may show, with what changed and what kind of change it was: `changed(row, kind)`, where `kind` is
one of `cli.CHANGES`. For a statement (`published`, `updated`, `withdrawn`, `removed`, `declined`) the row is the
statement as it now is; for `report_closed`, the report; for `hidden` and `shown`, the item's `item` (and its
`note`, when hidden). A site whose pages are built ahead of time writes them again there, as Where Landlords
Stand does; a site drops a hidden briefing's cached copy there, or marks a briefing's record as corrected. (A
callback that takes the row alone still works in 0.3.x, with a `DeprecationWarning`.) What the function returns
is added to the fields its line
is filled with (`"published #{id}: {pages_changed} pages written again"`).

Keeping an older shape of command. The commands are subcommands (`statements publish 3`). A site that had
one command with an option for each action (`statements --publish 3`: Where Landlords Stand) and must keep that
working for a while keeps it itself, as the callback of a group of its own, and gives the group to
`replies_commands`. The package's commands join that group, under the site's word, in one call. As in Where
Landlords Stand's `cli.py`:

```python
reports_app = typer.Typer(help="Readers' reports of mistakes. With no command, those still open.")
statements_app = typer.Typer(help="Statements from landlords in their own words. With no command, those waiting.")


@statements_app.callback(invoke_without_command=True)
def statements(ctx: typer.Context, publish: int = typer.Option(None), checked: str = typer.Option("")) -> None:
    if ctx.invoked_subcommand is not None:
        return                      # one of the package's commands was asked for: nothing to do here
    ...                             # the old shape: `landlords statements --publish 3 --checked "..."`


app.add_typer(replies_commands(
    _replies,
    # this site hides nothing yet, and its own `nightly` does the housekeeping: four commands left out,
    # and so four lines its RepliesWording need not have
    RepliesCommands(listed=("pending",), about_option="--landlord", hide=None, unhide=None, hidden=None, tidy=None),
    REPLIES_WORDING, about=_landlord, changed=_written_again,
    groups={"reports": reports_app, "statements": statements_app}))
```

A group named in `groups` that no command is in is refused when the commands are built.

The clock. `ops_commands`, `stats_commands` and `eval_commands` each take a clock, or a function that gives
one when a command runs. A site builds its commands once, when its command line is imported, so a test that wants
a backup named by a time of its choosing gives the function (`clock=lambda: CLOCK`) and stands its own clock in
afterwards.

A `BackupSpec` says what the site's backups are called and what a restored database must hold.

From `examples/minimal-site/src/parks/site.py`:

```python
BACKUPS = BackupSpec(
    prefix="parks-state-",  # parks-state-2026-11-13.sqlite.gz: what marks a backup, here and off site, as this site's
    keep=14,  # how many stay on the server; `parks backup --keep` says otherwise for one run
    # How many nightly copies stay off site, and so about how many days a deleted address can remain in a backup.
    # Nothing else that holds old data may be kept longer (`parks tidy` is told this figure too).
    keep_offsite=60,
    required_tables=("wts_schema", "wts_spending", "wts_briefings", "wts_reports", "wts_statements"),
    # This site has no table of its own, so a sister site's backup has all the tables above. Its state database is
    # marked as this site's when it is opened (open_state below), and a restore refuses one marked as another's.
    site=SITE.package,
)
```

`keep_offsite` is how many of the site's copies stay in the off-site store: 60 if the spec does not say, which is
every site's figure today.

One command each night. The package's `tidy` is the housekeeping a site's timer runs. It applies the
retention to the record of briefings and to the weekly reports, forgets old visitor codes, and deletes copies of
the database made before an import once they are older than `backup_days` (a site passes the days it keeps a
backup). Given `also_tidy`, it then does the rest of the site's nightly housekeeping and prints what each step
says. `cli.replies_tidy` is the right of reply's step: statements nobody decided in three months lapse, old
confirming addresses and the contact details of old reports are deleted, and earlier days' counts are emptied. It
says what it did in the site's own words (`RepliesWording.tidied`).

From `examples/minimal-site/src/parks/cli.py`:

```python
    backup_days=BACKUPS.keep_offsite,  # tidy deletes copies of the database older than the backups are kept
    # The one command the site's timer runs each night does the right of reply's housekeeping too: what the
    # privacy notice promises of old addresses and undecided statements must not wait for a visitor.
    also_tidy=[replies_tidy(_replies, REPLIES_WORDING)],
```

`tidy` also keeps the site's old tables within its promises and drops them on the day the site stated, where
its state database declares any (`OldTables`, section 6), and says what it did.

The site's routes do the same housekeeping on every report and statement, and the nightly family check does it
when it asks what is waiting. The command is for the night nobody writes in, on a site with no check token set.
A site with no record of briefings (and so no `tidy`) runs `tidy-replies`, which `replies_commands` adds
(`RepliesCommands.tidy` names it, or leaves it out with `None`, as the example does).

What would lapse, before it does. Every write, every owner's listing and `waiting` tidy before they answer.
After a site's import of its old rows, the first of them lapses whatever has already waited three months: a
statement nobody decided is declined, and an old open report loses its contact. `replies.would_lapse()` reads
what that tidy would do and does nothing: the statements and reports concerned, each with its number, when it
was sent and its age in days, and never an address. The `would-lapse` command prints it, in the site's line
(`RepliesWording.lapsing`, which a site must give, or leave the command out with
`RepliesCommands(would_lapse=None)`). The owner runs it whenever they want to know.

From `examples/minimal-site/src/parks/cli.py`:

```python
    lapsing=lambda w: (f"At the next tidy, {w['statements']} statements would lapse and {w['reports']} open "
                       f"reports would lose their contact details (those sent before {w['before']})."
                       + (f" Statements: {w['statement_ids']}." if w["statements"] else "")
                       + (f" Reports: {w['report_ids']}." if w["reports"] else "")),
```

That reads the package's tables, so it answers only once the site's rows are in them.

The `waiting` line when nothing waits. `RepliesWording.waiting` is filled with `reports`, `statements`,
`hidden` and `oldest_working_days`. With no report and no statement waiting there is no oldest. A site gives
`RepliesWording.nothing_waiting`, a line said in its place then; or makes `waiting` a function, which is given
`oldest_working_days` as `None` and words it as it likes, as the example does. A template with neither is filled
with an empty text there.

An older name for a command says what replaces it. A name kept through `RepliesCommands.also` does its
work and prints, on standard error, `"list-statements" is an older name for this command: it is now
"statements".` ([ADR 0008](adr/0008-reports-and-statements.md)). The line is `RepliesWording.old_name` where the
site gives one (`{old}`, `{new}`); `RepliesCommands(also_silent=True)` keeps old names silent, for a site whose
own scripts read standard error.

The order of the night's work. `tidy` makes the package's own deletions, then runs the site's steps
(`also_tidy`: the right of reply's), then keeps the site's old tables within its promises, and last writes the
state database's file out afresh, so that nothing deleted is left in it or in the backups made from then on
(section 6). Where the site was using the file at that moment it says plainly that this was NOT done; one such
night is ordinary, and on the second night running the command ends with status 1. A site gives it its cache
hours, so that cached answers older than the site keeps them go on a night when no new answer is stored.

From `examples/minimal-site/src/parks/cli.py`:

```python
    also_tidy=[replies_tidy(_replies, REPLIES_WORDING)],
    # tidy also deletes cached answers older than the site keeps them, which otherwise go when the next is stored
    cache_hours=lambda: float(load().usage["answer_cache_hours"]),
    experiment=_experiment,  # stats says whether the experiment is running, and why not
```

Proposed test questions. `propose-questions --since 30d` writes, under the site's data folder, a file of
test questions proposed from the period's real questions (those that found no records, were rated not useful, or
whose briefings the checks flagged most), in the shape of the site's `eval/questions.toml`, and prints its path.
It adds nothing to the test set: a person reads it, removes anything personal, says what each question should
find, and copies what is approved across by hand ([`IMPROVING.md`](IMPROVING.md#growing-the-test-sets)). Only
questions the record may hold are proposed, and of saved briefings only those not since withdrawn, corrected or
reported by a reader.

The site says which briefings are hidden, and the command will not run until it has. A briefing hidden
while a concern about it is decided must not have its question copied into another file meanwhile, and this
group cannot find that out for itself: nothing near the record of briefings reads the right of reply's tables
([ADR 0008](adr/0008-reports-and-statements.md)). So the site gives a function of a saved briefing's id.

From `examples/minimal-site/src/parks/cli.py`:

```python
    # no question of a briefing that is hidden while a concern about it is decided is proposed as a test question
    proposals_leave_out=lambda briefing: _replies().hidden(f"/b/{briefing}") is not None,
```

A site that also shows a briefing as hidden because of what it cites (a hidden record, a hidden council) asks
the same thing its pages ask. A site where nothing can be hidden says so: `lambda briefing: False`.

The file is named for the day it was made and the first day of the period it covers
(`2026-11-16-from-2026-10-17.toml`), and the nightly `tidy` deletes it once that first day is as old as the
record of briefings is kept: so a file made for a year back does not keep a question a year longer than the
record does.

`stats --json` prints one object: `{"stats": …, "tripped": […], "counts": {…}}`. The figures
(`Stats.as_dict()`) are under `stats`, not at the top; `tripped` is the sentences for what is over its threshold,
and `counts` the daily totals the site counts.

`weekly-report` loads the site's real embedder. It always groups readers' questions by meaning where the
site gives `stats_commands` an embedder, so the model is loaded each time the command runs. A site's test of the
command gives a stand-in embedder in its place (`testing.RecordingEmbedder`, or the hashing embedder), or the
test loads the real model, or tries to download it.

An evaluation run's output folder must be on the data volume in a container. The image's `/app` is
read-only and the container a command runs in is removed when it ends, so `eval run` on the server cannot keep
its run under the code. `eval_commands(runs=…)` is asked when the command runs: give it a folder under the
site's data folder there ([`NEW-SITE.md`](NEW-SITE.md), step 10).

Figures read when a command runs. `eval_commands`' `max_cost_usd` and `stats_commands`' `similarity` each
take a number or a function that gives one. A function is called when the command runs, so the figure can live
in the site's settings.

From `examples/minimal-site/src/parks/cli.py`:

```python
    max_cost_usd=lambda: float(load().section("eval")["max_cost_usd"]),  # no run starts without a limit
```

A restore refuses a sister site's backup. A restore takes a file that has the tables `required_tables`
names. Two sites built on the package can have exactly the same tables, so the state database also carries a mark
of whose it is. `StateDB(..., site=SITE.package)` writes the site's package name into `wts_kv` (key `site`) the
first time the site opens the file, never writes over another's, and refuses to open a file marked as another
site's. With `site=` in its `BackupSpec`, a site's restore refuses a backup marked as another's
(`RestoreRefused.why` is `"other-site"`).

The example's `open_state` (section 6) does this. A backup with no mark is accepted as before, on its tables:
every backup made before the site started marking its database has none, and must still be restorable. A site
with a table of its own should still name it in `required_tables`.

The check route answers the nightly family check ([ADR 0010](adr/0010-ci-and-nightly-check.md)). `check_route`
returns a plain function; the site's own route calls it.

From `examples/minimal-site/src/parks/app.py`:

```python
    check = check_route(SITE, token=parks.check_token, replies=replies,
                        backups=lambda: backup_ages(settings.backups_dir, BACKUPS, clock=parks.clock),
                        figures=lambda: last_day_figures(parks.log, clock=parks.clock),
                        # the newest weekly report's totals, for the family's summary; and the experiment's state
                        weekly=lambda: latest_week_figures(parks.db),
                        experiment=lambda: parks.experiment.state(parks.clock), clock=parks.clock)

    @app.get("/api/check")
    def api_check(authorization: str | None = Header(None)) -> JSONResponse:
        status_code, body = check(authorization)
        return JSONResponse(body, status_code=status_code)
```

`weekly` puts the newest weekly report's totals in the answer (`cli.latest_week_figures`: numbers only), from
which the charity's nightly check writes the family's summary without reaching any server; `experiment` says
whether the site's experiment is running and, if not, why.

The site's ask route must also treat a question that carries the check token as the nightly check's: no cache key,
and `kind="check"`. The example does this in `is_the_nightly_check` in `parks/app.py`.

With no token set, the address must look as if it were never there. `check_route` then answers 404 with the
body a web framework gives a missing address (`{"detail": "Not Found"}`), which is right for a site whose missing
addresses answer that way, as the example's do. A site that answers a missing address with a page of its own (a
static site's `404.html`, as on Where Landlords Stand) would give the route away by answering this one address
differently. Such a site adds the route only when a token is set, so that with none the address falls through to
its own "not found" like any other:

```python
    if SITE.env("CHECK_TOKEN"):
        check = check_route(SITE, token=SITE.env("CHECK_TOKEN"), replies=replies, clock=clock)

        @app.get("/api/check")
        def api_check(authorization: str | None = Header(None)) -> JSONResponse:
            status_code, body = check(authorization)
            return JSONResponse(body, status_code=status_code)
```

## 11. The three checks every site's tests must call

All are in `wts_core.testing`, and all run over the site's real pipeline.

- `assert_statements_stay_out(...)`: a published statement never reaches the model, the embedder, the index, the
  record or a log ([ADR 0008](adr/0008-reports-and-statements.md)). The example calls it in
  `tests/test_replies.py`.
- `assert_no_reader_data(...)`: after a question, nothing kept or logged holds the reader's address; the day's
  visitor code is only where it is counted; the question is only where the privacy notice says a question is
  kept. The example calls it in `tests/test_privacy.py`.
- `assert_briefings_tied_to_no_one(state, clock=…)`: once its day is over, a record of a briefing is beside
  nothing that says whose it was. It fails on a spending row of a day gone by that still holds a visitor's
  code, an account, any mark that it was an account's, or a time finer than its day; on a record's time finer
  than the hour; on anything kept about an account more finely than the calendar month and the cent; and then
  it makes the attack itself (`testing.split_by_account_totals`): every way of making up each account's kept
  total out of the records of its month, failing on any record that is in every one. Call it after the site has
  been used and a day has passed (the nightly `tidy` run, or the next day's first model call recorded). A site with
  accounts gives it a database in which an account was not alone: if the month's only briefings are one
  account's, they are plainly its own, the check fails, and it says so
  ([ADR 0012](adr/0012-briefing-record-and-statistics.md) has what is promised, and the whole list of what is
  not). The example calls it in `tests/test_privacy.py`.

`assert_statements_stay_out` takes the package's stand-ins for the model, the embedder and the index, or anything
of the site's own that can say what they say (`testing.privacy.ModelSeen`, `EmbedderSeen`, `IndexSeen`): a real
`adapters.lancedb.LanceIndex` is passed as it is (it has `everything()`), and a real model client over a faked
SDK is wrapped in a few lines that give its `requests`.

## 12. What a site must never do

These rules are what keep four sites from drifting apart again
([ADR 0007](adr/0007-versioning.md); [`CONTRIBUTING.md`](../CONTRIBUTING.md), rule 7).

- Never patch the installed copy. A fix is made in the package, released, and taken by each site in a pull
  request. A fix made in place is how the four copies drifted.
- Never import a private name. A name that starts with an underscore is private everywhere, and so is a
  module-level name that is not in its module's `__all__`.
- Never reach past `__all__`. The public interface is what `wts_core.__all__` and each submodule's `__all__`
  export. Anything else may change in any release without notice.
- Never subclass anything but `Settings` (and `Hooks`, whose methods are the hooks). `Verifier` and
  `LoadedWords` are final. A site that needs a class to behave differently asks for a hook.
- Never copy a module of the package into the site. If the package does not fit, the package is changed.

If a hook is missing, the right step is an issue or a pull request on the package, and an amended ADR if the
design has to change.
