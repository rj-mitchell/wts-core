"""What a model call costs and the record of what was spent: the sites' own tests of ``cost_usd``, ``record_usage``
and their owner's reports, run against each site's prices."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from test_usage_sites import COUNCILS, COUNTRIES, MPS, site  # noqa: F401  (the fixture)
from wts_core import usage
from wts_core.ports import Price, UnknownModel, Usage
from wts_core.settings import SettingsError
from wts_core.state import StateDB
from wts_core.testing import FixedClock
from wts_core.usage import AccountSpending, DaySpending, Failures, PriceTable, Spending, SpendingTotals

SONNET, HAIKU, OPUS = "claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"


def table(input: float, output: float, cache_read: float = 0.2, multiplier: float = 1.25, **models) -> PriceTable:
    return PriceTable.from_settings({"price_input_per_mtok": input, "price_output_per_mtok": output,
                                     "price_cache_read_per_mtok": cache_read, "cache_write_multiplier": multiplier,
                                     "models": models})


def cost(prices: PriceTable, counts: dict | None, model: str | None = None) -> float:
    return prices.cost(Usage.from_mapping(counts) if counts is not None else None, model)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock("2026-11-13T12:00:00+00:00")


@pytest.fixture
def db(tmp_path, clock) -> StateDB:
    return StateDB(tmp_path / "state.db", migrations=usage.migrations(), clock=clock)


# Prices and cost


def test_cost_calculation():
    """Where MPs Stand's: a million tokens in and a hundred thousand out."""
    assert cost(table(4.0, 20.0), {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_tokens": 0}) \
        == pytest.approx(6.0)


def test_cache_writes_and_reads_are_priced():
    prices = table(4.0, 20.0, 0.2)
    assert cost(prices, {"input_tokens": 1_000_000, "cache_write_tokens": 1_000_000}) == 5.0
    assert cost(prices, {"input_tokens": 0, "cache_read_tokens": 1_000_000}) == 0.2


def test_the_sdks_own_token_names_cost_the_same_as_the_sites():
    """The SDK's input_tokens leaves out the cache writes and reads; the sites' own counts put the writes into
    input_tokens. Either way each token is priced once."""
    prices = table(4.0, 20.0, 0.2)
    raw = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_creation_input_tokens": 1_000_000,
           "cache_read_input_tokens": 1_000_000}
    ours = {"input_tokens": 2_000_000, "output_tokens": 100_000, "cache_read_tokens": 1_000_000,
            "cache_write_tokens": 1_000_000}
    assert cost(prices, raw) == pytest.approx(4.0 + 2.0 + 5.0 + 0.2) and cost(prices, ours) == cost(prices, raw)
    # counts that are missing, None or not whole numbers are coped with
    assert cost(prices, {"input_tokens": 1000, "cache_read_input_tokens": None}) == pytest.approx(0.004)
    assert cost(prices, {"input_tokens": 1000.0, "output_tokens": "20"}) == pytest.approx(0.0044)

    # Where Countries Stand's figures
    prices = table(4.0, 20.0, 0.4)
    ours = {"input_tokens": 1500, "output_tokens": 200, "cache_read_tokens": 3000, "cache_write_tokens": 500}
    raw = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 3000,
           "cache_creation_input_tokens": 500}
    assert Usage.from_mapping(raw).as_stored() == ours
    assert cost(prices, raw) == cost(prices, ours) == pytest.approx(
        1000 / 1e6 * 4 + 500 / 1e6 * 4 * 1.25 + 200 / 1e6 * 20 + 3000 / 1e6 * 0.4)

    # Where Councils Stand's
    prices = table(3.0, 15.0, 0.3, 1.25)
    expected = round(1_200 / 1e6 * 3.0 + 20_000 / 1e6 * 3.0 * 1.25 + 800 / 1e6 * 15.0 + 5_000 / 1e6 * 0.3, 6)
    raw = {"input_tokens": 1_200, "output_tokens": 800, "cache_creation_input_tokens": 20_000,
           "cache_read_input_tokens": 5_000}
    assert cost(prices, raw) == expected == 0.0921
    assert cost(prices, {"input_tokens": 21_200, "output_tokens": 800, "cache_read_tokens": 5_000,
                         "cache_write_tokens": 20_000}) == expected
    assert cost(prices, {"input_tokens": 1000, "output_tokens": None}) == 0.003   # a missing count is nought


def test_no_usage_costs_nothing_and_cost_is_rounded_to_six_places(site):  # noqa: F811
    prices = PriceTable.from_settings(site.usage)
    assert prices.cost(None, SONNET) == 0.0 and prices.cost(Usage(), SONNET) == 0.0
    assert prices.cost(Usage(input_uncached=1), HAIKU) == 0.0          # a ten-millionth of a dollar
    assert prices.cost(Usage(input_uncached=7), HAIKU) == 0.000001
    assert prices.cost(Usage(output=3, cache_read=11), SONNET) == round(3 / 1e6 * 10.0 + 11 / 1e6 * 0.2, 6)


