"""Row 277: the Library overview never shows a count it could not read as 0.

The downloaded-layer tiles (Wikipedia dumps, OpenStreetMap regions, local AI models) read "0" when a
download list threw or when Ollama's models sat in a protected store this app cannot read. Now the
count is null with a fixed reason, and the tile shows a dash, a visible "not read" and the reason on
hover (tests/library_unread_tiles_r277_node_test.js runs the shipped renderer).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.api import library
from src.api.library import (
    PROTECTED_MODELS,
    UNREAD_DOWNLOADS,
    UNREAD_MODELS,
    _downloads_done,
    _models_tile,
)

ROOT = Path(__file__).resolve().parents[1]


class _Manager:
    def __init__(self, entries=None, boom=False):
        self.entries, self.boom = entries or [], boom

    def list(self):
        if self.boom:
            raise RuntimeError("not ready")
        return self.entries


def test_a_download_list_that_cannot_be_read_is_null_with_its_reason():
    out = _downloads_done(lambda: _Manager(boom=True))
    assert out == {
        "count": None,
        "total_bytes": None,
        "available": False,
        "reason": UNREAD_DOWNLOADS,
    }


def test_a_real_count_and_a_real_zero_stay_measured():
    assert _downloads_done(lambda: _Manager([])) == {"count": 0, "total_bytes": 0}
    entries = [{"status": "done", "total_bytes": 10}, {"status": "downloading", "total_bytes": 99}]
    assert _downloads_done(lambda: _Manager(entries)) == {"count": 1, "total_bytes": 10}


def test_a_protected_model_store_is_not_read_as_zero_models():
    st = {"models": [], "total_bytes": 0, "protected_store": "/usr/share/ollama/.ollama/models"}
    assert _models_tile(st) == {
        "count": None,
        "total_bytes": None,
        "available": False,
        "reason": PROTECTED_MODELS,
    }


def test_a_readable_store_is_counted_even_beside_a_protected_one():
    st = {"models": [{"name": "a"}], "total_bytes": 5, "protected_store": None}
    assert _models_tile(st) == {"count": 1, "total_bytes": 5}
    assert _models_tile({"models": [], "total_bytes": 0, "protected_store": None}) == {
        "count": 0,
        "total_bytes": 0,
    }


@pytest.fixture()
def overview(monkeypatch):
    """The overview computed now, past the shared cache, over a real session."""
    from src.database.session import SessionLocal

    monkeypatch.setattr(library, "_cached", lambda key, compute, db: compute(db))

    def run():
        db = SessionLocal()
        try:
            return library.library_overview(db=db)
        finally:
            db.close()

    return run


def test_an_unreadable_model_store_is_null_in_the_overview(overview, monkeypatch):
    from src.backup import ollama_models

    def boom():
        raise OSError("denied")

    monkeypatch.setattr(ollama_models, "store_status", boom)
    models = overview()["downloaded"]["models"]
    assert models == {
        "count": None,
        "total_bytes": None,
        "available": False,
        "reason": UNREAD_MODELS,
    }


def _store_only(monkeypatch, store):
    from src.backup import ollama_models as om

    monkeypatch.setenv("OLLAMA_MODELS", str(store))
    monkeypatch.setattr(om, "candidate_stores", lambda: [store])


def test_an_empty_readable_store_on_disk_is_a_real_zero(overview, monkeypatch, tmp_path):
    # The Opus read's case: a store this app owns with an empty manifests folder is not "protected".
    store = tmp_path / "models"
    (store / "manifests").mkdir(parents=True)
    _store_only(monkeypatch, store)
    from src.backup.ollama_models import store_status

    assert store_status()["protected_store"] is None
    assert overview()["downloaded"]["models"] == {"count": 0, "total_bytes": 0}


def test_a_store_whose_models_were_all_removed_is_a_real_zero(overview, monkeypatch, tmp_path):
    # ollama rm leaves the namespace folders behind; nothing is refused, so nothing is "not read".
    store = tmp_path / "models"
    (store / "manifests" / "registry.ollama.ai" / "library" / "gone").mkdir(parents=True)
    (store / "blobs").mkdir()
    _store_only(monkeypatch, store)
    assert overview()["downloaded"]["models"] == {"count": 0, "total_bytes": 0}


def test_a_store_whose_manifests_cannot_be_opened_is_not_read(overview, monkeypatch, tmp_path):
    # The service install: the folders list, the manifest files are the service user's. Simulated
    # through os.access so the test does not depend on the runner's uid (root reads everything).
    import os

    store = tmp_path / "service"
    tag = store / "manifests" / "registry.ollama.ai" / "library" / "m"
    tag.mkdir(parents=True)
    # Not JSON: list_models skips it exactly as it skips a manifest it may not open.
    (tag / "latest").write_bytes(b"\x00")
    _store_only(monkeypatch, store)
    real_access = os.access

    def fake_access(path, mode, *a, **k):
        if str(path).endswith("latest"):
            return False
        return real_access(path, mode, *a, **k)

    monkeypatch.setattr(os, "access", fake_access)
    assert overview()["downloaded"]["models"]["reason"] == PROTECTED_MODELS
    assert overview()["downloaded"]["models"]["count"] is None


def test_every_reason_is_a_key_in_all_twelve_catalogues():
    for code in ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        cat = json.loads((ROOT / "src/static/locales" / f"{code}.json").read_text(encoding="utf-8"))
        for key in (UNREAD_DOWNLOADS, UNREAD_MODELS, PROTECTED_MODELS, "not read"):
            assert cat.get(key), (code, key)


def test_the_tiles_run_as_real_code():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run(
        [node, str(ROOT / "tests" / "library_unread_tiles_r277_node_test.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
