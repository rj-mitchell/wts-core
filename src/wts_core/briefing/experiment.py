"""Live experiments: versions of the method tried side by side on real questions, on the impartiality policy's
conditions (principle 6; ADR 0012).

A site declares one experiment at a time, in its settings::

    [experiment]
    name = "six-sources"
    start = 2026-12-01            # the first day it runs (UTC)
    end = 2026-12-14              # and the last
    decided_by = "any_check"      # the rate that decides it: one of observe.PROPORTIONS

    [[experiment.arms]]           # the first arm is the control: the site as it stands, and it changes nothing
    name = "control"
    share = 0.5

    [[experiment.arms]]
    name = "six"
    share = 0.5
    variant = "six-sources"       # a word of the site's own, which its pipeline reads
    # model = "…"                 # or another model, which needs its prices like any other
    # instructions = "…"          # or another version of the site's instructions

``experiment_switch`` reads and checks it when the site starts, and the briefing desk is given the switch
(``DeskParts.desk(config, experiment=switch, …)``). The policy's conditions, and where each is kept:

1. Every version passes the same checks and the same balance requirements. An arm may change the model, the
   version of the instructions and one variant word, and nothing else: any other key in an arm is refused, and a
   key that names a check, the loaded words, a threshold or the balance of sources is refused as such. An arm
   that changes anything must have passed the evaluation harness, on the whole of the site's test set, for
   exactly its configuration, under the site's thresholds as they stand now (``eval.has_passed``): the same
   thresholds for every arm, since an arm cannot bring its own. And while an experiment runs, the desk shows no
   briefing whose report lacks any check's figure (``desk.CHECKED``): a pipeline that skipped a check for one
   arm would fail every briefing of that arm.
2. A version is chosen by chance for each briefing, never for each reader. The desk asks ``ports.Random`` once
   a question, with the arms' shares. Nothing about the reader goes into the choice: not the visitor's code, an
   account, a cookie, an address or the question. The same reader asking twice may be given both versions.
3. The version used is recorded with each briefing: ``experiment``, ``arm`` and the arm's ``config_id`` on
   the briefing's record, with the settings behind the id kept in ``wts_configs``.
4. A saved briefing's address always shows what was originally shown: a briefing is saved as it was sent, and
   nothing here is consulted when it is shown again.
5. The answer cache is keyed on the version: the desk adds the experiment and the arm to the site's key, so
   no version is ever served another's answer.
6. Declared in settings, with a name, the versions and their shares, the first and last day, and the rate that
   decides it. Outside its dates it is off. The statistics report each arm side by side and say when there are
   too few briefings to tell; they never name a winner.

An experiment that cannot run does not stop the site. Anything wrong with the declaration, and any arm with
no pass noted, leaves the site on its control alone, exactly as if there were no experiment: an error is logged
naming what is wrong, and ``ExperimentSwitch.state`` says so to the check route and to the statistics, whose
``--check`` then fails so that the owner is told. Readers' briefings never depend on an experiment being right.

The nightly check's question and the evaluation harness's are never in an experiment.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from wts_core.observe.figures import PROPORTIONS
from wts_core.observe.log import SqliteBriefingLog, briefing_config
from wts_core.ports import SYSTEM_CLOCK, BriefingConfig, Clock, ExperimentState, Random, UnknownModel
from wts_core.settings import Settings, SettingsError
from wts_core.usage.pricing import PriceTable

__all__ = ["ARM_CHANGES", "Arm", "Experiment", "ExperimentSwitch", "arm_configs", "experiment_switch",
           "unpriced_arms"]

log = logging.getLogger(__name__)

# what an arm may change, and nothing else
ARM_CHANGES = ("model", "instructions", "variant")
_ARM_KEYS = ("name", "share", *ARM_CHANGES)
_KEYS = ("name", "arms", "start", "end", "decided_by")
# a name is written into records, cache keys, file names and the check's answer: plain, and short
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
# a key that would touch what every version must share: said as that, so the owner is not left guessing
_A_CHECK = re.compile(r"verif|check|loaded|word|neutral|spell|quot|citation|threshold|balance|group|spread|rules|"
                      r"ground|support", re.IGNORECASE)
_SAME_CHECKS = ("every version passes the same checks and the same balance requirements (the impartiality policy, "
                "principle 6), so an arm cannot change them")


@dataclass(frozen=True)
class Arm:
    """One version in an experiment: its name, its share of briefings, and what it changes. None leaves a thing
    as the site has it."""

    name: str
    share: float
    model: str | None = None
    instructions: str | None = None  # the version of the site's instructions
    variant: str | None = None  # a word of the site's own, which its pipeline reads

    @property
    def changes(self) -> dict[str, str]:
        return {key: value for key in ARM_CHANGES if (value := getattr(self, key)) is not None}


@dataclass(frozen=True)
class Experiment:
    """An experiment as a site declares it. The first arm is the control."""

    name: str
    arms: tuple[Arm, ...]
    start: date
    end: date
    decided_by: str

    @property
    def control(self) -> Arm:
        return self.arms[0]

    def on(self, day: date) -> bool:
        """Whether ``day`` (UTC) is within its dates: from the first day to the last, both included."""
        return self.start <= day <= self.end

    @classmethod
    def from_settings(cls, settings: Settings, *, section: str = "experiment") -> Experiment | None:
        """The experiment a site's settings declare, checked; None when they declare none. Everything wrong with
        the declaration is said in one ``SettingsError`` that names the file and each key.

        ``experiment_switch`` is what a site calls: it catches this error and leaves the site on its control. A
        site that would sooner not start with a faulty declaration calls this itself, first."""
        declared = settings.raw.get(section)
        if declared is None or declared == {}:
            return None
        problems: list[str] = []
        if not isinstance(declared, Mapping):
            problems.append(f"[{section}] must be one table: one experiment at a time (the impartiality policy), so "
                            f"not a list of them ([[{section}]])")
            raise _wrong(settings, problems)
        unknown = sorted(set(declared) - set(_KEYS))
        if unknown:
            problems.append(f"[{section}] has {', '.join(unknown)}, which an experiment does not have: its keys are "
                            + ", ".join(_KEYS))
        missing = [key for key in _KEYS if key not in declared]
        if missing:
            problems.append(f"[{section}] needs {', '.join(missing)}: an experiment is declared with a name, its "
                            "arms and their shares, its first and last day, and the rate that decides it")
        name = _name(declared.get("name"), f"[{section}] name", problems) if "name" in declared else ""
        start = _day(declared.get("start"), f"[{section}] start", problems) if "start" in declared else None
        end = _day(declared.get("end"), f"[{section}] end", problems) if "end" in declared else None
        if start is not None and end is not None and end < start:
            problems.append(f"[{section}] end ({end.isoformat()}) is before start ({start.isoformat()}): the last "
                            "day cannot come before the first")
        decided_by = declared.get("decided_by")
        if "decided_by" in declared and decided_by not in PROPORTIONS:
            problems.append(f"[{section}] decided_by is {decided_by!r}: the rates the statistics can test between "
                            "arms are " + ", ".join(PROPORTIONS))
        arms = _arms(declared.get("arms"), section, problems) if "arms" in declared else ()
        if problems or start is None or end is None:
            raise _wrong(settings, problems)
        return cls(name=name, arms=arms, start=start, end=end, decided_by=str(decided_by))


def _wrong(settings: Settings, problems: list[str]) -> SettingsError:
    count = "1 thing" if len(problems) == 1 else f"{len(problems)} things"
    return SettingsError(f"{settings.files}: the experiment cannot run: {count} missing or wrong.\n"
                         + "\n".join(f"  - {problem}" for problem in problems), problems=problems)


def _name(value: Any, where: str, problems: list[str]) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        problems.append(f"{where} is {value!r}: a name is lower-case letters, digits, hyphens and underscores, "
                        "beginning with a letter or a digit, 40 characters at most")
        return ""
    return value


def _day(value: Any, where: str, problems: list[str]) -> date | None:
    if isinstance(value, datetime):  # a date with a time is not a day: the experiment runs by whole days
        value = None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        problems.append(f"{where} must be a day, such as 2026-12-01 (the experiment runs from its first day to "
                        "its last, both included, in UTC)")
        return None


def _arms(declared: Any, section: str, problems: list[str]) -> tuple[Arm, ...]:
    where = f"[[{section}.arms]]"
    if not isinstance(declared, list) or len(declared) < 2 or not all(isinstance(a, Mapping) for a in declared):
        problems.append(f"{where}: an experiment has two arms or more, each a table with a name and a share; the "
                        "first is the control")
        return ()
    arms: list[Arm] = []
    for number, table in enumerate(declared, start=1):
        called = table.get("name")
        said = f"{where} {called!r}" if isinstance(called, str) else f"{where} number {number}"
        for key in sorted(set(table) - set(_ARM_KEYS)):
            if _A_CHECK.search(str(key)):
                problems.append(f"{said} has {key}: {_SAME_CHECKS}")
            else:
                problems.append(f"{said} has {key}, which is not something an arm can change: an arm may change "
                                + ", ".join(ARM_CHANGES) + ", and nothing else")
        name = _name(called, f"{said} name", problems) if "name" in table else ""
        if "name" not in table:
            problems.append(f"{said} needs a name")
        share = table.get("share")
        # (compared and never converted: a whole number too large to be a float is simply not below 1)
        if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 < share < 1:
            problems.append(f"{said} share is {share!r}: a share is a number above 0 and below 1, the part of "
                            "briefings the arm is given")
            share = 0.0
        changes: dict[str, str] = {}
        for key in ARM_CHANGES:
            if key in table:
                if not isinstance(table[key], str) or not table[key].strip():
                    problems.append(f"{said} {key} must be text")
                elif key == "variant":
                    changes[key] = _name(table[key], f"{said} variant", problems)
                else:
                    changes[key] = table[key].strip()
        arms.append(Arm(name=name, share=float(share), **changes))
    names = [arm.name for arm in arms if arm.name]
    if len(set(names)) != len(names):
        problems.append(f"{where}: two arms have the same name")
    if arms[0].changes:
        problems.append(f"{where}: the first arm is the control, the site as it stands, and changes nothing: "
                        f"{arms[0].name!r} changes {', '.join(arms[0].changes)}")
    for arm in arms[1:]:
        if not arm.changes:
            problems.append(f"{where} {arm.name!r} changes nothing: only the first arm, the control, is the site "
                            "as it stands. An arm changes " + ", ".join(ARM_CHANGES))
    total = sum(arm.share for arm in arms)
    if all(arm.share for arm in arms) and abs(total - 1.0) > 1e-6:
        problems.append(f"{where}: the shares must add up to 1, and they add up to {total:g}")
    return tuple(arms)


def _arm_config(config: BriefingConfig, experiment: Experiment, arm: Arm,
                log: SqliteBriefingLog | None) -> BriefingConfig:
    """The site's configuration as one arm runs it: the same in everything the arm does not change, with the
    experiment and the arm named in it, and so with an id of its own."""
    named = {"model", "parse_model", "instructions", "package_version", "site_version", "experiment", "arm",
             "variant", "config_id"}
    return briefing_config(
        log=log, model=arm.model or config.model, parse_model=config.parse_model,
        instructions=arm.instructions or config.instructions, site_version=config.site_version,
        experiment=experiment.name, arm=arm.name, variant=arm.variant,
        also={key: value for key, value in config.settings.items() if key not in named})


def arm_configs(experiment: Experiment, config: BriefingConfig, *,
                log: SqliteBriefingLog | None = None) -> dict[str, BriefingConfig]:
    """The configuration of each arm, by the arm's name, made from the site's own (``config``): what an
    evaluation run of an arm is made with and filed under (``eval_commands(arms=…)``), and what the desk writes
    into the record of each briefing the arm is given. ``log`` keeps the settings behind each id in
    ``wts_configs``; None only works the ids out."""
    return {arm.name: _arm_config(config, experiment, arm, log) for arm in experiment.arms}


class ExperimentSwitch:
    """A site's experiment as it stands on this start: declared or not, able to run or not, and why not.

    Made by ``experiment_switch`` and given to the briefing desk, which asks ``choose`` for each question. Its
    ``state`` is what the check route and the statistics say of the experiment."""

    def __init__(self, experiment: Experiment | None = None, configs: Mapping[str, BriefingConfig] | None = None,
                 *, fault: str | None = None, name: str = "") -> None:
        self.experiment = experiment
        self.configs: dict[str, BriefingConfig] = dict(configs or {})
        self.fault = fault  # why it cannot run whatever the date; None when it can, or when none is declared
        self._name = experiment.name if experiment is not None else name

    @property
    def declared(self) -> bool:
        """Whether the site's settings declare an experiment at all, sound or not."""
        return self.experiment is not None or self.fault is not None

    def choose(self, kind: str, random: Random, clock: Clock = SYSTEM_CLOCK) -> BriefingConfig | None:
        """The arm's configuration for one briefing, by chance; None when the briefing is in no experiment (none
        is declared, it cannot run, today is outside its dates, or the question is not a reader's).

        What goes in is the kind of question, chance and the date. Nothing about the reader is asked for, and
        there is nowhere to give it: the choice is made afresh for each briefing."""
        experiment = self.experiment
        if experiment is None or self.fault is not None or kind != "reader" \
                or not experiment.on(clock.now().date()):
            return None
        arm = random.choice(experiment.arms, [a.share for a in experiment.arms])
        return self.configs[arm.name]

    def state(self, clock: Clock = SYSTEM_CLOCK) -> ExperimentState | None:
        """What to say of the experiment now, for the owner: None when none is declared."""
        experiment = self.experiment
        if experiment is None:
            return None if self.fault is None else ExperimentState(name=self._name, running=False, fault=True,
                                                                   why=self.fault)
        today = clock.now().date()
        facts: dict[str, Any] = dict(start=experiment.start.isoformat(), end=experiment.end.isoformat(),
                                     decided_by=experiment.decided_by, arms=tuple(a.name for a in experiment.arms),
                                     shares=tuple(a.share for a in experiment.arms))
        if self.fault is not None:
            return ExperimentState(name=experiment.name, running=False, fault=True, why=self.fault, **facts)
        if today < experiment.start:
            return ExperimentState(name=experiment.name, running=False, fault=False,
                                   why=f"it has not started: its first day is {experiment.start.isoformat()}", **facts)
        if today > experiment.end:
            return ExperimentState(
                name=experiment.name, running=False, fault=False,
                why=f"it ended on {experiment.end.isoformat()}: release the version chosen (or keep the site as it "
                    "is), record the decision in the site's DECISIONS.md and take [experiment] out of the settings",
                **facts)
        return ExperimentState(name=experiment.name, running=True, fault=False, why="", **facts)


