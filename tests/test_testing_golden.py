"""The comparison with a stored file that the parity tests use."""

from __future__ import annotations

import json

import pytest

from wts_core.testing import golden


def test_what_matches_the_stored_file_passes(tmp_path):
    (tmp_path / "words.txt").write_text("backup: /backups/wcs-state-2026-11-12.sqlite.gz\n", encoding="utf-8")
    golden(tmp_path / "words.txt", "backup: /backups/wcs-state-2026-11-12.sqlite.gz\n", env={})
    golden(tmp_path / "settings.json", {"b": [1, 2], "a": "é"}, update=True, env={})
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == (
        '{\n  "a": "é",\n  "b": [\n    1,\n    2\n  ]\n}\n')
    golden(tmp_path / "settings.json", {"a": "é", "b": [1, 2]}, env={})  # the order of keys is not a difference


def test_what_differs_fails_showing_the_lines_that_differ(tmp_path):
    path = tmp_path / "said.txt"
    path.write_text("published\nwithdrawn\n", encoding="utf-8")
    with pytest.raises(AssertionError) as failed:
        golden(path, "published\nremoved\n", env={})
    said = str(failed.value)
    assert "-withdrawn" in said and "+removed" in said and " published" in said and str(path) in said
    assert "WTS_UPDATE_GOLDEN=1" in said
    assert path.read_text(encoding="utf-8") == "published\nwithdrawn\n"  # and the file is left as it was
    with pytest.raises(AssertionError, match='-  "cap": 5'):
        golden(tmp_path / "caps.json", {"cap": 5}, update=True, env={}) or golden(tmp_path / "caps.json", {"cap": 6},
                                                                                 env={})


def test_a_file_that_is_not_there_fails_and_says_how_to_write_it(tmp_path):
    with pytest.raises(AssertionError, match="is not there yet. Run the tests once with WTS_UPDATE_GOLDEN=1"):
        golden(tmp_path / "golden" / "new.json", {"a": 1}, env={})
    assert not (tmp_path / "golden").exists()


@pytest.mark.parametrize("how", ["argument", "environment", "the process's own environment"])
def test_the_file_is_written_when_asked(tmp_path, monkeypatch, how):
    path = tmp_path / "golden" / "cli" / "said.json"
    monkeypatch.delenv("WTS_UPDATE_GOLDEN", raising=False)
    if how == "argument":
        golden(path, {"lines": ["closed"]}, update=True, env={})
    elif how == "environment":
        golden(path, {"lines": ["closed"]}, env={"WTS_UPDATE_GOLDEN": "1"})
    else:
        monkeypatch.setenv("WTS_UPDATE_GOLDEN", "1")
        golden(path, {"lines": ["closed"]})
    assert json.loads(path.read_text(encoding="utf-8")) == {"lines": ["closed"]}
    monkeypatch.delenv("WTS_UPDATE_GOLDEN", raising=False)
    golden(path, {"lines": ["closed"]})
    with pytest.raises(AssertionError):
        golden(path, {"lines": ["open"]}, env={"WTS_UPDATE_GOLDEN": "0"})  # only "1" writes
