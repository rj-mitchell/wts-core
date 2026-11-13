"""The package against each site's own code: the same inputs must give the same results.

Each site's ``api/usage.py`` (and the state database it writes to) is run from its checkout, by file path, with its
clock replaced by the test's so both sides see the same time. Nothing is installed from a site and nothing in a
site is written: the files are read and compiled here, so not even a bytecode file is left behind. Where a
checkout is absent the comparison is skipped, saying so.

What is compared, on generated inputs: cost and the stored token counts, cache keys, the unit visitors are counted
by and the visitor's code, the limiter's decisions over a scripted run of calls and times, briefings in progress,
the caps' decision and wording over a grid of spending and counts, and what is written to the spending record.
"""

from __future__ import annotations

import ast
import hashlib
import ipaddress
import json
import random
import sys
import threading
import tomllib
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from test_usage_sites import COUNCILS, COUNTRIES, MPS, SITES_ROOT, SiteFacts, checkout_of, site  # noqa: F401
from wts_core import usage as core
from wts_core.ports import Usage
from wts_core.state import StateDB
from wts_core.testing import FixedClock
from wts_core.usage import (
    BriefingsInProgress,
    Caps,
    Failures,
    Limits,
    PriceTable,
    RateLimiter,
    Spending,
    SqliteAnswerCache,
    busy_refusal,
    cache_key,
    network_of,
    visitor_code,
)

# ---- running a site's own code -----------------------------------------------------------------------------------


def run_file(name: str, path: Path, beside: dict[str, ModuleType] | None = None) -> ModuleType:
    """A site's module, run from its file under ``name``. ``beside`` are the site's other modules it imports, put
    in ``sys.modules`` only while it runs. Compiled here, so no ``__pycache__`` is written into the checkout."""
    module = ModuleType(name)
    module.__file__ = str(path)
    during = {**(beside or {}), name: module}
    before = {n: sys.modules.get(n) for n in during}
    sys.modules.update(during)
    try:
        exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    finally:
        for n, old in before.items():
            if old is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = old
    return module


