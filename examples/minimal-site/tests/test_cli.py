"""The owner's commands: the site's own, and the package's shared ones under the site's own words."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner
from wts_core.testing.models import ScriptedModel

from conftest import DOGS, HOURS, ask, final_of
from parks.app import build, create_app
from parks.cli import app
from parks.site import ParksSettings

type Run = Callable[..., str]


@pytest.fixture
def run(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Run:
    """Run ``parks …`` as the owner would, against the temporary data folder."""
    monkeypatch.setenv("PARKS_DATA_DIR", str(data_dir))
    for name in ("PARKS_B2_BUCKET", "PARKS_B2_KEY_ID", "PARKS_B2_APPLICATION_KEY", "PARKS_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    runner = CliRunner()

    def invoke(*args: str, code: int = 0) -> str:
        result = runner.invoke(app, list(args))
        assert result.exit_code == code, result.output
        return result.output

    return invoke


@pytest.fixture
def site(settings: ParksSettings, model: ScriptedModel) -> TestClient:
    """The running site, on the real clock: the commands read the same state database."""
    return TestClient(create_app(build(settings, model=model, env={})))


def test_the_sites_own_command_lists_its_record(run: Run) -> None:
    listed = run("minutes", "--park", "Alder Park").splitlines()
    assert listed == ["2026-03-10  Alder Park: item 4, Dogs in the park", "2026-05-12  Alder Park: item 6, Opening hours",
                      "2026-09-08  Alder Park: item 3, Playground"]


def test_a_new_site_has_nothing_to_back_up(run: Run) -> None:
    assert run("backup") == "There is no state database yet, so there is nothing to back up.\n"


def test_backup_restore_and_the_backup_check_in_the_sites_words(run: Run, site: TestClient, data_dir: Path) -> None:
    briefing = final_of(ask(site, DOGS))["briefing_id"]

    said = run("backup").splitlines()
    (archive,) = (data_dir / "backups").glob("parks-state-*.sqlite.gz")
    assert said == [f"Backed up to {archive} (1 kept).", "No copy was sent off site: off-site copies are not set up."]
    assert '"error": "not set up: add PARKS_B2_BUCKET, PARKS_B2_KEY_ID and PARKS_B2_APPLICATION_KEY' in run("offsite")
    assert run("backup-check", "--in", str(data_dir / "backups")) \
        == "warning: Backups are kept on this server only: no off-site copy is set up.\n"

    ask(site, HOURS)
    restored = run("restore", str(archive), "--yes")
    assert restored == (f"Restored {data_dir / 'state.db'} from {archive}. The database it replaced is kept as "
                        f"{data_dir / 'state.db.before-restore'}.\n")
    assert site.get(f"/b/{briefing}").status_code == 200
    assert "move or delete it first" in run("restore", str(archive), "--yes", code=1)  # the kept copy is never lost


def test_a_statement_is_published_and_an_item_hidden_from_the_command_line(run: Run, site: TestClient) -> None:
    address = f"/b/{final_of(ask(site, DOGS))['briefing_id']}"
    assert run("waiting") == "0 reports and 0 statements are waiting, and 0 items are hidden.\n"
    site.post("/api/statements", json={"name": "Priya Raman", "role": "Chair, Alder Park Committee", "item": address,
                                       "text": "We stand by the decision.", "email": "chair@alderpark.example"})
    site.post("/api/report", json={"kind": "takedown", "page": address, "contact": "reader@example.org",
                                   "message": "Please take my name out of this briefing."})
    assert run("waiting") == ("1 reports and 1 statements are waiting, and 0 items are hidden. The oldest has waited "
                              "0 working days: the promise is five.\n")
    listed = run("statements", "list")
    assert "#1  pending  " in listed and f"beside {address}" in listed and "confirm with: chair@alderpark.example" in listed
    assert "say how you confirmed" in run("statements", "publish", "1", "--checked", " ", code=1)
    assert run("statements", "publish", "1", "--checked", "Replied from the committee's own address.") \
        == f"Published statement 1. It is shown beside {address}.\n"
    assert "Statement from Priya Raman" in site.get(address).text
    assert "published: Replied from the committee's own address." in run("statements", "log", "1")

    assert run("hide", address, "--note", "Hidden while a request about a name is decided.") \
        == f"Hidden: {address}. Its page now shows the note.\n"
    assert "Hidden while a request about a name is decided." in site.get(address).text
    assert address in run("hidden")
    assert run("unhide", address) == f"Shown again: {address}.\n"

    assert "#1  takedown" in run("reports", "list")
    assert run("reports", "close", "1", "--outcome", "resolved", "--note", "The name was not in the briefing.") \
        == "Closed report 1. Its contact details are deleted.\n"
    assert "reader@example.org" not in run("reports", "list", "--all")


def test_statistics_the_weekly_report_and_the_nightly_tidy(run: Run, site: TestClient, data_dir: Path) -> None:
    ask(site, DOGS)
    ask(site, DOGS)
    page = run("stats", "--since", "24h")
    assert "Where Parks Stand" in page and "Answered from the cache" in page
    assert run("stats", "--check") == ""  # no threshold is set, so nothing can be over one

    said = run("weekly-report", "--week", datetime.now(UTC).date().isoformat())
    written = sorted(p.name for p in (data_dir / "reports").iterdir())
    assert len(written) == 2 and written[0].endswith(".json") and written[1].endswith(".md")
    assert "No alert thresholds are set yet." in said and "daily_cost_usd = " in said  # proposed, for [alerts]

    tidied = run("tidy").splitlines()
    assert tidied[0] == "Deleted 0 records of briefings older than 13 months."
    assert tidied[-2:] == ["Forgot the visitor codes on 0 spending rows from before today.",
                           "Deleted 0 copies of the database made before an import, older than 60 days."]
    nightly = run("nightly").splitlines()
    assert nightly[0].startswith("0 statements lapsed with no decision in three months") and len(nightly) == 3


def test_an_evaluation_run_passes_is_noted_and_replays(run: Run, tmp_path: Path) -> None:
    said = run("eval", "run", "--out", str(tmp_path / "runs"), "--record-fixtures", str(tmp_path / "fixtures"))
    assert "dogs: completed" in said and "parking: no_records" in said
    assert "Passed: every threshold met by configuration" in said
    assert (tmp_path / "runs" / "passed.jsonl").exists()

    replayed = run("eval", "replay", str(tmp_path / "fixtures"))
    assert replayed == "The checks say of 2 recorded briefings exactly what they said when each was recorded.\n"
    assert "--max-cost" in run("eval", "run", "--help")