def experiment_switch(settings: Settings, config: BriefingConfig, *, log: SqliteBriefingLog | None, runs: Path,
                      thresholds: Mapping[str, float], prices: PriceTable | None = None,
                      section: str = "experiment") -> ExperimentSwitch:
    """Read and check the experiment a site's settings declare, when the site starts, and give the switch the
    briefing desk asks (``DeskParts.desk(config, experiment=…)``). With no ``[experiment]`` the switch is off
    and says nothing.

    ``config`` is the site's own configuration (``observe.briefing_config``): each arm's is made from it.
    ``log`` is the site's record of briefings, where the settings behind each arm's id are kept (None: nowhere,
    as for the site's own). ``runs`` is the folder the site's evaluation runs are noted in (``passed.jsonl``:
    on a server, the folder on the data volume) and ``thresholds`` its evaluation thresholds as they stand now.
    ``prices`` is the site's price table (``usage.PriceTable``): an arm that names a model needs it, and the
    model must have a table of its own under ``[usage.models]``. A model with none is costed at the base
    prices, whatever it really costs, and the spending caps would count an arm's briefings at the wrong price
    (an arm naming a dearer model on a site with only its own model's table was counted at half).

    It never stops the site. If the declaration is wrong in any way, an arm's model has no prices of its
    own, an arm that changes something has no pass noted for exactly its configuration under those thresholds,
    or anything at all goes wrong in finding that out (thresholds that are not numbers, a note of passes that
    cannot be read), the experiment does not run: the site is on its control alone, as if nothing were declared,
    an error is logged that names what is wrong (the arm, where it is an arm), and the switch's ``state`` says
    so."""
    declared = settings.raw.get(section)
    name = declared.get("name") if isinstance(declared, Mapping) else None
    name = name if isinstance(name, str) and _NAME.fullmatch(name) else ""
    try:
        return _switch(settings, config, log=log, runs=runs, thresholds=thresholds, prices=prices, section=section)
    except SettingsError as exc:
        return _off(name, str(exc))
    except Exception as exc:  # whatever it is, readers' briefings do not depend on an experiment being right
        return _off(name, f"it could not be read and checked ({type(exc).__name__}: {str(exc)[:300]}): mend what "
                          "it names, in the settings or in the folder of evaluation runs")