def definition(path: Path, name: str, **names: Any) -> Any:
    """One function or class from a site's file, where the file as a whole needs the web framework and the rest of
    the site: its source is cut out and run with the few names it uses."""
    source = path.read_text()
    node = next(n for n in ast.parse(source).body
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
    scope: dict[str, Any] = dict(names)
    exec(compile("from __future__ import annotations\n" + (ast.get_source_segment(source, node) or ""),
                 str(path), "exec"), scope)
    return scope[name]


def clock_for_site(clock: FixedClock) -> type[datetime]:
    class SiteDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return clock.now()

    return SiteDatetime


class SiteCode:
    """A site's usage code and state database, on the test's clock, behind one set of names."""

    def __init__(self, facts: SiteFacts, folder: Path, clock: FixedClock) -> None:
        src = checkout_of(facts) / "src" / facts.package
        self.facts = facts
        package = ModuleType(facts.package)
        if facts is COUNTRIES:  # its state database is in the same file
            self.usage = run_file("wcs.api.usage", src / "api" / "usage.py")
            state_module = self.usage
        else:
            where = ("store", "state.py") if facts is MPS else ("api", "state.py")
            state_name = f"{facts.package}.{where[0]}.state"
            state_module = run_file(state_name, src / where[0] / where[1])
            beside = {facts.package: package, f"{facts.package}.{where[0]}": ModuleType(f"{facts.package}.{where[0]}"),
                      state_name: state_module}
            self.usage = run_file(f"{facts.package}.api.usage", src / "api" / "usage.py", beside)
        for module in {state_module, self.usage}:
            if hasattr(module, "datetime"):
                module.datetime = clock_for_site(clock)  # type: ignore[attr-defined]
        self.usage.time = SimpleNamespace(monotonic=clock.monotonic)  # type: ignore[attr-defined]
        self.state = state_module.StateDB(folder / f"{facts.repo}.db")
        with open(facts.checkout / "config" / "settings.toml", "rb") as fh:
            self.settings: dict[str, Any] = tomllib.load(fh)["usage"]

    # the three copies take their arguments in three orders

    def record(self, kind: str, model: str | None, counts: dict[str, Any] | None, visitor: str | None = None,
               account: int | None = None) -> float:
        u = self.usage
        if self.facts is MPS:
            return u.record_usage(self.state, account, kind, model, counts, self.settings, visitor)
        if self.facts is COUNTRIES:
            return u.record_usage(self.state, kind, model, counts, self.settings, visitor)
        spent = u.record_usage(self.state, visitor, kind, model, counts, self.settings)
        if kind == "answer" and counts and visitor is not None:  # as its app does when an answer's cost is recorded
            u.count_question(self.state, visitor)
        return spent

    def refusal(self, visitor: str | None, account: int | None, pending: float, settings: dict[str, Any]) -> str | None:
        u = self.usage
        if self.facts is MPS:
            return u.check_caps(self.state, account, settings, visitor, pending)
        if self.facts is COUNTRIES:
            return u.check_caps(self.state, settings, visitor, pending)
        if visitor is None:
            return u.site_paused(self.state, settings, pending)
        return u.blocked(self.state, visitor, settings, pending)

    def spending_rows(self) -> list[tuple]:
        account = "user_id" if self.facts is MPS else "NULL"
        order = "rowid" if self.facts is COUNCILS else "id"
        with self.state.connect() as con:
            return [tuple(r) for r in con.execute(
                f"SELECT at, kind, model, visitor, {account}, input_tokens, output_tokens, cache_read_tokens, "
                f"cache_write_tokens, cost_usd FROM usage ORDER BY {order}")]


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock("2026-11-13T12:00:00+00:00")


@pytest.fixture
def theirs(site, tmp_path, clock) -> SiteCode:  # noqa: F811
    return SiteCode(site, tmp_path, clock)


@pytest.fixture
def db(tmp_path, clock) -> StateDB:
    return StateDB(tmp_path / "core.db", migrations=core.migrations(), clock=clock)


def spending_rows(db: StateDB) -> list[tuple]:
    with db.connect() as con:
        return [tuple(r) for r in con.execute(
            "SELECT at, kind, model, visitor, account, input_tokens, output_tokens, cache_read_tokens, "
            "cache_write_tokens, cost_usd FROM wts_spending ORDER BY id")]


# ---- generated inputs --------------------------------------------------------------------------------------------


def some_count(rng: random.Random) -> Any:
    """A token count as it may arrive: usually a whole number, sometimes nought, missing, a float or text."""
    kind = rng.random()
    if kind < 0.70:
        return rng.choice([rng.randrange(0, 2_000), rng.randrange(0, 200_000), rng.randrange(0, 5_000_000)])
    if kind < 0.80:
        return 0
    if kind < 0.87:
        return None
    if kind < 0.94:
        return float(rng.randrange(0, 100_000))
    return str(rng.randrange(0, 100_000))


def some_usage(rng: random.Random) -> dict[str, Any] | None:
    """One call's token counts in either of the two forms the sites meet, with keys left out now and then."""
    roll = rng.random()
    if roll < 0.01:
        return None
    if roll < 0.02:
        return {}
    counts: dict[str, Any] = {"input_tokens": some_count(rng), "output_tokens": some_count(rng)}
    if rng.random() < 0.5:  # the sites' own names: input includes the cache writes
        writes = some_count(rng)
        counts["cache_write_tokens"] = writes
        if isinstance(writes, int) and isinstance(counts["input_tokens"], int) and rng.random() < 0.9:
            counts["input_tokens"] += writes
        counts["cache_read_tokens"] = some_count(rng)
        if rng.random() < 0.1:
            counts["cache_read_input_tokens"] = some_count(rng)  # both names for cache reads at once
    else:  # the SDK's own names
        counts["cache_creation_input_tokens"] = some_count(rng)
        counts["cache_read_input_tokens"] = some_count(rng)
    for key in list(counts):
        if rng.random() < 0.08:
            del counts[key]
    return counts


def models_of(facts: SiteFacts) -> list[str | None]:
    """Every model the site's settings name, as named and with a longer id, and ones with no entry at all."""
    named = list(dict.fromkeys([*facts.models, *facts.usage["models"]]))
    return [*named, *(m + "-20261001" for m in named), None, "", "some-other-model", "claude", "claude-haiku"]


# ---- cost --------------------------------------------------------------------------------------------------------


def test_cost_is_the_sites_own_to_the_last_decimal(theirs):
    rng = random.Random(20261113)
    prices = PriceTable.from_settings(theirs.settings)
    models = models_of(theirs.facts)
    seen = set()
    for n in range(4000):
        counts, model = some_usage(rng), models[n % len(models)]
        expected = theirs.usage.cost_usd(counts, theirs.settings, model)
        got = prices.cost(Usage.from_mapping(counts) if counts is not None else None, model)
        assert got == expected and type(got) is float, (counts, model)
        assert Usage.from_mapping(counts).as_stored() == theirs.usage.token_counts(counts), counts
        seen.add((model, expected > 0))
    assert len(seen) == 2 * len(models)   # every model, with and without a cost


def test_cost_is_the_sites_own_whatever_prices_its_settings_give(theirs):
    """Other prices than today's: any entry may give any of the four figures, and the first matching name wins."""
    rng = random.Random(7)
    keys = ("price_input_per_mtok", "price_output_per_mtok", "price_cache_read_per_mtok", "cache_write_multiplier")
    for _ in range(300):
        def figures(share: float) -> dict[str, Any]:
            return {k: rng.choice([round(rng.uniform(0.01, 30), 3), rng.randrange(1, 40), "2.5"])
                    for k in keys if rng.random() < share}

        settings = {**theirs.settings, **figures(1.0),
                    "models": {name: figures(0.6) for name in rng.sample(
                        ["claude", "claude-haiku", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "gpt"],
                        k=rng.randrange(0, 5))}}
        prices = PriceTable.from_settings(settings)
        for model in ("claude-haiku-5-5-20261001", "claude-sonnet-5-5", "claude-opus-5-5", "other", None):
            counts = some_usage(rng)
            assert prices.cost(Usage.from_mapping(counts) if counts is not None else None, model) == \
                theirs.usage.cost_usd(counts, settings, model), (settings, counts, model)


# ---- the cache key -----------------------------------------------------------------------------------------------


def some_parts(rng: random.Random, facts: SiteFacts) -> dict[str, Any]:
    """The parts of a cache key, shaped as each site's are (docs/study/usage-state-stream.md, 3.3)."""
    words = ["trial", "by", "jury", "café", "naïve", "“quoted”", "climate", "finance", "bin", "collections", "£5", "日本"]
    question = " ".join(rng.choice(words) for _ in range(rng.randrange(1, 12)))
    history = [{"question": rng.choice(words), "answer": rng.choice(words) * rng.randrange(1, 50), "topic": None,
                "scope": {"votes": rng.random() < 0.5}} for _ in range(rng.randrange(0, 4))]
    parts: dict[str, Any] = {
        "q": question.lower(), "mode": rng.choice(["summary", "comprehensive"]), "sources_only": False,
        "plan": rng.choice([None, {"search_text": question, "date_from": date(2020, 1, rng.randrange(1, 28)),
                                   "parties": ["Labour", "Plaid Cymru"], "limit": rng.randrange(1, 50)}]),
        "history": history, "model": rng.choice(["claude-sonnet-5-5", None])}
    if facts is MPS:
        parts |= {"recency": rng.random(), "role_weight": rng.choice([0, 0.5, 1]), "follows": rng.choice([None, "abc"]),
                  "compare": rng.choice([None, ["a", "b"]]), "data": rng.choice([None, rng.randrange(1, 9999)]),
                  "scope": {k: rng.random() < 0.5 for k in ("written", "pbc", "votes", "edms", "devolved", "evidence")},
                  "instructions": hashlib.sha256(question.encode()).hexdigest()[:12]}
    elif facts is COUNTRIES:
        parts |= {"recency": rng.random(), "role_weight": rng.random(), "instructions": 3,
                  "data": rng.choice(["none", rng.randrange(1_700_000_000, 1_800_000_000)])}
    else:
        parts |= {"data": rng.choice([0.0, rng.uniform(1.7e9, 1.8e9)]), "v": "2"}
    return parts


def test_cache_keys_are_the_sites_own_byte_for_byte(site):  # noqa: F811
    src = checkout_of(site) / "src" / site.package
    if site is COUNCILS:  # its cache_key is in api/app.py, beside the web app
        theirs_key = definition(src / "api" / "app.py", "cache_key", hashlib=hashlib, json=json, Any=Any)
    else:
        theirs_key = SiteCode(site, Path("/nonexistent"), FixedClock()).usage.cache_key \
            if site is MPS else run_file("wcs.api.usage", src / "api" / "usage.py").cache_key
    rng = random.Random(3)
    keys = set()
    for _ in range(2000):
        parts = some_parts(rng, site)
        key = cache_key(parts, length=site.key_length)
        assert key == theirs_key(parts) and len(key) == site.key_length
        keys.add(key)
    assert len(keys) > 1990


# ---- who a visitor is --------------------------------------------------------------------------------------------


def some_addresses(rng: random.Random, n: int) -> list[str | None]:
    out: list[str | None] = [None, "", "testclient", "::1", "::", "127.0.0.1", "::ffff:203.0.113.9", "0.0.0.0",
                             "2001:db8:1:2:aaaa::1", "2001:DB8:1:2:BBBB::9", "fe80::1%eth0", " 203.0.113.5",
                             "203.0.113.5:8080", "unknown", "1.2.3", "256.1.1.1", "::ffff:0:0", "2002:c000:204::1"]
    for _ in range(n):
        roll = rng.random()
        if roll < 0.35:
            out.append(str(ipaddress.IPv4Address(rng.getrandbits(32))))
        elif roll < 0.8:
            out.append(str(ipaddress.IPv6Address(rng.getrandbits(128))))
        elif roll < 0.9:
            out.append("::ffff:" + str(ipaddress.IPv4Address(rng.getrandbits(32))))
        else:
            out.append(ipaddress.IPv6Address(rng.getrandbits(128)).exploded.upper())
    return out


def test_visitors_are_counted_by_the_same_unit_and_given_the_same_code(theirs, db, clock):
    rng = random.Random(11)
    addresses = some_addresses(rng, 3000)
    for address in addresses:
        assert network_of(address) == theirs.usage.network_of(address), address
    # the same secret in each store gives the same code
    salt, day = "5a" * 16, clock.now().strftime("%Y-%m-%d")
    with theirs.state.connect() as con:
        con.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (f"visitor_salt:{day}", salt))
    db.set(f"visitor_salt:{day}", salt)
    for address in addresses[:300]:
        assert visitor_code(db, address, clock=clock) == theirs.usage.visitor_key(theirs.state, address), address
    # and each makes and keeps its own secret for a new day, deleting the old one
    clock.advance(days=1)
    mine, its = visitor_code(db, "203.0.113.5", clock=clock), theirs.usage.visitor_key(theirs.state, "203.0.113.5")
    assert len(mine) == len(its) == 24 and mine != its
    with theirs.state.connect() as con:
        assert [r[0] for r in con.execute("SELECT key FROM kv WHERE key LIKE 'visitor_salt%'")] == \
            ["visitor_salt:2026-11-14"]
    assert db.get(f"visitor_salt:{day}") is None and len(db.get("visitor_salt:2026-11-14") or "") == 32


