"""The desk's parts built in one call from a site's settings, and the start-up check that goes first: each site's
real ``[usage]`` settings in turn (the fixture ``site``), and what is said when something is missing or wrong."""

from __future__ import annotations

import dataclasses
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from test_usage_sites import COUNCILS, MPS, SITES, SiteFacts, checkout_of, site  # noqa: F401
from wts_core import observe, usage
from wts_core.briefing import Ask, BriefingDesk, DeskParts, DeskSettings, desk_parts, desk_settings
from wts_core.ports import Price
from wts_core.settings import Settings, SettingsError, Site
from wts_core.state import StateDB
from wts_core.testing import FixedClock, FixedRandom
from wts_core.usage import Limits, PriceTable

WRITE = {"input_tokens": 8000, "output_tokens": 600, "cache_read_tokens": 2000, "cache_write_tokens": 1000}
ANSWER = {"segments": [], "markdown": "The motion was lost.", "no_records": False, "citations_total": 1,
          "citations_invalid": 0, "grounded_ratio": 1.0}


def settings_of(facts: SiteFacts, folder: Path, **changed: Any) -> Settings:
    """The site's settings as the package's ``Settings``: its real ``[usage]`` section, with ``changed`` laid over
    it (``None`` takes a key out)."""
    section = {**facts.usage, **changed}
    section = {key: value for key, value in section.items() if value is not None}
    return Settings(raw={"usage": section}, data_dir=folder, config_path=folder / "config" / "settings.toml",
                    site=Site(name=facts.name, package=facts.package, env_prefix=facts.package.upper(), root=folder))


def state(folder: Path, clock: FixedClock) -> StateDB:
    return StateDB(folder / "state.db", migrations=usage.migrations(), clock=clock)


def built(facts: SiteFacts, folder: Path, clock: FixedClock | None = None, random: FixedRandom | None = None,
          **changed: Any) -> DeskParts:
    clock = clock or FixedClock()
    return desk_parts(settings_of(facts, folder, **changed), state(folder, clock), facts.messages,
                      new_id=lambda chance: usage.token_id(8, random=chance), at_once_per_visitor=facts.at_once_key,
                      forget_over=facts.forget_over, keep_failures=facts is not COUNCILS, clock=clock,
                      random=random or FixedRandom())


def config() -> Any:
    return observe.briefing_config(log=None, model="model-a", parse_model="model-b", instructions="v7",
                                   site_version="1")


# ---- the parts ---------------------------------------------------------------------------------------------------


def test_every_part_is_built_from_the_sites_own_settings(site, tmp_path):  # noqa: F811
    parts = built(site, tmp_path)
    cfg = site.usage
    assert parts.prices == PriceTable.from_settings(cfg) and parts.limits == Limits.from_settings(cfg)
    assert (parts.limiter.per_minute, parts.limiter.forget_over) == (cfg["requests_per_minute"], site.forget_over)
    assert (parts.in_progress.per_key, parts.in_progress.total, parts.in_progress.estimate_usd) == (
        cfg[site.at_once_key], cfg["briefings_at_once"], cfg["briefing_estimate_usd"])
    assert parts.cache_hours == cfg["answer_cache_hours"] and parts.messages is site.messages
    assert (parts.failures is None) == (site is COUNCILS)  # Where Councils Stand keeps no notes of failures
    # an account's daily limit only where the site has accounts
    assert (parts.limits.per_account_daily is not None) == (site is MPS)


def test_the_two_figures_the_sites_name_differently_may_be_given_as_numbers_or_as_names(site, tmp_path):  # noqa: F811
    by_name = desk_settings(settings_of(site, tmp_path, forget_idle_visitors_over=77), site.messages,
                            at_once_per_visitor=site.at_once_key, forget_over="forget_idle_visitors_over")
    by_number = desk_settings(settings_of(site, tmp_path), site.messages, at_once_per_visitor=2, forget_over=77)
    assert isinstance(by_name, DeskSettings) and by_name == by_number


