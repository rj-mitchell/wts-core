"""The three sites that have limits, cost and caps today, as the usage tests see them: each one's real ``[usage]``
settings, its reader-facing messages and the few figures fixed in its code. The other usage tests are parametrised
over these (the fixture ``site``), and the tests here keep them true to each site's checkout where one is present."""

from __future__ import annotations

import ast
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from wts_core.settings import Messages

# where the four sites' checkouts are: WTS_SITES_DIR, or beside this one on the build machine
SITES_ROOT = Path(os.environ.get("WTS_SITES_DIR") or "/home/user")

TOO_MANY = "Too many requests. Please wait a minute and try again."
BUSY_VISITOR = "A briefing is already being written for you; please wait for it to finish."
BUSY_SITE = "Many briefings are being written at the moment; please try again in a minute."
SOURCES_FOLLOW = "{reason} The sources found are shown below."
DECLINED = "The model declined to answer this question."
BUDGET_VISITOR = ("You have reached today's limit for new briefings. It resets at midnight UTC; briefings others have "
                  "already asked for still load.")
BUDGET_DAY = "Today's budget for new briefings has been used up. It resets at midnight UTC."
BUDGET_MONTH = "This month's budget for new briefings has been used up."
HAIKU = {"price_input_per_mtok": 0.1, "price_output_per_mtok": 0.5, "price_cache_read_per_mtok": 0.01}


@dataclass(frozen=True)
class SiteFacts:
    name: str
    repo: str  # the checkout's folder under SITES_ROOT
    package: str
    usage: dict[str, Any]  # its [usage] section, as config/settings.toml has it
    messages: Messages
    forget_over: int  # the limiter forgets idle keys over this many (fixed in its code)
    key_length: int  # hexadecimal characters of its cache key
    at_once_key: str  # its name for "briefings at once, for one visitor"
    models: tuple[str, ...]  # the models its settings name
    sources: tuple[str, ...]  # the files its messages are written in

    @property
    def checkout(self) -> Path:
        return SITES_ROOT / self.repo

    @property
    def src(self) -> Path:
        return self.checkout / "src" / self.package

    def __str__(self) -> str:
        return self.repo


MPS = SiteFacts(
    name="Where MPs Stand", repo="wherempsstand", package="hansard",
    usage={
        "support_reminder_every": 10, "per_visitor_daily_questions": 40, "per_user_daily_questions": 60,
        "requests_per_minute": 20, "answer_cache_hours": 168, "briefing_estimate_usd": 0.15, "briefings_at_once": 8,
        "briefings_at_once_per_reader": 2, "daily_spend_cap_usd": 10.0, "monthly_spend_cap_usd": 150.0,
        "price_input_per_mtok": 4.0, "price_output_per_mtok": 20.0, "price_cache_read_per_mtok": 0.2,
        "cache_write_multiplier": 1.25,
        "models": {"claude-sonnet-5-5": {"price_input_per_mtok": 2.0, "price_output_per_mtok": 10.0,
                                         "price_cache_read_per_mtok": 0.2},
                   "claude-haiku-5-5": dict(HAIKU)}},
    messages=Messages(
        too_many_requests=TOO_MANY, visitor_daily_limit=BUDGET_VISITOR, daily_cap=BUDGET_DAY,
        monthly_cap=BUDGET_MONTH, busy_visitor=BUSY_VISITOR, busy_site=BUSY_SITE, sources_follow=SOURCES_FOLLOW,
        sources_only="Sources only: no briefing was written. Ask again without 'Sources only' for a written "
                     "briefing.",
        briefing_failed="The briefing could not be written just now. The sources found are shown above; please try "
                        "again later.",
        model_declined=DECLINED,
        account_daily_limit="You have reached today's question limit. It resets at midnight UTC."),
    forget_over=50_000, key_length=64, at_once_key="briefings_at_once_per_reader",
    models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
    sources=("api/usage.py", "api/app.py", "rag/pipeline.py"))

