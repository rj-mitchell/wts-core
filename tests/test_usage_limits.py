"""The limits on asking: requests a minute, who a visitor is, briefings in progress, and the daily and monthly caps.

The sites' own tests for these, brought across and run for each site's limits and messages (``test_usage_sites``)."""

from __future__ import annotations

import dataclasses
import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_usage_sites import COUNCILS, COUNTRIES, MPS, SiteFacts, site  # noqa: F401  (the fixture)
from wts_core import usage
from wts_core.ports import Busy
from wts_core.settings import SettingsError
from wts_core.state import StateDB
from wts_core.testing import FixedClock, FixedRandom
from wts_core.usage import (
    BriefingsInProgress,
    Caps,
    Limits,
    PriceTable,
    RateLimiter,
    Refusal,
    Spending,
    busy_refusal,
    client_address,
    network_of,
    visitor_code,
)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock("2026-11-13T12:00:00+00:00")


@pytest.fixture
def db(tmp_path, clock) -> StateDB:
    return StateDB(tmp_path / "state.db", migrations=usage.migrations(), clock=clock)


# ---- requests a minute -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("per_minute", [3, 2, 10])  # the sites' own tests: MPs' 3, Countries' and Councils' 2
def test_requests_over_the_limit_in_a_minute_are_refused(per_minute, clock):
    limiter = RateLimiter(per_minute, forget_over=50_000, clock=clock)
    assert [limiter.allow("v") for _ in range(per_minute + 1)] == [True] * per_minute + [False]


def test_each_site_allows_its_own_number_of_requests_a_minute(site, clock):  # noqa: F811
    per_minute = site.usage["requests_per_minute"]
    limiter = RateLimiter(per_minute, forget_over=site.forget_over, clock=clock)
    assert [limiter.allow("visitor:abc") for _ in range(per_minute + 1)] == [True] * 20 + [False]
    assert limiter.per_minute == 20 and limiter.forget_over == site.forget_over


def test_ten_posts_a_minute_from_one_visitor_and_no_more_until_a_minute_has_passed(clock):
    """Where Landlords Stand's test, with its ten a minute."""
    limiter = RateLimiter(10, forget_over=50_000, clock=clock)
    assert [limiter.allow("code-of-7") for _ in range(11)] == [True] * 10 + [False]
    assert limiter.allow("code-of-8")                              # another visitor is counted on their own
    clock.advance(59)
    assert not limiter.allow("code-of-7")                          # a refused try doesn't count against them
    clock.advance(2)                                               # the minute has passed since the first ten
    assert [limiter.allow("code-of-7") for _ in range(11)] == [True] * 10 + [False]


def test_an_entry_exactly_a_minute_old_still_counts(clock):
    limiter = RateLimiter(1, forget_over=50_000, clock=clock)
    assert limiter.allow("v")
    clock.advance(60)
    assert not limiter.allow("v")
    clock.advance(0.5)
    assert limiter.allow("v")


def test_the_minute_rolls_request_by_request(clock):
    limiter = RateLimiter(2, forget_over=50_000, clock=clock)
    assert limiter.allow("v")          # at 0
    clock.advance(30)
    assert limiter.allow("v")          # at 30
    clock.advance(29)
    assert not limiter.allow("v")      # at 59: two in the last minute
    clock.advance(2)
    assert limiter.allow("v")          # at 61: the first has gone
    assert not limiter.allow("v")      # the one at 30 and the one at 61
    clock.advance(30)
    assert limiter.allow("v")          # at 91: the one at 30 has gone


def test_the_limiter_forgets_visitors_with_nothing_in_the_last_minute(clock):
    """Where Landlords Stand's test: the memory used stays small however many visitors come."""
    limiter = RateLimiter(2, forget_over=3, clock=clock)
    for who in ("a", "b", "c"):
        assert limiter.allow(who)
    assert len(limiter._hits) == 3                                  # three remembered: not over three, so all kept
    clock.advance(30)
    assert limiter.allow("d") and len(limiter._hits) == 4           # over three, but all were here this minute
    clock.advance(40)                                               # a, b and c were last here 70 seconds ago
    assert limiter.allow("d") and not limiter.allow("d")            # d is still counted: two this minute
    assert limiter.allow("e")
    assert set(limiter._hits) == {"d", "e"}                         # a, b and c are forgotten
    assert not limiter.allow("d")