def test_the_desk_built_from_the_parts_runs_a_briefing_on_the_one_clock_and_the_one_chance(site, tmp_path):  # noqa: F811
    clock, random = FixedClock(), FixedRandom()
    parts = built(site, tmp_path, clock, random)
    assert parts.clock is clock and parts.random is random
    records: list[Any] = []

    class Log:
        def write(self, record: Any) -> None:
            records.append(record)

    def write() -> Iterator[dict[str, Any]]:
        yield {"type": "plan", "plan": {}, "usage": None}
        yield {"type": "sources", "sources": [{"n": 1}]}
        clock.advance(2)
        yield {"type": "final", "answer": dict(ANSWER), "usage": dict(WRITE), "model": "model-a"}

    desk = parts.desk(config(), log=Log(), strict=True)  # type: ignore[arg-type]
    assert isinstance(desk, BriefingDesk)
    final = list(desk.handle(Ask(question="What was decided?", visitor="v" * 24, write=write,
                                 sources_only=lambda note, free: iter(()), cache_key="k" * 64)))[-1]
    saved = parts.archive.get(final["briefing_id"])
    # the record's id and the briefing's are the next two the one source of chance gives
    assert [records[0].id, saved.id] == [FixedRandom().token(8), _second(FixedRandom())]
    assert saved.created_at == "2026-11-13T12:00:02+00:00" and records[0].at == "2026-11-13T12:00:00+00:00"
    assert parts.spending.briefings_today(visitor="v" * 24) == 1 and records[0].t_total == 2000
    assert parts.cache.get("k" * 64, parts.cache_hours)[-1]["cached"] is True
    assert (records[0].config_id, records[0].parse_model) == (config().config_id, "model-b")


def _second(random: FixedRandom) -> str:
    random.token(8)
    return random.token(8)


def test_the_parts_need_the_tables_of_the_usage_module(site, tmp_path):  # noqa: F811
    bare = StateDB(tmp_path / "state.db")
    with pytest.raises(ValueError, match=r"state\.db has no wts_spending, .*usage\.migrations\(\)"):
        desk_parts(settings_of(site, tmp_path), bare, site.messages, new_id=lambda chance: "x", at_once_per_visitor=2,
                   forget_over=10, keep_failures=True)


# ---- the start-up check ------------------------------------------------------------------------------------------


def test_each_sites_own_settings_file_passes_the_start_up_check(site):  # noqa: F811
    with open(checkout_of(site) / "config" / "settings.toml", "rb") as fh:
        raw = tomllib.load(fh)
    settings = Settings(raw=raw, data_dir=Path("data"), config_path=site.checkout / "config" / "settings.toml",
                        site=Site(name=site.name, package=site.package, env_prefix="X", root=site.checkout))
    read = desk_settings(settings, site.messages, at_once_per_visitor=site.at_once_key, forget_over=site.forget_over)
    assert read.limits == Limits.from_settings(site.usage) and read.at_once_per_visitor == 2


def test_everything_missing_is_reported_together_naming_the_file_and_each_key(site, tmp_path):  # noqa: F811
    settings = settings_of(site, tmp_path, daily_spend_cap_usd=None, price_output_per_mtok=None,
                           requests_per_minute=None, answer_cache_hours=None, **{site.at_once_key: None})
    with pytest.raises(SettingsError) as stopped:
        desk_settings(settings, site.messages, at_once_per_visitor=site.at_once_key,
                      forget_over="forget_idle_visitors_over")
    said = str(stopped.value)
    assert said.startswith(f"{tmp_path}/config/settings.toml: the briefing desk cannot be built: 6 things missing "
                           "or wrong.\n")
    assert said.splitlines()[1:] == [
        "  - [usage] needs daily_spend_cap_usd: the package has no limits of its own",
        "  - [usage] needs price_output_per_mtok: the package has no prices of its own",
        "  - [usage] needs requests_per_minute",
        "  - [usage] needs forget_idle_visitors_over",
        f"  - [usage] needs {site.at_once_key}",
        "  - [usage] needs answer_cache_hours"]
    assert len(stopped.value.problems) == 6
    # and nothing is built from settings like these
    with pytest.raises(SettingsError, match="6 things missing or wrong"):
        desk_parts(settings, state(tmp_path, FixedClock()), site.messages, new_id=lambda chance: "x",
                   at_once_per_visitor=site.at_once_key, forget_over="forget_idle_visitors_over", keep_failures=True)


def test_a_figure_that_is_not_a_number_is_named_with_the_rest(site, tmp_path):  # noqa: F811
    settings = settings_of(site, tmp_path, monthly_spend_cap_usd="plenty", briefing_estimate_usd="a few pence",
                           cache_write_multiplier="x", briefings_at_once=None)
    with pytest.raises(SettingsError) as stopped:
        desk_settings(settings, site.messages, at_once_per_visitor=site.at_once_key, forget_over=site.forget_over)
    assert stopped.value.problems == (
        "[usage] monthly_spend_cap_usd is not a number: 'plenty'",
        "[usage] cache_write_multiplier must be a number, not 'x'",
        "[usage] needs briefings_at_once",
        "[usage] briefing_estimate_usd is not a number: 'a few pence'")
    assert "settings.toml: the briefing desk cannot be built: 4 things" in str(stopped.value)


def test_one_thing_wrong_is_said_as_one(site, tmp_path):  # noqa: F811
    with pytest.raises(SettingsError, match=r"1 thing missing or wrong\.\n  - \[usage\] needs briefing_estimate_usd$"):
        desk_settings(settings_of(site, tmp_path, briefing_estimate_usd=None), site.messages,
                      at_once_per_visitor=site.at_once_key, forget_over=site.forget_over)


