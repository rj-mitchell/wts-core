# The public interface, sketched

**Where this page and the package differ, the code and [`AS-BUILT.md`](AS-BUILT.md) are the reference.**

13 November 2026. Part of the design for review: names and signatures, not code. The public interface is what each
module's `__all__` exports ([ADR 0007](adr/0007-versioning.md)); this page is its first draft. Signatures use
Python 3.12 syntax. `...` bodies are omitted. Anything not listed here is private.

Conventions: everything is passed in (no global state); times come from a `Clock`; nothing reader-facing has a
default; a refusal meant for a reader is an exception whose message the *site* supplied.

## `wts_core`

```python
__version__: str
__all__ = ["__version__", "Site", "Messages", "Settings", "load_settings"]
```

## `wts_core.ports`: what can be swapped

```python
class Clock(Protocol):
    def now(self) -> datetime: ...            # timezone-aware, UTC
    def monotonic(self) -> float: ...

class Random(Protocol):
    def token(self, nbytes: int) -> str: ...  # URL-safe
    def choice[T](self, items: Sequence[T], weights: Sequence[float]) -> T: ...

class ModelClient(Protocol):
    provider: str
    supports: frozenset[str]                  # "caching", "long_cache", "fallbacks", "effort", "citations"
    def stream(self, request: ModelRequest) -> Iterator[ModelEvent]: ...
    def structured[T: Schema](self, request: ModelRequest, schema: type[T]) -> tuple[T, Usage]: ...

class Schema(Protocol):                       # Pydantic's two methods, so ports needn't import Pydantic
    @classmethod
    def model_json_schema(cls) -> dict[str, Any]: ...
    @classmethod
    def model_validate(cls, data: Any) -> Self: ...

class Pricing(Protocol):
    def price_for(self, model: str) -> Price: ...             # raises UnknownModel
    def cost(self, usage: Usage, model: str) -> float: ...    # US dollars, 6 places

class Embedder(Protocol):
    id: str                                   # the model's name and weights hash
    dimension: int
    def embed_documents(self, texts: Sequence[str]) -> Vectors: ...
    def embed_query(self, text: str) -> Vector: ...

class VectorIndex(Protocol):
    meta: IndexMeta                           # embedder id, dimension, number type, schema version
    def replace(self, keys: Sequence[str], rows: Sequence[Row]) -> None: ...
    def add_vectors(self, keys: Sequence[str], rows: Sequence[Row], vectors: Vectors) -> None: ...
    def search_words(self, query: str, where: str | None, limit: int) -> list[Row]: ...
    def search_meaning(self, vector: Vector, where: str | None, limit: int) -> list[Row]: ...
    def build_indexes(self) -> None: ...
    def tidy(self) -> None: ...
    def rebuild(self, embedder: Embedder) -> None: ...

class OffsiteStore(Protocol):
    def put(self, path: Path) -> StoredFile: ...
    def list(self, prefix: str) -> list[StoredFile]: ...
    def delete(self, file: StoredFile) -> None: ...

class Limiter(Protocol):
    def allow(self, key: str) -> bool: ...

class InProgress(Protocol):
    def start(self, key: str) -> Busy | None: ...             # Busy.reason: "visitor" | "site"
    def finish(self, key: str) -> None: ...
    def pending_usd(self, besides: int = 0) -> float: ...

# storage, one small interface per need (ADR 0002); SQLite versions are in wts_core.state
class KeyValue(Protocol): ...        # get, set, delete_like
class SpendingRecord(Protocol): ...  # add, spent_since, briefings_today
class AnswerCache(Protocol): ...     # get, put
class BriefingArchive(Protocol): ... # save, get, withdraw, withdrawn
class BriefingLog(Protocol): ...     # write, mark, since
class ReplyStore(Protocol): ...      # the reports and statements tables

# values
@dataclass(frozen=True)
class Usage:
    input_uncached: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0
    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> Usage: ...   # both of today's forms
    def as_stored(self) -> dict[str, int]: ...                           # today's column meanings

@dataclass(frozen=True)
class Price: input: float; output: float; cache_read: float; cache_write_multiplier: float

@dataclass(frozen=True)
class Document: number: int; title: str; source: str; passages: tuple[str, ...]

@dataclass(frozen=True)
class ModelRequest:
    model: str
    instructions: str
    question: str
    documents: tuple[Document, ...] = ()
    max_tokens: int = 16000
    effort: str | None = None
    cache_instructions: Literal["off", "short", "long"] = "short"
    fallbacks: bool = True

class UnknownModel(LookupError): ...
class IndexOutOfDate(RuntimeError): ...       # .stored, .wanted
```