def test_the_limiter_counts_rightly_from_many_threads(clock):
    limiter = RateLimiter(100, forget_over=50, clock=clock)
    with ThreadPoolExecutor(8) as pool:
        mine = list(pool.map(lambda _: limiter.allow("one visitor"), range(400)))
        others = list(pool.map(lambda i: limiter.allow(f"visitor {i}"), range(400)))
    assert sum(mine) == 100 and all(others)


# ---- who a visitor is --------------------------------------------------------------------------------------------


def test_an_ipv6_connection_counts_as_one_visitor():
    """One home or phone connection is given a whole IPv6 /64: its addresses are one visitor for the limits."""
    assert network_of("2001:db8:1:2:aaaa::1") == network_of("2001:db8:1:2:bbbb::9") == "2001:db8:1:2::/64"
    assert network_of("2001:db8:1:2:ffff::9") == "2001:db8:1:2::/64"
    assert network_of("2001:db8:1:3::1") != network_of("2001:db8:1:2::1")
    assert network_of("203.0.113.9") == "203.0.113.9" and network_of("::ffff:203.0.113.9") == "203.0.113.9"
    assert network_of("203.0.113.5") == "203.0.113.5" and network_of("::ffff:203.0.113.7") == "203.0.113.7"
    assert network_of("::1") == "::1"
    assert network_of(None) == "-" and network_of("") == "-" and network_of("testclient") == "testclient"


def test_visitor_codes_change_daily_and_old_secrets_are_deleted(db):
    """Where MPs Stand's test: it once had a permanent secret, which goes with the earlier days'."""
    db.set("visitor_salt", "an-old-permanent-salt")
    monday = visitor_code(db, "203.0.113.5", day="2026-10-12", forget_undated_salt=True)
    assert visitor_code(db, "203.0.113.5", day="2026-10-12", forget_undated_salt=True) == monday
    assert visitor_code(db, "198.51.100.7", day="2026-10-12", forget_undated_salt=True) != monday
    tuesday = visitor_code(db, "203.0.113.5", day="2026-10-13", forget_undated_salt=True)
    assert tuesday != monday
    with db.connect() as con:
        keys = [r["key"] for r in con.execute("SELECT key FROM wts_kv WHERE key LIKE 'visitor_salt%'")]
    assert keys == ["visitor_salt:2026-10-13"]


def test_only_dated_secrets_are_deleted_unless_the_site_asks(db):
    """Where Countries Stand and Where Councils Stand never had an un-dated secret and delete dated ones only."""
    db.set("visitor_salt", "not-theirs-to-delete")
    db.set("other", "kept")
    visitor_code(db, "203.0.113.5", day="2026-10-12")
    visitor_code(db, "203.0.113.5", day="2026-10-13")
    with db.connect() as con:
        keys = sorted(r["key"] for r in con.execute("SELECT key FROM wts_kv"))
    assert keys == ["other", "visitor_salt", "visitor_salt:2026-10-13"]


def test_visitor_codes_change_daily_and_never_hold_the_address(db):
    a = visitor_code(db, "203.0.113.5", day="2026-10-24")
    b = visitor_code(db, "203.0.113.5", day="2026-10-25")
    assert a != b and "203.0.113.5" not in a
    assert len(a) == 24 and set(a) <= set("0123456789abcdef")


def test_visitor_codes_group_an_ipv6_64(db):
    day = "2026-11-06"
    assert visitor_code(db, "2001:db8::1", day=day) == visitor_code(db, "2001:db8::abcd:1", day=day)
    assert visitor_code(db, "2001:db8::1", day=day) != visitor_code(db, "2001:db8:0:1::1", day=day)
    assert visitor_code(db, "2001:db8:1:2::1", day=day) == visitor_code(db, "2001:db8:1:2:9::9", day=day)
    assert visitor_code(db, "203.0.113.7", day=day) != visitor_code(db, "203.0.113.8", day=day)


