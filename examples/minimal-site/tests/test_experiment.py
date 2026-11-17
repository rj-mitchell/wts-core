"""An experiment on this site: two versions of the method side by side on real questions, on the impartiality
policy's conditions (docs/EXTENDING.md, "An experiment").

The site declares none in its own settings. An owner switches one on by writing ``[experiment]`` into the settings
(here, the installation's own ``data/settings.local.toml``), and that is what these tests do.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner
from wts_core.testing import FixedClock, FixedRandom
from wts_core.testing.models import ScriptedModel

from conftest import DOGS, ask, final_of, rows
from parks.app import Parks, build, create_app
from parks.cli import app
from parks.pipeline import MORE_EFFORT, Pipeline, embedder_from_settings, new_index
from parks.site import ParksSettings

TOKEN = {"Authorization": "Bearer a-long-random-value"}
EXPERIMENT = """
[experiment]
name = "more-effort"
start = 2026-11-10
end = 2026-11-24
decided_by = "any_check"

[[experiment.arms]]
name = "control"
share = 0.5

[[experiment.arms]]
name = "more"
share = 0.5
variant = "more-effort"

[eval]
runs_dir = "{runs}"
"""


@pytest.fixture
def declared(data_dir: Path, tmp_path: Path, load_site: Callable[..., ParksSettings]) -> ParksSettings:
    """The site's settings with the experiment declared in the installation's own file."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "settings.local.toml").write_text(EXPERIMENT.format(runs=tmp_path / "runs"))
    return load_site()