# ---- the limiter -------------------------------------------------------------------------------------------------


def script(rng: random.Random, calls: int, keys: int) -> list[tuple[float, str]]:
    """Calls to the limiter: how long after the one before, and who from. Bursts, pauses, and gaps of exactly a
    minute."""
    out = []
    for _ in range(calls):
        wait = rng.choice([0.0, 0.0, 0.0, 0.1, 1.0, 2.5, 7.0, 29.0, 30.0, 31.0, 60.0, 60.0, 61.0, 120.0])
        out.append((wait, f"visitor:{rng.randrange(keys)}"))
    return out


@pytest.mark.parametrize("per_minute", [20, 3, 2, 1])
def test_the_limiter_decides_as_the_sites_own(theirs, clock, per_minute):
    rng = random.Random(per_minute)
    mine = RateLimiter(per_minute, forget_over=theirs.facts.forget_over, clock=clock)
    its = theirs.usage.RateLimiter(per_minute)
    allowed = 0
    for wait, key in script(rng, 6000, keys=5):
        clock.advance(wait)
        decision = mine.allow(key)
        assert decision == its.allow(key)
        allowed += decision
    assert 0 < allowed < 6000


def test_the_limiter_forgets_idle_keys_when_the_sites_own_does(theirs, clock):
    over = theirs.facts.forget_over
    mine = RateLimiter(2, forget_over=over, clock=clock)
    its = theirs.usage.RateLimiter(2)
    for n in range(over):
        assert mine.allow(f"v{n}") and its.allow(f"v{n}")
    clock.advance(30)
    for key in ("late1", "late2", "v0", "v0"):   # over the size, but nobody has been idle for a minute
        assert mine.allow(key) == its.allow(key)
    assert set(mine._hits) == set(its.hits) and len(mine._hits) == over + 2
    clock.advance(31)                             # the first visitors were last here 61 seconds ago
    for key in ("late1", "v0", "new"):
        assert mine.allow(key) == its.allow(key)
    assert set(mine._hits) == set(its.hits) == {"late1", "late2", "v0", "new"}