def test_each_sites_models_are_priced_as_its_settings_say(site):  # noqa: F811
    prices = PriceTable.from_settings(site.usage)
    sonnet, haiku = Price(2.0, 10.0, 0.2, 1.25), Price(0.1, 0.5, 0.01, 1.25)
    base = Price(4.0, 20.0, 0.2, 1.25) if site is MPS else sonnet
    assert prices.base == base
    assert prices.price_for(SONNET) == sonnet and prices.price_for(HAIKU) == haiku
    assert prices.price_for(OPUS) == base
    # a dated or longer id takes the prices of the name it starts with; no model, or one with no entry, the base
    assert prices.price_for(HAIKU + "-20261001") == haiku and prices.price_for(SONNET + "[1m]") == sonnet
    assert prices.price_for(None) == base and prices.price_for("") == base
    assert prices.price_for("some-other-model") == base and prices.price_for("claude-haiku") == base
    # Where Countries Stand's test: a briefing of 1,000 tokens in and 200 out, costed as the briefing model
    assert prices.cost(Usage(input_uncached=1000, output=200), SONNET) == 0.004
    assert [name for name, _ in prices.models] == list(site.usage["models"])


def test_a_models_own_prices_are_laid_over_the_base_and_the_longest_matching_name_wins():
    """Where Countries Stand's test of who read the question: each model at its own input price."""
    prices = table(2.0, 10.0, **{HAIKU: {"price_input_per_mtok": 0.1}, SONNET: {"price_input_per_mtok": 3.0}})
    million = Usage(input_uncached=1_000_000)
    assert prices.cost(million, HAIKU) == pytest.approx(0.1) and prices.cost(million, SONNET) == pytest.approx(3.0)
    assert prices.price_for(HAIKU) == Price(0.1, 10.0, 0.2, 1.25)      # what it doesn't give is the base's
    # a model whose id begins with two names takes the longer one's prices, whichever the settings give first
    for names in (("claude", HAIKU), (HAIKU, "claude")):
        nested = table(2.0, 10.0, **{name: {"price_input_per_mtok": 9.0 if name == "claude" else 0.1}
                                     for name in names})
        assert nested.price_for(HAIKU).input == 0.1 and nested.price_for(HAIKU + "-20261001").input == 0.1
        assert nested.price_for(SONNET).input == 9.0  # only the shorter name matches it


def test_a_variant_with_its_own_table_is_costed_at_its_own_prices_and_strict_prices_know_it():
    """Found by Where Countries Stand's fix-forward: with tables for a model and for a variant of it, the variant
    was costed at the model's prices when the model's table came first in the file, and strict prices said
    nothing, since the variant "had a price"."""
    fast = SONNET + "-fast"
    prices = table(2.0, 10.0, **{SONNET: {"price_input_per_mtok": 3.0}, fast: {"price_input_per_mtok": 12.0}})
    million = Usage(input_uncached=1_000_000)
    assert prices.cost(million, fast) == pytest.approx(12.0) and prices.cost(million, SONNET) == pytest.approx(3.0)
    assert prices.cost(million, fast + "-20261001") == pytest.approx(12.0)
    prices.require([SONNET, fast], base_counts=False)
    # What strict prices do not catch, and why it is kept: a name stands for every id that begins with it (a dated
    # id must find its model's table), so a variant with no table of its own takes the shorter name's.
    only = table(2.0, 10.0, **{SONNET: {"price_input_per_mtok": 3.0}})
    only.require([fast], base_counts=False)
    assert only.cost(million, fast) == pytest.approx(3.0)
    with pytest.raises(UnknownModel, match="claude-opus-5-5"):  # caught only when no shorter name matches
        only.require([fast, OPUS], base_counts=False)
    own = table(2.0, 10.0, **{HAIKU: {"cache_write_multiplier": 2.0, "price_cache_read_per_mtok": 0.01}})
    assert own.cost(Usage(cache_write=1_000_000), HAIKU) == 4.0 and own.cost(Usage(cache_write=1_000_000), "m") == 2.5


@pytest.mark.parametrize("key", ["price_input_per_mtok", "price_output_per_mtok", "price_cache_read_per_mtok",
                                 "cache_write_multiplier"])
def test_a_missing_base_price_stops_the_site_and_names_the_key(site, key):  # noqa: F811
    """Each site's copy fell back to prices in its code ($4 and $20 a million on two sites, $2 and $10 on the
    third: Where Councils Stand's test_default_prices_are_the_sites_own). The package has none."""
    with pytest.raises(SettingsError, match=rf"\[usage\] needs {key}"):
        PriceTable.from_settings({k: v for k, v in site.usage.items() if k != key})
    with pytest.raises(SettingsError, match=rf"\[usage\] {key} must be a number"):
        PriceTable.from_settings({**site.usage, key: "cheap"})


def test_prices_that_are_not_prices_stop_the_site():
    with pytest.raises(SettingsError, match="needs price_input_per_mtok, price_output_per_mtok, "
                                            "price_cache_read_per_mtok, cache_write_multiplier"):
        PriceTable.from_settings({})
    with pytest.raises(SettingsError, match=r'\[pricing.models."claude-haiku-5-5"\] price_input_per_mtok'):
        PriceTable.from_settings({**COUNTRIES.usage, "models": {HAIKU: {"price_input_per_mtok": None}}},
                                 section="pricing")
    with pytest.raises(SettingsError, match="must be a table of prices"):
        PriceTable.from_settings({**COUNTRIES.usage, "models": {HAIKU: 0.1}})
    with pytest.raises(SettingsError, match="models must be tables"):
        PriceTable.from_settings({**COUNTRIES.usage, "models": [HAIKU]})
    assert PriceTable.from_settings({k: v for k, v in COUNCILS.usage.items() if k != "models"}).models == ()


