"""R784: the large-data backup reads, and a restore writes, the REAL Hugging Face hub cache folder.

Before: the backup read ``hf_home() / "hub"``, and ``hf_home()`` answers the PARENT of
``HF_HUB_CACHE``. A cache folder named anything but ``hub`` was therefore never backed up (the
backup reported success over nothing), and a restore wrote the models into ``<parent>/hub``, where
nothing reads them. Now both ends use the hub cache folder itself; the checklist shows the folder a
restore would write to before the person chooses; a folder that cannot be used leaves the category
out with a named reason and the restore reads incomplete; the manifest records the layout, so an
older backup is said for what it may be missing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.backup import folder_backup as fb
from src.backup.folder_backup import (
    HF_TARGET_NOT_FOLDER,
    HF_TARGET_NOT_WRITABLE,
    HF_TARGET_UNRESOLVED,
    collect_hf_model_items,
    hf_restore_target,
    hf_target_refusal,
    place_artifact_file_members,
    restore_folder_backup,
    write_folder_backup,
)
from src.backup.hf_layout import HF_LAYOUT, hf_live_rel
from src.backup.import_scan import scan_import_folder
from src.llm.model_store import hf_hub_cache

ROOT = Path(__file__).resolve().parents[1]
_REL = "models--org--m/snapshots/r1/config.json"


def _cache(hub: Path) -> Path:
    """A hub cache folder with one model, named whatever the caller chose."""
    (hub / "models--org--m" / "snapshots" / "r1").mkdir(parents=True)
    (hub / "models--org--m" / "refs").mkdir(parents=True)
    (hub / "models--org--m" / "snapshots" / "r1" / "config.json").write_bytes(b"{}")
    (hub / "models--org--m" / "refs" / "main").write_text("r1", encoding="utf-8")
    return hub


@pytest.fixture
def no_hf_env(monkeypatch):
    for v in ("HF_HUB_CACHE", "HF_HOME"):
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


# --- where the cache folder is ------------------------------------------------------------------- #
def test_hf_hub_cache_follows_hugging_face_s_own_precedence(tmp_path, no_hf_env):
    no_hf_env.setenv("HF_HOME", str(tmp_path / "home"))
    assert hf_hub_cache() == tmp_path / "home" / "hub"
    no_hf_env.setenv("HF_HUB_CACHE", str(tmp_path / "elsewhere" / "my-models"))
    assert hf_hub_cache() == tmp_path / "elsewhere" / "my-models", "HF_HUB_CACHE IS the folder, whatever its name"


def test_a_cache_folder_not_named_hub_is_backed_up(tmp_path, no_hf_env):
    """The bug: this backed up NOTHING and called it done."""
    _cache(tmp_path / "disk" / "my-models")
    no_hf_env.setenv("HF_HUB_CACHE", str(tmp_path / "disk" / "my-models"))
    rels = {it.rel for it in collect_hf_model_items()}
    assert "hub/" + _REL in rels and "hub/models--org--m/refs/main" in rels


def test_a_round_trip_lands_in_the_target_s_own_cache_folder_and_nowhere_else(tmp_path, no_hf_env):
    _cache(tmp_path / "a" / "cache-a")
    no_hf_env.setenv("HF_HUB_CACHE", str(tmp_path / "a" / "cache-a"))
    bk = tmp_path / "bk"
    write_folder_backup(bk, collect_hf_model_items())
    manifest = json.loads((bk / "oo-folder-backup.json").read_text(encoding="utf-8"))
    assert manifest["hf_layout"] == HF_LAYOUT
    # Another computer, another folder name.
    no_hf_env.setenv("HF_HUB_CACHE", str(tmp_path / "b" / "models-here"))
    res = restore_folder_backup(bk, categories=["hf_models"])
    assert res["restored"] == 2 and res["incomplete"] is False and res["refused_targets"] == {}
    assert (tmp_path / "b" / "models-here" / _REL).read_bytes() == b"{}"
    assert not (tmp_path / "b" / "hub").exists(), "the old guess wrote beside the cache folder"
    placed = sorted(p.relative_to(tmp_path / "b").as_posix() for p in (tmp_path / "b").rglob("*") if p.is_file())
    assert all(p.startswith("models-here/models--org--m/") for p in placed), placed


def test_a_model_already_there_is_never_overwritten(tmp_path, no_hf_env):
    _cache(tmp_path / "a" / "hub")
    bk = tmp_path / "bk"
    write_folder_backup(bk, collect_hf_model_items(tmp_path / "a"))
    live = tmp_path / "live-cache"
    (live / "models--org--m" / "snapshots" / "r1").mkdir(parents=True)
    (live / _REL).write_bytes(b"mine")
    res = restore_folder_backup(bk, categories=["hf_models"], targets={"hf_models": live})
    assert (live / _REL).read_bytes() == b"mine" and res["skipped"] == 1 and res["restored"] == 1


def test_an_older_backup_restores_into_the_cache_folder_and_says_what_it_may_miss(tmp_path, no_hf_env):
    """A backup written before the marker: what it holds has the hub cache's shape, so it restores to
    the same place; the checklist says plainly that a cache folder named otherwise is not in it."""
    _cache(tmp_path / "a" / "hub")
    bk = tmp_path / "old"
    write_folder_backup(bk, collect_hf_model_items(tmp_path / "a"))
    m = json.loads((bk / "oo-folder-backup.json").read_text(encoding="utf-8"))
    del m["hf_layout"]
    (bk / "oo-folder-backup.json").write_text(json.dumps(m), encoding="utf-8")
    f = scan_import_folder(tmp_path)["found"]
    assert f["blobs"]["hf_models"]["layout_unrecorded"] == 1
    no_hf_env.setenv("HF_HUB_CACHE", str(tmp_path / "live" / "cache"))
    res = restore_folder_backup(bk, categories=["hf_models"])
    assert (tmp_path / "live" / "cache" / _REL).is_file() and res["restored"] == 2


def test_a_folder_with_no_manifest_is_not_called_old(tmp_path):
    """Nothing says when a hand-copied folder was made, so the older-backup note is not drawn for it."""
    _cache(tmp_path / "bk" / "hf_models" / "hub")
    hf = scan_import_folder(tmp_path / "bk")["found"]["blobs"]["hf_models"]
    assert hf["count"] == 2 and "layout_unrecorded" not in hf


@pytest.mark.skipif(os.name == "nt", reason="POSIX links")
def test_a_cache_folder_that_is_a_link_to_nothing_is_refused_by_name(tmp_path):
    os.symlink(tmp_path / "unplugged-disk" / "cache", tmp_path / "cache")
    assert hf_target_refusal(tmp_path / "cache") == HF_TARGET_NOT_FOLDER


def test_the_import_queue_carries_the_refusal_to_the_result(monkeypatch):
    """The summary the page renders comes from the queue; a field dropped there never reaches a line."""
    from src.backup import import_queue as iq

    class _Mgr:
        def start(self, *a, **k): pass
        def status(self): return {"state": "done", "progress": {"refused_targets": {"hf_models": "not-writable"},
                                                                 "incomplete": True}}
        def cancel(self): pass

    monkeypatch.setattr(fb, "get_folder_manager", lambda: _Mgr())
    q = object.__new__(iq.ImportQueueManager)
    q._await = lambda status, cancel: status()  # an instance attribute: the class is untouched
    out = iq.ImportQueueManager._run_blobs(q, {"path": "/x", "categories": ["hf_models"]})
    assert out["refused_targets"] == {"hf_models": "not-writable"} and out["incomplete"] is True


def test_a_new_backup_is_not_called_old(tmp_path):
    _cache(tmp_path / "a" / "hub")
    write_folder_backup(tmp_path / "bk", collect_hf_model_items(tmp_path / "a"))
    hf = scan_import_folder(tmp_path / "bk")["found"]["blobs"]["hf_models"]
    assert "layout_unrecorded" not in hf and hf["count"] == 2


# --- a cache folder that cannot be used -------------------------------------------------------- #
def test_a_cache_path_taken_by_a_file_refuses_the_category_with_its_reason(tmp_path, no_hf_env):
    _cache(tmp_path / "a" / "hub")
    bk = tmp_path / "bk"
    write_folder_backup(bk, collect_hf_model_items(tmp_path / "a"))
    (tmp_path / "taken").write_bytes(b"not a folder")
    for target in (tmp_path / "taken", tmp_path / "taken" / "below"):
        res = restore_folder_backup(bk, categories=["hf_models"], targets={"hf_models": target})
        assert res["refused_targets"] == {"hf_models": HF_TARGET_NOT_FOLDER}, target
        assert res["incomplete"] is True and res["restored"] == 0
    assert (tmp_path / "taken").read_bytes() == b"not a folder"


def test_a_tilde_cache_path_is_the_person_s_home_folder_on_both_ends(tmp_path, no_hf_env):
    """``~/x`` left unexpanded is RELATIVE: the backup read, and a restore wrote, a folder named "~"
    under whatever folder the app started in, while the check looked at the home folder."""
    no_hf_env.setenv("HOME", str(tmp_path / "me"))
    no_hf_env.setenv("HF_HUB_CACHE", "~/hf-cache")
    assert hf_hub_cache() == tmp_path / "me" / "hf-cache"
    assert hf_restore_target() == {"path": str(tmp_path / "me" / "hf-cache"), "refused": None}
    no_hf_env.delenv("HF_HUB_CACHE")
    no_hf_env.setenv("HF_HOME", "~/hf-home")
    assert hf_hub_cache() == tmp_path / "me" / "hf-home" / "hub"
    assert hf_target_refusal("~/unexpanded") == HF_TARGET_UNRESOLVED, "the check never expands what the write would not"


def test_a_relative_cache_path_is_refused_never_guessed(tmp_path):
    assert hf_target_refusal("relative/cache") == HF_TARGET_UNRESOLVED
    assert hf_target_refusal(None) == HF_TARGET_UNRESOLVED
    assert hf_target_refusal("") == HF_TARGET_UNRESOLVED
    assert hf_target_refusal(tmp_path / "not" / "yet" / "made") is None, "a folder not made yet is made on restore"


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="POSIX permissions; root writes anywhere")
def test_a_cache_folder_that_cannot_be_written_is_refused(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        assert hf_target_refusal(ro / "cache") == HF_TARGET_NOT_WRITABLE
        assert hf_target_refusal(ro) == HF_TARGET_NOT_WRITABLE
    finally:
        ro.chmod(0o700)


# --- what the checklist is told ------------------------------------------------------------------ #
def test_the_scan_endpoint_names_the_folder_before_the_person_chooses(tmp_path, no_hf_env):
    from src.api.backup_v2 import import_scan_endpoint

    _cache(tmp_path / "bk" / "hf_models" / "hub")
    no_hf_env.setenv("HF_HUB_CACHE", str(tmp_path / "live" / "cache"))
    out = import_scan_endpoint(str(tmp_path / "bk"))
    assert out["found"]["hf_target"] == {"path": str(tmp_path / "live" / "cache"), "refused": None}
    (tmp_path / "file").write_bytes(b"x")
    no_hf_env.setenv("HF_HUB_CACHE", str(tmp_path / "file"))
    assert import_scan_endpoint(str(tmp_path / "bk"))["found"]["hf_target"]["refused"] == HF_TARGET_NOT_FOLDER
    # No model cache in the backup: no folder is looked up or shown.
    (tmp_path / "w" / "wiki_dumps").mkdir(parents=True)
    (tmp_path / "w" / "wiki_dumps" / "d.xml.bz2").write_bytes(b"d")
    assert "hf_target" not in import_scan_endpoint(str(tmp_path / "w"))["found"]


def test_hf_restore_target_is_the_folder_the_restore_uses(tmp_path, no_hf_env):
    no_hf_env.setenv("HF_HUB_CACHE", str(tmp_path / "c"))
    assert hf_restore_target() == {"path": str(tmp_path / "c"), "refused": None}
    assert fb.live_targets()["hf_models"] == tmp_path / "c"


# --- the artifact path places the same way ----------------------------------------------------- #
def test_artifact_members_land_in_the_cache_folder_and_only_its_layout(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "m1").write_bytes(b"{}")
    (staging / "m2").write_bytes(b"evil")
    live = tmp_path / "cache"
    out = place_artifact_file_members(staging, [
        {"category": "hf_models", "rel": "hub/" + _REL, "name": "m1"},
        {"category": "hf_models", "rel": ".bash_profile", "name": "m2"},
    ], targets={"hf_models": live}, place_hf=True)
    assert out["placed"] == 1 and (live / _REL).read_bytes() == b"{}"
    assert [r["why"] for r in out["refused"]] == ["outside the model cache's layout"]
    assert not (live / ".bash_profile").exists() and not (live / "hub").exists()
    (tmp_path / "taken").write_bytes(b"x")
    out = place_artifact_file_members(staging, [{"category": "hf_models", "rel": "hub/" + _REL, "name": "m1"}],
                                      targets={"hf_models": tmp_path / "taken"}, place_hf=True)
    assert out["placed"] == 0 and out["refused"][0]["why"] == f"model cache folder {HF_TARGET_NOT_FOLDER}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX links")
def test_artifact_placement_never_writes_through_a_link_in_the_live_cache(tmp_path):
    """A real cache is made of links; a dangling one read as absent and was replaced by a file."""
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "m1").write_bytes(b"{}")
    live = tmp_path / "cache"
    snap = live / "models--org--m" / "snapshots" / "r1"
    snap.mkdir(parents=True)
    (live / "models--org--m" / "blobs").mkdir()
    os.symlink(Path("..") / ".." / "blobs" / "gone-blob", snap / "config.json")  # inside the cache, dangling
    out = place_artifact_file_members(staging, [{"category": "hf_models", "rel": "hub/" + _REL, "name": "m1"}],
                                      targets={"hf_models": live}, place_hf=True)
    # R787 reads: a link AT the file's own name is that file already here -- kept, counted as skipped,
    # never written through (it still dangles, and nothing was created beside it).
    assert out["placed"] == 0 and out["skipped"] == 1 and out["refused"] == [] and out["incomplete"] is False
    assert (snap / "config.json").is_symlink() and not (live / "models--org--m" / "blobs" / "gone-blob").exists()
    # A link in a folder ON THE WAY is still refused.
    other = live / "models--org--n"
    other.mkdir()
    (live / "elsewhere").mkdir()
    os.symlink(live / "elsewhere", other / "snapshots")  # inside the cache, so only the link rule can refuse it
    out = place_artifact_file_members(staging, [{"category": "hf_models", "rel": "hub/models--org--n/snapshots/r1/a.json", "name": "m1"}],
                                      targets={"hf_models": live}, place_hf=True)
    assert out["placed"] == 0 and out["refused"][0]["why"] == "a link on the way in your data folder"
    assert not (live / "elsewhere" / "r1").exists()
    assert (snap / "config.json").is_symlink() and not (live / "models--org--m" / "blobs" / "gone-blob").exists()


def test_the_layout_rule_maps_hub_to_the_folder_itself():
    assert hf_live_rel("hub/" + _REL) == _REL
    for bad in ("hub/x", ".bash_profile", "other/models--a/snapshots/r/f", "hub/models--a/blobs/x"):
        assert hf_live_rel(bad) is None, bad


def test_the_stream_backup_records_the_layout():
    src = (ROOT / "src/backup/stream_backup.py").read_text(encoding="utf-8")
    assert '{"hf_layout": HF_LAYOUT} if any(fm.get("category") == "hf_models"' in src


# --- words ------------------------------------------------------------------------------------------ #
_KEYS = [
    "This backup was made before it recorded which Hugging Face cache folder it read: if that computer's cache "
    "folder was not named “hub”, its models are not in this backup.",
    "Hugging Face models are restored to",
    "Hugging Face models will not be restored on this computer",
    "Restore incomplete — the Hugging Face model cache was not restored",
    "its folder cannot be written to",
    "its folder could not be worked out",
    "its path is taken by something that is not a folder",
]
_LANGS = ("en", "fr", "de", "es", "pt", "ru", "ar", "hi", "bn", "id", "ja", "zh")


def test_every_string_is_translated_in_all_twelve_languages():
    for lang in _LANGS:
        cat = json.loads((ROOT / "src/static/locales" / f"{lang}.json").read_text(encoding="utf-8"))
        for k in _KEYS:
            assert cat.get(k) and (lang == "en" or cat[k] != k), (lang, k)


def test_the_help_says_it_in_every_language():
    for lang in _LANGS:
        f = ROOT / ("docs/USER_MANUAL.md" if lang == "en" else f"docs/i18n/{lang}/USER_MANUAL.md")
        text = f.read_text(encoding="utf-8")
        cat = json.loads((ROOT / "src/static/locales" / f"{lang}.json").read_text(encoding="utf-8"))
        assert "HF_HUB_CACHE" in text and cat[_KEYS[1]] in text and cat[_KEYS[3]] in text, lang


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_checklist_note_and_the_result_line_node():
    r = subprocess.run(["node", str(ROOT / "tests" / "hf_cache_folder_r784_node_test.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