## `wts_core.events`: the briefing's event format

```python
EVENTS_VERSION = 1

# from a model adapter (typed; nothing provider-specific)
@dataclass(frozen=True)
class TextDelta: text: str
@dataclass(frozen=True)
class CitationDelta: document: int | None; quoted: str
@dataclass(frozen=True)
class Block: text: str; citations: tuple[Citation, ...] = ()
@dataclass(frozen=True)
class Citation: document: int | None; quoted: str
@dataclass(frozen=True)
class Completed: blocks: tuple[Block, ...]; model: str; stop_reason: str; usage: Usage
type ModelEvent = TextDelta | CitationDelta | Completed

# to a reader (today's JSON, described not rebuilt)
class PlanEvent(TypedDict, total=False): type: Literal["plan"]; plan: dict[str, Any]; usage: dict | None; parse_error: str
class SourcesEvent(TypedDict, total=False): type: Literal["sources"]; sources: list[dict]; candidates: int; semantic: bool; evidence: dict
class TextEvent(TypedDict): type: Literal["text"]; text: str
class CitationEvent(TypedDict, total=False): type: Literal["citation"]; search_result_index: int | None; cited_text: str
class FinalEvent(TypedDict, total=False):
    type: Literal["final"]; answer: Answer | None; usage: dict | None; model: str; stop_reason: str
    cached: bool; briefing_id: str; note: str
class ErrorEvent(TypedDict): type: Literal["error"]; message: str
type ReaderEvent = PlanEvent | SourcesEvent | TextEvent | CitationEvent | FinalEvent | ErrorEvent

def to_reader(event: TextDelta | CitationDelta) -> ReaderEvent: ...   # today's "text" and "citation" shapes
def blocks_as_today(done: Completed) -> list[dict[str, Any]]: ...     # what the verifier and saved data hold
```

## `wts_core.settings` and the site's own facts

```python
@dataclass(frozen=True)
class Settings:                       # sites subclass this, and only this
    raw: dict[str, Any]; data_dir: Path; config_path: Path; overrides: dict[str, Any]
    def section(self, name: str) -> dict[str, Any]: ...
    @property
    def answer(self) -> dict[str, Any]: ...
    @property
    def usage(self) -> dict[str, Any]: ...
    @property
    def state_db(self) -> Path: ...   # the site says the file's name

def load_settings[S: Settings](cls: type[S], site: Site, config_path: str | Path | None = None,
                               env: Mapping[str, str] | None = None, **overrides: Any) -> S: ...
def save_local_settings(data_dir: Path, updates: dict[str, dict[str, Any]], written_by: str) -> Path: ...
def check_settings(settings: Settings, site: Site) -> None: ...      # raises SettingsError naming the key

@dataclass(frozen=True)
class Site:
    name: str                         # "Where Councils Stand"
    package: str                      # "councils"
    env_prefix: str                   # "COUNCILS"
    root: Path                        # the repository's root
    hosts: tuple[str, ...]
    state_file: str                   # "state.db" or "state.sqlite"
    instructions_version: str
    backup: BackupSpec
    version: str

@dataclass(frozen=True)
class Messages:                       # every field required; the package has no wording of its own
    too_many_requests: str
    visitor_daily_limit: str
    account_daily_limit: str | None   # only Where MPs Stand has accounts
    daily_cap: str
    monthly_cap: str
    busy_visitor: str
    busy_site: str
    sources_follow: str               # "{reason} The sources found are shown below."
    sources_only: str
    briefing_failed: str
    model_declined: str
    replies: ReplyMessages            # every refusal a sender can be shown, the heading, the disclaimer
```

## `wts_core.state`

```python
class StateDB:
    def __init__(self, path: Path, *, migrations: Sequence[Migration] = (), imports: Sequence[Import] = (),
                 clock: Clock = SYSTEM_CLOCK) -> None: ...
    def connect(self) -> ContextManager[sqlite3.Connection]: ...   # rows by name; commits on success
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...

@dataclass(frozen=True)
class Migration: number: int; name: str; statements: tuple[str, ...]   # additive only
@dataclass(frozen=True)
class Import: name: str; statements: tuple[str, ...]; needs: tuple[str, ...]   # a site's own, run once

def package_migrations() -> tuple[Migration, ...]: ...
def backup_before_first_import(db: StateDB) -> Path | None: ...
```

