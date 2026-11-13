"""The evaluation commands (eval run, compare and replay), with a site that says what it is told: the scripted sites
of ``test_eval_run.py``, whose every figure is worked out by hand there. No model is called."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from checks_sites import COUNCILS
from cli_sites import Said, mounted, run
from eval_briefings import fixture
from test_eval_replay import GOLDEN
from test_eval_run import CONFIG, PRICES, SCRIPTS, Full, Keeping, Plain
from wts_core.checks import EVIDENCE_NOTES_STRICT, LoadedWords, Verifier
from wts_core.cli import eval_commands
from wts_core.eval import PASSED_FILE, checked, has_passed, load, save_fixture
from wts_core.testing import FixedClock
from wts_core.testing.models import recorded

MET = {"min_grounded_ratio": 0.8, "max_error_rate": 0.5}
STRICT = {"min_grounded_ratio": 0.95, "max_errors": 1}


class Desk:
    """A site's evaluation as its command line has it: its questions and pipeline (scripted), its configuration,
    prices and thresholds, its folder of runs, and the most it lets a run spend."""

    def __init__(self, tmp_path: Path, site: type[Plain] = Full, *, max_cost_usd: float | None = 2.0,
                 **more: Any) -> None:
        self.root = tmp_path
        self.clock = FixedClock("2026-11-13T12:00:00+00:00")
        self.site = site(self.clock)
        self.thresholds: dict[str, float] = dict(MET)
        self.built = 0
        self.app = mounted(eval_commands(self.eval_site, config=lambda: CONFIG,
                                         config_id=lambda config: f"cfg-{config['model']}", pricing=lambda: PRICES,
                                         thresholds=lambda: self.thresholds, runs=lambda: tmp_path / "runs",
                                         max_cost_usd=max_cost_usd, clock=self.clock, **more))

    def eval_site(self) -> Plain:
        self.built += 1
        return self.site

    def __call__(self, *args: Any) -> Said:
        return run(self.app, list(args), self.root)

    def runs(self) -> list[Path]:
        folder = self.root / "runs"
        return sorted(p for p in folder.glob("*-eval-*.json")) if folder.exists() else []


@pytest.fixture
def desk(tmp_path: Path) -> Desk:
    return Desk(tmp_path)


# ---- eval run ------------------------------------------------------------------------------------------------------


def test_a_run_that_meets_every_threshold_is_saved_and_noted_as_a_pass(desk):
    said = desk("eval", "run")
    [saved] = desk.runs()
    made = load(saved)
    assert said.exit_code == 0 and said.stderr == "" and saved.name == "20261113-120000-eval-cfg-big.json"
    lines = said.stdout.splitlines()
    # each question as it is done, then the figures, where it was saved, and the pass
    assert lines[:7] == ["wind: completed, $0.0299", "nhs: completed, $0.0120", "none: no_records, $0.0000",
                         "boom: error (RuntimeError), $0.0015", "declined: error (ErrorEvent), $0.0000",
                         "evidence: sources_only, $0.0000", "third: completed, $0.0180"]
    assert "Questions in the set: 7" in lines and "Questions asked: 7" in lines and "Errors: 2" in lines
    assert f"Grounded ratio (mean): {made.summary['grounded_ratio']:.6g}" in lines
    assert f"Saved as <root>/runs/{saved.name}" in lines
    assert lines[-1] == f"Passed: every threshold met by configuration cfg-big. Noted in <root>/runs/{PASSED_FILE}"
    assert [qid for qid, _ in desk.site.asked] == list(SCRIPTS) and desk.site.asked[0][1] == CONFIG
    assert has_passed(desk.root / "runs", "cfg-big", MET)
    noted = [json.loads(line) for line in (desk.root / "runs" / PASSED_FILE).read_text().splitlines()]
    assert len(noted) == 1 and noted[0]["config_id"] == "cfg-big" and noted[0]["thresholds"] == MET


def test_a_run_that_fails_a_threshold_says_why_and_is_not_noted(desk):
    desk.thresholds = dict(STRICT)
    said = desk("eval", "run")
    assert said.exit_code == 1 and len(desk.runs()) == 1  # saved all the same: it is what there is to read
    assert said.stdout.splitlines()[-3:] == [
        "The run did not pass (configuration cfg-big):",
        "- Grounded ratio (mean): 0.9 is below the least allowed, 0.95.",
        "- Errors: 2 is above the most allowed, 1.",
    ]
    assert not (desk.root / "runs" / PASSED_FILE).exists() and not has_passed(desk.root / "runs", "cfg-big")


def test_a_run_stops_at_its_limit_and_that_is_a_failure(desk):
    said = desk("eval", "run", "--max-cost", "0.03")  # the second question takes it past three cents
    assert said.exit_code == 1 and [qid for qid, _ in desk.site.asked] == ["wind", "nhs"]
    lines = said.stdout.splitlines()
    assert lines[:2] == ["wind: completed, $0.0299", "nhs: completed, $0.0120"] and "Questions not asked: 5" in lines
    assert lines[-2:] == ["The run did not pass (configuration cfg-big):",
                          "- The run stopped at its limit of $0.03: 5 questions not asked."]
    assert load(desk.runs()[0]).summary["not_run"] == 5 and not (desk.root / "runs" / PASSED_FILE).exists()


def test_no_run_starts_without_a_limit_on_what_it_may_spend(tmp_path):
    """The package has no figure of its own: the site gives one, or the owner says each time."""
    desk = Desk(tmp_path, max_cost_usd=None)
    refused = desk("eval", "run")
    assert refused.exit_code == 2 and desk.site.asked == [] and desk.built == 0 and desk.runs() == []
    said = "".join(refused.stderr.replace("│", "").split())
    assert "--max-cost" in refused.stderr and "norunstartswithoutalimit" in said
    assert desk("eval", "run", "--max-cost", "-1").exit_code == 2 and desk.site.asked == []
    assert desk("eval", "run", "--max-cost", "1.50").exit_code == 0 and len(desk.site.asked) == 7
    import inspect

    assert inspect.signature(eval_commands).parameters["max_cost_usd"].default is inspect.Parameter.empty


def test_part_of_the_set_can_be_asked_but_is_never_a_pass(desk):
    only = desk("eval", "run", "--only", "nhs", "--only", "wind")
    assert only.exit_code == 0 and [qid for qid, _ in desk.site.asked] == ["wind", "nhs"]  # in the set's order
    assert only.stdout.splitlines()[-1] == ("Not noted as a pass: 2 of the set's 7 questions were asked: a pass is "
                                            "for the whole set.")
    desk.clock.advance(60)
    limited = desk("eval", "run", "--limit", "1")
    assert limited.exit_code == 0 and "Questions asked: 1" in limited.stdout and len(desk.runs()) == 2
    assert not (desk.root / "runs" / PASSED_FILE).exists()
    unknown = desk("eval", "run", "--only", "potholes")
    assert unknown == Said(1, "", "no question with the id potholes\n", None) and len(desk.runs()) == 2


def test_a_run_held_to_no_thresholds_is_saved_but_has_passed_nothing(desk):
    desk.thresholds = {}
    said = desk("eval", "run")
    assert said.exit_code == 0 and len(desk.runs()) == 1
    assert said.stdout.splitlines()[-1] == ("Not noted as a pass: no thresholds were given: a run held to nothing "
                                            "has passed nothing.")
    desk.thresholds = {"min_groundedness": 0.9}
    wrong = desk("eval", "run")
    assert wrong.exit_code == 1 and wrong.stderr.startswith("unknown threshold 'min_groundedness': ")


def test_the_run_and_its_fixtures_go_where_they_are_sent(tmp_path):
    desk = Desk(tmp_path, Keeping)
    desk.thresholds = {}
    said = desk("eval", "run", "--out", tmp_path / "elsewhere", "--record-fixtures", tmp_path / "fixtures")
    assert said.exit_code == 0 and desk.runs() == [] and len(list((tmp_path / "elsewhere").glob("*.json"))) == 1
    assert sorted(p.name for p in (tmp_path / "fixtures").iterdir()) == ["bins.jsonl", "bins.report.json"]
    assert "Saved as <root>/elsewhere/" in said.stdout
    # and what was recorded replays clean with the same checks
    replaying = Desk(tmp_path / "again", verifier=lambda: COUNCILS.verifier, loaded_words=lambda: COUNCILS.loaded_words)
    assert replaying("eval", "replay", tmp_path / "fixtures") == Said(
        0, "The checks say of 1 recorded briefing exactly what they said when each was recorded.\n", "", None)


# ---- eval compare --------------------------------------------------------------------------------------------------


def test_compare_prints_two_saved_runs_side_by_side(desk):
    desk.thresholds = {}
    desk("eval", "run")
    desk.clock.advance(3600)
    desk.site.scripts = {**SCRIPTS, "boom": SCRIPTS["nhs"]}  # the change being tried mends one question
    desk("eval", "run")
    first, second = desk.runs()
    said = desk("eval", "compare", first, second)
    assert said.exit_code == 0 and said.stdout.startswith("# Evaluation: cfg-big compared with cfg-big\n")
    assert "| Errors | 2 | 1 | better |" in said.stdout and "## Question by question" in said.stdout
    from wts_core.eval import compare

    assert said.stdout == compare(load(first), load(second)).to_markdown()


def test_compare_refuses_what_is_not_a_run_of_the_harness(desk, tmp_path):
    desk.thresholds = {}
    desk("eval", "run")
    [saved] = desk.runs()
    theirs = tmp_path / "plans.json"
    theirs.write_text(json.dumps({"stage": "plans", "results": []}))
    said = desk("eval", "compare", saved, theirs)
    assert said.exit_code == 1 and said.stdout == ""
    assert said.stderr.startswith("<root>/plans.json is not a run saved by wts_core.eval (its stage is 'plans')")
    assert desk("eval", "compare", saved, tmp_path / "nowhere.json").exit_code == 2


# ---- eval replay ---------------------------------------------------------------------------------------------------


def replaying(tmp_path: Path, verifier: Verifier | None = None) -> Desk:
    return Desk(tmp_path, verifier=lambda: verifier or COUNCILS.verifier, loaded_words=lambda: COUNCILS.loaded_words,
                curled=COUNCILS.curled)


def recorded_briefings(folder: Path) -> Path:
    """Two recorded briefings with the report Where Councils Stand's checks make of each today."""
    from dataclasses import replace

    from wts_core.eval import load_fixture

    made = fixture()
    uncited = load_fixture(recorded("uncited_claim"), report=GOLDEN / "councils" / "uncited_claim.report.json")
    for f in (made, replace(uncited, report=None)):
        report = checked(f.blocks, f.documents, COUNCILS.verifier, COUNCILS.loaded_words, headings=f.headings,
                         curled=COUNCILS.curled)
        save_fixture(replace(f, report=report), folder)
    return folder


