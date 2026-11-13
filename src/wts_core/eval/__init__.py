"""The evaluation harness: how a change is measured before it ships (docs/ARCHITECTURE.md, section 6).

Two halves.

**Replay, free and offline** (``replay``). A fixture is a recorded briefing: the question, the documents the model
was given, the blocks it returned and the report the checks made. ``replay`` runs the checks over fixtures again
and names every difference, each as stricter, weaker or other; ``assert_never_weaker`` is CI's guard on "the checks
on briefings never weaken". ``checked`` is the one function that turns a model's blocks and documents into a
checked report, in the order every site's pipeline runs the checks.

**Live runs, on the site's data** (``run``, ``compare``). The site supplies an ``EvalSite``: its questions
(``load_cases`` reads each site's ``eval/questions.toml`` as it stands), a way to ask one, and the group a source
belongs to. ``run`` reports for each question and overall: what the checks found, a judged score where the site
has one, the spread of sources by group, the time to the first word and to the end, and the cost; it can stop at a
budget. ``compare`` sets two runs side by side; ``save`` and ``load`` keep them under the site's ``eval/runs/``;
``check_thresholds`` holds a run to the site's thresholds, and ``mark_passed`` and ``has_passed`` are the note the
experiment guard reads (ADR 0012).

Nothing here calls a model, reads the environment or imports an outside library. The clock, the prices and the
configuration's id are passed in.
"""

from __future__ import annotations

from wts_core.eval.cases import Case, Judgement, load_cases, load_judgements, read_as_if
from wts_core.eval.compare import (
    PASSED_FILE,
    Change,
    Comparison,
    Verdict,
    check_thresholds,
    compare,
    has_passed,
    load,
    mark_passed,
    passed_line,
    save,
)
from wts_core.eval.replay import (
    Difference,
    Fixture,
    Kind,
    assert_never_weaker,
    checked,
    load_fixture,
    replay,
    save_fixture,
)
from wts_core.eval.run import (
    FIGURES,
    CaseOutcome,
    CaseResult,
    EvalSite,
    Judges,
    Recording,
    Records,
    Run,
    Scores,
    percentile,
    run,
    summarise,
)

__all__ = [
    "FIGURES",
    "PASSED_FILE",
    "Case",
    "CaseOutcome",
    "CaseResult",
    "Change",
    "Comparison",
    "Difference",
    "EvalSite",
    "Fixture",
    "Judgement",
    "Judges",
    "Kind",
    "Recording",
    "Records",
    "Run",
    "Scores",
    "Verdict",
    "assert_never_weaker",
    "check_thresholds",
    "checked",
    "compare",
    "has_passed",
    "load",
    "load_cases",
    "load_fixture",
    "load_judgements",
    "mark_passed",
    "passed_line",
    "percentile",
    "read_as_if",
    "replay",
    "run",
    "save",
    "save_fixture",
    "summarise",
]