## `wts_core.usage`

**Built** (`src/wts_core/usage/`); this section is as built, and departs from the first sketch where the sites' code
required it: a model with no entry of its own takes the base prices, as today, and `require` is the start-up check a
site asks for; prices and limits are read from the `[usage]` mapping; saved briefings are kept here
(`BriefingArchive`), with the interfaces `ports` does not have; the spending record also gives the figures for the
owner's reports; and the limiter's size and the way a briefing's id is made have no default.

```python
class RateLimiter:                                             # implements ports.Limiter; in memory, one process
    def __init__(self, per_minute: int, *, forget_over: int, clock: Clock = SYSTEM_CLOCK) -> None: ...
    def allow(self, key: str) -> bool: ...

def network_of(address: str | None) -> str: ...               # IPv4 address, or an IPv6 /64
def client_address(headers: Mapping[str, str], peer: str | None, *, behind_proxy: bool,
                   trust_forwarded_first: bool) -> str | None: ...
def visitor_code(kv: KeyValue, address: str | None, *, day: str | None = None, forget_undated_salt: bool = False,
                 clock: Clock = SYSTEM_CLOCK, random: Random = SYSTEM_RANDOM) -> str: ...

@dataclass(frozen=True)
class PriceTable:                                              # implements ports.Pricing
    base: Price; models: tuple[tuple[str, Price], ...] = ()
    @classmethod
    def from_settings(cls, usage: Mapping[str, Any], *, section: str = "usage") -> PriceTable: ...
    def price_for(self, model: str | None) -> Price: ...       # the base prices where the model has no entry
    def cost(self, usage: Usage | None, model: str | None) -> float: ...     # US dollars, 6 places
    def require(self, models: Iterable[str | None], *, base_counts: bool) -> None: ...   # raises UnknownModel

class Spending:                                                # implements ports.SpendingRecord, SpendingFigures
    def __init__(self, db: StateDB, pricing: Pricing, *, clock: Clock = SYSTEM_CLOCK) -> None: ...
    def add(self, kind: str, model: str | None, usage: Usage | Mapping[str, Any] | None, *,
            visitor: str | None = None, account: int | None = None) -> float: ...   # no row when there is no usage
    def spent_since(self, since: str) -> float: ...
    def briefings_today(self, *, visitor: str | None = None, account: int | None = None) -> int: ...
    def totals(self, since: str) -> SpendingTotals: ...
    def by_day(self, since: str) -> list[DaySpending]: ...
    def by_account(self, since: str) -> list[AccountSpending]: ...

class SpendingFigures(Protocol): ...   # totals, by_day, by_account
@dataclass(frozen=True)
class SpendingTotals: spent_usd: float; calls: int; briefings: int; visitors: int
@dataclass(frozen=True)
class DaySpending: day: str; spent_usd: float; calls: int; briefings: int
@dataclass(frozen=True)
class AccountSpending: account: int | None; public: bool; spent_usd: float; calls: int; visitors: int

@dataclass(frozen=True)
class Limits:
    per_visitor_daily: int; per_account_daily: int | None; daily_cap_usd: float; monthly_cap_usd: float
    @classmethod
    def from_settings(cls, usage: Mapping[str, Any], *, section: str = "usage") -> Limits: ...

class Caps:
    def __init__(self, spending: SpendingRecord, limits: Limits, messages: Messages, clock: Clock = SYSTEM_CLOCK) -> None: ...
    def refusal(self, *, visitor: str | None, account: int | None = None, pending_usd: float = 0.0) -> Refusal | None: ...
    def site_paused(self, pending_usd: float = 0.0) -> Refusal | None: ...   # for a status page

@dataclass(frozen=True)
class Refusal: kind: Literal["visitor_limit", "account_limit", "daily_cap", "monthly_cap", "busy_visitor", "busy_site"]; message: str
def busy_refusal(busy: Busy, messages: Messages) -> Refusal: ...

class BriefingsInProgress:                                     # implements ports.InProgress; in memory, one process
    def __init__(self, per_key: int, total: int, estimate_usd: float) -> None: ...
    @property
    def running(self) -> dict[str, int]: ...
    def start(self, key: str) -> Busy | None: ...
    def finish(self, key: str) -> None: ...
    def pending_usd(self, besides: int = 0) -> float: ...

def cache_key(parts: Mapping[str, Any], *, length: int = 64) -> str: ...
class SqliteAnswerCache:                                       # implements ports.AnswerCache
    def __init__(self, db: StateDB, *, clock: Clock = SYSTEM_CLOCK) -> None: ...
    def get(self, key: str, max_hours: float) -> list[dict[str, Any]] | None: ...
    def put(self, key: str, events: list[dict[str, Any]], max_hours: float) -> None: ...

class FailureLog(Protocol): ...        # note, recent
class Failures:                                                # implements FailureLog
    def __init__(self, db: StateDB, *, clock: Clock = SYSTEM_CLOCK) -> None: ...
    def note(self, kind: str, question: str | None, error: str) -> None: ...
    def recent(self, limit: int | None = 20, *, since: str | None = None) -> list[dict[str, Any]]: ...

@dataclass(frozen=True)
class SavedBriefing:
    id: str; created_at: str; question: str; options: dict[str, Any]; events: list[dict[str, Any]]
    extra: dict[str, Any] = {}; withdrawn_at: str | None = None; withdrawn_reason: str | None = None
@dataclass(frozen=True)
class BriefingListing: id: str; created_at: str; question: str; withdrawn_at: str | None; withdrawn_reason: str | None
class SavedBriefings(Protocol): ...    # new_id, save, get, withdraw, withdrawn, recent
class BriefingArchive:                                         # implements SavedBriefings
    def __init__(self, db: StateDB, *, new_id: Callable[[], str], clock: Clock = SYSTEM_CLOCK) -> None: ...
    def new_id(self) -> str: ...
    def save(self, question: str, options: Mapping[str, Any], events: Sequence[Mapping[str, Any]], *,
             id: str | None = None, extra: Mapping[str, Any] | None = None) -> SavedBriefing: ...
    def get(self, id: str) -> SavedBriefing | None: ...
    def withdraw(self, id: str, reason: str) -> bool: ...
    def withdrawn(self) -> list[BriefingListing]: ...
    def recent(self, limit: int = 50) -> list[BriefingListing]: ...
def token_id(nbytes: int, *, random: Random = SYSTEM_RANDOM) -> str: ...                   # Countries, Councils
def alphabet_id(alphabet: str, length: int, *, random: Random = SYSTEM_RANDOM) -> str: ... # MPs

def migrations() -> tuple[Migration, ...]: ...   # wts_spending, wts_answer_cache, wts_briefings, wts_failures
```