def test_an_unknown_model_stops_a_site_that_asks_for_strict_pricing(site):  # noqa: F811
    prices = PriceTable.from_settings(site.usage)
    # today's rule: the base prices are an entry, so every model has a price
    prices.require([*site.models, "some-other-model", None], base_counts=True)
    # strict: the model each site's base prices are for has no entry of its own yet
    without = OPUS if site is MPS else SONNET
    with pytest.raises(UnknownModel, match=f"no price for {without}: add .usage.models"):
        prices.require(site.models, base_counts=False)
    with pytest.raises(UnknownModel, match="no price for another-model, some-other-model"):
        prices.require([HAIKU, "some-other-model", "another-model", "some-other-model"], base_counts=False)
    # with an entry for it (the base prices, written out), every model the site names is known
    explicit = {**site.usage, "models": {**site.usage["models"], without: {}}}
    strict = PriceTable.from_settings(explicit)
    strict.require([*site.models, HAIKU + "-20261001", None, ""], base_counts=False)
    assert strict.price_for(without) == prices.price_for(without) == prices.base
    assert isinstance(UnknownModel("x"), LookupError)


# The spending record


def rows(db: StateDB, columns: str = "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd"):
    with db.connect() as con:
        return [tuple(r) for r in con.execute(f"SELECT {columns} FROM wts_spending ORDER BY id")]


def test_token_counts_are_stored_the_same_whichever_names_the_usage_uses(db, clock):
    """What is written: the sites' own counts as they are, and the SDK's own names the same way, with the cache
    writes counted into input_tokens (the three sites' tests of ``record_usage``)."""
    spending = Spending(db, table(4.0, 20.0, 0.2), clock=clock)
    raw = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_creation_input_tokens": 1_000_000,
           "cache_read_input_tokens": 1_000_000}
    assert spending.add("answer", "m", raw) == 11.2
    assert spending.add("answer", "m", Usage.from_mapping(raw).as_stored()) == 11.2
    assert spending.add("answer", "m", Usage.from_mapping(raw)) == 11.2
    assert rows(db) == [(2_000_000, 100_000, 1_000_000, 1_000_000, 11.2)] * 3


def test_a_row_holds_who_what_and_when_and_no_usage_writes_nothing(db, clock):
    """Where Councils Stand's test."""
    prices = table(3.0, 15.0, 0.3)
    spending = Spending(db, prices, clock=clock)
    ours = {"input_tokens": 1500, "output_tokens": 200, "cache_read_tokens": 3000, "cache_write_tokens": 500}
    raw = {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 3000,
           "cache_creation_input_tokens": 500}
    spent = spending.add("answer", "m", ours, visitor="v1")
    assert spent == cost(prices, raw) == spending.add("answer", "m", raw, visitor="v1")
    assert rows(db, "at, visitor, account, kind, model, input_tokens, output_tokens, cache_read_tokens, "
                    "cache_write_tokens, cost_usd") == [
        ("2026-11-13T12:00:00+00:00", "v1", None, "answer", "m", 1500, 200, 3000, 500, spent)] * 2
    assert spending.add("answer", "m", None, visitor="v1") == 0.0     # no usage: nothing is written
    assert spending.add("answer", "m", {}, visitor="v1") == 0.0
    assert len(rows(db)) == 2
    assert spending.add("parse", None, {"input_tokens": 0}, account=7) == 0.0   # counts of nought are still a call
    assert rows(db, "visitor, account, kind, model, input_tokens, cost_usd")[-1] == (None, 7, "parse", None, 0, 0.0)


def test_each_call_is_costed_at_its_models_prices(site, db, clock):  # noqa: F811
    spending = Spending(db, PriceTable.from_settings(site.usage), clock=clock)
    million = {"input_tokens": 1_000_000}
    assert spending.add("parse", HAIKU, million, visitor="v") == 0.1
    assert spending.add("answer", SONNET, million, visitor="v") == 2.0
    assert spending.add("answer", OPUS, million, visitor="v") == (4.0 if site is MPS else 2.0)
    assert spending.add("topic", None, million) == (4.0 if site is MPS else 2.0)
    assert spending.spent_since("2026-11-13") == pytest.approx(sum(r[0] for r in rows(db, "cost_usd")))
    assert spending.briefings_today(visitor="v") == 2


def test_a_briefing_begun_and_paid_for_but_not_finished_counts_towards_the_limit_and_not_as_a_briefing(db, clock):
    """A visitor who left part-way through, or whose briefing the model broke off, was still charged: without this
    they could begin briefings and leave each one before its end, every one of them paid for, without limit."""
    spending = Spending(db, table(2.0, 10.0), clock=clock)
    spending.add("answer", "m", {"input_tokens": 1000}, visitor="v")
    spending.add("unfinished", "m", {"input_tokens": 1000, "output_tokens": 4}, visitor="v")
    spending.add("parse", "m", {"input_tokens": 1000}, visitor="v")
    assert spending.briefings_today(visitor="v") == 2 and spending.briefings_today(visitor="w") == 0
    spending.add("unfinished", "m", {"input_tokens": 1000}, account=7)
    assert spending.briefings_today(account=7) == 1
    totals = spending.totals("2026-11-13")
    assert (totals.calls, totals.briefings) == (4, 1)  # the owner's reports count only briefings written
    assert [d.briefings for d in spending.by_day("2026-11-13")] == [1]


