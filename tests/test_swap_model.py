"""Swapping parts, first of three: the model is changed in configuration, and nothing else is.

Each AI site's own ``[usage]`` settings and messages are taken in turn; the briefing model named in its settings is
switched to the larger model the family's settings name, ``claude-opus-5-5``, by changing one value. A small
pipeline over the scripted model client stands for the site's own: it reads the model from the settings, as each
site's does. Nothing here is a site's production code, and no model is called.

What must hold, and is checked:

* pricing: with strict prices the site does not start while the new model has no price table (the error names
  the model and the key to add); with one, each call is costed at the new model's prices, to the cent;
* the event flow: a reader is sent the same events, in the same order, whichever model wrote them;
* the configuration id changes, so every figure in the statistics can be set before and after the change;
* the answer cache does not serve one model's answer as the other's.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from checks_sites import COUNCILS as CHECKS
from test_usage_sites import SiteFacts, site  # noqa: F401  (the fixture: each AI site's settings and messages)
from wts_core import observe, usage
from wts_core.briefing import Ask, BriefingDesk, desk_parts
from wts_core.eval import checked
from wts_core.events import Completed, to_reader
from wts_core.observe import SqliteBriefingLog, briefing_config
from wts_core.ports import ModelRequest, Usage
from wts_core.settings import Settings, SettingsError, Site
from wts_core.state import StateDB
from wts_core.testing import FixedClock, FixedRandom
from wts_core.testing.models import ScriptedModel, load_documents, load_stream, recorded
from wts_core.usage import PriceTable, cache_key

SMALLER, LARGER, READS = "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"
QUESTION = "What was decided about weekly bin collections?"
# US dollars a million tokens, as a site would write them under [usage.models."claude-opus-5-5"]
OPUS_PRICES = {"price_input_per_mtok": 4.0, "price_output_per_mtok": 20.0, "price_cache_read_per_mtok": 0.4}
SONNET_PRICES = {"price_input_per_mtok": 2.0, "price_output_per_mtok": 10.0, "price_cache_read_per_mtok": 0.2}
DOCUMENTS = load_documents(recorded("cited_briefing"))
SCRIPT = load_stream(recorded("cited_briefing"))
USED = next(e for e in SCRIPT if isinstance(e, Completed)).usage


def settings_for(facts: SiteFacts, folder: Path, model: str, *, priced: tuple[str, ...]) -> Settings:
    """The site's own settings, with the briefing model its ``[answer]`` names set to ``model``, and a price
    table for each model in ``priced`` that the site's own file has none for."""
    tables = dict(facts.usage["models"])
    for name, prices in ((SMALLER, SONNET_PRICES), (LARGER, OPUS_PRICES)):
        if name in priced:
            tables.setdefault(name, prices)
    raw = {"usage": {**facts.usage, "models": {name: tables[name] for name in tables if name in (*priced, READS)}},
           "answer": {"model": model, "query_parse_model": READS}}
    return Settings(raw=raw, data_dir=folder, config_path=folder / "config" / "settings.toml",
                    site=Site(name=facts.name, package=facts.package, env_prefix=facts.package.upper(), root=folder,
                              instructions_version="v7", version="2026.11"))


