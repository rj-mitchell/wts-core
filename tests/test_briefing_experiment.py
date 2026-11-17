"""Live experiments (wts_core.briefing.experiment), on the impartiality policy's conditions: principle 6 and
ADR 0012. Each condition the package says it enforces has a test here, named for it.

The desk is the one ``test_briefing_desk.py`` builds, on Where Councils Stand's messages and limits; the experiment
is declared in settings as a site declares it, and passes are noted as the evaluation harness notes them.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from test_briefing_desk import ANSWER, CARDS, PARSE, WRITE, Q, Told, types
from test_usage_sites import COUNCILS
from wts_core import eval as harness
from wts_core import observe
from wts_core import usage as core_usage
from wts_core.briefing import (
    ARM_CHANGES,
    CHECKED,
    Arm,
    Experiment,
    ExperimentSwitch,
    arm_configs,
    current_config,
    experiment_switch,
)
from wts_core.observe import PROPORTIONS, SqliteBriefingLog, briefing_config
from wts_core.ports import BriefingConfig, ExperimentState, Price, Usage
from wts_core.settings import Settings, SettingsError, Site
from wts_core.state import StateDB
from wts_core.testing import FixedClock, FixedRandom
from wts_core.usage import Limits, PriceTable

THRESHOLDS = {"min_grounded_ratio": 0.8, "max_invalid_citations": 0}
DECLARED: dict[str, Any] = {
    "name": "six-sources", "start": date(2026, 11, 10), "end": date(2026, 11, 24), "decided_by": "any_check",
    "arms": [{"name": "control", "share": 0.5},
             {"name": "six", "share": 0.5, "variant": "six-sources", "model": "claude-opus-5-5"}],
}
SITE = Site(name="Where Councils Stand", package="councils", env_prefix="COUNCILS", root=Path("/srv/councils"))
# the site's prices: the base (its own model's), and a table of its own for the model the arm names
PRICES = PriceTable(base=Price(2.0, 10.0, 0.2), models=(("claude-opus-5-5", Price(4.0, 20.0, 0.2)),))


def settings(experiment: Any = DECLARED, **changes: Any) -> Settings:
    declared = {**experiment, **changes} if isinstance(experiment, dict) else experiment
    raw = {} if declared is None else {"experiment": declared}
    return Settings(raw=raw, data_dir=Path("/srv/councils/data"), config_path=Path("/srv/councils/config/settings.toml"),
                    site=SITE)


def arms(*more: dict[str, Any], control: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [{"name": "control", "share": 0.5, **(control or {})}, *more]


def base(log: SqliteBriefingLog | None = None) -> BriefingConfig:
    """The site's own configuration, as it makes it when it starts."""
    return briefing_config(log=log, model="claude-sonnet-5-5", parse_model="claude-haiku-5-5", instructions="v7",
                           site_version="2026.11", also={"ranking": {"per_group": 2}, "sources": 8})


def note_a_pass(folder: Path, config_id: str, thresholds: dict[str, float] = THRESHOLDS, **figures: float) -> None:
    """A pass, as ``eval run`` notes one: the whole set asked, every threshold met."""
    summary = {"cases": 3, "questions": 3, "grounded_ratio": 0.9, "invalid_citations": 0, **figures}
    harness.mark_passed(harness.Run(config_id, {}, "2026-11-09T09:00:00+00:00", [], summary), thresholds, folder)


def passed_switch(runs: Path, config: BriefingConfig | None = None, log: SqliteBriefingLog | None = None,
                  declared: Settings | None = None) -> ExperimentSwitch:
    """The experiment, with its arm's pass noted: able to run."""
    declared, config = declared or settings(), config or base()
    experiment = Experiment.from_settings(declared)
    assert experiment is not None
    for name, arm in arm_configs(experiment, config).items():
        if name != experiment.control.name:
            note_a_pass(runs, arm.config_id)
    return experiment_switch(declared, config, log=log, runs=runs, thresholds=THRESHOLDS, prices=PRICES)


class InExperiment(Told):
    """The desk with the experiment running, and a pipeline that reads its version from the desk."""

    def __init__(self, folder: Path, *, choices: tuple[int, ...] = (), **more: Any) -> None:
        self.runs = folder / "runs"
        self.written_with: list[tuple[str, str | None, str | None]] = []
        config = more.pop("config", None) or base()
        switch = more.pop("experiment", None) or passed_switch(self.runs, config)
        limits = Limits(per_visitor_daily=50, per_account_daily=None, daily_cap_usd=100.0, monthly_cap_usd=1000.0)
        super().__init__(COUNCILS, folder, config=config, experiment=switch, random=FixedRandom(choices=choices),
                         limits=limits, **more)
        self.clock.set("2026-11-13T12:00:00+00:00")
        self.switch = switch

    def versioned(self, answer: dict[str, Any] | None = None):
        """A pipeline as a site writes one for an experiment: the model and the variant come from the desk."""

        def write() -> Iterator[dict[str, Any]]:
            config = current_config()
            assert config is not None
            self.written_with.append((config.model, config.variant, config.arm))
            yield {"type": "plan", "plan": {"parser": "model"}, "usage": dict(PARSE)}
            yield {"type": "sources", "sources": CARDS[:6] if config.variant == "six-sources" else CARDS}
            yield {"type": "text", "text": f"Written by {config.model}."}
            yield {"type": "final", "answer": dict(ANSWER if answer is None else answer), "usage": dict(WRITE),
                   "model": config.model, "stop_reason": "end_turn"}

        return write

    def asked(self, **more: Any) -> list[dict[str, Any]]:
        return self.run(write=self.versioned(), **more)


# Condition 6: declared in settings, with a name, the versions, their shares, the dates and what decides it


