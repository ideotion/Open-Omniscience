"""Ollama model-store DETECTION for the companion backup (maintainer 2026-06-18).

Ollama's official Linux install runs as a dedicated ``ollama`` system user, so the
model store is /usr/share/ollama/.ollama/models — NOT ~/.ollama/models — and it is
permission-protected (mode 0700). The backup used to look ONLY at ~/.ollama/models,
so on a stock Linux install it silently found nothing. These tests pin the fix:
candidate detection (incl. the service dir), and that a PROTECTED store degrades
LOUDLY with an actionable OLLAMA_MODELS hint instead of a silent empty result.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path

import src.backup.ollama_models as om


def _make_store(root: Path, ref_tag: str = "3b") -> Path:
    """A minimal valid Ollama store: one manifest + the blob it references."""
    store = root / "store"
    mdir = store / "manifests" / "registry.ollama.ai" / "library" / "llama3.2"
    mdir.mkdir(parents=True)
    (store / "blobs").mkdir()
    digest = "sha256:" + "a" * 64
    (store / "blobs" / ("sha256-" + "a" * 64)).write_bytes(b"x" * 10)
    (mdir / ref_tag).write_text(json.dumps({"layers": [{"digest": digest}]}), encoding="utf-8")
    return store


def test_candidate_stores_env_first_then_linux_service(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODELS", "/custom/models")
    monkeypatch.setattr(sys, "platform", "linux")
    cands = [str(p) for p in om.candidate_stores()]
    assert cands[0] == "/custom/models", "OLLAMA_MODELS must come first"
    assert any(c.endswith("/usr/share/ollama/.ollama/models") for c in cands), (
        "the protected Linux systemd service store must be a candidate"
    )


def test_default_store_finds_the_store_that_has_models(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    store = _make_store(tmp_path)
    # ~/.ollama/models is empty; the service store HAS the models -> pick it.
    monkeypatch.setattr(om, "candidate_stores", lambda: [tmp_path / "empty", store])
    assert str(om.default_store()) == str(store)


def test_env_store_always_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "explicit"))
    assert str(om.default_store()) == str(tmp_path / "explicit")


def test_store_status_reports_models_without_a_hint(tmp_path, monkeypatch):
    store = _make_store(tmp_path)
    monkeypatch.setenv("OLLAMA_MODELS", str(store))
    st = om.store_status()
    assert st["models"] and st["hint"] is None
    assert st["total_bytes"] == 10


def test_empty_store_degrades_loudly_with_an_actionable_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "empty"))
    st = om.store_status()
    assert not st["models"]
    assert st["hint"] and "OLLAMA_MODELS" in st["hint"]


def test_protected_store_is_named_and_explained_not_silently_empty(tmp_path, monkeypatch):
    """A store that EXISTS but we cannot read (the ollama-user service dir) must be
    surfaced as protected with the OLLAMA_MODELS fix — never a silent 'no models'.
    Simulated via PermissionError so the test is independent of the runner's uid."""
    protected = tmp_path / "service"
    (protected / "manifests").mkdir(parents=True)  # exists, but unreadable below
    chosen = tmp_path / "mine"  # our default, empty + readable

    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    monkeypatch.setattr(om, "candidate_stores", lambda: [chosen, protected])

    real_iterdir = pathlib.Path.iterdir

    def fake_iterdir(self):
        if str(self) == str(protected / "manifests"):
            raise PermissionError(13, "Permission denied")
        return real_iterdir(self)

    monkeypatch.setattr(pathlib.Path, "iterdir", fake_iterdir)

    # list_models must NOT raise on the protected dir (rglob guarded)
    assert om.list_models(protected) == []
    st = om.store_status()
    assert not st["models"]
    assert st["protected_store"] == str(protected)
    assert st["hint"] and "OLLAMA_MODELS" in st["hint"] and str(protected) in st["hint"]