## `wts_core.checks`

**Built** (`src/wts_core/checks/`); this section is as built, and departs from the first sketch where the sites' code
required it: quotations are also looked for in a source's title and heading, so `check_quotes` needs four fields of
a source; the note-about-the-evidence pattern is a required argument, with both of today's forms exported; Where
Countries Stand's curled quotes need `recheck(..., curled=True)`; the three ranking functions take what the
sites' own arithmetic takes, so that results are identical; and `check_briefing` runs the checks in their one order.

```python
class SourceText(Protocol):          # what verify() needs of a site's source
    @property
    def n(self) -> int: ...          # its number, from 1
    @property
    def blocks(self) -> Sequence[str]: ...

class TitledSource(Protocol):        # what check_quotes() needs: the two above, a title and meta["heading"]
    @property
    def n(self) -> int: ...
    @property
    def blocks(self) -> Sequence[str]: ...
    @property
    def title(self) -> str: ...
    @property
    def meta(self) -> Mapping[str, Any]: ...

type Status = Literal["cited", "connective", "unsupported", "invalid"]
@dataclass
class Segment:                       # only text is required: the lists start empty, status as "cited"
    text: str; sources: list[int]; cited: list[dict]; status: Status; loaded: list[dict]; misquotes: list[dict]
    def to_dict(self) -> dict[str, Any]: ...
@dataclass
class Verification:
    segments: list[Segment]; no_records: bool; citations_total: int; citations_invalid: int
    unsupported_chars: int; cited_chars: int; quotes_total: int = 0; quotes_unverified: int = 0
    rules: int = RULES_VERSION
    @property
    def grounded_ratio(self) -> float: ...
    def markdown(self) -> str: ...
    def to_dict(self) -> Answer: ...                         # today's keys, exactly, then "rules"

RULES_VERSION = 1
COMMON_HONORIFICS: tuple[str, ...]
EVIDENCE_NOTES_WIDE: re.Pattern[str]      # Where MPs Stand's and Where Countries Stand's form today
EVIDENCE_NOTES_STRICT: re.Pattern[str]    # Where Councils Stand's form today

class Verifier:
    rules_version: int
    def __init__(self, *, no_records: str, evidence_notes: re.Pattern[str],
                 honorifics: Sequence[str] = COMMON_HONORIFICS) -> None: ...
    def verify(self, blocks: Sequence[Mapping[str, Any]], sources: Sequence[SourceText]) -> Verification: ...
    def check_quotes(self, report: Verification, sources: Sequence[TitledSource]) -> int: ...
    def drop_preambles(self, segments: list[Segment]) -> int: ...
    def recheck(self, answer: Answer | None, *, curled: bool = False) -> Answer | None: ...
        # only answers written under older rules (or with no stamp); never newly flags

class LoadedWords:
    def __init__(self, pattern: re.Pattern[str]) -> None: ...
    def flag(self, segments: list[Segment]) -> int: ...
    def still_loaded(self, answer: Answer | None) -> Answer | None: ...
COMMON_LOADED_WORDS: str             # the alternation all three sites share, for a site to extend

def to_british(text: str) -> str: ...
def britishise_segments(segments: Sequence[Segment]) -> None: ...
def outside_quotes(segments: Sequence[Segment]) -> list[tuple[int, int, str]]: ...
def curl_quotes(text: str) -> str: ...                       # Where Countries Stand's typography
def curl_answer(answer: Answer | None) -> Answer | None: ...
def curl_event(event: ReaderEvent) -> ReaderEvent: ...
def curl_events(events: list[ReaderEvent]) -> list[ReaderEvent]: ...

# every check in the one order the sites run them; the answer as it is sent and saved
def check_briefing(blocks: Sequence[Mapping[str, Any]], sources: Sequence[TitledSource], verifier: Verifier,
                   loaded_words: LoadedWords, *, curled: bool = False) -> Answer: ...

# wts_core.checks.balance: the three functions every site's ranking shares
def blend(word_scores: Sequence[float | None], meaning_scores: Sequence[float | None], *, word_weight: float,
          meaning_floor: float, meaning_ceiling: float) -> list[float]: ...
def recency_factor(d: date, today: date, *, recency: float, floor: float, min_half_life_years: float) -> float: ...
def round_robin[T](pool: Sequence[T], limit: int, *, group_of: Callable[[T], str], key_of: Callable[[T], str],
                   score_of: Callable[[T], float], caps: Sequence[tuple[Callable[[T], str], int]] = (),
                   seeds: Sequence[T] = ()) -> list[T]: ...
```