def test_an_experiment_is_declared_in_settings_with_its_name_arms_shares_dates_and_deciding_rate():
    experiment = Experiment.from_settings(settings())
    assert experiment == Experiment(
        name="six-sources", start=date(2026, 11, 10), end=date(2026, 11, 24), decided_by="any_check",
        arms=(Arm("control", 0.5), Arm("six", 0.5, model="claude-opus-5-5", variant="six-sources")))
    assert experiment.control.changes == {} and experiment.arms[1].changes == {"model": "claude-opus-5-5",
                                                                               "variant": "six-sources"}
    assert Experiment.from_settings(settings(None)) is None and Experiment.from_settings(settings({})) is None
    # days may be written as text, as a settings.local.toml written by a command would have them
    assert Experiment.from_settings(settings(start="2026-11-10", end="2026-11-24")) == experiment
    assert ARM_CHANGES == ("model", "instructions", "variant")


@pytest.mark.parametrize("wrong, says", [
    ({"arms": arms({"name": "six", "share": 0.4, "variant": "six"})}, "the shares must add up to 1, and they add up to 0.9"),
    ({"arms": arms({"name": "six", "share": 0.5})}, "'six' changes nothing"),
    ({"arms": arms({"name": "six", "share": 0.5, "variant": "six"}, control={"model": "another"})},
     "the first arm is the control, the site as it stands, and changes nothing: 'control' changes model"),
    ({"arms": [{"name": "control", "share": 1.0}]}, "an experiment has two arms or more"),
    ({"arms": arms({"name": "control", "share": 0.5, "variant": "six"})}, "two arms have the same name"),
    ({"arms": arms({"name": "six", "share": 0, "variant": "six"})}, "share is 0: a share is a number above 0"),
    ({"arms": arms({"name": "Six Sources!", "share": 0.5, "variant": "six"})}, "a name is lower-case letters"),
    ({"start": date(2026, 11, 25)}, r"end \(2026-11-24\) is before start \(2026-11-25\)"),
    ({"start": "next week"}, r"\[experiment\] start must be a day, such as 2026-12-01"),
    ({"decided_by": "cost"}, "decided_by is 'cost': the rates the statistics can test between arms are cache_hits"),
    ({"name": ""}, r"\[experiment\] name is ''"),
    ({"reader_cookie": "arm"}, "has reader_cookie, which an experiment does not have"),
])
def test_a_declaration_that_is_wrong_is_refused_with_the_file_and_the_key(wrong, says):
    with pytest.raises(SettingsError, match=says) as stopped:
        Experiment.from_settings(settings(**wrong))
    assert str(stopped.value).startswith("/srv/councils/config/settings.toml: the experiment cannot run: ")


def test_everything_missing_is_said_at_once():
    with pytest.raises(SettingsError) as stopped:
        Experiment.from_settings(settings({"name": "six-sources"}))
    assert "2 things missing or wrong" not in str(stopped.value) and len(stopped.value.problems) == 1
    assert "needs arms, start, end, decided_by" in stopped.value.problems[0]


def test_the_deciding_rate_is_one_the_statistics_can_test():
    for rate in PROPORTIONS:
        assert Experiment.from_settings(settings(decided_by=rate)).decided_by == rate


def test_only_one_experiment_at_a_time():
    """The policy: one experiment at a time on each site. Two ``[experiment]`` tables are not TOML at all, and
    the site does not start; a list of them is refused here."""
    import tomllib

    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads('[experiment]\nname = "a"\n[experiment]\nname = "b"\n')
    with pytest.raises(SettingsError, match="one experiment at a time"):
        Experiment.from_settings(settings([dict(DECLARED), dict(DECLARED, name="another")]))


def test_outside_its_dates_the_experiment_is_off(tmp_path):
    told = InExperiment(tmp_path, choices=(1, 1, 1, 1))
    for day, running, why in (("2026-11-09T23:59:59+00:00", False, "it has not started: its first day is 2026-11-10"),
                              ("2026-11-10T00:00:00+00:00", True, ""),
                              ("2026-11-24T23:59:59+00:00", True, ""),
                              ("2026-11-25T00:00:00+00:00", False, "it ended on 2026-11-24")):
        told.clock.set(day)
        state = told.switch.state(told.clock)
        assert (state.running, state.fault) == (running, False) and state.why.startswith(why), day
        told.asked(cache_key=None)
        record = told.log.records[-1]
        assert (record.experiment, record.arm) == (("six-sources", "six") if running else (None, None)), day
        assert record.config_id == (told.switch.configs["six"].config_id if running else base().config_id)
    assert [arm for _, _, arm in told.written_with] == [None, "six", "six", None]


# Condition 1: every version passes the same checks and the same balance requirements


@pytest.mark.parametrize("key", ["verifier", "loaded_words", "checks", "balance", "per_group", "thresholds",
                                 "min_grounded_ratio", "quote_check", "spelling", "citation_rules"])
def test_an_arm_may_not_change_the_checks_the_loaded_words_or_the_balance_requirements(key):
    """Nothing in an arm can turn a check off: such a key is refused, and said to be one."""
    changed = arms({"name": "six", "share": 0.5, "variant": "six", key: "off"})
    with pytest.raises(SettingsError, match=f"'six' has {key}: every version passes the same checks and the same "
                                            "balance requirements"):
        Experiment.from_settings(settings(arms=changed))


def test_an_arm_may_change_the_model_the_instructions_version_and_one_variant_and_nothing_else():
    for key in ("sources", "cache_hours", "per_visitor_daily_questions", "embedding", "parse_model"):
        with pytest.raises(SettingsError, match=f"has {key}, which is not something an arm can change: an arm may "
                                                "change model, instructions, variant, and nothing else"):
            Experiment.from_settings(settings(arms=arms({"name": "six", "share": 0.5, "variant": "six", key: 6})))
    allowed = Experiment.from_settings(settings(arms=arms({"name": "six", "share": 0.5, "instructions": "v8"})))
    assert allowed.arms[1] == Arm("six", 0.5, instructions="v8")
    assert {f.name for f in dataclasses.fields(Arm)} == {"name", "share", *ARM_CHANGES}


