"""
Companion backup of the Ollama model store (PR 6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Verifies the opt-in models companion artifact end-to-end (stdlib only — runs without
the app installed): enumerate -> archive (checksum-dedup) -> restore (additive,
bit-safe), plus zip-slip rejection and the OLLAMA_MODELS override.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from src.backup.ollama_models import (
    build_models_archive,
    default_store,
    list_models,
    restore_models_archive,
)


def _fake_store(root: Path) -> Path:
    """A minimal Ollama store: two models that SHARE one blob (the dedup case)."""
    store = root / "models"
    man = store / "manifests" / "registry.ollama.ai" / "library"
    (man / "m1").mkdir(parents=True)
    (man / "m2").mkdir(parents=True)
    # m1: config 1111 + layer 2222 ; m2: config 3333 + layer 2222 (SHARED 2222)
    (man / "m1" / "3b").write_text(json.dumps(
        {"schemaVersion": 2, "config": {"digest": "sha256:1111", "size": 1},
         "layers": [{"digest": "sha256:2222", "size": 6}]}))
    (man / "m2" / "1b").write_text(json.dumps(
        {"schemaVersion": 2, "config": {"digest": "sha256:3333", "size": 1},
         "layers": [{"digest": "sha256:2222", "size": 6}]}))
    blobs = store / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "sha256-1111").write_text("a")
    (blobs / "sha256-2222").write_text("shared")
    (blobs / "sha256-3333").write_text("c")
    return store


def test_list_models_resolves_blobs_and_sizes(tmp_path):
    store = _fake_store(tmp_path)
    models = {m.ref: m for m in list_models(store)}
    assert set(models) == {"registry.ollama.ai/library/m1:3b", "registry.ollama.ai/library/m2:1b"}
    m1 = models["registry.ollama.ai/library/m1:3b"]
    assert set(m1.blobs) == {"sha256-1111", "sha256-2222"}
    assert m1.bytes == 1 + 6  # "a" + "shared"


def test_archive_dedups_shared_blobs_and_round_trips(tmp_path):
    store = _fake_store(tmp_path)
    arc = tmp_path / "models.oo-ollama"
    summary = build_models_archive(arc, store)
    assert summary["models"] == 2
    assert summary["blobs"] == 3        # 2222 shared -> stored ONCE (checksum dedup)
    with zipfile.ZipFile(arc) as z:
        names = z.namelist()
        assert names.count("blobs/sha256-2222") == 1
        assert json.loads(z.read("manifest.json"))["schema"] == "oo-ollama-models-1"

    # Restore into a FRESH store -> everything lands.
    dest = tmp_path / "restored"
    r1 = restore_models_archive(arc, dest)
    assert r1["models"] == 2 and r1["blobs_added"] == 3 and r1["blobs_skipped"] == 0
    assert (dest / "blobs" / "sha256-2222").read_text() == "shared"
    assert (dest / "manifests" / "registry.ollama.ai" / "library" / "m1" / "3b").is_file()
    # Re-restore is additive + bit-safe: existing blobs are SKIPPED, never overwritten.
    r2 = restore_models_archive(arc, dest)
    assert r2["blobs_added"] == 0 and r2["blobs_skipped"] == 3


def test_restore_rejects_zip_slip(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("manifest.json", "{}")
        z.writestr("../escape.txt", "pwned")
        z.writestr("blobs/../../escape2.txt", "pwned")
        z.writestr("/abs.txt", "pwned")
        z.writestr("etc/passwd", "pwned")          # not under manifests/ or blobs/
        z.writestr("blobs/sha256-9999", "ok")      # the one legitimate member
    dest = tmp_path / "store"
    r = restore_models_archive(evil, dest)
    assert r["blobs_added"] == 1 and r["rejected"] >= 3
    assert (dest / "blobs" / "sha256-9999").is_file()
    # nothing escaped the store
    assert not (tmp_path / "escape.txt").exists()
    assert not (tmp_path / "escape2.txt").exists()


def test_default_store_honours_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "custom"))
    assert default_store() == tmp_path / "custom"
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    assert default_store() == Path.home() / ".ollama" / "models"


def test_build_raises_when_no_models(tmp_path):
    (tmp_path / "models" / "manifests").mkdir(parents=True)
    try:
        build_models_archive(tmp_path / "x.zip", tmp_path / "models")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