def test_todays_code_is_made_from_the_days_secret_and_the_network(db, clock):
    """With no day given the clock's day (UTC) is used, as Where Councils Stand's copy always did."""
    chance = FixedRandom(tokens=["5a" * 16, "6b" * 16])
    code = visitor_code(db, "2001:db8:1:2::1", clock=clock, random=chance)
    assert db.get("visitor_salt:2026-11-13") == "5a" * 16
    assert code == hashlib.sha256(f"{'5a' * 16}|2001:db8:1:2::/64".encode()).hexdigest()[:24]
    assert visitor_code(db, "2001:db8:1:2::9", clock=clock, random=chance) == code  # the secret is made once a day
    clock.advance(hours=12)  # midnight UTC
    tomorrow = visitor_code(db, "2001:db8:1:2::1", clock=clock, random=chance)
    assert tomorrow != code and db.get("visitor_salt:2026-11-14") == "6b" * 16
    assert db.get("visitor_salt:2026-11-13") is None
    assert visitor_code(db, None, clock=clock) == hashlib.sha256(f"{'6b' * 16}|-".encode()).hexdigest()[:24]


def test_the_address_is_the_web_servers_own_where_the_site_leaves_it_to_the_server():
    """Where MPs Stand and Where Councils Stand: a header the visitor could set is never read by the site."""
    headers = {"x-forwarded-for": "198.51.100.7, 10.0.0.1"}
    for behind_proxy in (False, True):
        assert client_address(headers, "203.0.113.5", behind_proxy=behind_proxy,
                              trust_forwarded_first=False) == "203.0.113.5"
    assert client_address({}, None, behind_proxy=True, trust_forwarded_first=False) is None


def test_the_address_is_the_first_forwarded_one_where_the_site_reads_the_header():
    """Where Countries Stand and Where Landlords Stand, behind the proxy only."""
    def address(headers, peer="10.0.0.1", behind_proxy=True):
        return client_address(headers, peer, behind_proxy=behind_proxy, trust_forwarded_first=True)

    assert address({"x-forwarded-for": "198.51.100.7, 10.0.0.2"}) == "198.51.100.7"
    assert address({"X-Forwarded-For": " 2001:db8::1 "}) == "2001:db8::1"      # a plain dictionary, as written
    assert address({"x-forwarded-for": "198.51.100.7"}, behind_proxy=False) == "10.0.0.1"
    assert address({}) == "10.0.0.1" and address({"x-forwarded-for": ""}) == "10.0.0.1"
    assert address({"x-forwarded-for": " , 198.51.100.7"}) == "10.0.0.1"       # an empty first entry is no address
    assert address({}, peer=None) is None


# ---- briefings in progress ---------------------------------------------------------------------------------------


def test_briefings_in_progress_are_limited_for_one_visitor_and_in_all():
    """Where MPs Stand's test of its ``InFlight``."""
    f = BriefingsInProgress(per_key=2, total=3, estimate_usd=0.5)
    assert f.start("a") is None and f.start("a") is None
    assert f.start("a") == Busy("visitor")
    assert f.start("b") is None and f.start("c") == Busy("site")
    assert f.pending_usd() == 1.5 and f.pending_usd(besides=1) == 1.0
    assert set(f.running) == {"a", "b"}  # the refused visitor left nothing behind
    f.finish("a")
    assert f.start("c") is None
    for key in ("a", "b", "c"):
        f.finish(key)
    assert f.running == {} and f.pending_usd() == 0


def test_a_refused_visitor_leaves_nothing_behind():
    """Where Councils Stand's test."""
    f = BriefingsInProgress(per_key=1, total=2, estimate_usd=0.1)
    assert f.start("a") is None and f.start("a") == Busy("visitor")
    assert f.start("b") is None and f.start("c") == Busy("site")
    assert f.pending_usd(besides=1) == 0.1
    f.finish("a")
    f.finish("b")
    # a visitor who was refused ("c", and "a" the second time) leaves nothing behind
    assert f.running == {} and f.pending_usd() == 0
    assert f.start("c") is None