def test_an_arm_that_has_not_passed_the_evaluation_harness_never_goes_live(tmp_path, caplog):
    """The site starts on its control alone, logs an error naming the arm, and the switch says why."""
    runs, config = tmp_path / "runs", base()
    with caplog.at_level(logging.ERROR, logger="wts_core.briefing.experiment"):
        switch = experiment_switch(settings(), config, log=None, runs=runs, thresholds=THRESHOLDS, prices=PRICES)
    arm_id = arm_configs(Experiment.from_settings(settings()), config)["six"].config_id
    assert switch.declared and switch.fault is not None and switch.configs == {}
    assert f"the arm six (configuration {arm_id}) has no pass noted" in switch.fault
    assert "a version that has not passed the evaluation harness never goes live" in switch.fault
    [said] = [r.getMessage() for r in caplog.records]
    assert "the experiment 'six-sources' is declared and is not running: the site is on its control alone" in said
    assert f"the arm six (configuration {arm_id})" in said
    state = switch.state(FixedClock("2026-11-13T12:00:00+00:00"))
    assert (state.name, state.running, state.fault) == ("six-sources", False, True) and "arm six" in state.why
    # and the desk, given that switch, is the site with no experiment at all
    told = InExperiment(tmp_path, experiment=switch, choices=(1, 1))
    first = told.asked()
    assert [arm for _, _, arm in told.written_with] == [None]
    record = told.log.records[-1]
    assert (record.experiment, record.arm, record.config_id) == (None, None, config.config_id)
    assert told.cache.get("k" * 64, 168)[-1]["briefing_id"] == first[-1]["briefing_id"]  # under the site's own key


def test_a_pass_counts_only_for_exactly_the_arms_configuration_under_the_thresholds_as_they_stand(tmp_path):
    config = base()
    experiment = Experiment.from_settings(settings())
    arm_id = arm_configs(experiment, config)["six"].config_id

    def running(folder: Path, thresholds: dict[str, float] = THRESHOLDS, **more: Any) -> bool:
        return experiment_switch(settings(), more.get("config", config), log=None, runs=folder,
                                 thresholds=thresholds, prices=PRICES).fault is None

    # a pass for the site as it stands, or for the control, is not a pass for the arm
    note_a_pass(tmp_path / "a", config.config_id)
    note_a_pass(tmp_path / "a", arm_configs(experiment, config)["control"].config_id)
    assert not running(tmp_path / "a")
    note_a_pass(tmp_path / "a", arm_id)
    assert running(tmp_path / "a")
    # thresholds raised since the run was made are not got round by the old pass
    assert not running(tmp_path / "a", {**THRESHOLDS, "min_grounded_ratio": 0.95})
    note_a_pass(tmp_path / "a", arm_id, {**THRESHOLDS, "min_grounded_ratio": 0.95}, grounded_ratio=0.97)
    assert running(tmp_path / "a", {**THRESHOLDS, "min_grounded_ratio": 0.95})
    # every arm is held to the site's thresholds: with none set, nothing can have passed them
    assert "no evaluation thresholds" in experiment_switch(settings(), config, log=None, runs=tmp_path / "a",
                                                           thresholds={}, prices=PRICES).fault
    # the same arm on a changed site (its instructions moved on) is another configuration: it has not passed
    moved = briefing_config(log=None, model="claude-sonnet-5-5", parse_model="claude-haiku-5-5", instructions="v8",
                            site_version="2026.11", also={"ranking": {"per_group": 2}, "sources": 8})
    assert not running(tmp_path / "a", config=moved)
    # a note of passes that cannot be read is not a pass
    (tmp_path / "a" / harness.PASSED_FILE).write_text("not json\n")
    assert "could not be read" in experiment_switch(settings(), config, log=None, runs=tmp_path / "a",
                                                    thresholds=THRESHOLDS, prices=PRICES).fault


def test_a_faulty_declaration_never_stops_the_site_it_runs_on_its_control_and_says_why(tmp_path, caplog):
    declared = settings(arms=arms({"name": "six", "share": 0.5, "variant": "six", "verifier": "off"}))
    with caplog.at_level(logging.ERROR, logger="wts_core.briefing.experiment"):
        switch = experiment_switch(declared, base(), log=None, runs=tmp_path, thresholds=THRESHOLDS, prices=PRICES)
    assert switch.experiment is None and switch.declared and "every version passes the same checks" in switch.fault
    assert "is declared and is not running" in caplog.records[0].getMessage()
    state = switch.state(FixedClock())
    assert state == ExperimentState(name="six-sources", running=False, fault=True, why=switch.fault)
    assert switch.choose("reader", FixedRandom(choices=[1]), FixedClock("2026-11-13T12:00:00+00:00")) is None
    none = experiment_switch(settings(None), base(), log=None, runs=tmp_path, thresholds=THRESHOLDS, prices=PRICES)
    assert (none.declared, none.fault, none.state(FixedClock())) == (False, None, None)  # none declared: nothing said