def test_the_limiter_decides_as_where_landlords_stands():
    """Where Landlords Stand's ``Limiter`` keeps a hash of who it is given; the decisions are the same."""
    api = SITES_ROOT / "wherelandlordsstand" / "src" / "landlords" / "api.py"
    if not api.exists():
        pytest.skip(f"Where Landlords Stand's checkout is not at {api.parents[2]}: nothing to compare with")
    clock = FixedClock()
    limiter_class = definition(api, "Limiter", deque=deque, defaultdict=defaultdict, threading=threading,
                               sha256=hashlib.sha256, time=SimpleNamespace(monotonic=clock.monotonic))
    for per_minute, forget_over in ((10, 50_000), (2, 3), (3, 10)):
        its = limiter_class() if per_minute == 10 else limiter_class(per_minute=per_minute, forget_over=forget_over)
        assert (its.per_minute, its.forget_over) == (per_minute, forget_over)
        mine = RateLimiter(per_minute, forget_over=forget_over, clock=clock)
        for wait, key in script(random.Random(per_minute), 5000, keys=8):
            clock.advance(wait)
            assert mine.allow(key) == its.allow(key)
            assert {hashlib.sha256(k.encode()).hexdigest()[:16] for k in mine._hits} == set(its.seen)


# ---- briefings in progress ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("places", [(2, 8), (1, 2), (2, 3), (3, 4)])
def test_briefings_in_progress_are_counted_as_the_sites_own(theirs, places):
    facts, u = theirs.facts, theirs.settings
    estimate = u["briefing_estimate_usd"]
    if places == (2, 8):  # the site's own figures, from its settings
        places = (u[facts.at_once_key], u["briefings_at_once"])
        its = theirs.usage.InFlight()   # its code's fallbacks are what its settings file says
    else:
        its = theirs.usage.InFlight(*places, estimate)
    assert (its.per_key, its.total, its.estimate_usd) == (*places, estimate)
    mine = BriefingsInProgress(*places, estimate)
    rng = random.Random(sum(places))
    started: list[str] = []
    refused = {"visitor": 0, "site": 0}
    for _ in range(4000):
        key = f"v{rng.randrange(6)}"
        roll = rng.random()
        if roll < 0.55:
            said, busy = its.start(key), mine.start(key)
            assert said == (busy_refusal(busy, facts.messages).message if busy else None)
            if busy:
                refused[busy.reason] += 1
            else:
                started.append(key)
        elif roll < 0.95 and started:
            done = started.pop(rng.randrange(len(started)))
            its.finish(done), mine.finish(done)
        elif roll > 0.99:
            its.finish("never-started"), mine.finish("never-started")
        assert mine.running == dict(its.running)
        besides = rng.randrange(0, 3)
        assert mine.pending_usd(besides) == its.pending_usd(besides) and mine.pending_usd() == its.pending_usd()
    assert refused["visitor"] > 0 and refused["site"] > 0


