"""R787: Hugging Face models inside an encrypted oo-volumes-2 artifact follow R784's on-screen rules.

They are placed only when the person ticked them on the checklist (which shows the folder they go to on
this computer), never by default; an artifact made before it recorded its cache layout is said; a cache
folder that cannot take them makes the restore incomplete, with one fixed reason.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.backup.folder_backup import HF_TARGET_NOT_FOLDER, place_artifact_file_members
from src.backup.hf_layout import HF_LAYOUT
from src.backup.import_scan import scan_import_folder
from tests.js_source_helper import python_function_source

ROOT = Path(__file__).resolve().parents[1]
_REL = "hub/models--org--m/snapshots/r1/config.json"


def _staging(tmp: Path) -> Path:
    s = tmp / "staging"
    s.mkdir()
    (s / "m1").write_bytes(b"{}")
    (s / "w1").write_bytes(b"dump")
    return s


def _members():
    return [{"category": "hf_models", "rel": _REL, "name": "m1"},
            {"category": "wiki_dumps", "rel": "a.bz2", "name": "w1"}]


def test_models_are_never_placed_unasked(tmp_path):
    tg = {"hf_models": tmp_path / "cache", "wiki_dumps": tmp_path / "wiki"}
    out = place_artifact_file_members(_staging(tmp_path), _members(), targets=tg)
    assert out["hf_not_chosen"] == 1 and out["placed"] == 1
    assert not (tmp_path / "cache").exists(), "nothing of the models is written, not even a folder"
    assert (tmp_path / "wiki" / "a.bz2").read_bytes() == b"dump"
    assert out["incomplete"] is False and out["refused_targets"] == {}


def test_ticked_models_land_in_the_cache_folder(tmp_path):
    tg = {"hf_models": tmp_path / "cache", "wiki_dumps": tmp_path / "wiki"}
    out = place_artifact_file_members(_staging(tmp_path), _members(), targets=tg, place_hf=True)
    assert out["placed"] == 2 and out["hf_not_chosen"] == 0
    assert (tmp_path / "cache" / "models--org--m" / "snapshots" / "r1" / "config.json").read_bytes() == b"{}"


def test_a_cache_folder_that_cannot_take_them_makes_the_restore_incomplete(tmp_path):
    (tmp_path / "taken").write_bytes(b"x")
    tg = {"hf_models": tmp_path / "taken", "wiki_dumps": tmp_path / "wiki"}
    out = place_artifact_file_members(_staging(tmp_path), _members(), targets=tg, place_hf=True)
    assert out["refused_targets"] == {"hf_models": HF_TARGET_NOT_FOLDER}
    assert out["incomplete"] is True and out["placed"] == 1


def _artifact(tmp: Path, **extra) -> Path:
    d = tmp / "bk" / "set1"
    d.mkdir(parents=True)
    vman = {"kind": "oo-volumes-2", "file_members": [
        {"category": "hf_models", "rel": _REL, "name": "x"},
        {"category": "hf_models", "rel": "hub/models--o--n/snapshots/r/a.json", "name": "y"},
        {"category": "wiki_dumps", "rel": "a.bz2", "name": "z"}], **extra}
    (d / "volumes.json").write_text(json.dumps(vman), encoding="utf-8")
    return tmp / "bk"


def test_the_scan_says_what_an_artifact_carries_and_whether_it_recorded_its_layout(tmp_path):
    found = scan_import_folder(_artifact(tmp_path, hf_layout=HF_LAYOUT))["found"]
    assert found["corpus"][0]["hf_models"] == {"count": 2, "layout_recorded": True}


def test_an_old_artifact_without_the_layout_marker_is_said(tmp_path):
    found = scan_import_folder(_artifact(tmp_path))["found"]
    assert found["corpus"][0]["hf_models"] == {"count": 2, "layout_recorded": False}


def test_an_artifact_without_models_or_of_another_kind_says_nothing(tmp_path):
    d = tmp_path / "bk" / "set1"
    d.mkdir(parents=True)
    (d / "volumes.json").write_text(json.dumps({"kind": "oo-volumes-1", "file_members": [
        {"category": "hf_models", "rel": _REL}]}), encoding="utf-8")
    assert "hf_models" not in scan_import_folder(tmp_path / "bk")["found"]["corpus"][0]


def test_the_scan_endpoint_shows_the_target_folder_for_an_artifact(tmp_path, monkeypatch):
    from src.api.backup_v2 import import_scan_endpoint

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "cache"))
    out = import_scan_endpoint(str(_artifact(tmp_path, hf_layout=HF_LAYOUT)))
    assert out["found"]["hf_target"] == {"path": str(tmp_path / "cache"), "refused": None}


def test_only_an_explicit_tick_travels_to_the_placement():
    q = (ROOT / "src" / "backup" / "import_queue.py").read_text(encoding="utf-8")
    assert '"place_hf_models": raw.get("place_hf_models") is True' in q
    assert 'place_hf_models=item.get("place_hf_models") is True' in python_function_source(q, "_run_corpus")
    v = (ROOT / "src" / "backup" / "volume_job.py").read_text(encoding="utf-8")
    assert "place_hf=place_hf_models" in python_function_source(v, "_run_restore")
    assert "place_hf_models: bool = False" in python_function_source(v, "start_restore")


def test_one_name_the_system_cannot_use_refuses_that_member_only(tmp_path):
    tg = {"hf_models": tmp_path / "cache", "wiki_dumps": tmp_path / "wiki"}
    bad = {"category": "wiki_dumps", "rel": "x" * 300 + "/a.bz2", "name": "w1"}
    out = place_artifact_file_members(_staging(tmp_path), [bad, *_members()], targets=tg, place_hf=True)
    assert out["placed"] == 2, "the members after it are still placed"
    assert [r["why"] for r in out["refused"]] == ["a name that cannot be used here"] and out["incomplete"] is True


def test_a_folder_restore_finds_the_model_already_here_and_calls_it_skipped(tmp_path, monkeypatch):
    import os

    import pytest

    if os.name == "nt":
        pytest.skip("POSIX links")
    from src.backup.folder_backup import restore_folder_backup

    rel = "models--org--m/snapshots/r1/config.json"
    bk = tmp_path / "bk"
    (bk / "hf_models" / "hub" / "models--org--m" / "snapshots" / "r1").mkdir(parents=True)
    (bk / "hf_models" / "hub" / rel).write_bytes(b"{}")
    live = tmp_path / "cache"
    (live / "models--org--m" / "blobs").mkdir(parents=True)
    (live / "models--org--m" / "blobs" / "abc").write_bytes(b"{}")
    (live / "models--org--m" / "snapshots" / "r1").mkdir(parents=True)
    os.symlink(Path("..") / ".." / "blobs" / "abc", live / rel)
    res = restore_folder_backup(bk, categories=["hf_models"], targets={"hf_models": live})
    assert res["skipped"] == 1 and res["refused_dest_links"] == 0 and not res.get("incomplete")
    assert (live / rel).is_symlink()


def test_a_restore_that_names_no_category_never_places_the_models():
    fb = (ROOT / "src" / "backup" / "folder_backup.py").read_text(encoding="utf-8")
    assert '[c for c in _CATEGORIES if c != "hf_models"] if mode == "restore"' in fb
    api = (ROOT / "src" / "api" / "backup_v2.py").read_text(encoding="utf-8")
    assert '[c for c in _FOLDER_CATEGORIES if c != "hf_models"]' in python_function_source(api, "folder_backup_restore")