def test_a_call_whose_cost_is_known_and_its_tokens_are_not_is_recorded_at_that_cost(db, clock):
    """How the briefing desk charges a briefing given up before its model said what it had used: the estimate it
    was reserved at, with no tokens."""
    spending = Spending(db, table(2.0, 10.0), clock=clock)
    assert spending.add("unfinished", "m", None, visitor="v", cost_usd=0.1600004) == 0.16
    assert rows(db, "kind, visitor, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd") == [
        ("unfinished", "v", 0, 0, 0, 0, 0.16)]
    assert spending.spent_since("2026-11-13") == 0.16 and spending.briefings_today(visitor="v") == 1


def test_spending_is_summed_from_a_day_a_month_or_a_time(db, clock):
    spending = Spending(db, table(2.0, 10.0), clock=clock)
    clock.set("2026-10-31T23:59:59+00:00")
    spending.add("answer", "m", {"input_tokens": 500_000}, visitor="v")          # $1 in October
    clock.set("2026-11-01T00:00:00+00:00")
    spending.add("answer", "m", {"input_tokens": 1_000_000}, visitor="v")        # $2 on the 1st
    clock.set("2026-11-13T00:00:00+00:00")
    spending.add("answer", "m", {"input_tokens": 2_000_000}, visitor="v")        # $4 at midnight on the 13th
    clock.set("2026-11-13T12:00:00+00:00")
    assert spending.spent_since("2026-11-13") == 4.0 and spending.spent_since("2026-11") == 6.0
    assert spending.spent_since("2026-10") == 7.0 and spending.spent_since("2026-11-13T00:00:01+00:00") == 0.0
    assert spending.spent_since("2026-12") == 0.0
    assert spending.briefings_today(visitor="v") == 1 and spending.briefings_today(visitor="w") == 0
    with pytest.raises(ValueError, match="a visitor's code or an account"):
        spending.briefings_today()


def test_usage_report_figures_near_a_cap(db, clock):
    """Where Countries Stand's ``test_usage_report_warns_near_a_cap``: the figures its ``summary`` and ``warnings``
    are made from (the wording stays the site's)."""
    spending = Spending(db, table(2.0, 10.0), clock=clock)
    failures = Failures(db, clock=clock)
    day, month = clock.now().strftime("%Y-%m-%d"), clock.now().strftime("%Y-%m")
    spending.add("answer", "m", {"input_tokens": 300_000, "output_tokens": 10_000}, visitor="v1")       # $0.70
    today = spending.totals(day)
    assert today == SpendingTotals(spent_usd=pytest.approx(0.7), calls=1, briefings=1, visitors=1)
    assert round(today.spent_usd, 4) == 0.7 and round(today.spent_usd, 4) < 0.8 * 1.0     # no warning yet
    spending.add("answer", "m", {"input_tokens": 50_000}, visitor="v2")                                # $0.80
    assert round(spending.totals(day).spent_usd, 4) == 0.8                                # "80% used ($0.80 spent)"
    spending.add("answer", "m", {"input_tokens": 100_000}, visitor="v2")
    spending.add("parse", "m", {"input_tokens": 10}, visitor="v2")
    failures.note("briefing", "q", "APIError: overloaded")
    today = spending.totals(day)
    assert round(today.spent_usd, 4) >= 1.0                          # "reached: new briefings are paused"
    assert (today.calls, today.briefings, today.visitors) == (4, 3, 2)
    assert spending.totals(month) == today
    since = (clock.now() - timedelta(days=7)).isoformat(timespec="seconds")
    assert failures.recent(None, since=since) == [
        {"at": "2026-11-13T12:00:00+00:00", "kind": "briefing", "question": "q", "error": "APIError: overloaded"}]
    assert spending.by_day(since) == [DaySpending("2026-11-13", pytest.approx(today.spent_usd), 4, 3)]


def test_each_days_spending_is_listed_oldest_first(db, clock):
    spending = Spending(db, table(2.0, 10.0), clock=clock)
    for day, tokens in (("2026-11-10", 100_000), ("2026-11-12", 200_000), ("2026-11-12", 300_000)):
        clock.set(f"{day}T09:30:00+00:00")
        spending.add("answer", "m", {"input_tokens": tokens}, visitor="v")
        spending.add("parse", "m", {"input_tokens": tokens}, visitor="v")
    assert spending.by_day("2026-11-11") == [DaySpending("2026-11-12", pytest.approx(2.0), 4, 2)]
    assert [d.day for d in spending.by_day("2026-11")] == ["2026-11-10", "2026-11-12"]
    assert spending.by_day("2026-12") == [] and spending.totals("2026-12") == SpendingTotals(0.0, 0, 0, 0)


def test_spending_shows_who_it_was_for(db, clock):
    """Where MPs Stand's admin page (``summary``): each signed-in account, the public and the site's own work, the
    largest first; and its alert at 80% of the day's cap."""
    spending = Spending(db, PriceTable.from_settings(MPS.usage), clock=clock)
    assert spending.by_account("2026-11") == []
    spending.add("answer", OPUS, {"input_tokens": 10_000, "output_tokens": 1_000}, account=1)
    assert sum(a.spent_usd for a in spending.by_account("2026-11")) > 0          # its test: total_usd > 0
    spending.add("answer", "m", {"input_tokens": 2_000_000}, visitor="v")          # $8 of a $10 day
    spending.add("answer", "m", {"input_tokens": 1_000}, visitor="w")
    spending.add("topic", "m", {"input_tokens": 500_000})                          # the site's own: $2
    spending.add("parse", "m", {"input_tokens": 1_000}, account=1)
    who = spending.by_account("2026-11")
    assert who == [
        AccountSpending(account=None, public=True, spent_usd=pytest.approx(8.004), calls=2, visitors=2),
        AccountSpending(account=None, public=False, spent_usd=pytest.approx(2.0), calls=1, visitors=0),
        AccountSpending(account=1, public=False, spent_usd=pytest.approx(0.064), calls=2, visitors=0)]
    today = spending.totals("2026-11-13")
    assert today.calls == 5 and today.spent_usd == pytest.approx(sum(a.spent_usd for a in who))
    assert f"{today.spent_usd / 10.0:.0%}" == "101%" and f"{who[0].spent_usd / 10.0:.0%} of the $10 cap" == \
        "80% of the $10 cap"