def test_a_briefing_written_in_an_experiment_without_a_checks_figure_is_not_shown(tmp_path):
    """Every version passes the same checks. A pipeline that left a check out for an arm fails every briefing of
    that arm: the reader is told it failed, and it is neither saved nor cached."""
    told = InExperiment(tmp_path, choices=(1,))
    unchecked = {k: v for k, v in ANSWER.items() if k != "loaded_words"}
    events = told.run(write=told.versioned(unchecked))
    assert events[-1] == {"type": "error", "message": told.messages.briefing_failed}
    record = told.log.records[-1]
    assert (record.outcome, record.error_type, record.arm, record.briefing_id) == ("error", "ChecksMissing", "six",
                                                                                   None)
    assert told.rows("wts_briefings") == [] and told.rows("wts_answer_cache") == []
    assert "without loaded_words" in told.failures.recent()[0]["error"]
    assert set(CHECKED) <= set(ANSWER)  # the figures a checked briefing's report holds on every site
    # a "no records" answer was written by no model: there is nothing of the arm's to check
    none = InExperiment(tmp_path / "none", choices=(1,))
    events = none.run(write=none.versioned({"segments": [], "markdown": "No records found.", "no_records": True}))
    assert events[-1]["type"] == "final" and none.log.records[-1].outcome == "no_records"
    # and outside an experiment the desk asks nothing new of a site's report
    plain = Told(COUNCILS, tmp_path / "plain")
    assert plain.run(write=plain.written(final={"type": "final", "answer": unchecked, "usage": dict(WRITE)})
                     )[-1]["type"] == "final"


# Condition 2: assignment is by chance for each briefing, never for each reader


def test_a_version_is_chosen_by_chance_for_each_briefing_so_the_same_visitor_is_given_both(tmp_path):
    told = InExperiment(tmp_path, choices=(0, 1, 1, 0, 1))
    for _ in range(5):
        told.asked(cache_key=None)  # the same visitor, the same question, five times
    assert [arm for _, _, arm in told.written_with] == ["control", "six", "six", "control", "six"]
    assert [r.arm for r in told.log.records] == ["control", "six", "six", "control", "six"]


def test_nothing_about_the_visitor_is_an_input_to_the_choice(tmp_path):
    """The same run of chance gives the same versions whoever asks, whatever they ask and however they are known;
    and the choice has nowhere to be given a visitor, an account, an address or a cookie."""
    chance = (1, 0, 0, 1, 1, 0)
    who = [dict(visitor="a" * 24), dict(visitor="b" * 24, options={"cookie": "x"}),
           dict(visitor=None, limiter_key="203.0.113.9"),
           dict(visitor="c" * 24, question="Another question altogether?"), dict(visitor="a" * 24, mode="comprehensive"),
           dict(visitor="d" * 24, follow_up=True)]
    one = InExperiment(tmp_path / "one", choices=chance)
    for _ in who:
        one.asked(cache_key=None)
    other = InExperiment(tmp_path / "other", choices=chance)
    for someone in who:
        other.asked(cache_key=None, **someone)
    assert [r.arm for r in one.log.records] == [r.arm for r in other.log.records] == [
        "six", "control", "control", "six", "six", "control"]
    assert list(inspect.signature(ExperimentSwitch.choose).parameters) == ["self", "kind", "random", "clock"]

    class Watched(FixedRandom):
        def __init__(self) -> None:
            super().__init__()
            self.asked: list[tuple[Any, Any]] = []

        def choice(self, items, weights):
            self.asked.append((tuple(a.name for a in items), tuple(weights)))
            return items[0]

    watched = Watched()
    switch = passed_switch(tmp_path / "runs")
    switch.choose("reader", watched, FixedClock("2026-11-13T12:00:00+00:00"))
    assert watched.asked == [(("control", "six"), (0.5, 0.5))]  # the arms and their shares, and nothing else


def test_the_nightly_checks_question_and_the_evaluation_harnesss_are_never_in_an_experiment(tmp_path):
    told = InExperiment(tmp_path, choices=(1, 1, 1))
    for kind in ("check", "eval", "reader"):
        told.asked(cache_key=None, kind=kind)
    assert [(r.kind, r.arm) for r in told.log.records] == [("check", None), ("eval", None), ("reader", "six")]


def test_a_request_for_the_sources_only_and_a_refused_one_are_in_the_version_they_were_given(tmp_path):
    """The arm is chosen before anything is found, so the sources a reader is shown are that version's too."""
    told = InExperiment(tmp_path, choices=(1, 1))
    seen: list[str | None] = []

    def sources_only(note: str, free: bool) -> Iterator[dict[str, Any]]:
        seen.append(current_config().arm)
        yield {"type": "sources", "sources": CARDS}
        yield {"type": "final", "answer": None, "usage": None, "note": note}

    told.run(sources_only=sources_only, only_sources=True)
    assert seen == ["six"] and (told.log.records[-1].outcome, told.log.records[-1].arm) == ("sources_only", "six")
    assert told.log.records[-1].question == ""  # and its question is kept no more than before


# Condition 3: the version used is recorded with each briefing


def test_the_version_used_is_recorded_with_each_briefing_and_what_it_was_can_be_read_back(tmp_path):
    clock = FixedClock("2026-11-13T12:00:00+00:00")
    db = StateDB(tmp_path / "state.db", migrations=(*core_usage.migrations(), *observe.migrations()), clock=clock)
    log = SqliteBriefingLog(db, clock=clock)
    config = base(log)
    switch = passed_switch(tmp_path / "runs", config, log)
    told = InExperiment(tmp_path / "desk", config=config, experiment=switch, log=log, choices=(1, 0))
    told.asked(cache_key=None)
    told.asked(cache_key=None)
    six, control = log.since("2026-11-13T00:00:00+00:00")
    assert (six.experiment, six.arm, six.model) == ("six-sources", "six", "claude-opus-5-5")
    assert (control.experiment, control.arm, control.model) == ("six-sources", "control", "claude-sonnet-5-5")
    assert len({six.config_id, control.config_id, config.config_id}) == 3  # each version has an id of its own
    # the settings behind each id are kept, so any briefing can be explained: what the arm changed, and all the rest
    kept = log.config(six.config_id)
    assert kept == {**config.settings, "experiment": "six-sources", "arm": "six", "variant": "six-sources",
                    "model": "claude-opus-5-5"}
    assert log.config(control.config_id) == {**config.settings, "experiment": "six-sources", "arm": "control"}
    assert observe.config_id(kept) == six.config_id
    # nothing of the reader went into the record with it
    assert "c0ffee" not in repr(six) + repr(control)
    # and the statistics set the arms side by side from those records
    clock.advance(hours=1)
    found = observe.stats(log, since=clock.now().replace(hour=0), clock=clock, experiment=switch.state(clock))
    assert set(found.by_arm["six-sources"]) == {"control", "six"} and found.decided_by == "any_check"