def test_replay_with_the_checks_unchanged_finds_no_difference(tmp_path):
    folder = recorded_briefings(tmp_path / "fixtures")
    assert replaying(tmp_path)("eval", "replay", folder) == Said(
        0, "The checks say of 2 recorded briefings exactly what they said when each was recorded.\n", "", None)


def test_replay_prints_every_difference_and_fails_when_the_checks_have_weakened(tmp_path):
    folder = recorded_briefings(tmp_path / "fixtures")
    excusing = Verifier(no_records=COUNCILS.no_records, honorifics=COUNCILS.honorifics,
                        evidence_notes=re.compile(EVIDENCE_NOTES_STRICT.pattern + r"|the first council", re.I))
    said = replaying(tmp_path, excusing)("eval", "replay", folder)
    assert said.exit_code == 1
    lines = said.stdout.splitlines()
    assert ("uncited_claim: status in 'This makes Northbridge the first council in the county to do so.' was "
            "'unsupported' and is now 'connective' (weaker)") in lines
    assert lines[-1].endswith(" in 2 recorded briefings: 3 weaker.") and len(lines) == int(lines[-1].split()[0]) + 1
    assert said.stderr == ("The checks on briefings have weakened: something that was flagged is no longer "
                           "flagged.\n")


def test_replay_that_only_finds_stricter_checks_passes_and_says_so(tmp_path):
    """A word added to the site's list: flagged now where it was not. For a person to read, not a failure."""
    folder = recorded_briefings(tmp_path / "fixtures")
    longer = LoadedWords(re.compile(COUNCILS.loaded.pattern + r"|\bscrap\b", re.I))
    desk = Desk(tmp_path, verifier=lambda: COUNCILS.verifier, loaded_words=lambda: longer, curled=COUNCILS.curled)
    said = desk("eval", "replay", folder)
    assert said.exit_code == 0 and said.stderr == ""
    assert ("made-up: loaded_words in 'It also resolved to scrap them next year.' was None and is now 'scrap' "
            "(stricter)") in said.stdout.splitlines()
    assert said.stdout.splitlines()[-1] == "2 differences in 2 recorded briefings: 0 weaker."