# ---- the caps ----------------------------------------------------------------------------------------------------


def tokens_costing(usd: float, settings: dict[str, Any]) -> int:
    return round(usd / settings["price_input_per_mtok"] * 1e6)


def same_decision(theirs: SiteCode, caps: Caps, settings: dict[str, Any], visitor: str | None, account: int | None,
                  pending: float) -> str | None:
    said = theirs.refusal(visitor, account, pending, settings)
    refusal = caps.refusal(visitor=visitor, account=account, pending_usd=pending)
    assert (refusal.message if refusal else None) == said, (visitor, account, pending)
    if visitor is None and account is None:
        paused = caps.site_paused(pending)
        assert (paused.message if paused else None) == said
    return said


def test_the_caps_decide_and_say_what_the_sites_own_do_over_a_grid_of_spending_and_counts(theirs, tmp_path, clock):
    """For spending today and earlier this month just under, at and just over each cap, and a visitor one short of,
    at and over the daily limit: the site's own function, on a database built by the site's own code, against the
    package's on its own tables."""
    facts, settings = theirs.facts, theirs.settings
    limits, messages = Limits.from_settings(settings), facts.messages
    day_cap, month_cap, estimate = limits.daily_cap_usd, limits.monthly_cap_usd, settings["briefing_estimate_usd"]
    tick = 1 / 1e6 * settings["price_input_per_mtok"] * 1
    said: set[str | None] = set()
    scenario = 0
    for today_usd in (0.0, day_cap - 1.0, day_cap - tick, day_cap, day_cap + tick):
        for earlier_usd in (0.0, month_cap - day_cap, month_cap - tick, month_cap, month_cap + tick):
            scenario += 1
            folder = tmp_path / str(scenario)
            folder.mkdir()
            its = SiteCode(facts, folder, clock)
            db = StateDB(folder / "core.db", migrations=core.migrations(), clock=clock)
            spending = Spending(db, PriceTable.from_settings(settings), clock=clock)
            caps = Caps(spending, limits, messages, clock)

            def record(kind, model, counts, visitor=None, account=None, its=its, spending=spending):
                assert spending.add(kind, model, counts, visitor=visitor, account=account) == \
                    its.record(kind, model, counts, visitor, account)

            clock.set("2026-11-03T09:00:00+00:00")
            if earlier_usd:
                record("answer", None, {"input_tokens": tokens_costing(earlier_usd, settings)}, "earlier")
            clock.set("2026-11-13T12:00:00+00:00")
            if today_usd:
                record("topic", None, {"input_tokens": tokens_costing(today_usd, settings)})
            checks = [("v1", None), ("v2", None), (None, None)]
            if facts is MPS:
                checks += [(None, 7), ("v1", 7)]
            # the visitor's count: none; one short of the limit; at it; over it
            for add in (0, limits.per_visitor_daily - 1, 1, 1):
                for _ in range(add):
                    record("answer", "claude-sonnet-5-5", {"input_tokens": 0}, "v1")
                    record("parse", "claude-haiku-5-5", {"input_tokens": 0}, "v1")
                for visitor, account in checks:
                    for pending in (0.0, tick, estimate, day_cap, month_cap):
                        said.add(same_decision(its, caps, settings, visitor, account, pending))
            if facts is MPS and scenario <= 3:   # and a signed-in account's own count
                for add in (limits.per_account_daily - 1, 1, 1):
                    for _ in range(add):
                        record("answer", "claude-sonnet-5-5", {"input_tokens": 0}, None, 7)
                    for visitor, account in checks:
                        said.add(same_decision(its, caps, settings, visitor, account, 0.0))
            assert spending_rows(db) == its.spending_rows()
            clock.advance(hours=12)          # past midnight UTC: the day's counts and spending start again
            for visitor, account in checks:
                said.add(same_decision(its, caps, settings, visitor, account, 0.0))
    expected = {None, messages.visitor_daily_limit, messages.daily_cap, messages.monthly_cap}
    if facts is MPS:
        expected.add(messages.account_daily_limit)
    assert said == expected


