# wts-core

The shared foundation of the [Where They Stand](https://wheretheystand.uk) sites.

Where They Stand's sites each answer questions from a public record, and each must keep the same promises to
readers: every claim checked against its source, spending kept within the charity's caps, nothing stored about a
reader beyond what the privacy notice says, and a right of reply for anyone named. This package holds the code
that keeps those promises, written once, so that a fix reaches every site and every site is held to the same
checks. Each site keeps what is its own: its record, how it finds sources, its pages and every word a reader sees.

Version 0.1.0, not yet released (13 November 2026). The four sites adopt it one at a time
([`docs/MIGRATION.md`](docs/MIGRATION.md)).

## What is in it, and what installs what

The package comes in two slices. **The base** needs nothing but Python. **The adapters** are the only code that
touches an outside tool, and each arrives with an extra.

| Install | Brings | Gives |
|---|---|---|
| `wts-core` | nothing but Python | settings; the state database; limits, cost and caps; the checks on briefings; the briefing desk and the streamer; reports and the right of reply; backup and restore; the record of each briefing, statistics and alerts; the evaluation harness; the testing helpers |
| `wts-core[cli]` | Typer | the owner's shared commands: backups, reports and statements, statistics, evaluation |
| `wts-core[offsite]` | httpx | off-site copies of backups |
| `wts-core[duckdb]` | DuckDB | the thread-safe DuckDB connection |
| `wts-core[ai]` | the model provider's library, fastembed, LanceDB, numpy, pyarrow | the adapters for the model, the embedder and the search index |

A site with no AI-written briefings installs `wts-core[cli,offsite]` and no AI library arrives with it: CI checks
that. A site with briefings installs `wts-core[cli,offsite,duckdb,ai]`. The reasons are in
[ADR 0001](docs/adr/0001-slices-and-module-boundaries.md).

## Quick start

The fewest lines that give a working `/api/ask`. It needs the base package and FastAPI, and no key: a recorded
briefing that ships with the package stands in for the model, and its documents for a search. Save it as
`quickstart.py`, run `uvicorn quickstart:app`, and post a question:

```bash
curl -N -X POST http://127.0.0.1:8000/api/ask -H 'Content-Type: application/json' \
     -d '{"question": "What have the councils decided about waste?"}'
```

```python
import re
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from wts_core import Messages, usage
from wts_core.briefing import Ask, BriefingDesk, TooManyRequests, sse
from wts_core.checks import COMMON_LOADED_WORDS, EVIDENCE_NOTES_STRICT, LoadedWords, Verifier, check_briefing
from wts_core.events import Completed, blocks_as_today, to_reader
from wts_core.ports import ModelRequest, Price
from wts_core.state import StateDB
from wts_core.testing.models import ScriptedModel, load_documents, recorded

# Every word a reader can be shown is the site's own: the package has none.
MESSAGES = Messages(
    too_many_requests="Too many requests. Please wait a minute.",
    visitor_daily_limit="You have reached today's limit on new briefings.",
    daily_cap="The site has reached today's budget for briefings.",
    monthly_cap="The site has reached this month's budget for briefings.",
    busy_visitor="Two of your briefings are still being written.",
    busy_site="The site is busy. Please try again in a minute.",
    sources_follow="{reason} The sources found are shown below.",
    sources_only="These are the sources found. No briefing was written.",
    briefing_failed="Something went wrong. Please try again.",
    model_declined="The model declined to answer this question.",
)
VERIFIER = Verifier(no_records="No records found.", evidence_notes=EVIDENCE_NOTES_STRICT)
LOADED_WORDS = LoadedWords(re.compile(rf"\b({COMMON_LOADED_WORDS})\b", re.IGNORECASE))

# A recorded briefing and the documents it was written from stand in for a model and a search.
MODEL = ScriptedModel(recorded("cited_briefing"))
DOCUMENTS = load_documents(recorded("cited_briefing"))


@dataclass(frozen=True)
class Source:  # what the checks read of a source
    n: int
    title: str
    blocks: tuple[str, ...]
    meta: dict = field(default_factory=dict)


def found(question):  # the site's own search goes here
    yield {"type": "plan", "plan": {"search": question}, "usage": None}
    yield {"type": "sources", "sources": [{"n": d.number, "title": d.title, "url": d.source} for d in DOCUMENTS]}


def write(question):  # the site's pipeline: sources first, then the model's words, then the checks
    yield from found(question)
    request = ModelRequest(model="synthetic-model", instructions="Use only the sources.", question=question,
                           documents=DOCUMENTS)
    for event in MODEL.stream(request):
        if not isinstance(event, Completed):
            yield dict(to_reader(event))
            continue
        sources = [Source(d.number, d.title, d.passages) for d in DOCUMENTS]
        report = check_briefing(blocks_as_today(event), sources, VERIFIER, LOADED_WORDS)
        yield {"type": "final", "answer": report, "usage": event.usage.as_stored(), "model": event.model,
               "stop_reason": event.stop_reason}


def sources_only(question, note):  # what a reader gets when a limit stops the briefing
    yield from found(question)
    yield {"type": "final", "answer": None, "usage": None, "note": note}


db = StateDB(Path("data/state.db"), migrations=usage.migrations())
spending = usage.Spending(db, usage.PriceTable(base=Price(input=3.0, output=15.0, cache_read=0.3)))
limits = usage.Limits(per_visitor_daily=30, per_account_daily=None, daily_cap_usd=3.0, monthly_cap_usd=50.0)
desk = BriefingDesk(
    messages=MESSAGES, limiter=usage.RateLimiter(20, forget_over=50_000),
    caps=usage.Caps(spending, limits, MESSAGES), in_progress=usage.BriefingsInProgress(2, 8, 0.10),
    spending=spending, cache=usage.SqliteAnswerCache(db), cache_hours=168,
    archive=usage.BriefingArchive(db, new_id=lambda: usage.token_id(8)), failures=usage.Failures(db),
    log=None, parse_model=None, config={})

app = FastAPI()


class Question(BaseModel):
    question: str


@app.post("/api/ask")
def ask(body: Question, request: Request):
    visitor = usage.visitor_code(db, request.client.host if request.client else None)
    try:
        desk.allow(visitor)  # the per-minute limit
    except TooManyRequests as exc:
        raise HTTPException(429, exc.message) from None
    key = usage.cache_key({"question": body.question.lower(), "model": "synthetic-model"}, length=64)
    events = desk.handle(Ask(question=body.question, visitor=visitor, cache_key=key,
                             write=lambda: write(body.question),
                             sources_only=lambda note, free: sources_only(body.question, note)))
    return StreamingResponse(sse(events), media_type="text/event-stream")
```

What the package did there: counted the request against the per-minute limit; looked in the answer cache; checked
the visitor's daily limit and the spending caps; ran the pipeline and passed its events on as server-sent events;
checked every citation against its source; recorded the cost; saved the briefing at its own address; and put it
in the cache, so the same question again costs nothing. A test (`tests/test_readme.py`) runs this code on every
change.

A real site is the same shape with its own parts in place of the stand-ins. The example site,
[`examples/minimal-site/`](examples/minimal-site/), is that site in full: settings from a file, a pipeline over a
record of its own, the record of each briefing, reports and statements, backups, the owner's commands and an
evaluation set. CI runs it end to end. To start a new site, copy it: [`docs/NEW-SITE.md`](docs/NEW-SITE.md).

## The hooks

Everything a site supplies, and where each is explained in [`docs/EXTENDING.md`](docs/EXTENDING.md).

| A site supplies | As | Section |
|---|---|---|
| Its name, package, settings prefix, hosts and versions | a `Site` object | [1.1](docs/EXTENDING.md#11-site-the-facts-fixed-in-code) |
| Its own settings | a subclass of `Settings` | [1.2](docs/EXTENDING.md#12-the-settings-subclass-and-the-prefix) |
| Limits, prices and models | `config/settings.toml` | [1.3](docs/EXTENDING.md#13-what-must-be-in-settingstoml), [4.2](docs/EXTENDING.md#42-spending-caps-and-prices) |
| Every word a reader or sender is shown | `Messages`, `ReplyMessages` | [2](docs/EXTENDING.md#2-wording) |
| Its loaded-words list and the verifier's own patterns | `LoadedWords`, `Verifier` | [3](docs/EXTENDING.md#3-the-checks-word-lists-and-the-verifiers-patterns) |
| Its pipeline and its sources-only search | two functions on an `Ask` | [4.3](docs/EXTENDING.md#43-ask-one-question-as-the-route-describes-it) |
| The answer cache's key, the instructions version, how sources are grouped | `Ask.cache_key`, `Site`, `group_of` | [4.4](docs/EXTENDING.md#44-briefing-defaults-the-cache-key-the-instructions-version-group_of) |
| Steps only this site has in the flow of a briefing | a subclass of `Hooks` | [4.5](docs/EXTENDING.md#45-hooks-the-steps-only-some-sites-have) |
| Where a statement may sit, and its limits | `Items`, `ReplyRules` | [5](docs/EXTENDING.md#5-items-and-replyrules-the-right-of-reply) |
| Rows from the tables it had before | an `Import` | [6](docs/EXTENDING.md#6-the-state-database-migrations-and-a-sites-one-off-import) |
| Another model provider, embedder, index or off-site store | an adapter that passes its contract test | [7](docs/EXTENDING.md#7-adapters-and-how-to-swap-one) |
| Its test questions | an `EvalSite` | [8](docs/EXTENDING.md#8-evalsite-the-sites-test-questions) |
| What the owner is alerted to | `[alerts]` in settings | [9](docs/EXTENDING.md#9-the-record-of-each-briefing-and-the-alert-thresholds) |
| The names and words of the owner's commands | arguments to the command groups | [10](docs/EXTENDING.md#10-the-owners-commands-and-the-check-route) |

A site never patches its installed copy, never imports a private name and never reaches past `__all__`
([section 12](docs/EXTENDING.md#12-what-a-site-must-never-do)).

## How a site pins a release

A site depends on the wheel attached to a tagged release, by its address, with the extras it uses. Its `uv.lock`
records the file's hash ([ADR 0006](docs/adr/0006-distribution.md)). In the site's `pyproject.toml`:

```toml
dependencies = [
    "wts-core[cli,offsite,duckdb,ai] @ https://github.com/rj-mitchell/wts-core/releases/download/v0.1.0/wts_core-0.1.0-py3-none-any.whl",
]

[tool.hatch.metadata]
allow-direct-references = true
```

The second table is needed with the build backend the sites use, which otherwise refuses a dependency written as
an address. A site calls the shared CI workflows in this repository at the same tag
(`rj-mitchell/wts-core/.github/workflows/python.yml@v0.1.0`), so it has one number to raise. An upgrade is a pull
request in the site that raises it.

The repository is public. Nothing here needs a token to fetch: not the wheel, not the workflows. The sites'
Docker images need no `git`.

## Read next

| Read | For |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | the design; its first page is a summary for the owner |
| [`docs/adr/`](docs/adr/) | twelve short decision records, each with the alternatives weighed |
| [`docs/AS-BUILT.md`](docs/AS-BUILT.md) | where the built package differs from the design's sketch, module by module |
| [`docs/EXTENDING.md`](docs/EXTENDING.md) | every hook a site has, each with an example from the example site |
| [`docs/NEW-SITE.md`](docs/NEW-SITE.md) | the checklist for a new site, and what happened when it was tried |
| [`docs/MIGRATION.md`](docs/MIGRATION.md) | for each existing site: what replaces what, and how sameness is proved |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | how code in this package is written |
| [`CHANGELOG.md`](CHANGELOG.md) | what changed in each version, and what a site must do |

The brief this answers is `plans/family/wts-core-brief.md` in the charity's repository.

## Working on the package

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy
uv run pytest
```

The example site has its own environment and its own tests: `cd examples/minimal-site && uv sync && uv run pytest`.

## Licence

AGPL-3.0, like the sites: see [`LICENSE`](LICENSE). Anyone may read, run, change and share this code. A changed
version that is run as a public service must offer its source to the people who use it.