def test_writes_to_the_one_hour_cache_are_costed_at_their_own_higher_rate():
    """No site uses the one-hour cache today. If one turns it on, its writes cost twice the input price (Anthropic's
    published rate), not the five-minute cache's 1.25 times: costing them alike would under-count spending against
    the daily and monthly caps."""
    usage = {"price_input_per_mtok": 2.0, "price_output_per_mtok": 10.0, "price_cache_read_per_mtok": 0.2,
             "cache_write_multiplier": 1.25}
    prices = PriceTable.from_settings(usage)
    short = Usage(cache_write=1_000_000)
    long = Usage(cache_write=1_000_000, cache_write_long=1_000_000)
    mixed = Usage(cache_write=1_000_000, cache_write_long=400_000)
    assert prices.cost(short, "m") == 2.5 and prices.cost(long, "m") == 4.0
    assert prices.cost(mixed, "m") == round(0.6 * 2.5 + 0.4 * 4.0, 6)
    # a site may set its own figure, for all models or for one
    own = PriceTable.from_settings({**usage, "cache_write_long_multiplier": 3.0,
                                    "models": {"small": {"price_input_per_mtok": 1.0,
                                                         "cache_write_long_multiplier": 2.5}}})
    assert own.cost(long, "m") == 6.0 and own.cost(long, "small-1") == 2.5
    # the stored form says how many only when there were any, and reads back to the same
    assert "cache_write_long_tokens" not in short.as_stored()
    assert Usage.from_mapping(mixed.as_stored()) == mixed and (mixed + mixed).cache_write_long == 800_000


def test_a_visitors_code_is_kept_only_for_its_own_day(tmp_path):
    """Found in review: with the code left on every row for good, a visitor's day could be gathered from the
    spending record, and through each row's time and token counts tied to the new record of each briefing. The
    code is for the daily limit, so it is kept for its day and then forgotten; each day's number of visitors is
    kept, so the owner's reports say what they said."""
    clock = FixedClock("2026-11-12T10:00:00+00:00")
    db = StateDB(tmp_path / "state.db", migrations=usage.migrations(), clock=clock)
    prices = PriceTable.from_settings({"price_input_per_mtok": 2.0, "price_output_per_mtok": 10.0,
                                       "price_cache_read_per_mtok": 0.2, "cache_write_multiplier": 1.25})
    spending = Spending(db, prices, clock=clock)
    for visitor, account in (("a" * 24, None), ("a" * 24, None), ("b" * 24, None), ("c" * 24, 7), (None, None)):
        spending.add("answer", "m", Usage(input_uncached=1000), visitor=visitor, account=account)
    before = (spending.totals("2026-11"), spending.by_account("2026-11"), spending.by_day("2026-11"))
    assert before[0].visitors == 3 and spending.briefings_today(visitor="a" * 24) == 2

    def codes() -> list[str | None]:
        with db.connect() as con:
            return [r[0] for r in con.execute("SELECT visitor FROM wts_spending ORDER BY id")]

    assert spending.forget_visitors() == 0 and codes()[:4] == ["a" * 24, "a" * 24, "b" * 24, "c" * 24]  # still today
    clock.advance(days=1)
    spending.add("answer", "m", Usage(input_uncached=1000), visitor="d" * 24)  # the first call of the new day
    assert codes() == ["", "", "", "", None, "d" * 24]
    after = (spending.totals("2026-11"), spending.by_account("2026-11"), spending.by_day("2026-11"))
    assert after[0].visitors == 4 and after[0].calls == 6
    assert {(a.account, a.public): a.visitors for a in after[1]} == {(None, True): 3, (7, False): 1, (None, False): 0}
    assert {(a.account, a.public): a.visitors for a in before[1]} == {(None, True): 2, (7, False): 1, (None, False): 0}
    assert spending.totals("2026-11-13").visitors == 1 and spending.forget_visitors() == 0  # twice changes nothing
    assert spending.totals("2026-11").visitors == 4


def _spending(tmp_path, at="2026-11-12T10:00:00+00:00", migrations=None):
    clock = FixedClock(at)
    db = StateDB(tmp_path / "state.db", migrations=usage.migrations() if migrations is None else migrations,
                 clock=clock)
    prices = PriceTable.from_settings({"price_input_per_mtok": 2.0, "price_output_per_mtok": 10.0,
                                       "price_cache_read_per_mtok": 0.2, "cache_write_multiplier": 1.25})
    return clock, db, Spending(db, prices, clock=clock)


def _rows(db, what="account"):
    with db.connect() as con:
        return [r[0] for r in con.execute(f"SELECT {what} FROM wts_spending ORDER BY id")]