def test_a_month_of_spending_is_recorded_and_capped_as_the_sites_own(theirs, db, clock):
    """A month of calls of every kind, in both forms of token counts, for every model the site names: the same
    rows are written, the same cost returned, and after every call the caps decide the same."""
    facts = theirs.facts
    settings = {**theirs.settings, "per_visitor_daily_questions": 4, "per_user_daily_questions": 3}
    spending = Spending(db, PriceTable.from_settings(settings), clock=clock)
    caps = Caps(spending, Limits.from_settings(settings), facts.messages, clock)
    rng = random.Random(5)
    models = models_of(facts)
    clock.set("2026-10-30T22:00:00+00:00")
    said: dict[str | None, int] = defaultdict(int)
    for _ in range(700):
        clock.advance(rng.choice([1, 30, 600, 3_600, 7_200, 20_000]))
        kind = rng.choice(["answer", "answer", "parse", "interests", "topic"])
        account = 7 if facts is MPS and rng.random() < 0.2 else None
        visitor = None if account is not None or kind == "topic" else f"v{rng.randrange(4)}"
        counts = some_usage(rng)
        if facts is not COUNCILS and not counts:
            continue   # the other two wrote a row of noughts for no usage, and their callers took care not to ask
        if rng.random() < 0.15:   # now and then a call that costs dollars, so the caps are reached
            counts = {"input_tokens": rng.randrange(100_000, 3_000_000), "output_tokens": rng.randrange(0, 200_000)}
        model = rng.choice(models)
        assert spending.add(kind, model, counts, visitor=visitor, account=account) == \
            theirs.record(kind, model, counts, visitor, account)
        who = (rng.choice(["v0", "v1", "v2", "v3", None]), 7 if facts is MPS and rng.random() < 0.3 else None)
        pending = rng.choice([0.0, 0.0, settings["briefing_estimate_usd"], 1.0])
        said[same_decision(theirs, caps, settings, who[0], who[1], pending)] += 1
    assert spending_rows(db) == theirs.spending_rows() and len(spending_rows(db)) > 600
    assert set(said) >= {None, facts.messages.visitor_daily_limit, facts.messages.daily_cap,
                         facts.messages.monthly_cap}
    assert clock.now().strftime("%Y-%m") == "2026-11"