def test_finishing_what_was_never_started_changes_nothing():
    f = BriefingsInProgress(per_key=2, total=8, estimate_usd=0.15)
    f.finish("nobody")
    assert f.running == {} and f.pending_usd() == 0 and f.pending_usd(besides=3) == 0
    assert f.start("a") is None
    f.finish("a")
    f.finish("a")
    assert f.running == {} and f.start("a") is None and f.running == {"a": 1}


def test_each_site_has_its_own_places_estimate_and_words(site):  # noqa: F811
    u, m = site.usage, site.messages
    f = BriefingsInProgress(u[site.at_once_key], u["briefings_at_once"], u["briefing_estimate_usd"])
    assert (f.per_key, f.total) == (2, 8)
    assert f.start("a") is None and f.start("a") is None
    busy = f.start("a")
    assert busy is not None and busy_refusal(busy, m) == Refusal("busy_visitor", m.busy_visitor)
    assert "already being written" in m.busy_visitor
    for other in "bcdefg"[: 8 - 2]:
        assert f.start(other) is None
    full = f.start("z")
    assert full is not None and busy_refusal(full, m) == Refusal("busy_site", m.busy_site)
    assert m.busy_site.startswith("Many briefings")
    assert f.pending_usd() == 8 * u["briefing_estimate_usd"]
    assert f.pending_usd(besides=1) == 7 * u["briefing_estimate_usd"]
    assert m.with_sources(m.busy_visitor) == ("A briefing is already being written for you; please wait for it to "
                                              "finish. The sources found are shown below.")


# ---- the caps ----------------------------------------------------------------------------------------------------


def caps_for(facts: SiteFacts, db: StateDB, clock: FixedClock, **changed) -> tuple[Caps, Spending]:
    settings = {**facts.usage, **changed}
    spending = Spending(db, PriceTable.from_settings(settings), clock=clock)
    return Caps(spending, Limits.from_settings(settings), facts.messages, clock), spending


def spend(spending: Spending, usd: float, **who) -> None:
    """A briefing that cost ``usd`` at the site's base input price."""
    price = spending._pricing.price_for(None).input
    assert spending.add("answer", None, {"input_tokens": round(usd / price * 1e6)}, **who) == pytest.approx(usd)


def test_each_sites_limits_are_read_from_its_settings(site):  # noqa: F811
    limits = Limits.from_settings(site.usage)
    assert limits == {
        "wherempsstand": Limits(40, 60, 10.0, 150.0), "wherecountriesstand": Limits(40, None, 3.0, 50.0),
        "wherecouncilsstand": Limits(30, None, 3.0, 50.0)}[site.repo]
    assert type(limits.per_visitor_daily) is int and type(limits.daily_cap_usd) is float


@pytest.mark.parametrize("key", ["per_visitor_daily_questions", "daily_spend_cap_usd", "monthly_spend_cap_usd"])
def test_a_missing_limit_stops_the_site_and_names_the_key(site, key):  # noqa: F811
    """Each site's copy fell back to a figure in its code (40 or 30 a day, $3 or $10, $50 or $150); the package
    has none."""
    with pytest.raises(SettingsError, match=rf"\[usage\] needs {key}"):
        Limits.from_settings({k: v for k, v in site.usage.items() if k != key})
    with pytest.raises(SettingsError, match="not a number"):
        Limits.from_settings({**site.usage, key: "plenty"})


def test_a_site_with_accounts_needs_their_limit_and_its_message(db, clock):
    spending = Spending(db, PriceTable.from_settings(MPS.usage), clock=clock)
    without = {k: v for k, v in MPS.usage.items() if k != "per_user_daily_questions"}
    with pytest.raises(SettingsError, match="per_user_daily_questions"):
        Caps(spending, Limits.from_settings(without), MPS.messages, clock)
    with pytest.raises(SettingsError, match="account_daily_limit"):
        Caps(spending, Limits.from_settings(MPS.usage), COUNTRIES.messages, clock)
    no_accounts = Caps(spending, Limits.from_settings(COUNTRIES.usage), COUNTRIES.messages, clock)
    with pytest.raises(ValueError, match="no daily limit for signed-in accounts"):
        no_accounts.refusal(visitor=None, account=7)


