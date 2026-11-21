"""Row 284: the storage footprint never counts what it could not read as 0.

The Library's and the task manager's "X on disk, all stores" left out an Ollama store this app is not
allowed to read (``default_store`` skips it and falls back to the app's own, empty, store) and every
folder or file the walk was refused, then printed the rest as the whole footprint. Now a store it may
not read is its own line with ``bytes: None`` and the reason, a line walked with refusals is
``partial``, and ``totals.complete`` is False with ``totals.not_counted`` naming them. The protected
store is never sized another way. tests/storage_footprint_r284_node_test.js runs the shipped painter.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import src.backup.ollama_models as ollama_models
import src.monitoring.forensics as forensics
from src.monitoring.forensics import (
    FOOTPRINT_PARTIAL,
    FOOTPRINT_PROTECTED_STORE,
    FOOTPRINT_UNREAD_DATA_DIR,
    FOOTPRINT_UNREAD_STORE,
)
from tests.os_scope import scope_os

ROOT = Path(__file__).resolve().parents[1]
_DB = "open_omniscience.db"


@pytest.fixture()
def data(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / _DB).write_bytes(b"d" * 4000)
    (d / "wiki_dumps").mkdir()
    (d / "wiki_dumps" / "a.bz2").write_bytes(b"k" * 9000)
    (d / "wiki_dumps" / "b.bz2").write_bytes(b"k" * 1000)
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    return d


def _store(path: Path, blob: int = 0) -> Path:
    (path / "manifests" / "registry" / "lib" / "m").mkdir(parents=True)
    (path / "manifests" / "registry" / "lib" / "m" / "latest").write_bytes(b"\x00")
    (path / "blobs").mkdir()
    if blob:
        (path / "blobs" / "sha256-x").write_bytes(b"m" * blob)
    return path


def _refuse_under(monkeypatch, root: Path) -> None:
    """``os.access`` as ollama_models sees it refuses everything under ``root`` -- the service store's wall."""
    real = os.access

    def fake_access(p, mode, *a, **kw):
        if str(p).startswith(str(root)):
            return False
        return real(p, mode, *a, **kw)

    scope_os(monkeypatch, ollama_models, access=fake_access)


def _line(fp, name):
    return next(c for c in fp["components"] if c["name"] == name)


def test_a_clean_walk_is_complete(data, monkeypatch, tmp_path):
    app = _store(tmp_path / "app", blob=700)
    monkeypatch.setattr(ollama_models, "candidate_stores", lambda: [app])
    monkeypatch.setattr(ollama_models, "default_store", lambda: app)
    fp = forensics.storage_footprint()
    t = fp["totals"]
    assert t["complete"] is True and t["not_counted"] == []
    assert t["data_dir_complete"] is True and t["ollama_models_complete"] is True
    assert t["ollama_models_bytes"] == 701
    assert t["grand_total_bytes"] == t["data_dir_bytes"] + 701
    assert all(c["measured"] for c in fp["components"])


