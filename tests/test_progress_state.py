"""
Direct unit coverage for the shared persisted-cursor helpers in
``src.jobs.progress_state`` -- extracted from four near-identical copies that had
drifted apart (a copy-paste-drift audit finding): triage_job.py / source_tags_job.py
/ perception_extract_job.py all shared one implementation byte-for-byte, while
narration_job.py had independently picked up two pieces of real hardening -- a
``mkdir`` before writing, and a ``try/finally`` that cleans up the tmp file even when
``os.replace`` itself fails -- that the other three lacked. This file pins the shared
logic directly (so a future edit here reaches every caller at once) and re-runs the
concrete regression the hardening prevents through each of the four call sites' own
thin load/save wrappers, since a resume-after-restart bug here would be a real
data-safety regression, not just a style nit.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

import pytest

from src.jobs import progress_state as PS


def test_load_missing_file_returns_empty_dict(tmp_path):
    assert PS.load_progress_state(tmp_path / "does-not-exist.json") == {}


def test_load_corrupt_file_returns_empty_dict(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert PS.load_progress_state(p) == {}


def test_load_non_dict_json_returns_empty_dict(tmp_path):
    """A cursor file must be an object -- a list or scalar is not a state dict,
    and is treated the same as "no sweep ever ran"."""
    p = tmp_path / "state.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert PS.load_progress_state(p) == {}


def test_save_then_load_roundtrips(tmp_path):
    p = tmp_path / "state.json"
    PS.save_progress_state({"cursor": "abc", "n": 3}, p)
    assert PS.load_progress_state(p) == {"cursor": "abc", "n": 3}


def test_save_creates_the_state_directory_if_missing(tmp_path):
    """The concrete regression the mkdir hardening prevents: three of the four
    original copies assumed their state directory already existed and raised
    FileNotFoundError on a fresh install / a module's first-ever save."""
    p = tmp_path / "not-yet-created" / "nested" / "state.json"
    assert not p.parent.exists()
    PS.save_progress_state({"cursor": "x"}, p)
    assert p.exists()
    assert PS.load_progress_state(p) == {"cursor": "x"}


def test_save_is_atomic_tmp_file_fully_written_before_the_swap(tmp_path, monkeypatch):
    """os.replace is the atomic swap -- the tmp file must be complete before it
    runs, so a crash mid-write never leaves the real path holding a partial write."""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"cursor": "old"}), encoding="utf-8")
    real_replace = PS.os.replace
    seen = {}

    def spy(src, dst):
        seen["tmp_existed"] = (tmp_path / "state.json.tmp").exists()
        return real_replace(src, dst)

    monkeypatch.setattr(PS.os, "replace", spy)
    PS.save_progress_state({"cursor": "new"}, p)
    assert seen.get("tmp_existed") is True
    assert PS.load_progress_state(p) == {"cursor": "new"}


def test_save_cleans_up_tmp_file_even_when_replace_raises(tmp_path, monkeypatch):
    """If write_text succeeds but os.replace fails partway (a permissions issue,
    a concurrent holder of the destination path), the pre-fix copies could leave a
    stray .tmp file behind forever; the shared version must not, and the original
    destination must be left completely untouched."""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"cursor": "old"}), encoding="utf-8")

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(PS.os, "replace", boom)

    with pytest.raises(OSError):
        PS.save_progress_state({"cursor": "new"}, p)

    assert not (tmp_path / "state.json.tmp").exists(), "the tmp file must not linger"
    assert PS.load_progress_state(p) == {"cursor": "old"}, "the original file is untouched"


# --------------------------------------------------------------------------- #
# The same "save into a not-yet-existing directory" regression, exercised through
# each of the four call sites' own load/save wrappers -- the shared logic doing
# the right thing is necessary but not sufficient if a wrapper's own default-path
# resolution or delegation silently diverges. This is the concrete, testable
# regression that should have failed against three of the four modules before
# this refactor and pass after.
# --------------------------------------------------------------------------- #


def test_triage_job_save_into_missing_directory_succeeds(tmp_path):
    from src.ai_layer import triage_job as J

    p = tmp_path / "fresh" / "state.json"
    J._save_progress_state({"cursor": "t"}, p)
    assert J.load_progress_state(p) == {"cursor": "t"}


def test_source_tags_job_save_into_missing_directory_succeeds(tmp_path):
    from src.ai_layer import source_tags_job as J

    p = tmp_path / "fresh" / "state.json"
    J._save_progress_state({"cursor": "s"}, p)
    assert J.load_progress_state(p) == {"cursor": "s"}


def test_perception_extract_job_save_into_missing_directory_succeeds(tmp_path):
    from src.ai_layer import perception_extract_job as J

    p = tmp_path / "fresh" / "state.json"
    J._save_progress_state({"cursor": "p"}, p)
    assert J.load_progress_state(p) == {"cursor": "p"}


def test_narration_job_save_into_missing_directory_succeeds(tmp_path):
    from src.bulletin import narration_job as J

    p = tmp_path / "fresh" / "state.json"
    J._save_progress_state({"cursor": "n"}, p)
    assert J.load_progress_state(p) == {"cursor": "n"}