`rules_version` covers the package's rules. A site that later changes its own pattern or honorifics in a way that
should clear old flags raises the version it passes (an argument to add when the first site needs it).

## `wts_core.briefing`

```python
@dataclass
class Ask:
    question: str
    visitor: str | None
    write: Callable[[], Iterator[ReaderEvent]]               # the site's pipeline
    sources_only: Callable[[str, bool], Iterator[ReaderEvent]]   # (note, free): the site's sources-only stream
    account: int | None = None
    limiter_key: str | None = None
    cache_key: str | None = None                             # None: don't cache (a follow-up, on Countries)
    only_sources: bool = False
    model_available: bool = True
    follow_up: bool = False
    mode: str = "summary"
    kind: Literal["reader", "check", "eval"] = "reader"
    save: Callable[[FinalEvent, list[ReaderEvent], str], dict[str, Any]] | None = None   # the site's saved shape

class Hooks:                                                 # subclass and override; each default does nothing
    def on_cached(self, ask: Ask, events: list[ReaderEvent]) -> list[ReaderEvent]: ...
    def on_event(self, ask: Ask, event: ReaderEvent) -> ReaderEvent | None: ...
    def usages(self, ask: Ask, event: ReaderEvent) -> Iterable[tuple[str, str | None, Usage]]: ...
    def finish(self, ask: Ask, final: FinalEvent, kept: list[ReaderEvent]) -> FinalEvent: ...
    def for_this_reader(self, ask: Ask, final: FinalEvent) -> FinalEvent: ...
    def send(self, ask: Ask, event: ReaderEvent) -> ReaderEvent: ...   # e.g. Councils strips token counts

class BriefingDesk:
    def __init__(self, *, site: Site, messages: Messages, limiter: Limiter, caps: Caps, in_progress: InProgress,
                 spending: SpendingRecord, cache: AnswerCache, cache_hours: float, archive: BriefingArchive,
                 failures: Failures, log: BriefingLog | None, hooks: Hooks = Hooks(), clock: Clock = SYSTEM_CLOCK,
                 random: Random = SYSTEM_RANDOM, experiment: Experiment | None = None) -> None: ...
    def allow(self, key: str) -> None: ...                   # raises TooManyRequests (the site answers 429)
    def handle(self, ask: Ask) -> Iterator[ReaderEvent]: ...

class TooManyRequests(Exception): ...                        # .message from Messages

class Stages:                                                # the site's pipeline marks its own stages
    def mark(self, stage: Literal["parsed", "searched", "ranked", "sources_sent", "first_token", "written", "checked"]) -> None: ...
def current_stages() -> Stages: ...                          # a context variable set by the desk; a no-op outside one

def sse(events: Iterator[ReaderEvent], keep_alive: float = 10.0) -> Iterator[bytes]: ...
async def gather_first[A, B](parse: Awaitable[A], search_offline: Awaitable[B]) -> tuple[A, B]: ...   # phase 6's overlap helper
```