def test_replay_of_a_folder_with_nothing_to_replay_is_said(tmp_path):
    desk = replaying(tmp_path)
    (tmp_path / "empty").mkdir()
    assert desk("eval", "replay", tmp_path / "empty") == Said(
        1, "", "There are no recorded briefings (*.jsonl) in <root>/empty.\n", None)
    save_fixture(fixture("no-report"), tmp_path / "bare")  # recorded, but nobody kept what the checks said of it
    said = desk("eval", "replay", tmp_path / "bare")
    assert said.exit_code == 1 and said.stderr.startswith("the fixture 'no-report' has no recorded report")
    assert desk("eval", "replay", tmp_path / "nowhere").exit_code == 2


def test_replay_is_offered_only_where_the_site_gives_its_checks(desk):
    assert desk("eval", "replay", desk.root).exit_code == 2 and "No such command" in desk("eval", "replay", ".").stderr


# ---- where the commands sit ----------------------------------------------------------------------------------------


def test_the_commands_join_a_group_the_site_already_has(tmp_path):
    """Where MPs Stand has an ``eval`` group of its own: the package's commands are added to it."""
    import typer

    clock = FixedClock()
    site = Plain(clock)
    app = typer.Typer(add_completion=False, no_args_is_help=True)
    own = typer.Typer(no_args_is_help=True, help="Score the site against the test set (eval/questions.toml).")
    app.add_typer(own, name="eval")

    @own.command("plans")
    def plans() -> None:
        typer.echo("the site's own")

    own.add_typer(eval_commands(lambda: site, config=lambda: CONFIG, config_id=lambda config: "c",
                                pricing=lambda: PRICES, thresholds=dict, runs=lambda: tmp_path / "runs",
                                max_cost_usd=1.0, group=None, clock=clock))
    assert run(app, ["eval", "plans"], tmp_path).stdout == "the site's own\n"
    assert run(app, ["eval", "run", "--limit", "1"], tmp_path).exit_code == 0 and len(site.asked) == 1


def test_nothing_of_the_sites_is_built_until_a_command_runs(desk):
    assert desk("eval", "--help").exit_code == 0 and desk("eval", "run", "--help").exit_code == 0
    assert desk.built == 0 and desk.site.asked == []
