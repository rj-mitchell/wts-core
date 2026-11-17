# wts-core

[![CI](https://github.com/rj-mitchell/wts-core/actions/workflows/ci.yml/badge.svg)](https://github.com/rj-mitchell/wts-core/actions/workflows/ci.yml)

wts-core is the shared Python package behind the [Where They Stand](https://wheretheystand.uk) sites: Where MPs
Stand, Where Councils Stand, Where Countries Stand and Where Landlords Stand. Each site answers questions from a
public record and makes the same promises to readers: every claim is checked against its source, spending stays
within the charity's caps, nothing is kept about a reader beyond what the privacy notice says, and anyone named
has a right of reply. This package holds the code for those promises, so that a fix reaches every site and every
site is held to the same checks. Each site keeps its own record, search, pages and wording.

## Status

Beta, version 0.3.1 (17 November 2026). All four sites run on the package: each pins version 0.3.0 and was
running it on its live server on 17 November 2026. While the version is 0.x a minor release may change the public interface, and
[`CHANGELOG.md`](CHANGELOG.md) says what a site must do for each change.

## What it does

- Settings, the state database and its migrations, and a site's one-off import of its earlier tables.
- Per-minute and daily limits, prices, the spending record and the daily and monthly caps.
- The checks on briefings: citations, quotations, unsupported sentences, loaded words and British spelling.
- The flow of a briefing from question to last word, including the answer cache and the event stream to the
  reader.
- Readers' reports, the corrections log and the right of reply.
- Backup, restore and off-site copies.
- A record of each briefing, weekly statistics, alerts, live experiments and an evaluation harness.
- Shared GitHub Actions workflows and one toolchain definition for the sites' CI.

## Design

The package has two layers. The base needs nothing but the Python standard library. The adapters are the only
code that imports an outside library, each behind an interface in `wts_core.ports`, and each comes with an extra:

| Install | Brings | Gives |
|---|---|---|
| `wts-core` | nothing but Python | settings; the state database; limits, cost and caps; the checks on briefings; the briefing desk and the streamer; reports and the right of reply; backup and restore; the record of each briefing, statistics and alerts; the evaluation harness; the testing helpers |
| `wts-core[cli]` | Typer | the shared commands: backups, reports and statements, statistics, evaluation |
| `wts-core[offsite]` | httpx | off-site copies of backups |
| `wts-core[duckdb]` | DuckDB | the thread-safe DuckDB connection |
| `wts-core[ai]` | the model provider's library, fastembed, LanceDB, numpy, pyarrow | the adapters for the model, the embedder and the search index |

A site with no AI-written briefings installs `wts-core[cli,offsite]`, and CI checks that no AI library comes with
it. A site with briefings installs `wts-core[cli,offsite,duckdb,ai]`. Each site plugs in its own parts (its
settings, wording, word lists, pipeline and pages) through the hooks listed in
[`docs/EXTENDING.md`](docs/EXTENDING.md), and never patches the package or reaches past its public interface.
The design is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quick start

This is the smallest working `/api/ask` route. It needs [uv](https://docs.astral.sh/uv/) 0.11.32 and Python 3.12
or later, and no API key: a recorded briefing that ships with the package stands in for the model, and its
documents stand in for a search. First get a checkout and its environment:

```bash
git clone https://github.com/rj-mitchell/wts-core
cd wts-core
uv sync --all-extras
```

Save the code below as `quickstart.py` in the checkout, start it with `uv run uvicorn quickstart:app`, and post a
question from another terminal:

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

from wts_core import Messages, Settings, Site, usage
from wts_core.briefing import Ask, TooManyRequests, desk_parts, sse
from wts_core.checks import COMMON_LOADED_WORDS, EVIDENCE_NOTES_STRICT, LoadedWords, Verifier, check_briefing
from wts_core.events import Completed, blocks_as_today, to_reader
from wts_core.observe import briefing_config
from wts_core.ports import ModelRequest
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
    briefing_failed="The briefing could not be finished. Any sources found are shown above.",
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
            yield to_reader(event)
            continue
        sources = [Source(d.number, d.title, d.passages) for d in DOCUMENTS]
        report = check_briefing(blocks_as_today(event), sources, VERIFIER, LOADED_WORDS)
        yield {"type": "final", "answer": report, "usage": event.usage.as_stored(), "model": event.model,
               "stop_reason": event.stop_reason}


def sources_only(question, note):  # what a reader gets when a limit stops the briefing
    yield from found(question)
    yield {"type": "final", "answer": None, "usage": None, "note": note}


# The package has no limit or price of its own. A real site keeps these in config/settings.toml.
SETTINGS = Settings(
    site=Site(name="Quick start", package="quickstart", env_prefix="QUICKSTART", root=Path(".")),
    data_dir=Path("data"), config_path=Path("quickstart.py"), raw={"usage": {
        "per_visitor_daily_questions": 30, "daily_spend_cap_usd": 3.0, "monthly_spend_cap_usd": 50.0,
        "requests_per_minute": 20, "answer_cache_hours": 168, "briefing_estimate_usd": 0.10, "briefings_at_once": 8,
        "price_input_per_mtok": 3.0, "price_output_per_mtok": 15.0, "price_cache_read_per_mtok": 0.3,
        "cache_write_multiplier": 1.25}})

db = StateDB(SETTINGS.state_db, migrations=usage.migrations())
# One call checks the settings and makes the spending record, caps, limiter, answer cache and saved briefings.
parts = desk_parts(SETTINGS, db, MESSAGES, new_id=lambda chance: usage.token_id(8, random=chance),
                   at_once_per_visitor=2, forget_over=50_000, keep_failures=True)
desk = parts.desk(briefing_config(log=None, model="synthetic-model", parse_model=None, instructions="1",
                                  site_version="1"), log=None)  # log=None: no record of each briefing is kept

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

On each request the package counts the visitor against the per-minute limit, looks in the answer cache, checks
the visitor's daily limit and the spending caps, runs the pipeline and streams its events, checks every citation
against its source, records the cost, saves the briefing at its own address and caches it. When the file is
loaded it also checks that every limit, price and message the briefing flow needs has been given. A test
(`tests/test_readme.py`) runs this code on every change.

A real site has the same shape, with its own parts in place of the stand-ins. The example site in
[`examples/minimal-site/`](examples/minimal-site/) is a complete one: settings from a file, a pipeline over its own
record, the record of each briefing, reports and statements, backups, the shared commands and an evaluation set.
To start a new site, copy it and follow [`docs/NEW-SITE.md`](docs/NEW-SITE.md).

### Running the checks

In the checkout:

```bash
uv sync --all-extras
uv run ruff check .
uv run mypy
uv run pytest
```

The example site has its own environment and tests: run the same commands in `examples/minimal-site` (`uv sync`
without extras). Some tests compare the package with the sites' own code; they are skipped unless the sites'
repositories are checked out beside this one, or in the folder named by `WTS_SITES_DIR`.

## Using it in a site

A site depends on the wheel attached to a tagged release, by its address, with the extras it uses, and its
`uv.lock` records the file's hash ([ADR 0006](docs/adr/0006-distribution.md)). In the site's `pyproject.toml`:

```toml
dependencies = [
    "wts-core[cli,offsite,duckdb,ai] @ https://github.com/rj-mitchell/wts-core/releases/download/v0.3.1/wts_core-0.3.1-py3-none-any.whl",
]

[tool.hatch.metadata]
allow-direct-references = true
```

Hatchling, the build backend the sites use, refuses a dependency given as an address without the second table. A
site calls the shared CI workflows at the same tag (`rj-mitchell/wts-core/.github/workflows/python.yml@v0.3.1`),
so it has one version number to raise. The repository is public, so neither the wheel nor the workflows need a
token, and a site's Docker image does not need `git`.

## Documentation

[`docs/README.md`](docs/README.md) lists every document and who it is for. The main ones:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): the design, and the decision records in [`docs/adr/`](docs/adr/).
- [`docs/EXTENDING.md`](docs/EXTENDING.md): every hook a site has, each with an example from the example site.
- [`docs/NEW-SITE.md`](docs/NEW-SITE.md): the checklist for a new site.
- [`docs/UPGRADING.md`](docs/UPGRADING.md): moving a site to a new version, deploying it, and going back to a site's old code.
- [`docs/IMPROVING.md`](docs/IMPROVING.md): the weekly routine of reading the statistics and improving a site.
- [`CHANGELOG.md`](CHANGELOG.md): what changed in each version, and what a site must do.
- [`CONTRIBUTING.md`](CONTRIBUTING.md): the rules for changing the package, and how a release is made.

## Data

The package holds no public data. The recorded model streams in
[`src/wts_core/testing/recorded/`](src/wts_core/testing/recorded/) and the example site's minutes are invented test
material. Each site documents its own data sources and their licences.

## Licence

AGPL-3.0, like the sites: see [`LICENSE`](LICENSE). A modified version that is run as a public service must offer
its source to its users.