@pytest.fixture
def cli(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., tuple[int, str]]:
    monkeypatch.setenv("PARKS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("PARKS_CONFIG", raising=False)

    def invoke(*args: str) -> tuple[int, str]:
        result = CliRunner().invoke(app, list(args))
        return result.exit_code, result.output

    return invoke


def site(settings: ParksSettings, model: ScriptedModel, clock: FixedClock, *choices: int) -> Parks:
    return build(settings, model=model, clock=clock, random=FixedRandom(choices=choices),
                 env={"PARKS_CHECK_TOKEN": "a-long-random-value"})


def test_the_site_declares_no_experiment_and_says_nothing_of_one(parks: Parks, settings: ParksSettings,
                                                                 model: ScriptedModel, clock: FixedClock) -> None:
    assert parks.experiment.declared is False and parks.experiment.state(clock) is None
    client = TestClient(create_app(site(settings, model, clock)))
    assert client.get("/api/check", headers=TOKEN).json()["experiment"] is None


def test_an_arm_that_has_not_passed_the_evaluation_harness_does_not_go_live(
        declared: ParksSettings, model: ScriptedModel, clock: FixedClock, cli: Callable[..., tuple[int, str]]) -> None:
    """The site starts, on its control alone, and says why wherever the owner looks."""
    parks = site(declared, model, clock, 1, 1)
    assert parks.experiment.fault is not None and "the arm more (configuration " in parks.experiment.fault
    client = TestClient(create_app(parks))
    final_of(ask(client, DOGS))
    assert model.requests[-1].effort == "medium"  # the site as it stands
    assert rows(parks, "SELECT experiment, arm FROM wts_briefing_log") == [{"experiment": None, "arm": None}]
    said = client.get("/api/check", headers=TOKEN).json()["experiment"]
    assert (said["name"], said["running"], said["fault"]) == ("more-effort", False, True)
    code, page = cli("stats")
    assert code == 0 and "The experiment `more-effort` is declared and is not running" in page
    code, tripped = cli("stats", "--check")  # what runs after each update: it fails, so the owner is told
    assert code == 1 and "The experiment more-effort is declared and is not running: the arm more" in tripped


def test_once_the_arm_has_passed_each_briefing_is_given_a_version_by_chance(
        declared: ParksSettings, model: ScriptedModel, clock: FixedClock, cli: Callable[..., tuple[int, str]]) -> None:
    code, said = cli("eval", "run", "--arm", "more")  # the arm's own run, held to the site's thresholds
    assert code == 0 and "Passed: every threshold met by configuration" in said
    assert (declared.runs_dir / "passed.jsonl").exists()
    code, _ = cli("stats", "--check")
    assert code == 0  # nothing is wrong with the experiment now

    parks = site(declared, model, clock, 1, 0, 1)  # chance: the arm, the control, the arm
    assert parks.experiment.fault is None and parks.experiment.state(clock).running is True
    client = TestClient(create_app(parks))
    first, second, third = (final_of(ask(client, DOGS)) for _ in range(3))  # one visitor, one question, three times
    # the arm's briefing was written with the arm's variant; the control's as the site stands
    assert [r.effort for r in model.requests] == ["high", "medium"]
    # the answer cache is keyed on the version: the control was not served the arm's answer; the arm then was its own
    assert "cached" not in first and "cached" not in second and third["cached"] is True
    assert third["briefing_id"] == first["briefing_id"] != second["briefing_id"]
    # the version is recorded with each briefing, under an id of its own, with the settings behind it kept
    log = rows(parks, "SELECT experiment, arm, config_id, outcome FROM wts_briefing_log ORDER BY rowid")
    assert [(r["experiment"], r["arm"], r["outcome"]) for r in log] == [
        ("more-effort", "more", "completed"), ("more-effort", "control", "completed"), ("more-effort", "more", "cached")]
    assert log[0]["config_id"] == log[2]["config_id"] != log[1]["config_id"] != parks.config.config_id
    assert parks.log.config(log[0]["config_id"])["variant"] == MORE_EFFORT
    # a saved briefing's address shows what was originally shown, whichever version wrote it
    for briefing in (first, second):
        page = client.get(f"/b/{briefing['briefing_id']}")
        assert page.status_code == 200 and "Alder Park" in page.text
    said = client.get("/api/check", headers=TOKEN).json()["experiment"]
    assert (said["running"], said["fault"], said["decided_by"]) == (True, False, "any_check")
    # the nightly check's own question is never in an experiment
    ask(client, "When do the parks open and close?", headers=TOKEN)
    assert rows(parks, "SELECT kind, arm FROM wts_briefing_log ORDER BY rowid")[-1] == {"kind": "check", "arm": None}

    clock.set("2026-11-25T09:00:00+00:00")  # the day after its last: off, with no restart
    final_of(ask(client, "Which parks have a playground?"))
    assert rows(parks, "SELECT arm FROM wts_briefing_log ORDER BY rowid")[-1] == {"arm": None}
    assert "it ended on 2026-11-24" in parks.experiment.state(clock).why


def test_an_arm_cannot_turn_a_check_off_and_a_faulty_declaration_does_not_stop_the_site(
        data_dir: Path, load_site: Callable[..., ParksSettings], model: ScriptedModel, clock: FixedClock) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "settings.local.toml").write_text(
        EXPERIMENT.format(runs=data_dir / "runs").replace('variant = "more-effort"',
                                                         'variant = "more-effort"\nloaded_words = "off"'))
    parks = site(load_site(), model, clock, 1)
    assert "has loaded_words: every version passes the same checks" in (parks.experiment.fault or "")
    final_of(ask(TestClient(create_app(parks)), DOGS))  # and readers are served, by the site as it stands
    assert rows(parks, "SELECT arm FROM wts_briefing_log") == [{"arm": None}]


def test_the_pipeline_stops_at_a_variant_it_does_not_know(settings: ParksSettings, model: ScriptedModel) -> None:
    """A version recorded as one thing and written as another would make the experiment's figures a lie."""
    embedder = embedder_from_settings(settings)
    pipeline = Pipeline(settings, model=model, embedder=embedder, index=new_index(embedder))
    with pytest.raises(ValueError, match="no variant 'fewer-sources': it knows more-effort"):
        list(pipeline.write(DOGS, config={"variant": "fewer-sources"}))
    list(pipeline.write(DOGS, config={"variant": MORE_EFFORT, "model": "another-model"}))
    assert (model.requests[-1].effort, model.requests[-1].model) == ("high", "another-model")