## `wts_core.replies`

```python
@dataclass(frozen=True)
class Item: address: str; about: str | None                  # about: the member, country, council or landlord

class Items(Protocol):                                       # the site's
    def resolve(self, pasted: str) -> Item: ...              # raises Refused with the site's words
    def shown(self, item: Item) -> bool: ...                 # exists, and not withdrawn

@dataclass(frozen=True)
class ReplyRules:
    max_words: int = 150; min_words: int = 1; max_chars: int = 1500
    name_max: int = 120; role_max: int = 200; link_max: int = 500
    daily_statements: int = 5; daily_reports: int = 10
    email_kept_months: int = 3
    report_kinds: Mapping[str, str] = ...                    # the words a form may send -> the stored kind

class Refused(ValueError): ...                               # the message is for the sender

type StatementStatus = Literal["pending", "published", "declined", "withdrawn", "removed"]
PUBLIC_FIELDS: tuple[str, ...]                               # id, item, about, name, role, text, link, date

class Replies:
    def __init__(self, store: ReplyStore, *, items: Items, rules: ReplyRules, messages: ReplyMessages,
                 clock: Clock = SYSTEM_CLOCK) -> None: ...
    # statements
    def submit(self, *, name: str, role: str, item: str, text: str, link: str | None, email: str,
               visitor: str | None = None, trap: str = "") -> int: ...
    def published(self, *, items: Sequence[str] = (), about: str | None = None) -> list[dict[str, Any]]: ...
    def publish(self, sid: int, *, checked: str, about: str | None = None) -> None: ...
    def decline(self, sid: int, reason: str) -> None: ...
    def update(self, sid: int, *, text: str | None = None, name: str | None = None, role: str | None = None,
               link: str | None = None, clear_link: bool = False, about: str | None = None) -> None: ...
    def withdraw(self, sid: int, note: str | None = None) -> None: ...
    def remove(self, sid: int, reason: str) -> None: ...
    def statements(self, status: StatementStatus | None = None) -> list[dict[str, Any]]: ...   # owner only
    def log(self, sid: int) -> list[dict[str, Any]]: ...
    def forget_old_emails(self) -> int: ...
    # reports
    def report(self, *, kind: str, page: str, message: str, contact: str | None, briefing_id: str | None = None,
               visitor: str | None = None, trap: str = "") -> int: ...
    def reports(self, open_only: bool = True) -> list[dict[str, Any]]: ...   # takedown requests first
    def close(self, rid: int, *, outcome: str, note: str | None = None, public_note: str | None = None) -> None: ...
    # corrections and hiding
    def corrections(self, limit: int = 100) -> list[dict[str, Any]]: ...
    def hide(self, item: str, note: str) -> None: ...
    def unhide(self, item: str) -> None: ...
    def hidden(self, item: str) -> dict[str, Any] | None: ...
    # for the owner, the update report and the nightly check
    def waiting(self) -> Waiting: ...                        # counts, and the oldest's age in working days

@dataclass(frozen=True)
class Waiting: reports: int; statements: int; oldest_working_days: int | None
def working_days_between(start: date, end: date) -> int: ...
```

## `wts_core.observe`