# ---- the answer cache and failures -------------------------------------------------------------------------------


def test_the_answer_cache_gives_and_forgets_as_the_sites_own(theirs, db, clock):
    facts, u = theirs.facts, theirs.usage
    cache = SqliteAnswerCache(db, clock=clock)
    rng = random.Random(9)
    table, when = ("answer_cache", "at" if facts is COUNCILS else "created_at")
    stored: dict[str, datetime] = {}
    hits = 0
    for n in range(600):
        clock.advance(rng.choice([0, 1, 60, 1800, 3600, 3600, 7200, 86_400]))
        key = cache_key({"q": rng.randrange(12)}, length=facts.key_length)
        hours = rng.choice([1, 2, 24, 168, 0.5])
        if rng.random() < 0.4:
            events = [{"type": "sources", "sources": [{"n": n, "on": date(2024, 12, 17)}]},
                      {"type": "final", "answer": {"markdown": f"Briefing {n} “quoted”."}, "briefing_id": f"b{n}"}]
            cache.put(key, events, hours)
            if facts is COUNCILS:
                theirs.state.store_cached(key, events, hours)
            else:
                u.store_events(theirs.state, key, events, hours)
            stored[key] = clock.now()
        else:
            if key in stored and clock.now() - stored[key] == timedelta(hours=hours) and facts is COUNCILS:
                continue   # exactly the cache's life old: Where Councils Stand's copy stopped a second sooner
            got = theirs.state.cached(key, hours) if facts is COUNCILS else u.cached_events(theirs.state, key, hours)
            assert cache.get(key, hours) == got
            hits += got is not None
        with theirs.state.connect() as con:
            its = sorted(tuple(r) for r in con.execute(f"SELECT key, {when}, events FROM {table}"))
        with db.connect() as con:
            mine = sorted(tuple(r) for r in con.execute("SELECT key, created_at, events FROM wts_answer_cache"))
        assert mine == its
    assert 50 < hits < 350


def test_failures_are_noted_and_cleared_as_where_countries_stands(tmp_path, clock, db):
    """Where Countries Stand's is the rule every site now has: the newest 500, and none older than 90 days. (Where
    MPs Stand's copy has no 90 days; Where Councils Stand's has no such table.)"""
    theirs = SiteCode(COUNTRIES, tmp_path, clock)
    failures = Failures(db, clock=clock)
    rng = random.Random(13)
    for n in range(900):
        clock.advance(rng.choice([1, 60, 3600, 86_400, 86_400 * 3]))
        args = (rng.choice(["briefing", "question reading"]), rng.choice([None, "q" * rng.randrange(0, 700)]),
                f"Error {n}: " + "x" * rng.randrange(0, 700))
        failures.note(*args)
        theirs.usage.record_failure(theirs.state, *args)
        if n % 50 == 0 or n > 880:
            with theirs.state.connect() as con:
                its = [tuple(r) for r in con.execute("SELECT at, kind, question, error FROM failures ORDER BY id DESC")]
            assert [tuple(f.values()) for f in failures.recent(None)] == its
    assert 0 < len(failures.recent(None)) <= 500