def _switch(settings: Settings, config: BriefingConfig, *, log: SqliteBriefingLog | None, runs: Path,
            thresholds: Mapping[str, float], prices: PriceTable | None, section: str) -> ExperimentSwitch:
    """``experiment_switch``, where it may raise: its caller turns whatever is raised into the off state."""
    experiment = Experiment.from_settings(settings, section=section)
    if experiment is None:
        return ExperimentSwitch()
    from wts_core.eval.compare import has_passed  # here: the briefing desk itself needs nothing of the harness

    if not thresholds:
        return _off(experiment.name, "the site has no evaluation thresholds, so no arm can be shown to have passed "
                                     "them: set [eval.thresholds] and make an evaluation run of each arm",
                    experiment)
    if not isinstance(thresholds, Mapping) or not all(_a_number(limit) for limit in thresholds.values()):
        # (nan and inf are numbers to TOML, and hold a run to nothing: every comparison with them is false)
        return _off(experiment.name, "the site's evaluation thresholds are not a table of finite numbers, so no "
                                     "arm can be shown to have passed them: mend [eval.thresholds]", experiment)
    unpriced = unpriced_arms(experiment, prices)
    if unpriced:
        return _off(experiment.name, unpriced, experiment)
    configs = arm_configs(experiment, config)  # the ids only: nothing is kept until the experiment may run
    not_passed: list[str] = []
    for arm in experiment.arms[1:]:
        try:
            passed = has_passed(runs, configs[arm.name].config_id, thresholds)
        except (ValueError, OSError) as exc:  # the note of passes cannot be read
            return _off(experiment.name, f"the passes noted in {runs} could not be read ({exc})", experiment)
        if not passed:
            not_passed.append(f"{arm.name} (configuration {configs[arm.name].config_id})")
    if not_passed:
        several = len(not_passed) > 1
        return _off(
            experiment.name,
            f"the arm{'s' if several else ''} {', '.join(not_passed)} {'have' if several else 'has'} no pass noted "
            f"in {runs} under the site's thresholds as they stand: a version that has not passed the evaluation "
            "harness never goes live. Make an evaluation run of the arm (eval run --arm), on the whole test set; "
            "a pass made before the thresholds, the package or the site's version changed does not count",
            experiment)
    return ExperimentSwitch(experiment, arm_configs(experiment, config, log=log))