COUNTRIES = SiteFacts(
    name="Where Countries Stand", repo="wherecountriesstand", package="wcs",
    usage={
        "daily_spend_cap_usd": 3.0, "monthly_spend_cap_usd": 50.0, "per_visitor_daily_questions": 40,
        "requests_per_minute": 20, "answer_cache_hours": 168, "briefing_estimate_usd": 0.10, "briefings_at_once": 8,
        "briefings_at_once_per_visitor": 2, "price_input_per_mtok": 2.0, "price_output_per_mtok": 10.0,
        "price_cache_read_per_mtok": 0.2, "cache_write_multiplier": 1.25,
        "models": {"claude-haiku-5-5": dict(HAIKU)}},
    messages=Messages(
        too_many_requests=TOO_MANY, visitor_daily_limit=BUDGET_VISITOR, daily_cap=BUDGET_DAY,
        monthly_cap=BUDGET_MONTH, busy_visitor=BUSY_VISITOR, busy_site=BUSY_SITE, sources_follow=SOURCES_FOLLOW,
        sources_only="Sources only: no briefing was written.",
        briefing_failed="The briefing could not be written just now. The sources found are shown above; please try "
                        "again later.",
        model_declined=DECLINED),
    forget_over=50_000, key_length=64, at_once_key="briefings_at_once_per_visitor",
    models=("claude-sonnet-5-5", "claude-haiku-5-5"),
    sources=("api/usage.py", "api/app.py", "rag/pipeline.py"))

COUNCILS = SiteFacts(
    name="Where Councils Stand", repo="wherecouncilsstand", package="councils",
    usage={
        "per_visitor_daily_questions": 30, "requests_per_minute": 20, "answer_cache_hours": 168,
        "daily_spend_cap_usd": 3.0, "monthly_spend_cap_usd": 50.0, "briefing_estimate_usd": 0.15,
        "briefings_at_once_per_visitor": 2, "briefings_at_once": 8, "price_input_per_mtok": 2.0,
        "price_output_per_mtok": 10.0, "price_cache_read_per_mtok": 0.2, "cache_write_multiplier": 1.25,
        "models": {"claude-haiku-5-5": dict(HAIKU)}},
    messages=Messages(
        too_many_requests=TOO_MANY,
        visitor_daily_limit="You have asked a lot of questions today, so new briefings are paused until tomorrow.",
        daily_cap="The site has reached today's limit on new briefings, which keeps its costs down.",
        monthly_cap="The site has reached this month's limit on new briefings, which keeps its costs down.",
        busy_visitor=BUSY_VISITOR, busy_site=BUSY_SITE, sources_follow=SOURCES_FOLLOW,
        sources_only="Sources only: no briefing was written. Ask again without 'Sources only' for a written "
                     "briefing.",
        briefing_failed="The briefing could not be written just now. Any sources found are shown above; please try "
                        "again later.",
        model_declined=DECLINED),
    forget_over=10_000, key_length=32, at_once_key="briefings_at_once_per_visitor",
    models=("claude-sonnet-5-5", "claude-haiku-5-5"),
    sources=("api/usage.py", "api/app.py", "rag/pipeline.py"))

SITES = (MPS, COUNTRIES, COUNCILS)


@pytest.fixture(params=SITES, ids=str)
def site(request: pytest.FixtureRequest) -> SiteFacts:
    return request.param


def checkout_of(facts: SiteFacts) -> Path:
    """The site's checkout, or the test is skipped: the comparisons with a site's own code need its repository."""
    if not (facts.src / "api" / "usage.py").exists():
        pytest.skip(f"{facts.name}'s checkout is not at {facts.checkout} (set WTS_SITES_DIR to the folder that "
                    f"holds {facts.repo}): nothing to compare with")
    return facts.checkout


def test_the_settings_here_are_the_sites_own(site):
    with open(checkout_of(site) / "config" / "settings.toml", "rb") as fh:
        assert tomllib.load(fh)["usage"] == site.usage


def test_every_message_here_is_written_in_the_sites_own_code(site):
    checkout_of(site)
    written: set[str] = set()
    for name in site.sources:
        tree = ast.parse((site.src / name).read_text())
        written |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    m = site.messages
    said = [m.too_many_requests, m.visitor_daily_limit, m.daily_cap, m.monthly_cap, m.busy_visitor, m.busy_site,
            m.sources_only, m.briefing_failed, m.model_declined, m.sources_follow.removeprefix("{reason}")]
    if m.account_daily_limit:
        said.append(m.account_daily_limit)
    assert [s for s in said if s not in written] == []
    assert m.with_sources(m.daily_cap) == f"{m.daily_cap} The sources found are shown below."


def test_the_figures_fixed_in_each_sites_code_are_the_ones_here(site):
    """The size at which the limiter forgets idle keys, and the length of the cache key, are written in the code."""
    checkout_of(site)
    usage_py = (site.src / "api" / "usage.py").read_text()
    assert f"len(self.hits) > {site.forget_over:_}" in usage_py
    key_code = (site.src / "api" / ("app.py" if site.key_length == 32 else "usage.py")).read_text()
    assert ("default=str).encode()).hexdigest()" + ("[:32]" if site.key_length == 32 else "\n")) in key_code
    assert site.at_once_key in (site.src / "api" / "app.py").read_text()