def test_a_protected_store_beside_the_chosen_one_is_its_own_unmeasured_line(data, monkeypatch, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    svc = _store(tmp_path / "svc", blob=5000)
    monkeypatch.setattr(ollama_models, "candidate_stores", lambda: [app, svc])
    monkeypatch.setattr(ollama_models, "default_store", lambda: app)  # what the real one does: skips svc
    _refuse_under(monkeypatch, svc)
    fp = forensics.storage_footprint()
    prot = _line(fp, "Ollama model store (protected)")
    assert prot["bytes"] is None and prot["files"] is None and prot["measured"] is False
    assert prot["reason"] == FOOTPRINT_PROTECTED_STORE and prot["detail"] == str(svc)
    t = fp["totals"]
    assert t["complete"] is False and t["ollama_models_complete"] is False and t["data_dir_complete"] is True
    assert [n["status"] for n in t["not_counted"]] == ["not measured"]
    # The 5000 bytes it holds are nowhere in the total, and nothing says 0 for them.
    assert t["ollama_models_bytes"] == 0  # the chosen store, measured and really empty
    assert t["grand_total_bytes"] == t["data_dir_bytes"]
    assert fp["components"][-1] is prot  # a line with no figure sorts last


def test_a_protected_chosen_store_is_never_walked(data, monkeypatch, tmp_path):
    svc = _store(tmp_path / "svc", blob=5000)
    monkeypatch.setenv("OLLAMA_MODELS", str(svc))
    monkeypatch.setattr(ollama_models, "candidate_stores", lambda: [svc])
    monkeypatch.setattr(ollama_models, "list_models", lambda store: [])
    _refuse_under(monkeypatch, svc)
    walked = []
    real = forensics._tree_measure
    monkeypatch.setattr(forensics, "_tree_measure", lambda root: walked.append(Path(root)) or real(root))
    fp = forensics.storage_footprint()
    line = _line(fp, "Ollama model store")
    assert line["bytes"] is None and line["reason"] == FOOTPRINT_PROTECTED_STORE
    assert not any(str(p).startswith(str(svc)) for p in walked), walked
    assert fp["totals"]["ollama_models_bytes"] is None
    assert fp["totals"]["grand_total_bytes"] == fp["totals"]["data_dir_bytes"]
    assert fp["totals"]["complete"] is False


def test_a_store_status_that_throws_is_unmeasured_not_zero(data, monkeypatch):
    def boom(store=None):
        raise RuntimeError("no")

    monkeypatch.setattr(ollama_models, "store_status", boom)
    fp = forensics.storage_footprint()
    line = _line(fp, "Ollama model store")
    assert line["bytes"] is None and line["reason"] == FOOTPRINT_UNREAD_STORE
    assert fp["totals"]["ollama_models_bytes"] is None and fp["totals"]["complete"] is False


def test_a_refused_file_marks_its_line_partial(data, monkeypatch, tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(ollama_models, "candidate_stores", lambda: [app])
    monkeypatch.setattr(ollama_models, "default_store", lambda: app)
    refused = str(data / "wiki_dumps" / "b.bz2")
    real = os.lstat

    def fake_lstat(p, *a, **kw):
        if str(p) == refused:
            raise PermissionError(errno.EACCES, "denied", p)
        return real(p, *a, **kw)

    scope_os(monkeypatch, forensics, lstat=fake_lstat)
    fp = forensics.storage_footprint()
    wiki = _line(fp, "wiki dumps")
    assert wiki["bytes"] == 9000  # what could be read: a lower bound
    assert wiki["partial"] is True and wiki["unread_entries"] == 1 and wiki["reason"] == FOOTPRINT_PARTIAL
    t = fp["totals"]
    assert t["complete"] is False and t["data_dir_complete"] is False and t["ollama_models_complete"] is True
    assert t["not_counted"] == [{"name": "wiki dumps", "kind": "wiki_dumps", "detail": None,
                                 "reason": FOOTPRINT_PARTIAL, "status": "partial"}]


def test_a_refused_folder_is_counted_as_unread(tmp_path, monkeypatch):
    root = tmp_path / "t"
    (root / "locked").mkdir(parents=True)
    (root / "ok.bin").write_bytes(b"x" * 10)
    real_walk = os.walk

    def fake_walk(top, onerror=None, followlinks=False):
        for dirpath, dirs, files in real_walk(top, onerror=onerror, followlinks=followlinks):
            if dirpath.endswith("locked"):
                onerror(PermissionError(errno.EACCES, "denied", dirpath))
                continue
            yield dirpath, dirs, files

    scope_os(monkeypatch, forensics, walk=fake_walk)
    assert forensics._tree_measure(root) == (10, 1, 1)


def test_a_file_that_vanished_mid_walk_is_gone_not_unread(tmp_path, monkeypatch):
    root = tmp_path / "t"
    root.mkdir()
    (root / "a").write_bytes(b"x" * 3)
    (root / "gone").write_bytes(b"x" * 99)
    real = os.lstat

    def fake_lstat(p, *a, **kw):
        if str(p).endswith("gone"):
            raise FileNotFoundError(errno.ENOENT, "gone", p)
        return real(p, *a, **kw)

    scope_os(monkeypatch, forensics, lstat=fake_lstat)
    assert forensics._tree_measure(root) == (3, 1, 0)


def test_symlinks_are_still_never_followed(tmp_path):
    root = tmp_path / "t"
    root.mkdir()
    big = tmp_path / "big"
    big.mkdir()
    (big / "f").write_bytes(b"x" * 500)
    (root / "a").write_bytes(b"x" * 4)
    try:
        (root / "link").symlink_to(big, target_is_directory=True)
        (root / "flink").symlink_to(big / "f")
    except OSError:
        pytest.skip("symlinks not permitted here")
    assert forensics._tree_measure(root) == (4, 1, 0)
    assert forensics._tree_measure(root / "link") == (0, 0, 0)


def test_an_unreadable_data_folder_is_null_not_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(forensics, "data_dir_inventory",
                        lambda: {"unreadable": True, "note": "data dir unreadable: PermissionError",
                                 "entries": [], "totals": {}})
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(ollama_models, "candidate_stores", lambda: [app])
    monkeypatch.setattr(ollama_models, "default_store", lambda: app)
    fp = forensics.storage_footprint()
    inside = [c for c in fp["components"] if not c["outside_data_dir"]]
    assert inside and all(c["bytes"] is None and c["reason"] == FOOTPRINT_UNREAD_DATA_DIR for c in inside)
    t = fp["totals"]
    assert t["data_dir_bytes"] is None and t["complete"] is False and t["data_dir_complete"] is False
    assert t["grand_total_bytes"] == 0  # the model store, measured and empty -- the folder adds nothing it did not read


def test_nothing_measured_is_a_null_total(monkeypatch):
    monkeypatch.setattr(forensics, "data_dir_inventory", lambda: {"unreadable": True, "entries": [], "totals": {}})
    monkeypatch.setattr(forensics, "_ollama_components", lambda: (None, [
        {"name": "Ollama model store", "kind": "ollama_models", "bytes": None, "files": None, "detail": None,
         "outside_data_dir": True, "measured": False, "reason": FOOTPRINT_UNREAD_STORE}]))
    assert forensics.storage_footprint()["totals"]["grand_total_bytes"] is None


def test_the_inventory_counts_refusals_in_its_totals(data, monkeypatch):
    real = os.lstat

    def fake_lstat(p, *a, **kw):
        if str(p).endswith("a.bz2"):
            raise PermissionError(errno.EACCES, "denied", p)
        return real(p, *a, **kw)

    scope_os(monkeypatch, forensics, lstat=fake_lstat)
    inv = forensics.data_dir_inventory()
    assert inv["totals"]["unread_entries"] == 1
    assert next(e for e in inv["entries"] if e["name"] == "wiki_dumps")["unread_entries"] == 1


def test_every_reason_and_the_method_are_keys_in_all_twelve_catalogues(data):
    method = forensics.storage_footprint()["method"]
    keys = [FOOTPRINT_PROTECTED_STORE, FOOTPRINT_UNREAD_STORE, FOOTPRINT_UNREAD_DATA_DIR, FOOTPRINT_PARTIAL, method,
            "Not every store could be measured, so this total is a lower bound. Hover a line for the reason.",
            "not measured", "at least"]
    for p in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
        cat = json.loads(p.read_text(encoding="utf-8"))
        missing = [k for k in keys if not cat.get(k)]
        assert not missing, (p.name, missing)


def test_the_panel_runs_as_real_code():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(ROOT / "tests" / "storage_footprint_r284_node_test.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