class Swappable:
    """A site as far as a change of model can reach: its settings, the desk built from them with strict prices,
    and a pipeline that names the model its settings name. The state database is the folder's, so a second one
    over the same folder is the same site started again with its settings changed."""

    def __init__(self, facts: SiteFacts, folder: Path, model: str, *, priced: tuple[str, ...] = (SMALLER, LARGER),
                 start: int = 1):
        self.facts, self.settings = facts, settings_for(facts, folder, model, priced=priced)
        # each start has ids of its own, as chance would give them
        chance = FixedRandom(tokens=[f"start{start}n{n:04d}" for n in range(40)])
        self.clock = FixedClock()
        self.db = StateDB(folder / "state.db", migrations=(*usage.migrations(), *observe.migrations()),
                          clock=self.clock)
        answer = self.settings.answer
        # the start-up check: with strict prices, every model the settings name must have a table of its own
        self.parts = desk_parts(self.settings, self.db, facts.messages,
                                new_id=lambda chance: usage.token_id(8, random=chance),
                                at_once_per_visitor=facts.at_once_key, forget_over=facts.forget_over,
                                keep_failures=True, require_prices_for=(answer["model"], answer["query_parse_model"]),
                                clock=self.clock, random=chance)
        self.log = SqliteBriefingLog(self.db, clock=self.clock)
        self.config = briefing_config(log=self.log, model=answer["model"], parse_model=answer["query_parse_model"],
                                      instructions="v7", site_version="2026.11", also={"sources": 8})
        self.desk: BriefingDesk = self.parts.desk(self.config, log=self.log, strict=True)
        # the scripted client answers as the model it was asked for, under the dated id a provider gives back
        self.model = ScriptedModel([dataclasses.replace(e, model=f"{answer['model']}-20261001")
                                    if isinstance(e, Completed) else e for e in SCRIPT])

    def write(self) -> Iterator[dict[str, Any]]:
        """The site's pipeline, in little: the documents and the question go to the model its settings name."""
        yield {"type": "plan", "plan": {"read_by": "rules"}, "usage": None}
        yield {"type": "sources", "sources": [{"n": d.number, "title": d.title} for d in DOCUMENTS]}
        request = ModelRequest(model=self.settings.answer["model"], instructions="Use only the sources.",
                               question=QUESTION, documents=DOCUMENTS)
        done: Completed | None = None
        for event in self.model.stream(request):
            if isinstance(event, Completed):
                done = event
            else:
                yield to_reader(event)
        assert done is not None
        report = checked(done.blocks, DOCUMENTS, CHECKS.verifier, CHECKS.loaded_words)  # every check, as ever
        yield {"type": "final", "answer": report, "usage": done.usage.as_stored(), "model": done.model,
               "stop_reason": done.stop_reason}

    def key(self) -> str:
        """The site's cache key: the model is one of its parts, as on every site (ADR 0009)."""
        return cache_key({"q": QUESTION.lower(), "model": self.settings.answer["model"], "instructions": "v7"},
                         length=self.facts.key_length)

    def ask(self) -> list[dict[str, Any]]:
        return list(self.desk.handle(Ask(question=QUESTION, visitor="v" * 24, write=self.write,
                                         sources_only=lambda note, free: iter(()), cache_key=self.key())))

    def spent(self) -> list[tuple[str, str, float]]:
        with self.db.connect() as con:
            return [(r["kind"], r["model"], r["cost_usd"]) for r in con.execute(
                "SELECT kind, model, cost_usd FROM wts_spending ORDER BY id")]


def cost_at(prices: dict[str, float], used: Usage, write_multiplier: float = 1.25) -> float:
    """What a call costs, worked out here by hand from the published shape of the prices."""
    return round(used.input_uncached / 1e6 * prices["price_input_per_mtok"]
                 + used.cache_write / 1e6 * prices["price_input_per_mtok"] * write_multiplier
                 + used.cache_read / 1e6 * prices["price_cache_read_per_mtok"]
                 + used.output / 1e6 * prices["price_output_per_mtok"], 6)


# Pricing


def test_strict_prices_refuse_the_new_model_until_it_has_a_price_table(site, tmp_path):  # noqa: F811
    """The rule: an unknown model fails loudly at start-up, never silently at the wrong price. One value was
    changed in the settings; the site says exactly what else must be."""
    Swappable(site, tmp_path / "before", SMALLER, priced=(SMALLER,))  # as it stands: it starts
    with pytest.raises(SettingsError) as stopped:
        Swappable(site, tmp_path / "after", LARGER, priced=(SMALLER,))
    said = str(stopped.value)
    assert f"no price for {LARGER}" in said and 'add [usage.models."<name>"] with its prices' in said
    assert str(tmp_path / "after" / "config" / "settings.toml") in said  # and names the file to change
    with StateDB(tmp_path / "after" / "state.db").connect() as con:  # and nothing was spent, saved or recorded
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE name = 'wts_spending'").fetchone()[0] in (0, 1)