```python
@dataclass
class BriefingRecord: ...                                    # the fields of ADR 0012

def config_id(*, site: Site, settings: Settings, package_version: str, arm: str | None = None) -> str: ...
class SqliteBriefingLog:                                     # implements ports.BriefingLog
    def write(self, record: BriefingRecord) -> None: ...
    def mark(self, briefing_id: str, *, useful: bool | None = None, reported: bool = False,
             corrected: bool = False, followed_up: bool = False) -> None: ...
    def tidy(self) -> int: ...                               # retention
def count(db: StateDB, name: str, clock: Clock = SYSTEM_CLOCK) -> None: ...   # a daily total, no visitor

def json_logging(path: Path, *, site: Site, max_bytes: int = 5_000_000, keep: int = 9) -> logging.Handler: ...
def log_event(event: str, *, briefing: str | None = None, stage: str | None = None, ms: int | None = None,
              error_type: str | None = None, level: int = logging.INFO) -> None: ...

@dataclass
class Stats: ...                                             # every figure of brief 3.7, with the earlier period's
def stats(log: BriefingLog, *, since: timedelta, embedder: Embedder | None = None, clock: Clock = SYSTEM_CLOCK) -> Stats: ...
def weekly_report(stats: Stats, folder: Path) -> tuple[Path, Path]: ...       # the .md and the .json
def proposed_thresholds(stats: Stats) -> dict[str, float]: ...
def tripped(stats: Stats, thresholds: Mapping[str, float]) -> list[str]: ...

@dataclass(frozen=True)
class Experiment: name: str; arms: Mapping[str, float]; start: date; end: date; decided_by: str   # v0.2.0
def proposed_test_questions(log: BriefingLog, *, since: timedelta, limit: int = 20) -> list[dict[str, Any]]: ...   # v0.2.0
```

## `wts_core.eval`

```python
@dataclass(frozen=True)
class Case: id: str; question: str; expect: Mapping[str, Any]            # each site's own expectations

class EvalSite(Protocol):                                               # the site's
    def cases(self) -> Sequence[Case]: ...
    def ask(self, case: Case, config: Mapping[str, Any]) -> Iterator[ReaderEvent]: ...
    def group_of(self, source: Mapping[str, Any]) -> str: ...
    def judge(self, case: Case, answer: Answer) -> float | None: ...     # optional

@dataclass
class CaseResult: ...            # checks, spread by group, time to first word and to the end, cost
@dataclass
class Run: config_id: str; results: list[CaseResult]; summary: dict[str, float]

def run(site: EvalSite, config: Mapping[str, Any], *, record_fixtures: Path | None = None) -> Run: ...
def compare(a: Run, b: Run) -> Comparison: ...
def save(run: Run, folder: Path) -> Path: ...
def check_thresholds(run: Run, thresholds: Mapping[str, float]) -> list[str]: ...   # empty means it passed

@dataclass(frozen=True)
class Fixture: question: str; documents: tuple[Document, ...]; blocks: tuple[Block, ...]; report: Answer
def replay(fixtures: Iterable[Fixture], verifier: Verifier, loaded: LoadedWords) -> list[Difference]: ...
```

## `wts_core.ops`

**Built** (`src/wts_core/ops/`, with `adapters/b2.py` and `adapters/duckdb.py`, listed under the adapters below);
this section is as built, and departs from the first sketch where the sites' code required it: a `BackupSpec` is
given by keyword and is passed to each function (it is not a field of `Site`), with no default for how many to keep
or for the tables a backup must have; `wal` says whether a kept copy carries a write-ahead log; a refusal says why
in one word; and the alerts' wording is the site's.

```python
@dataclass(frozen=True, kw_only=True)
class BackupSpec:
    prefix: str                                   # "wcs-state-"
    stamp: str = "%Y-%m-%d"                       # Landlords: "%Y%m%d-%H%M%S"
    format: Literal["gzip", "tar"] = "gzip"       # MPs: "tar"
    member: str = "state.db"                      # the database's name inside a tar; MPs: "state.sqlite"
    extra_files: tuple[str, ...] = ()             # MPs: ("settings.local.toml",)
    keep: int
    required_tables: tuple[str, ...]
    wal: bool = False                             # MPs: True
    @property
    def suffix(self) -> str: ...                  # ".sqlite.gz" or ".tar.gz"
    def archives(self, folder: Path) -> list[Path]: ...

def make_backup(state_db: Path, dest: Path, spec: BackupSpec, *, keep: int | None = None,
                clock: Clock = SYSTEM_CLOCK) -> Path | None: ...          # None: nothing to back up yet
def restore_backup(archive: Path, state_db: Path, spec: BackupSpec) -> Path | None: ...   # the replaced file's copy
class RestoreRefused(RuntimeError):
    def __init__(self, message: str, *, why: str) -> None: ...
    why: str      # "kept-copy", "unreadable", "foreign", "not-a-database", "damaged" or "swap-failed"

@dataclass(frozen=True)
class Alert: level: Literal["error", "warning"]; text: str
@dataclass(frozen=True)
class AlertWording:                               # every field required
    no_backups: str; backup_stale: str; server_only: str; no_offsite_yet: str; offsite_failed: str; offsite_stale: str

def send_offsite(archive: Path, store: OffsiteStore | None, spec: BackupSpec, *, keep: int = 60,
                 clock: Clock = SYSTEM_CLOCK) -> dict[str, Any]: ...
def check_offsite(store: OffsiteStore | None, spec: BackupSpec, *, how_to_set_up: str | None = None) -> dict[str, Any]: ...
def backup_alerts(folder: Path, spec: BackupSpec, *, offsite_set_up: bool, wording: AlertWording,
                  stale_hours: int = 50, clock: Clock = SYSTEM_CLOCK) -> list[Alert]: ...
OffsiteError, OffsiteUnavailable                  # from wts_core.ports, exported here too
```