def test_an_arms_configuration_is_kept_only_once_the_experiment_may_run(tmp_path):
    clock = FixedClock("2026-11-13T12:00:00+00:00")
    db = StateDB(tmp_path / "state.db", migrations=observe.migrations(), clock=clock)
    log = SqliteBriefingLog(db, clock=clock)
    config = base(log)
    experiment_switch(settings(), config, log=log, runs=tmp_path / "runs", thresholds=THRESHOLDS, prices=PRICES)  # not passed
    with db.connect() as con:
        assert [r["config_id"] for r in con.execute("SELECT config_id FROM wts_configs")] == [config.config_id]


# Condition 4: a saved briefing's address always shows what was originally shown


def test_a_saved_briefing_always_shows_what_was_originally_shown_whatever_becomes_of_the_experiment(tmp_path):
    told = InExperiment(tmp_path, choices=(1, 0))
    sent = told.asked(cache_key=None)
    briefing_id = sent[-1]["briefing_id"]
    as_saved = told.archive.get(briefing_id).events
    assert as_saved[-2] == {"type": "text", "text": "Written by claude-opus-5-5."}
    assert as_saved[0]["type"] == "plan" and len(as_saved[1]["sources"]) == len(sent[1]["sources"])
    # the experiment ends, the control is kept, and the site is started without it
    told.clock.set("2026-12-01T09:00:00+00:00")
    after = Told(COUNCILS, tmp_path, config=base())
    assert after.archive.get(briefing_id).events == as_saved  # the arm's briefing, as its reader was sent it
    after.run()  # the same question, on the site as it now stands: written afresh, at an address of its own
    assert after.archive.get(briefing_id).events == as_saved


# Condition 5: the answer cache is keyed on the version


def test_the_answer_cache_is_keyed_on_the_version_so_versions_never_serve_each_others_answers(tmp_path):
    told = InExperiment(tmp_path, choices=(0, 1, 0, 1))
    first_control, first_six = told.asked()[-1], told.asked()[-1]
    assert [arm for _, _, arm in told.written_with] == ["control", "six"]  # the second was not served the first's
    again_control, again_six = told.asked()[-1], told.asked()[-1]
    assert len(told.written_with) == 2  # each is now served its own
    assert (again_control["cached"], again_control["briefing_id"]) == (True, first_control["briefing_id"])
    assert (again_six["cached"], again_six["briefing_id"]) == (True, first_six["briefing_id"])
    assert first_control["briefing_id"] != first_six["briefing_id"]
    assert [(r.outcome, r.arm) for r in told.log.records] == [
        ("completed", "control"), ("completed", "six"), ("cached", "control"), ("cached", "six")]
    assert len(told.rows("wts_answer_cache")) == 2 and told.cache.get("k" * 64, 168) is None  # neither is the site's


def test_an_answer_cached_before_the_experiment_is_not_served_as_any_arms_and_no_arms_is_served_after_it(tmp_path):
    short = passed_switch(tmp_path / "runs", declared=settings(end=date(2026, 11, 12)))  # three days long
    told = InExperiment(tmp_path, experiment=short, choices=(0, 1))
    told.clock.set("2026-11-09T12:00:00+00:00")  # the day before it starts
    before = told.asked()[-1]
    told.clock.set("2026-11-11T12:00:00+00:00")
    assert "cached" not in told.asked()[-1] and "cached" not in told.asked()[-1]  # control and six: both written
    told.clock.set("2026-11-13T12:00:00+00:00")  # it has ended (and the first answer is still within its week)
    after = told.asked()[-1]
    assert (after["cached"], after["briefing_id"]) == (True, before["briefing_id"])


# What the pipeline is told, and what the owner is


def test_the_pipeline_reads_its_version_from_the_desk_and_nowhere_outside_one(tmp_path):
    assert current_config() is None  # outside a desk: a command, a test of the pipeline alone
    told = InExperiment(tmp_path, choices=(1, 0))
    told.asked(cache_key=None)
    told.asked(cache_key=None)
    assert told.written_with == [("claude-opus-5-5", "six-sources", "six"), ("claude-sonnet-5-5", None, "control")]
    assert current_config() is None
    plain = Told(COUNCILS, tmp_path / "plain")
    seen: list[BriefingConfig | None] = []

    def write() -> Iterator[dict[str, Any]]:
        seen.append(current_config())
        yield {"type": "final", "answer": None, "usage": None}

    plain.run(write=write)
    assert seen[0] is not None and seen[0].config_id == "abc123def456" and seen[0].arm is None  # the site's own