def test_a_site_that_keeps_its_limits_elsewhere_says_where(site, tmp_path):  # noqa: F811
    base = settings_of(site, tmp_path)
    moved = dataclasses.replace(base, raw={"limits": {k: v for k, v in site.usage.items()
                                                      if k != "monthly_spend_cap_usd"}})
    with pytest.raises(SettingsError, match=r"\[limits\] needs monthly_spend_cap_usd"):
        desk_settings(moved, site.messages, at_once_per_visitor=site.at_once_key, forget_over=1, section="limits")
    whole = dataclasses.replace(base, raw={"limits": dict(site.usage)})
    assert desk_settings(whole, site.messages, at_once_per_visitor=site.at_once_key, forget_over=1,
                         section="limits").limits == Limits.from_settings(site.usage)


def test_the_messages_are_checked_with_the_settings(site, tmp_path):  # noqa: F811
    wrong = dataclasses.replace(site.messages, busy_site="  ", sources_follow="The sources found are shown below.")
    with pytest.raises(SettingsError) as stopped:
        desk_settings(settings_of(site, tmp_path, daily_spend_cap_usd=None), wrong,
                      at_once_per_visitor=site.at_once_key, forget_over=site.forget_over)
    said = stopped.value.problems
    assert said[0].startswith("[usage] needs daily_spend_cap_usd")
    assert said[1].startswith("Messages.busy_site is empty: every word a reader is shown is the site's own")
    assert said[2].startswith("Messages.sources_follow must have {reason} in it")
    stray = dataclasses.replace(site.messages, sources_follow="{reason} See the {sources} below.")
    with pytest.raises(SettingsError, match="Messages.sources_follow must have {reason} in it, and no other"):
        desk_settings(settings_of(site, tmp_path), stray, at_once_per_visitor=2, forget_over=1)


def test_a_limit_for_accounts_and_its_message_must_come_together(tmp_path):
    no_message = dataclasses.replace(MPS.messages, account_daily_limit=None)
    with pytest.raises(SettingsError, match=r"Messages.account_daily_limit is missing: \[usage\] "
                                            "per_user_daily_questions sets"):
        desk_settings(settings_of(MPS, tmp_path), no_message, at_once_per_visitor=2, forget_over=1)
    with pytest.raises(SettingsError, match=r"\[usage\] needs per_user_daily_questions: the site has a message"):
        desk_settings(settings_of(MPS, tmp_path, per_user_daily_questions=None), MPS.messages,
                      at_once_per_visitor=2, forget_over=1)


def test_a_site_may_ask_that_every_model_has_prices_of_its_own(site, tmp_path):  # noqa: F811
    settings = settings_of(site, tmp_path)
    priced = site.models[-1]  # the question-reading model has an entry on every site
    assert desk_settings(settings, site.messages, at_once_per_visitor=2, forget_over=1,
                         require_prices_for=[priced, None]).prices.price_for(priced) == Price(0.1, 0.5, 0.01)
    with pytest.raises(SettingsError, match=r'settings\.toml: .*\n  - no price for a-new-model: add '
                                            r'\[usage\.models\."<name>"\]'):
        desk_settings(settings, site.messages, at_once_per_visitor=2, forget_over=1,
                      require_prices_for=[priced, "a-new-model"])
    # left alone it is today's rule on every site: a model with no entry takes the base prices
    assert desk_settings(settings, site.messages, at_once_per_visitor=2, forget_over=1).prices.price_for(
        "a-new-model") == PriceTable.from_settings(site.usage).base


def test_limits_and_prices_read_on_their_own_name_the_file_when_told_it():
    with pytest.raises(SettingsError, match=r"^config/settings\.toml: \[usage\] needs per_visitor_daily_questions, "
                                            r"daily_spend_cap_usd, monthly_spend_cap_usd"):
        Limits.from_settings({}, file=Path("config/settings.toml"))
    with pytest.raises(SettingsError, match=r"^/srv/site/settings\.toml: \[usage\] needs price_input_per_mtok"):
        PriceTable.from_settings({}, file="/srv/site/settings.toml")
    for facts in SITES:  # everything wrong with the prices is said at once
        with pytest.raises(SettingsError) as stopped:
            PriceTable.from_settings({**facts.usage, "price_input_per_mtok": "x",
                                      "models": {"m": {"price_output_per_mtok": "y"}, "n": 3}})
        assert stopped.value.problems == ("[usage] price_input_per_mtok must be a number, not 'x'",
                                          '[usage.models."m"] price_output_per_mtok must be a number, not \'y\'',
                                          '[usage.models."n"] must be a table of prices')
