"""What a model call costs and the record of what was spent: the sites' own tests of ``cost_usd``, ``record_usage``
and their owner's reports, run against each site's prices."""

from __future__ import annotations

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


# ---- prices and cost ---------------------------------------------------------------------------------------------


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


def test_a_models_own_prices_are_laid_over_the_base_and_the_first_matching_name_wins():
    """Where Countries Stand's test of who read the question: each model at its own input price."""
    prices = table(2.0, 10.0, **{HAIKU: {"price_input_per_mtok": 0.1}, SONNET: {"price_input_per_mtok": 3.0}})
    million = Usage(input_uncached=1_000_000)
    assert prices.cost(million, HAIKU) == pytest.approx(0.1) and prices.cost(million, SONNET) == pytest.approx(3.0)
    assert prices.price_for(HAIKU) == Price(0.1, 10.0, 0.2, 1.25)      # what it doesn't give is the base's
    first = table(2.0, 10.0, **{"claude": {"price_input_per_mtok": 9.0}, HAIKU: {"price_input_per_mtok": 0.1}})
    assert first.price_for(HAIKU).input == 9.0                         # in the order the settings give them
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


# ---- the spending record -----------------------------------------------------------------------------------------


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