def test_the_sites_hooks_are_given_the_version_too(tmp_path):
    from wts_core.briefing import Ask, Hooks

    seen: list[str | None] = []

    class Noting(Hooks):
        def on_cached(self, ask: Ask, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            seen.append(current_config().arm)
            return events

    told = InExperiment(tmp_path, choices=(1, 1), hooks=Noting())
    told.asked()
    told.asked()
    assert seen == ["six"]


def test_the_check_route_and_the_statistics_say_the_experiment_is_not_running_and_why(tmp_path):
    from cli_sites import mounted, run
    from wts_core.cli import check_route, stats_commands

    clock = FixedClock("2026-11-13T12:00:00+00:00")
    db = StateDB(tmp_path / "state.db", migrations=observe.migrations(), clock=clock)
    config = base()
    not_passed = experiment_switch(settings(), config, log=None, runs=tmp_path / "runs", thresholds=THRESHOLDS, prices=PRICES)
    arm_id = arm_configs(not_passed.experiment, config)["six"].config_id
    why = f"the arm six (configuration {arm_id}) has no pass noted"

    def commands(switch: ExperimentSwitch):
        return mounted(stats_commands(SITE, lambda: db, thresholds=dict, folder=lambda: tmp_path / "reports",
                                      experiment=lambda: switch.state(clock), clock=clock))

    status, body = check_route(SITE, token="t0ken", clock=clock,
                               experiment=lambda: not_passed.state(clock))("Bearer t0ken")
    assert status == 200 and body["experiment"]["name"] == "six-sources"
    assert (body["experiment"]["running"], body["experiment"]["fault"]) == (False, True)
    assert body["experiment"]["why"].startswith(why)
    page = run(commands(not_passed), ["stats"], tmp_path)
    assert page.exit_code == 0 and "**The experiment `six-sources` is declared and is not running: the site is on " \
        "its control alone.** The arm six" in page.stdout
    # the owner is told: the check that runs after each update and each weekly report fails
    checked = run(commands(not_passed), ["stats", "--check"], tmp_path)
    assert checked.exit_code == 1 and checked.stdout.startswith(
        f"The experiment six-sources is declared and is not running: {why}")
    weekly = run(commands(not_passed), ["weekly-report", "--week", "2026-W45"], tmp_path)
    assert weekly.exit_code == 1 and "The experiment six-sources is declared and is not running" in weekly.stdout
    # once the arm has passed it runs, and nothing is wrong
    note_a_pass(tmp_path / "runs", arm_id)
    passed = experiment_switch(settings(), config, log=None, runs=tmp_path / "runs", thresholds=THRESHOLDS, prices=PRICES)
    assert check_route(SITE, token="t0ken", clock=clock, experiment=lambda: passed.state(clock))("t0ken")[1][
        "experiment"] == {"name": "six-sources", "running": True, "fault": False, "why": "", "start": "2026-11-10",
                          "end": "2026-11-24", "decided_by": "any_check"}
    assert run(commands(passed), ["stats", "--check"], tmp_path) .exit_code == 0
    assert "The experiment `six-sources` is running, from 10 November 2026 to 24 November 2026" in run(
        commands(passed), ["stats"], tmp_path).stdout
    # before its first day and after its last it is not running, and that is no fault
    clock.set("2026-12-02T09:00:00+00:00")
    over = run(commands(passed), ["stats", "--check"], tmp_path)
    assert over.exit_code == 0 and over.stdout == ""
    assert "is not running: it ended on 2026-11-24: release the version chosen" in run(
        commands(passed), ["stats"], tmp_path).stdout
    # a site with no experiment is asked, and says nothing of one
    none = experiment_switch(settings(None), config, log=None, runs=tmp_path / "runs", thresholds=THRESHOLDS, prices=PRICES)
    assert check_route(SITE, token="t0ken", clock=clock, experiment=lambda: none.state(clock))("t0ken")[1][
        "experiment"] is None
    assert "experiment" not in run(commands(none), ["stats"], tmp_path).stdout.lower()


def test_an_arm_is_passed_by_the_evaluation_commands_under_exactly_the_id_the_experiment_looks_for(tmp_path):
    """End to end: ``eval run --arm six`` hands the site's pipeline the arm's configuration, saves and notes the
    run under the arm's id, and with that pass the experiment runs."""
    from cli_sites import mounted, run
    from test_eval_run import Plain
    from wts_core.cli import eval_commands

    clock = FixedClock("2026-11-13T09:30:00+00:00")
    config, runs = base(), tmp_path / "runs"
    experiment = Experiment.from_settings(settings())
    versions = {name: dict(arm.settings) for name, arm in arm_configs(experiment, config).items()}
    site = Plain(clock, cases=Plain(clock).cases()[1:2])  # one question whose briefing is written and well checked
    app = mounted(eval_commands(lambda: site, config=lambda: dict(config.settings), config_id=observe.config_id,
                                pricing=lambda: PRICES, thresholds=lambda: THRESHOLDS, runs=lambda: runs,
                                max_cost_usd=1.0, arms=lambda: versions, clock=clock))
    assert experiment_switch(settings(), config, log=None, runs=runs, thresholds=THRESHOLDS, prices=PRICES).fault is not None
    plain = run(app, ["eval", "run"], tmp_path)  # the site as it stands: a pass, and not the arm's
    assert plain.exit_code == 0 and f"configuration {config.config_id}" in plain.stdout
    assert experiment_switch(settings(), config, log=None, runs=runs, thresholds=THRESHOLDS, prices=PRICES).fault is not None
    unknown = run(app, ["eval", "run", "--arm", "seven"], tmp_path)
    assert unknown.exit_code == 1 and "There is no arm called 'seven' to evaluate: the site's experiment has " \
        "control, six." in unknown.stderr
    arm = run(app, ["eval", "run", "--arm", "six"], tmp_path)
    arm_id = arm_configs(experiment, config)["six"].config_id
    assert arm.exit_code == 0 and f"Passed: every threshold met by configuration {arm_id}." in arm.stdout
    asked_with = site.asked[-1][1]
    assert (asked_with["model"], asked_with["variant"], asked_with["arm"]) == ("claude-opus-5-5", "six-sources", "six")
    assert experiment_switch(settings(), config, log=None, runs=runs, thresholds=THRESHOLDS, prices=PRICES).fault is None
    # An arm whose model has no prices of its own is not run at another model's: nothing is asked, nothing noted.
    asked = len(site.asked)
    for prices, says in ((PriceTable(base=Price(2.0, 10.0, 0.2)),
                          "The arm 'six' names the model claude-opus-5-5, which has no price table of its own"),
                         (BasePricesOnly(), "the site's prices cannot say whether it has a table of its own")):
        unpriced = mounted(eval_commands(lambda: site, config=lambda: dict(config.settings),
                                         config_id=observe.config_id, pricing=lambda prices=prices: prices,
                                         thresholds=lambda: THRESHOLDS, runs=lambda: tmp_path / "other",
                                         max_cost_usd=1.0, arms=lambda: versions, clock=clock))
        refused = run(unpriced, ["eval", "run", "--arm", "six"], tmp_path)
        assert refused.exit_code == 1 and says in refused.stderr and len(site.asked) == asked
        assert run(unpriced, ["eval", "run", "--arm", "control"], tmp_path).exit_code == 0  # the site's own model
        asked = len(site.asked)
    assert not (tmp_path / "other" / harness.PASSED_FILE).exists() or arm_id not in (
        tmp_path / "other" / harness.PASSED_FILE).read_text()


class BasePricesOnly:
    """Prices that are not ``usage.PriceTable``: they can cost a call, and cannot say whose prices they used."""

    def price_for(self, model: str | None) -> Price:
        return Price(2.0, 10.0, 0.2)

    def cost(self, usage: Usage | None, model: str | None) -> float:
        return 0.0


# An arm's model is costed at its own prices (rule 5), found by the independent review of 0.3.0


def test_an_arm_that_names_a_model_with_no_prices_of_its_own_never_goes_live(tmp_path, caplog):
    """An arm naming a dearer model on a site whose table has only its own model's was costed at the base prices:
    half the real cost on Where Councils Stand's table, so the spending caps counted half. The arm's model must
    have a table of its own, and the site must give its prices for that to be checked."""
    config, runs = base(), tmp_path / "runs"
    experiment = Experiment.from_settings(settings())
    note_a_pass(runs, arm_configs(experiment, config)["six"].config_id)
    only_its_own = PriceTable(base=Price(2.0, 10.0, 0.2), models=(("claude-sonnet-5-5", Price(2.0, 10.0, 0.2)),))
    call = Usage(input_uncached=20_000, output=1_500)
    assert only_its_own.cost(call, "claude-opus-5-5") == 0.055 and PRICES.cost(call, "claude-opus-5-5") == 0.11
    clock = FixedClock("2026-11-13T12:00:00+00:00")
    for prices, says in ((only_its_own, "the arm six names the model claude-opus-5-5, which has no price table of "
                                        "its own: add [usage.models.\"<name>\"]"),
                         (None, "the arm six names the model claude-opus-5-5, and the site gave no price table")):
        with caplog.at_level(logging.ERROR, logger="wts_core.briefing.experiment"):
            switch = experiment_switch(settings(), config, log=None, runs=runs, thresholds=THRESHOLDS, prices=prices)
        assert switch.fault is not None and says in switch.fault and says in caplog.text
        assert switch.choose("reader", FixedRandom(choices=(1,)), clock) is None  # the site is on its control
        state = switch.state(clock)
        assert state is not None and state.fault and not state.running
    assert experiment_switch(settings(), config, log=None, runs=runs, thresholds=THRESHOLDS,
                             prices=PRICES).fault is None
    # a table under a shorter name the model's id begins with is a table of its own, as for any model
    family = PriceTable(base=Price(2.0, 10.0, 0.2), models=(("claude-opus", Price(4.0, 20.0, 0.2)),))
    assert experiment_switch(settings(), config, log=None, runs=runs, thresholds=THRESHOLDS,
                             prices=family).fault is None
    # and an arm that names no model needs no prices looked up: it runs on the site's own
    no_model = settings(arms=arms({"name": "six", "share": 0.5, "variant": "six-sources"}))
    note_a_pass(runs, arm_configs(Experiment.from_settings(no_model), config)["six"].config_id)
    assert experiment_switch(no_model, config, log=None, runs=runs, thresholds=THRESHOLDS).fault is None


# A faulty experiment never stops the site: the review's fuzz

_JUNK: list[Any] = [
    None, True, False, 0, 1, -1, 0.5, 1.0, 1e308, 10 ** 400, -10 ** 400, float("nan"), float("inf"), "", " ", "x",
    "control", "six", "A" * 5000, "2026-13-45", "2026-11-10", [], [1], [[]], {}, {"a": 1}, date(2026, 11, 10),
    b"bytes", 0.3333333, 0.6666667, 0.1 + 0.2, [{"name": "control", "share": 0.5}] * 3, {"name": "x", "share": 0.5},
    "claude-nonexistent-9", "../../etc/passwd", "Six", "six\n", "\u0000", 2 ** 63]
_KEYS = ["share", "name", "model", "instructions", "variant", "loaded_words", "thresholds", "checks", "verifier",
         "min_grounded_ratio", "sources", "arms", "start", "end", "decided_by", "extra"]


def _mutated(rng: Any) -> Any:
    import copy

    declared = copy.deepcopy(DECLARED)
    for _ in range(rng.randint(1, 3)):
        tables = [arm for arm in declared["arms"] if isinstance(arm, dict)] if isinstance(
            declared.get("arms"), list) else []
        target = declared if rng.random() < 0.45 or not tables else rng.choice(tables)
        key = rng.choice(list(target) + _KEYS)
        if rng.random() < 0.15:
            target.pop(key, None)
        else:
            target[key] = rng.choice(_JUNK)
    if rng.random() < 0.1 and isinstance(declared.get("arms"), list):
        declared["arms"] = declared["arms"] + [{"name": f"arm{i}", "share": 1e-5, "variant": f"v{i}"}
                                              for i in range(rng.choice([1, 50, 500]))]
    return declared


def test_no_declaration_however_broken_stops_the_site_or_runs_an_arm_it_should_not(tmp_path):
    """The independent review of 0.3.0 mutated a sound declaration thirty thousand times. One mutation stopped
    the site (a share too large to be a float), and none ran an arm it should not have. Both are held here, on
    four thousand: the switch never raises; a declaration the strict reading refuses never gives a briefing to
    an arm, and says why; and no arm runs without its pass."""
    import random

    rng = random.Random(3)
    config, runs = base(), tmp_path / "runs"
    switch = passed_switch(runs, config)
    clock = FixedClock("2026-11-13T12:00:00+00:00")
    assert switch.fault is None and switch.choose("reader", FixedRandom(choices=(1,)), clock).arm == "six"
    logging.disable(logging.CRITICAL)
    try:
        sound_ones = 0
        for n in range(4000):
            declared = settings(_mutated(rng) if n else [DECLARED, DECLARED])
            try:
                Experiment.from_settings(declared)
                sound = True
            except SettingsError:
                sound = False
            switch = experiment_switch(declared, config, log=None, runs=runs, thresholds=THRESHOLDS, prices=PRICES)
            chosen = [switch.choose("reader", FixedRandom(choices=(i,)), clock) for i in (0, 1)]
            state = switch.state(clock)
            if not sound:
                assert chosen == [None, None] and state is not None and state.fault and state.why, declared.raw
            if switch.fault is None and switch.experiment is not None:
                sound_ones += 1
                for arm in switch.experiment.arms[1:]:
                    assert harness.has_passed(runs, switch.configs[arm.name].config_id, THRESHOLDS), declared.raw
                    assert not arm.model or arm.model.startswith("claude-opus-5-5"), declared.raw  # priced
        assert sound_ones > 20  # some mutations leave it sound, and those still run
    finally:
        logging.disable(logging.NOTSET)


@pytest.mark.parametrize("thresholds", [
    {"min_grounded_ratio": "high"}, {"min_nonsense": 1}, {"min_grounded_ratio": None}, {"min_grounded_ratio": True},
    [1], "x",
    # numbers to TOML, and a bar no run can fail to clear: found by the second review, where an arm then ran
    {"min_grounded_ratio": float("nan")}, {"min_grounded_ratio": float("-inf")},
    {"max_invalid_citations": float("inf")}, {**THRESHOLDS, "max_errors": float("nan")}], ids=repr)
def test_thresholds_that_are_not_a_table_of_numbers_leave_the_site_on_its_control(tmp_path, thresholds):
    switch = passed_switch(tmp_path / "runs")
    assert switch.fault is None
    broken = experiment_switch(settings(), base(), log=None, runs=tmp_path / "runs", thresholds=thresholds,
                               prices=PRICES)
    assert broken.fault and broken.choose("reader", FixedRandom(choices=(1,)), FixedClock(
        "2026-11-13T12:00:00+00:00")) is None


@pytest.mark.parametrize("broken", ["the folder is a file", "the note is a folder", "the note is not text",
                                    "figures that are a list", "figures that are text", "a line that is a list",
                                    "figures that are text numbers"])
def test_a_note_of_passes_that_cannot_be_read_leaves_the_site_on_its_control(tmp_path, broken):
    import json

    config, runs = base(), tmp_path / "runs"
    arm_id = arm_configs(Experiment.from_settings(settings()), config)["six"].config_id
    if broken == "the folder is a file":
        runs.write_text("x")
    else:
        runs.mkdir()
        note = runs / harness.PASSED_FILE
        if broken == "the note is a folder":
            note.mkdir()
        elif broken == "the note is not text":
            note.write_bytes(b"\xff\xfe\x00garbage")
        else:
            figures: Any = {"figures that are a list": [1, 2], "figures that are text": "all good",
                            "figures that are text numbers": {"grounded_ratio": "0.9", "invalid_citations": 0},
                            "a line that is a list": None}[broken]
            note.write_text(("[1, 2]" if figures is None else json.dumps({"config_id": arm_id, "figures": figures}))
                            + "\n")
    switch = experiment_switch(settings(), config, log=None, runs=runs, thresholds=THRESHOLDS, prices=PRICES)
    assert switch.fault and switch.state(FixedClock("2026-11-13T12:00:00+00:00")).fault
    assert switch.choose("reader", FixedRandom(choices=(1,)), FixedClock("2026-11-13T12:00:00+00:00")) is None


def test_types_is_the_desk_tests_own():
    assert types([{"type": "plan"}, {"type": "final"}]) == ["plan", "final"] and Q


def test_a_threshold_that_is_not_a_finite_number_holds_no_run_and_so_is_refused(tmp_path):
    """``nan`` and ``inf`` are valid TOML. Every comparison with ``nan`` is false, so a run held to it was held
    to nothing, noted as a pass, and an arm then ran on the strength of it."""
    run = harness.Run("an-id", {}, "2026-11-09T09:00:00+00:00", [],
                      {"cases": 3, "questions": 3, "grounded_ratio": 0.1, "invalid_citations": 9})
    for limit in (float("nan"), float("inf"), float("-inf"), True, "0.8"):
        with pytest.raises(ValueError, match="the threshold min_grounded_ratio is .*: a threshold is a finite number"):
            harness.check_thresholds(run, {"min_grounded_ratio": limit})
        with pytest.raises(ValueError, match="a threshold is a finite number"):
            harness.mark_passed(run, {"min_grounded_ratio": limit}, tmp_path)
    assert not (tmp_path / harness.PASSED_FILE).exists()
    assert harness.check_thresholds(run, {"min_grounded_ratio": 0.8})  # a real threshold: the run fails it