def test_once_its_day_is_over_a_spending_row_does_not_say_it_was_an_accounts_at_all(tmp_path):
    """Found by the independent reviews of Where MPs Stand's adoption and then of 0.3.0 itself. A spending row
    kept its account for good, beside token counts the record of each briefing also holds, so an account's
    questions could be read off. A first mend left "some account" where the account's number was, and each
    account's total for the day beside it: the day's account rows were still told from the public's, and the
    totals dealt them out among the accounts. So when its day is over a row loses the account altogether and is
    the same as a member of the public's, and what is kept for an account is its calls and cost by the calendar
    month, to the cent."""
    clock, db, spending = _spending(tmp_path)
    for kind, tokens, visitor, account in (("parse", 1_000, "c" * 24, 7), ("answer", 41_237, "c" * 24, 7),
                                           ("answer", 9_000, None, 8), ("answer", 5_000, "a" * 24, None),
                                           ("topic", 2_000, None, None)):
        spending.add(kind, "m", Usage(input_uncached=tokens), visitor=visitor, account=account)
    before = (spending.totals("2026-11"), spending.by_account("2026-11"), spending.by_day("2026-11"))
    assert spending.briefings_today(account=7) == 1 and spending.briefings_today(account=8) == 1

    spending.forget_visitors()
    assert _rows(db) == [7, 7, 8, None, None]  # still today: the day's limit counts by them
    clock.advance(days=1)
    spending.add("answer", "m", Usage(input_uncached=3_000), visitor="f" * 24, account=7)  # the new day's first call
    # yesterday's rows: an account's (with a visitor's code or without one) and the public's are the same thing,
    # "somebody's"; the site's own work is as it was
    assert _rows(db) == [None, None, None, None, None, 7]
    assert _rows(db, "visitor") == ["", "", "", "", None, "f" * 24]
    with db.connect() as con:
        assert [tuple(r) for r in con.execute("SELECT * FROM wts_account_months ORDER BY account")] == [
            ("2026-11", 7, 0.08, 2, 1), ("2026-11", 8, 0.02, 1, 0)]  # by the month, to the cent
        assert [tuple(r) for r in con.execute("SELECT * FROM wts_visitor_days ORDER BY who")] == [
            ("2026-11", "", 1), ("2026-11-12", "*", 2)]  # the public's by the month; the whole day's by the day
        assert "wts_account_days" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    # the owner's report: the same lines, each account's past days to the cent, and still adding up to what was spent
    after = spending.by_account("2026-11")
    assert {(a.account, a.public): (round(a.spent_usd, 6), a.calls) for a in before[1]} == {
        (7, False): (0.084474, 2), (8, False): (0.018, 1), (None, True): (0.01, 1), (None, False): (0.004, 1)}
    assert {(a.account, a.public): (round(a.spent_usd, 6), a.calls) for a in after} == {
        (7, False): (0.086, 3), (8, False): (0.02, 1), (None, True): (0.012474, 1), (None, False): (0.004, 1)}
    assert [a.account for a in after] == [7, 8, None, None]  # the largest first, as before
    assert {(a.account, a.public): a.visitors for a in after} == {(7, False): 2, (8, False): 0, (None, True): 1,
                                                                 (None, False): 0}
    assert spending.totals("2026-11").spent_usd == pytest.approx(sum(a.spent_usd for a in after))
    assert spending.by_day("2026-11")[0] == before[2][0]  # the day's own figures are untouched
    assert spending.by_account("2026-11-13") == [AccountSpending(7, False, pytest.approx(0.006), 1, 1)]  # today alone
    assert spending.by_account("2026-11-13T10:00:01+00:00") == []  # and from a time later today: exactly
    assert spending.briefings_today(account=7) == 1  # and the day's limit counts today's
    spending.forget_visitors()
    spending.forget_visitors()  # twice changes nothing
    assert _rows(db) == [None, None, None, None, None, 7] and spending.by_account("2026-11") == after
    with db.connect() as con:  # the row and its counts are still there: it is whose that is gone
        assert tuple(con.execute("SELECT account, visitor, cost_usd FROM wts_spending WHERE input_tokens = 41237"
                                 ).fetchone()) == (None, "", pytest.approx(0.082474))


def test_who_the_spending_was_for_is_counted_by_whole_months_but_for_today(tmp_path):
    """An account's part of a month gone by cannot be divided, so a period that begins on a day that is over is
    counted from the first of its month, for every line: the review found one that counted the whole day for the
    accounts and part of it for the public."""
    clock, db, spending = _spending(tmp_path, "2026-10-30T09:00:00+00:00")
    spending.add("answer", "m", Usage(input_uncached=10_000), visitor="o" * 24, account=7)  # October
    for day, hour in (("2026-11-03", 9), ("2026-11-03", 15), ("2026-11-20", 9)):
        clock.set(f"{day}T{hour:02d}:00:00+00:00")
        spending.add("answer", "m", Usage(input_uncached=10_000), visitor=f"{day}{hour}" * 2, account=7)
        spending.add("answer", "m", Usage(input_uncached=20_000), visitor=f"p{day}{hour}" * 2)
    clock.set("2026-11-21T08:00:00+00:00")
    spending.add("answer", "m", Usage(input_uncached=5_000), visitor="t" * 24, account=7)
    november = {(a.account, a.public): (round(a.spent_usd, 6), a.calls, a.visitors)
                for a in spending.by_account("2026-11")}
    assert november == {(7, False): (0.07, 4, 4), (None, True): (0.12, 3, 3)}
    for since in ("2026-11-01", "2026-11-03", "2026-11-03T12:00:00+00:00", "2026-11-20T23:59:59+00:00"):
        assert {(a.account, a.public): (round(a.spent_usd, 6), a.calls, a.visitors)
                for a in spending.by_account(since)} == november, since
    assert [(a.account, a.calls) for a in spending.by_account("2026-10")] == [(None, 3), (7, 5)]
    assert [(a.account, round(a.spent_usd, 6)) for a in spending.by_account("2026-11-21")] == [(7, 0.01)]
    assert spending.by_account("2026-11-22") == []