def _a_number(value: Any) -> bool:
    """Whether a threshold is a number a figure can be held to: whole or not, and finite."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return isinstance(value, int) or math.isfinite(value)


def unpriced_arms(experiment: Experiment, prices: PriceTable | None) -> str:
    """Why an experiment's arms cannot be costed, in words for the owner; empty when they can. An arm that names
    a model needs the site's price table to have a table of that model's own (its name, or a shorter name it
    begins with, under ``[usage.models]``): the base prices are the site's own model's, not this one's."""
    models = {arm.name: arm.model for arm in experiment.arms if arm.model}
    if not models:
        return ""
    if prices is None:
        return ("the arm " + ", ".join(f"{arm} names the model {model}" for arm, model in models.items())
                + ", and the site gave no price table to check it against (experiment_switch(..., prices=…)): an "
                  "arm's model must have prices of its own, or the spending caps would count it at the wrong price")
    without: list[str] = []
    for arm, model in models.items():
        try:
            prices.require([model], base_counts=False)
        except UnknownModel:
            without.append(f"{arm} names the model {model}")
    if not without:
        return ""
    return ("the arm " + ", ".join(without) + ', which has no price table of its own: add [usage.models."<name>"] '
            "with its prices to the site's settings. Without one its briefings would be costed at the base "
            "prices, and the spending caps would count them at the wrong price")


def _off(name: str, why: str, experiment: Experiment | None = None) -> ExperimentSwitch:
    log.error("the experiment %s is declared and is not running: the site is on its control alone. %s",
              repr(name) if name else "in the settings", why)
    return ExperimentSwitch(experiment, fault=why, name=name)
