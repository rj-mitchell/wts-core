"""The site's test questions through the package's evaluation harness: a live run, and the free replay."""

from __future__ import annotations

from pathlib import Path

from wts_core import eval as harness
from wts_core.testing import FixedClock
from wts_core.usage import PriceTable

from parks.evaluation import ParksEval
from parks.pipeline import configuration
from parks.site import LOADED_WORDS, VERIFIER, ParksSettings


def run_the_set(settings: ParksSettings, clock: FixedClock, fixtures: Path | None = None) -> harness.Run:
    site = ParksEval(settings, env={})
    config = configuration(settings, site.embedder, None)
    return harness.run(site, config.settings, config_id=config.config_id, pricing=PriceTable.from_settings(settings.usage),
                       clock=clock, max_cost_usd=float(settings.section("eval")["max_cost_usd"]),
                       record_fixtures=fixtures)


def test_a_run_asks_every_question_and_reports_what_the_checks_found(settings: ParksSettings,
                                                                     clock: FixedClock) -> None:
    run = run_the_set(settings, clock)
    dogs, hours, parking = run.results

    assert [r.outcome for r in run.results] == ["completed", "completed", "no_records"]
    assert (dogs.citations_total, dogs.citations_invalid, dogs.unsupported, dogs.loaded_words) == (5, 0, 0, 0)
    assert (hours.unsupported, hours.loaded_words) == (1, 1)  # the recording's one flawed sentence, marked
    assert dogs.spread == {"Alder Park": 1, "Birchfield Common": 1, "Canal Gardens": 1}  # group_of: by park
    # the site's own expectations (score): the park the question was read as about, and the parks in the evidence
    assert dogs.expect_met == {"park": True, "include": True}
    assert parking.expect_met == {"no_records": True, "park": True}  # the harness scores no_records itself
    # the cost: the reading and the briefing, each at its own model's prices
    assert dogs.cost_usd == round(0.000166 + 0.004218, 6)
    assert run.summary["questions"] == 3 and run.summary["errors"] == 0
    assert run.summary["expectations_met_rate"] == 1.0


def test_a_run_that_meets_the_sites_thresholds_is_noted_as_a_pass(settings: ParksSettings, clock: FixedClock,
                                                                  tmp_path: Path) -> None:
    thresholds = settings.section("eval")["thresholds"]
    run = run_the_set(settings, clock)

    assert harness.check_thresholds(run, thresholds) == []
    saved = harness.save(run, tmp_path / "runs")
    assert saved.name == f"20261113-120000-eval-{run.config_id}.json" and harness.load(saved).summary == run.summary
    harness.mark_passed(run, thresholds, tmp_path / "runs")
    assert harness.has_passed(tmp_path / "runs", run.config_id, thresholds)  # what the experiment guard reads
    # a stricter threshold than the set can meet fails, in a plain sentence
    (failure,) = harness.check_thresholds(run, {"max_loaded_words": 0})
    assert "1 is above the most allowed, 0" in failure


def test_recorded_briefings_replay_through_the_checks_free_and_never_weaker(settings: ParksSettings,
                                                                           clock: FixedClock, tmp_path: Path) -> None:
    run = run_the_set(settings, clock, fixtures=tmp_path / "fixtures")
    assert [r.fixture for r in run.results] == ["dogs", "opening-hours", None]  # only briefings that were written

    fixtures = [harness.load_fixture(path) for path in sorted((tmp_path / "fixtures").glob("*.jsonl"))]
    assert [f.name for f in fixtures] == ["dogs", "opening-hours"]
    differences = harness.replay(fixtures, VERIFIER, LOADED_WORDS)
    assert differences == []  # the checks say today exactly what they said when these were recorded
    harness.assert_never_weaker(differences)