def test_each_visitor_has_a_daily_limit_of_exactly_that_many_new_briefings(site, db, clock):  # noqa: F811
    caps, spending = caps_for(site, db, clock)
    limit = site.usage["per_visitor_daily_questions"]
    for _ in range(limit - 1):
        spending.add("answer", "m", {"input_tokens": 10}, visitor="v1")
        spending.add("parse", "m", {"input_tokens": 10}, visitor="v1")   # reading a question is not a briefing
    assert spending.briefings_today(visitor="v1") == limit - 1
    assert caps.refusal(visitor="v1") is None
    spending.add("answer", "m", {"input_tokens": 10}, visitor="v1")
    assert caps.refusal(visitor="v1") == Refusal("visitor_limit", site.messages.visitor_daily_limit)
    assert caps.refusal(visitor="v2") is None                            # another visitor is not limited
    assert caps.site_paused() is None                                    # nor is the site
    clock.advance(hours=12)                                              # midnight UTC: the count starts again
    assert caps.refusal(visitor="v1") is None and spending.briefings_today(visitor="v1") == 0


def test_the_sites_own_tests_limit_of_two(site, db, clock):  # noqa: F811
    """Where MPs Stand's tests set both daily limits to 2: the third new question gets the sources and a note."""
    caps, spending = caps_for(site, db, clock, per_visitor_daily_questions=2)
    for _ in range(2):
        assert caps.refusal(visitor="v1") is None
        spending.add("answer", "m", {"input_tokens": 1000, "output_tokens": 200}, visitor="v1")
    refused = caps.refusal(visitor="v1")
    assert refused is not None and refused.kind == "visitor_limit"
    assert ("limit" in refused.message) == (site is not COUNCILS) and "today" in refused.message


def test_a_signed_in_account_has_its_own_daily_limit(db, clock):
    """Where MPs Stand alone has accounts: an account is counted by its own limit and not as a visitor."""
    caps, spending = caps_for(MPS, db, clock, per_user_daily_questions=2, per_visitor_daily_questions=2)
    for _ in range(2):
        assert caps.refusal(visitor=None, account=7) is None
        spending.add("answer", "m", {"input_tokens": 1000}, account=7)
    refused = caps.refusal(visitor=None, account=7)
    assert refused == Refusal("account_limit", "You have reached today's question limit. It resets at midnight UTC.")
    assert "limit" in refused.message
    assert caps.refusal(visitor=None, account=8) is None and caps.refusal(visitor="v1") is None
    # the account's limit is the one that counts, even if a visitor's code came with it
    for _ in range(2):
        spending.add("answer", "m", {"input_tokens": 1000}, visitor="v1")
    assert caps.refusal(visitor="v1", account=8) is None
    assert caps.refusal(visitor="v1") == Refusal("visitor_limit", MPS.messages.visitor_daily_limit)
    assert spending.briefings_today(account=7) == 2 and spending.briefings_today(visitor="v1") == 2


def test_spending_that_reaches_todays_cap_stops_new_briefings(site, db, clock):  # noqa: F811
    caps, spending = caps_for(site, db, clock)
    cap = site.usage["daily_spend_cap_usd"]
    spend(spending, cap - 1.0)
    assert caps.refusal(visitor="v1") is None and caps.site_paused() is None
    spend(spending, 1.0)                                                # equal to the cap: that stops them
    assert spending.spent_since("2026-11-13") == cap
    paused = caps.site_paused()
    assert paused == Refusal("daily_cap", site.messages.daily_cap) and caps.refusal(visitor="v1") == paused
    assert caps.refusal(visitor=None) == paused                          # the site's own work is stopped too
    # the words the sites' tests look for
    assert ("budget" if site is not COUNCILS else "today's limit") in paused.message
    if site is not COUNCILS:
        assert "Today's budget" in paused.message
    clock.advance(hours=12)                                              # tomorrow, with the month's cap far off
    assert caps.site_paused() is None


def test_a_cap_of_nought_stops_every_briefing(site, db, clock):  # noqa: F811
    caps, _ = caps_for(site, db, clock, daily_spend_cap_usd=0.0)
    assert caps.refusal(visitor="v1") == Refusal("daily_cap", site.messages.daily_cap)
    caps, _ = caps_for(site, db, clock, monthly_spend_cap_usd=0)
    assert caps.site_paused() == Refusal("monthly_cap", site.messages.monthly_cap)