def test_a_period_that_begins_part_way_through_a_day_that_is_over_counts_the_whole_day(tmp_path):
    """The time of day of a call is forgotten with its day, so a day that is over is all or nothing: and it is
    the same answer before the night's forgetting and after it."""
    clock, db, spending = _spending(tmp_path, "2026-11-12T09:00:00+00:00")
    spending.add("answer", "m", Usage(input_uncached=10_000), visitor="a" * 24)
    clock.set("2026-11-12T18:00:00+00:00")
    spending.add("answer", "m", Usage(input_uncached=20_000), visitor="b" * 24)
    part_way = "2026-11-12T12:00:00+00:00"
    assert spending.spent_since(part_way) == pytest.approx(0.04)  # today: from that time on, exactly
    assert (spending.totals(part_way).calls, [d.calls for d in spending.by_day(part_way)]) == (1, [1])
    clock.set("2026-11-13T02:00:00+00:00")  # the day is over; nothing has forgotten it yet

    def figures():
        totals = spending.totals(part_way)
        return (round(spending.spent_since(part_way), 6), totals.calls, totals.visitors,
                [(d.day, d.calls) for d in spending.by_day(part_way)])

    assert figures() == (0.06, 2, 2, [("2026-11-12", 2)])
    assert _rows(db, "at") == ["2026-11-12T09:00:00+00:00", "2026-11-12T18:00:00+00:00"]
    assert spending.forget_visitors() == 2
    assert _rows(db, "at") == ["2026-11-12T00:00:00+00:00"] * 2  # the day, and no time
    assert figures() == (0.06, 2, 2, [("2026-11-12", 2)])
    assert spending.spent_since("2026-11-12") == pytest.approx(0.06) == spending.spent_since("2026-11")
    assert spending.spent_since("2026-11-13") == 0  # what the daily cap asks: today's


def test_an_account_numbered_nought_is_an_account_like_any_other(tmp_path):
    """As on 0.2.1. (The first mend used 0 to mean "some account", and the report then lost a real account 0.)"""
    clock, db, spending = _spending(tmp_path)
    spending.add("answer", "m", Usage(input_uncached=10_000), visitor="z" * 24, account=0)
    spending.add("answer", "m", Usage(input_uncached=5_000), visitor="p" * 24)
    assert [(a.account, a.public, a.calls) for a in spending.by_account("2026-11")] == [(0, False, 1), (None, True, 1)]
    assert spending.briefings_today(account=0) == 1
    clock.advance(days=1)
    assert spending.forget_visitors() == 2
    assert [(a.account, a.public, a.calls, a.spent_usd) for a in spending.by_account("2026-11")] == [
        (0, False, 1, 0.02), (None, True, 1, 0.01)]
    assert _rows(db) == [None, None]


def test_a_database_that_0_2_1_wrote_is_brought_to_the_same(tmp_path):
    """0.2.1 forgot the visitor's code and kept the account and the second for good, and counted the public's and
    each account's visitors by the day. Opened by this version, and forgotten once, it holds what any other does."""
    as_0_2_1 = tuple(m for m in usage.migrations() if m.number <= 14)
    clock, db, _ = _spending(tmp_path, "2026-11-14T10:00:00+00:00", migrations=as_0_2_1)
    with db.connect() as con:
        con.executemany("INSERT INTO wts_spending (at, kind, model, visitor, account, input_tokens, cost_usd) "
                        "VALUES (?, 'answer', 'm', ?, ?, ?, ?)", [
                            ("2026-11-12T09:13:44+00:00", "", 7, 1000, 0.031234),
                            ("2026-11-12T11:02:07+00:00", "", None, 2000, 0.02),
                            ("2026-11-13T08:00:01+00:00", "", 7, 3000, 0.04)])
        con.executemany("INSERT INTO wts_visitor_days (day, who, visitors) VALUES (?, ?, ?)", [
            ("2026-11-12", "*", 2), ("2026-11-12", "", 1), ("2026-11-12", "7", 1),
            ("2026-11-13", "*", 1), ("2026-11-13", "7", 1)])
    clock, db, spending = _spending(tmp_path, "2026-11-14T10:00:00+00:00")
    with db.connect() as con:  # the migrations: the visitors by the month, and no row of a day gone by to the second
        assert [tuple(r) for r in con.execute("SELECT * FROM wts_visitor_days ORDER BY day, who")] == [
            ("2026-11", "", 1), ("2026-11-12", "*", 2), ("2026-11-13", "*", 1)]
        assert [tuple(r) for r in con.execute("SELECT month, account, visitors FROM wts_account_months")] == [
            ("2026-11", 7, 2)]
    assert _rows(db, "at") == ["2026-11-12T00:00:00+00:00"] * 2 + ["2026-11-13T00:00:00+00:00"]
    assert _rows(db) == [7, None, 7]  # the account goes with the first forgetting, which has the package's clock
    assert usage.forget_earlier_days(db, clock=clock) == usage.Forgotten(codes=0, accounts=2, times=0)
    assert _rows(db) == [None, None, None]
    assert {(a.account, a.public): (round(a.spent_usd, 6), a.calls, a.visitors)
            for a in spending.by_account("2026-11")} == {(7, False): (0.07, 2, 2), (None, True): (0.021234, 1, 1)}
    assert spending.totals("2026-11").visitors == 3