## `wts_core.adapters`

```python
# each imports its library when first used; none is imported by the base
adapters.anthropic.AnthropicClient(api_key: str | None, *, base_url: str, timeout: float = 300.0,
                                   connect: float = 10.0, max_retries: int = 2)
adapters.anthropic.api_key(site: Site, settings: Settings, env: Mapping[str, str]) -> str | None
adapters.fastembed.FastEmbedEmbedder(model: str, cache_dir: Path, threads: int | None = None, batch_size: int = 64)
adapters.hashing.HashingEmbedder(dim: int = 256)             # needs numpy only; tests and sample data
adapters.lancedb.LanceIndex(path: Path, embedder: Embedder, *, schema, scalar_columns: Sequence[str])
# adapters.b2 and adapters.duckdb are as built
adapters.b2.B2Store(bucket: str, key_id: str, application_key: str, client: httpx.Client | None = None, *,
                    env_prefix: str | None = None)             # implements ports.OffsiteStore
adapters.b2.configured(site: Site, env: Mapping[str, str] | None = None, *,
                       client: httpx.Client | None = None) -> B2Store | None
adapters.b2.how_to_set_up(site: Site) -> str
adapters.duckdb.SharedConnection(con: duckdb.DuckDBPyConnection | None = None)   # and .cursor_for_thread()
adapters.duckdb.shared(con: duckdb.DuckDBPyConnection | SharedConnection | None = None) -> SharedConnection
def model_client(settings: Settings, site: Site, env: Mapping[str, str]) -> ModelClient   # reads [answer] provider
```

## `wts_core.cli`: commands a site adds to its own Typer app

```python
def ops_commands(site: Site, settings: Callable[[], Settings]) -> typer.Typer: ...       # backup, restore, offsite, backup-check
def replies_commands(replies: Callable[[], Replies]) -> typer.Typer: ...                 # reports …, statements …, hide, unhide
def stats_commands(site: Site, settings: Callable[[], Settings]) -> typer.Typer: ...     # stats, weekly-report
def eval_commands(site: Callable[[], EvalSite]) -> typer.Typer: ...                      # eval run | compare | replay
def check_route(site: Site, replies: Replies, log: BriefingLog, token: str | None) -> Callable[..., dict]: ...   # GET /api/check
```

## `wts_core.testing`

```python
FixedClock(start: datetime); FixedRandom(tokens: Sequence[str], choices: Sequence[int] = ())
ScriptedModel(script: Sequence[ModelEvent] | Path)           # replays a recorded stream; records every request
RecordingEmbedder(dimension: int = 8); MemoryIndex(embedder: Embedder); MemoryOffsiteStore()
recorded(name: str) -> Path                                  # the recorded streams that ship with the package

class ModelClientContract: ...     # a test class to subclass, one per port
class EmbedderContract: ...
class VectorIndexContract: ...
class OffsiteStoreContract: ...
class SpendingRecordContract: ...; class AnswerCacheContract: ...; class ReplyStoreContract: ...

def assert_statements_stay_out(*, replies: Replies, ask: Callable[[str], Iterator[ReaderEvent]],
                               model: ScriptedModel, embedder: RecordingEmbedder, index: MemoryIndex,
                               state: StateDB, log_lines: Callable[[], Iterable[str]]) -> None: ...
def assert_no_reader_data(state: StateDB, log_lines: Iterable[str], *, question: str, address: str) -> None: ...
def golden(path: Path, value: Any, *, update: bool = False) -> None: ...   # the parity tests' helper
```
