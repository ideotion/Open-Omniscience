"""R777: the import scan lists the Hugging Face model cache (``hf_models``) under "LLM models".

The folder backup has written ``hf_models`` since it learned the category, but the scan only knew
``wiki_dumps``, ``osm_regions`` and ``models``, so no restore ever asked for it and those models were
skipped. The scan now lists it, the restore receives it, nothing is downloaded, an existing file is never
overwritten, and an older backup without the folder simply shows no such category.
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

from src.backup.folder_backup import restore_folder_backup
from src.backup.import_scan import scan_import_folder

ROOT = Path(__file__).resolve().parents[1]
_posix = pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="needs POSIX symlinks")
KEEP = "A file already in your data folders is kept as it is: a restore never overwrites it, and never downloads anything."


def _touch(p: Path, data: bytes = b"x") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _targets(tmp: Path) -> dict[str, Path]:
    return {c: tmp / "live" / c for c in ("wiki_dumps", "osm_regions", "models", "hf_models")}


def test_the_scan_lists_hf_models_and_the_restore_category_rides_with_it(tmp_path):
    _touch(tmp_path / "bk" / "hf_models" / "hub" / "models--org--m" / "snapshots" / "abc" / "model.safetensors", b"w" * 10)
    _touch(tmp_path / "bk" / "models" / "blobs" / "sha256-a", b"o")
    f = scan_import_folder(tmp_path)["found"]
    assert {k: f["blobs"]["hf_models"][k] for k in ("count", "bytes")} == {"count": 1, "bytes": 10}
    (br,) = f["blob_roots"]
    assert set(br["categories"]) == {"models", "hf_models"}


def test_an_older_backup_without_the_folder_shows_no_such_category(tmp_path):
    _touch(tmp_path / "bk" / "models" / "blobs" / "sha256-a")
    f = scan_import_folder(tmp_path)["found"]
    assert "hf_models" not in f["blobs"] and f["blob_roots"][0]["categories"] == ["models"]


def test_the_manifest_alone_recovers_hf_models(tmp_path):
    bk = tmp_path / "bk"
    bk.mkdir()
    (bk / "oo-folder-backup.json").write_text(json.dumps({"categories": {"hf_models": [{"rel": "hub/x", "size": 7}]}}), encoding="utf-8")
    f = scan_import_folder(tmp_path)["found"]
    assert f["blobs"]["hf_models"]["count"] == 1 and f["blob_roots"][0]["hf_models"]["from_manifest"] is True
    assert f["blob_roots"][0]["categories"] == ["hf_models"]


def test_the_scanned_categories_restore_and_an_existing_model_is_never_overwritten(tmp_path):
    bk = tmp_path / "bk"
    _touch(bk / "hf_models" / "hub" / "models--o--m" / "snapshots" / "r" / "a.safetensors", b"backup")
    _touch(bk / "hf_models" / "hub" / "models--o--m" / "snapshots" / "r" / "b.safetensors", b"backup")
    tgt = _targets(tmp_path)
    _touch(tgt["hf_models"] / "models--o--m" / "snapshots" / "r" / "a.safetensors", b"mine")
    cats = scan_import_folder(tmp_path)["found"]["blob_roots"][0]["categories"]
    res = restore_folder_backup(bk, categories=cats, targets=tgt)
    assert (tgt["hf_models"] / "models--o--m" / "snapshots" / "r" / "a.safetensors").read_bytes() == b"mine"
    assert (tgt["hf_models"] / "models--o--m" / "snapshots" / "r" / "b.safetensors").read_bytes() == b"backup"
    assert res["restored"] == 1 and res["skipped"] == 1


@_posix
def test_a_linked_hf_models_folder_is_refused_like_the_others(tmp_path):
    _touch(tmp_path / "elsewhere" / "secret")
    (tmp_path / "bk").mkdir()
    os.symlink(tmp_path / "elsewhere", tmp_path / "bk" / "hf_models")
    f = scan_import_folder(tmp_path / "bk")["found"]
    assert f["blobs"]["hf_models"]["linked"] == 1 and f["blobs"]["hf_models"]["count"] == 0
    res = restore_folder_backup(tmp_path / "bk", targets=_targets(tmp_path))
    assert res["refused_categories"] == ["hf_models"] and not (tmp_path / "live" / "hf_models").exists()


def test_the_restore_path_has_no_network_call():
    for f in ("src/backup/folder_backup.py", "src/backup/import_scan.py"):
        text = (ROOT / f).read_text(encoding="utf-8")
        for mod in ("requests", "httpx", "urllib.request", "huggingface_hub", "socket"):
            assert f"import {mod}" not in text and f"from {mod} import" not in text, (f, mod)


def test_the_new_line_is_a_key_in_all_twelve_catalogues():
    for f in sorted((ROOT / "src/static/locales").glob("*.json")):
        assert json.loads(f.read_text(encoding="utf-8")).get(KEEP), f.name


def test_the_page_says_it_as_real_code():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "import_scan_hf_models_r777_node_test.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_only_the_model_cache_layout_is_ever_placed_in_the_hugging_face_home(tmp_path):
    # Security read: with HF_HUB_CACHE set, the Hugging Face home can be a person's own home folder,
    # so a backup carrying hf_models/.bash_profile would have placed it there.
    bk = tmp_path / "bk"
    _touch(bk / "hf_models" / "hub" / "models--org--m" / "snapshots" / "r1" / "config.json", b"{}")
    _touch(bk / "hf_models" / "hub" / "models--org--m" / "snapshots" / "r1" / ".gitattributes", b"*")
    _touch(bk / "hf_models" / "hub" / "models--org--m" / "refs" / "main", b"r1")
    _touch(bk / "hf_models" / ".bash_profile", b"evil")
    _touch(bk / "hf_models" / ".config" / "autostart" / "x.desktop", b"evil")
    _touch(bk / "hf_models" / "hub" / "models--org--m" / "blobs" / "abc", b"planted")
    _touch(bk / "hf_models" / "hub" / "datasets--x" / "snapshots" / "r" / "f", b"other")
    f = scan_import_folder(bk)["found"]
    assert f["blobs"]["hf_models"]["count"] == 3 and f["blobs"]["hf_models"]["refused_layout"] == 4
    tgt = _targets(tmp_path)
    res = restore_folder_backup(bk, targets=tgt)
    home = tgt["hf_models"]
    placed = sorted(p.relative_to(home).as_posix() for p in home.rglob("*") if p.is_file())
    assert placed == [  # R784: the target is the hub cache folder itself, so ``hub/`` is not repeated
        "models--org--m/refs/main",
        "models--org--m/snapshots/r1/.gitattributes",
        "models--org--m/snapshots/r1/config.json",
    ]
    assert res["refused_layout"] == 4 and res["incomplete"] is True  # the scan and the restore agree


def test_the_layout_rule():
    from src.backup.hf_layout import hf_member_allowed

    assert hf_member_allowed("hub/models--a--b/snapshots/r/x.safetensors")
    assert hf_member_allowed("hub/models--a--b/refs/main")
    for bad in (".bash_profile", "hub/x", "hub/models--a/blobs/z", "other/models--a/refs/main", "hub/datasets--a/refs/main",
                "hub/models--a/refs", "hub/models--a/snapshots/../../../.profile", "hub//refs/x"):
        assert not hf_member_allowed(bad), bad