def test_after_an_undo_and_a_second_import_nobodys_spending_is_counted_twice(tmp_path):
    """Found by the second independent review of 0.3.0. A site's undo script writes its old tables again from the
    package's and clears the package's rows and the import's mark; the import then runs again. Each account's
    month totals survived that, and the same spending came back beside them: the lines of who the spending was
    for added up to 0.56 of 0.40 spent. When an import runs over an empty spending record, what was kept in
    summary of the rows that are gone goes with them."""
    from wts_core.state import Import

    old = "CREATE TABLE usage (id INTEGER PRIMARY KEY, user_id INTEGER, at TEXT, kind TEXT, model TEXT, " \
          "input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, visitor TEXT)"
    move = Import("the-move", (
        "INSERT INTO wts_spending (id, at, kind, model, visitor, account, input_tokens, output_tokens, cost_usd) "
        "SELECT id, at, kind, model, visitor, user_id, input_tokens, output_tokens, cost_usd FROM usage",),
        needs=("usage",))
    clock = FixedClock("2026-11-10T09:00:00+00:00")
    path = tmp_path / "state.db"
    sqlite3.connect(path).executescript(old)

    def moved():
        db = StateDB(path, migrations=usage.migrations(), imports=[move], clock=clock)
        prices = PriceTable.from_settings({"price_input_per_mtok": 2.0, "price_output_per_mtok": 10.0,
                                           "price_cache_read_per_mtok": 0.2, "cache_write_multiplier": 1.25})
        return db, Spending(db, prices, clock=clock)

    def figures(spending):
        lines = spending.by_account("2026-11")
        return (round(spending.spent_since("2026-11"), 4), round(sum(a.spent_usd for a in lines), 4),
                sorted((str(a.account), a.public, a.calls) for a in lines))

    db, spending = moved()
    for who in ({"account": 1}, {"account": 2}, {"visitor": "a" * 24}, {"visitor": "b" * 24}, {}):
        spending.add("answer", "m", Usage(input_uncached=30000, output=2000), **who)
    clock.set("2026-11-12T09:00:00+00:00")
    usage.forget_earlier_days(db, clock=clock)
    assert figures(spending) == (0.4, 0.4, [("1", False, 1), ("2", False, 1), ("None", False, 1), ("None", True, 2)])
    # the site's undo script, as the four sites' are written: the old table again from the package's, the
    # package's rows and the import's mark cleared
    con = sqlite3.connect(path)
    con.executescript(
        "DELETE FROM usage; INSERT INTO usage (id, user_id, at, kind, model, input_tokens, output_tokens, "
        "cost_usd, visitor) SELECT id, account, at, kind, model, input_tokens, output_tokens, cost_usd, "
        "nullif(visitor, '') FROM wts_spending; DELETE FROM wts_spending; "
        "DELETE FROM wts_schema WHERE name = 'import:the-move';")
    con.close()
    db, spending = moved()  # coming forward again: the import runs afresh
    total, lines_add_up_to, lines = figures(spending)
    assert (total, lines_add_up_to) == (0.4, 0.4)  # it was 0.4 and 0.56
    # what an undo after the forgetting gives back: the spending, all of it, and no longer whose
    assert lines == [("None", False, 5)]
    with db.connect() as con:
        assert con.execute("SELECT count(*) FROM wts_account_months").fetchone()[0] == 0
        assert [tuple(r) for r in con.execute("SELECT day, who FROM wts_visitor_days")] == [("2026-11-10", "*")]
    assert spending.totals("2026-11").visitors == 2  # the day's count of visitors is kept, and counted once


def test_a_site_on_which_everyone_signs_in_has_no_line_for_the_public(tmp_path):
    """The second review: with accounts only, the report of who the spending was for showed a "(public)" line of
    a cent and no calls, which was the rounding of the accounts' months and nobody's spending. No line is shown
    for the public where the public made no call; the lines then differ from the total by that rounding."""
    clock, db, spending = _spending(tmp_path)
    for account, tokens in ((1, 12_700), (2, 9_100), (3, 2_300)):  # 2.54, 1.82 and 0.46 cents
        spending.add("answer", "m", Usage(input_uncached=tokens), visitor=f"{account}" * 24, account=account)
    clock.advance(days=1)
    spending.forget_visitors()
    lines = spending.by_account("2026-11")
    assert [(a.account, a.public, a.calls, a.spent_usd) for a in lines] == [
        (1, False, 1, 0.03), (2, False, 1, 0.02), (3, False, 1, 0.0)]
    assert spending.totals("2026-11").spent_usd == pytest.approx(0.0482)  # the rows themselves are exact
    # and where the public did ask, its line is there, with its calls
    spending.add("answer", "m", Usage(input_uncached=5_000), visitor="p" * 24)
    assert [(a.account, a.public, a.calls) for a in spending.by_account("2026-11")][-1] in (
        (None, True, 1), (3, False, 1))
    assert (None, True, 1) in [(a.account, a.public, a.calls) for a in spending.by_account("2026-11")]
