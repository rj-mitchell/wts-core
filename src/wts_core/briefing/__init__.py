"""A briefing, from question to last word: the desk that runs the flow every site shares, the parts it is built
from, the stage timings, and the streamer.

A site makes the parts and the desk once, when it starts (``desk_parts``, then ``DeskParts.desk``), and its route
builds an ``Ask`` and sends ``sse(desk.handle(ask))``. The pipeline, the sources, the request and every word a
reader sees stay the site's (ADR 0009); the desk writes one record of how each briefing went (ADR 0012), through
``ports.BriefingLog``.

A site may try versions of its method side by side on real questions, on the impartiality policy's conditions:
``experiment_switch`` reads the experiment its settings declare, and the desk does the rest (``experiment``).
"""

from wts_core.briefing.build import DeskParts, DeskSettings, desk_parts, desk_settings
from wts_core.briefing.desk import CHECKED, Ask, BriefingDesk, Event, Hooks, TooManyRequests
from wts_core.briefing.experiment import (
    ARM_CHANGES,
    Arm,
    Experiment,
    ExperimentSwitch,
    arm_configs,
    experiment_switch,
    unpriced_arms,
)
from wts_core.briefing.stages import Stage, Stages, current_config, current_stages
from wts_core.briefing.stream import KEEP_ALIVE_SECONDS, sse

__all__ = [
    "ARM_CHANGES",
    "CHECKED",
    "KEEP_ALIVE_SECONDS",
    "Arm",
    "Ask",
    "BriefingDesk",
    "DeskParts",
    "DeskSettings",
    "Event",
    "Experiment",
    "ExperimentSwitch",
    "Hooks",
    "Stage",
    "Stages",
    "TooManyRequests",
    "arm_configs",
    "current_config",
    "current_stages",
    "desk_parts",
    "desk_settings",
    "experiment_switch",
    "sse",
    "unpriced_arms",
]
