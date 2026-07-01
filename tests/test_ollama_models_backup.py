"""
Ollama model-store enumeration (feeds the unified folder backup's "models" category).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The separate ``.oomodels`` companion archive was retired (models are now a category
in the unified Export/Import folder backup). What remains, and is tested here, is the
store enumeration the folder backup reuses: ``list_models`` + ``default_store``.
Stdlib only — runs without the app installed.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.backup.ollama_models import default_store, list_models


def _fake_store(root: Path) -> Path:
    """A minimal Ollama store: two models that SHARE one blob (the dedup case)."""
    store = root / "models"
    man = store / "manifests" / "registry.ollama.ai" / "library"
    (man / "m1").mkdir(parents=True)
    (man / "m2").mkdir(parents=True)
    # m1: config 1111 + layer 2222 ; m2: config 3333 + layer 2222 (SHARED 2222)
    (man / "m1" / "3b").write_text(json.dumps(
        {"schemaVersion": 2, "config": {"digest": "sha256:1111", "size": 1},
         "layers": [{"digest": "sha256:2222", "size": 6}]}), encoding="utf-8")
    (man / "m2" / "1b").write_text(json.dumps(
        {"schemaVersion": 2, "config": {"digest": "sha256:3333", "size": 1},
         "layers": [{"digest": "sha256:2222", "size": 6}]}), encoding="utf-8")
    blobs = store / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "sha256-1111").write_text("a", encoding="utf-8")
    (blobs / "sha256-2222").write_text("shared", encoding="utf-8")
    (blobs / "sha256-3333").write_text("c", encoding="utf-8")
    return store


def test_list_models_resolves_blobs_and_sizes(tmp_path):
    store = _fake_store(tmp_path)
    models = {m.ref: m for m in list_models(store)}
    assert set(models) == {"registry.ollama.ai/library/m1:3b", "registry.ollama.ai/library/m2:1b"}
    m1 = models["registry.ollama.ai/library/m1:3b"]
    assert set(m1.blobs) == {"sha256-1111", "sha256-2222"}
    assert m1.bytes == 1 + 6  # "a" + "shared"


def test_default_store_honours_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "custom"))
    assert default_store() == tmp_path / "custom"
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    assert default_store() == Path.home() / ".ollama" / "models"