def test_with_its_table_each_call_is_costed_at_the_new_models_prices(site, tmp_path):  # noqa: F811
    smaller, larger = Swappable(site, tmp_path / "s", SMALLER), Swappable(site, tmp_path / "l", LARGER)
    smaller.ask()
    larger.ask()
    sonnet = dict(site.usage["models"].get(SMALLER, SONNET_PRICES))
    opus = dict(site.usage["models"].get(LARGER, OPUS_PRICES))
    multiplier = site.usage["cache_write_multiplier"]
    assert smaller.spent() == [("answer", f"{SMALLER}-20261001", cost_at(sonnet, USED, multiplier))]
    assert larger.spent() == [("answer", f"{LARGER}-20261001", cost_at(opus, USED, multiplier))]
    assert larger.spent()[0][2] > smaller.spent()[0][2] > 0  # the larger model is the dearer, and neither is free
    # the record of each briefing says what it cost and which model it ran with
    [record] = larger.log.since("2026-11-01T00:00:00+00:00")
    assert (record.model, record.cost_usd) == (LARGER, cost_at(opus, USED, multiplier))
    # and the table is found by the dated id the provider gives back, as well as by the name in the settings
    table = PriceTable.from_settings(larger.settings)
    assert table.price_for(f"{LARGER}-20261001") == table.price_for(LARGER) != table.price_for(SMALLER)
    table.require([LARGER, f"{LARGER}-20261001", SMALLER, READS], base_counts=False)


# The event flow


def test_a_reader_is_sent_the_same_events_whichever_model_wrote_them(site, tmp_path):  # noqa: F811
    smaller, larger = Swappable(site, tmp_path / "s", SMALLER), Swappable(site, tmp_path / "l", LARGER)
    before, after = smaller.ask(), larger.ask()
    assert [e["type"] for e in before] == [e["type"] for e in after]
    assert before[0]["type"] == "plan" and before[1]["type"] == "sources" and before[-1]["type"] == "final"
    assert {"text", "citation"} <= {e["type"] for e in before}  # the briefing, with its citations, as it is written
    # event for event the same, but for the name of the model on the last
    assert before[:-1] == after[:-1]
    assert {k: v for k, v in before[-1].items() if k != "model"} == {k: v for k, v in after[-1].items() if k != "model"}
    assert (before[-1]["model"], after[-1]["model"]) == (f"{SMALLER}-20261001", f"{LARGER}-20261001")
    # the checks ran on both and found the same: the verifier reads the events, never the provider
    assert before[-1]["answer"]["citations_total"] > 0 and before[-1]["answer"] == after[-1]["answer"]
    # and the model was asked for by the name in the settings, and by nothing else that changed
    asked_before, asked_after = smaller.model.requests[0], larger.model.requests[0]
    assert (asked_before.model, asked_after.model) == (SMALLER, LARGER)
    assert dataclasses.replace(asked_before, model=LARGER) == asked_after


def test_the_configuration_id_changes_with_the_model(site, tmp_path):  # noqa: F811
    smaller, larger = Swappable(site, tmp_path / "s", SMALLER), Swappable(site, tmp_path / "l", LARGER)
    assert smaller.config.config_id != larger.config.config_id
    assert Swappable(site, tmp_path / "again", SMALLER).config.config_id == smaller.config.config_id
    assert {**smaller.config.settings, "model": LARGER} == larger.config.settings  # and nothing else is in it
    smaller.ask()
    [record] = smaller.log.since("2026-11-01T00:00:00+00:00")
    assert record.config_id == smaller.config.config_id and smaller.log.config(record.config_id)["model"] == SMALLER


# The answer cache


def test_the_answer_cache_does_not_serve_the_other_models_answer(site, tmp_path):  # noqa: F811
    """One site, its settings changed and changed back: three starts over the same state database."""
    first = Swappable(site, tmp_path, SMALLER)
    written = first.ask()[-1]
    assert "cached" not in written and first.ask()[-1]["cached"] is True  # the same model: served from the cache
    switched = Swappable(site, tmp_path, LARGER, start=2)
    assert switched.key() != first.key()
    afresh = switched.ask()[-1]
    assert "cached" not in afresh and afresh["briefing_id"] != written["briefing_id"]  # written by the new model
    assert afresh["model"] == f"{LARGER}-20261001" and len(switched.model.requests) == 1
    assert switched.ask()[-1]["briefing_id"] == afresh["briefing_id"]  # and now served its own
    back = Swappable(site, tmp_path, SMALLER, start=3)
    again = back.ask()[-1]
    assert (again["cached"], again["briefing_id"]) == (True, written["briefing_id"]) and not back.model.requests
    # the saved briefings of both stay at their own addresses, each as its reader was sent it
    assert back.parts.archive.get(written["briefing_id"]) is not None
    assert back.parts.archive.get(afresh["briefing_id"]) is not None
    outcomes = [(r.model, r.outcome) for r in back.log.since("2026-11-01T00:00:00+00:00")]
    assert outcomes == [(SMALLER, "completed"), (SMALLER, "cached"), (LARGER, "completed"), (LARGER, "cached"),
                        (SMALLER, "cached")]
