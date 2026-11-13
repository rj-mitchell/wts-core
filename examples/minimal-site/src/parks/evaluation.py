"""This site's test questions, as the package's evaluation harness asks for them (``wts_core.eval.EvalSite``).

``parks eval run`` asks each question in ``eval/questions.toml`` of the site's real pipeline and reports what the
checks found, the spread of sources by park, the time taken and the cost. ``parks eval replay`` runs the checks
again over briefings recorded by an earlier run, free and offline: how a change to the checks is measured before
it ships.

The harness looks for two optional methods, and this site has both: ``score`` (were the site's own expectations
met?) and ``recording`` (what the model was given and what it wrote, to keep as a fixture).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from wts_core.eval import Case, Recording, load_cases
from wts_core.events import ReaderEvent
from wts_core.ports import ModelClient

from parks.pipeline import Pipeline, embedder_from_settings, model_from_settings, new_index, scripted_model
from parks.site import ROOT, ParksSettings

__all__ = ["QUESTIONS", "RUNS", "ParksEval"]

QUESTIONS = ROOT / "eval" / "questions.toml"
RUNS = ROOT / "eval" / "runs"  # where runs are saved, and the note of each pass (passed.jsonl)


class ParksEval:
    """Where Parks Stand, as the evaluation harness sees it."""

    def __init__(self, settings: ParksSettings, env: Mapping[str, str] | None = None,
                 questions: Path = QUESTIONS) -> None:
        self.settings = settings
        self.questions = questions
        self.embedder = embedder_from_settings(settings)
        self._scripted = str(settings.answer["provider"]).strip().lower() == "scripted"
        # a real model is made once and kept; a scripted one is made for each question, from its own recording
        self._model = None if self._scripted else model_from_settings(settings, env)
        self._kept: dict[str, Recording] = {}

    def cases(self) -> Sequence[Case]:
        return load_cases(self.questions)

    def _model_for(self, case: Case) -> ModelClient | None:
        if self._scripted:
            return scripted_model(self.settings.recordings_dir / f"{case.id}.jsonl")
        return self._model

    def ask(self, case: Case, config: Mapping[str, Any]) -> Iterator[ReaderEvent]:
        """Ask one question of the pipeline itself: never through the briefing desk, so never from the answer
        cache. ``config`` is the configuration this site was built from (``parks.pipeline.configuration``)."""
        pipeline = Pipeline(self.settings, model=self._model_for(case), embedder=self.embedder,
                            index=new_index(self.embedder))
        self._kept.pop(case.id, None)

        def keep(documents: Any, blocks: Any) -> None:
            self._kept[case.id] = Recording(documents, blocks)

        return cast(Iterator[ReaderEvent], pipeline.write(case.question, keep=keep))

    def group_of(self, source: Mapping[str, Any]) -> str:
        """The group a source belongs to on this site: its park."""
        return str(source.get("park") or "")

    def score(self, case: Case, plan: Mapping[str, Any] | None,
              sources: Sequence[Mapping[str, Any]]) -> Mapping[str, bool]:
        """This site's own expectations of a question, each met or not: the park it was read as being about, and
        whether the evidence holds a minute from every park the question's ``include`` names."""
        met: dict[str, bool] = {}
        if "park" in case.expect:
            met["park"] = ((plan or {}).get("park") or "") == case.expect["park"]
        if "include" in case.expect:
            met["include"] = set(case.expect["include"]) <= {s.get("park") for s in sources}
        return met

    def recording(self, case: Case) -> Recording | None:
        """What the model was given and what it wrote for the question just asked, where a briefing was written."""
        return self._kept.get(case.id)