def test_the_months_spending_has_its_own_cap(site, db, clock):  # noqa: F811
    caps, spending = caps_for(site, db, clock)
    daily, monthly = site.usage["daily_spend_cap_usd"], site.usage["monthly_spend_cap_usd"]
    clock.set("2026-11-01T00:00:00+00:00")
    each = daily * 0.9
    days = 0
    while (days + 1) * each < monthly:                                   # just under the day's cap, day after day
        spend(spending, each)
        days += 1
        clock.advance(days=1)
        assert caps.site_paused() is None, days
    assert clock.now().strftime("%Y-%m") == "2026-11" and spending.spent_since("2026-11") < monthly
    spend(spending, monthly - days * each)                               # the month's cap is reached exactly
    assert spending.spent_since("2026-11") == pytest.approx(monthly)
    paused = caps.site_paused(0.000001)
    assert paused == Refusal("monthly_cap", site.messages.monthly_cap) and "this month's" in paused.message.lower()
    assert caps.refusal(visitor="v1", pending_usd=0.000001) == paused
    clock.set("2026-12-01T00:00:00+00:00")                               # a new month
    assert caps.site_paused() is None and caps.refusal(visitor="v1") is None


def test_the_reasons_come_in_todays_order(site, db, clock):  # noqa: F811
    """The visitor's own limit, then today's spending, then the month's."""
    caps, spending = caps_for(site, db, clock, per_visitor_daily_questions=1, daily_spend_cap_usd=1.0,
                              monthly_spend_cap_usd=1.0)
    spend(spending, 1.0, visitor="v1")
    assert caps.refusal(visitor="v1") == Refusal("visitor_limit", site.messages.visitor_daily_limit)
    assert caps.refusal(visitor="v2") == Refusal("daily_cap", site.messages.daily_cap)
    clock.advance(hours=12)                                              # the next day of the same month
    assert caps.refusal(visitor="v1") == Refusal("monthly_cap", site.messages.monthly_cap)


def test_briefings_in_progress_count_against_the_caps(site, db, clock):  # noqa: F811
    """Where Countries Stand's test: many questions at once mustn't all pass a cap before any is counted."""
    caps, spending = caps_for(site, db, clock, daily_spend_cap_usd=1.0)
    spend(spending, 0.60, visitor="v1")
    flight = BriefingsInProgress(per_key=2, total=3, estimate_usd=0.25)
    assert flight.start("a") is None and flight.start("a") is None
    assert flight.start("a") == Busy("visitor")
    assert flight.start("b") is None and flight.start("c") == Busy("site")
    assert flight.pending_usd(besides=1) == 0.5
    assert caps.refusal(visitor="v2") is None                            # $0.60 alone is under $1
    late = caps.refusal(visitor="v2", pending_usd=flight.pending_usd(besides=1))   # with $0.50 more on the way
    assert late == Refusal("daily_cap", site.messages.daily_cap)
    flight.finish("a"), flight.finish("a"), flight.finish("b")
    assert flight.running == {} and flight.pending_usd() == 0


def test_a_briefing_being_written_can_reach_the_cap_for_the_next(site, db, clock):  # noqa: F811
    """Where Councils Stand's test, without the web server: with the cap and the estimate both $0.15, a second
    question while the first is being written is refused."""
    caps, _ = caps_for(site, db, clock, daily_spend_cap_usd=0.15)
    flight = BriefingsInProgress(2, 8, 0.15)
    assert caps.refusal(visitor="v1") is None and flight.start("v1") is None
    assert caps.refusal(visitor="v1", pending_usd=flight.pending_usd(besides=1)) is None   # its own is not counted
    assert flight.start("v2") is None
    late = caps.refusal(visitor="v2", pending_usd=flight.pending_usd(besides=1))
    assert late is not None and late.kind == "daily_cap"
    flight.finish("v2")


def test_limits_are_plain_values(site):  # noqa: F811
    limits = Limits.from_settings(site.usage)
    assert dataclasses.replace(limits, daily_cap_usd=0.0).daily_cap_usd == 0.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        limits.daily_cap_usd = 1.0  # type: ignore[misc]
