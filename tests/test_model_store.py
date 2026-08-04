"""Local model weights live in the APP's folder -- and the app says so honestly.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

Maintainer 2026-08-04: "Make sure all local models are stored in the Open-Omniscience
directory." Both backends honour an environment variable, so the mechanism is small;
what needs pinning is everything around it.

  * THE AGREEMENT PROPERTY. Three call sites have to resolve the same HF directory --
    the cache PROBE, the weights DOWNLOAD, and the SERVER spawn. If they drift, the
    probe reports "not downloaded" for weights that are present and the activation
    guard refuses a start that would have worked. Nothing about that failure looks
    like a path bug from the outside.
  * AN OPERATOR'S OWN CHOICE IS NEVER RELOCATED. Someone who put their weights on a
    second drive did so deliberately.
  * A SETTING THAT CANNOT REACH ITS TARGET SAYS SO. An env var reaches processes we
    spawn; a systemd Ollama keeps its own store. Reporting the configured path as
    though it were the live one is the fabrication to avoid here.
  * MIGRATION NEVER LOSES A BYTE: copy first, delete only what was confirmed copied,
    and a killed copy leaves the source whole.
"""

from __future__ import annotations

import json

import pytest

from src.llm import model_store


@pytest.fixture()
def app_dir(tmp_path, monkeypatch):
    """An app data dir of our own, with no inherited store variables."""
    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: tmp_path)
    for var in ("OLLAMA_MODELS", "HF_HOME", "HF_HUB_CACHE"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


# --------------------------------------------------------------------------- #
#  Where things go
# --------------------------------------------------------------------------- #
def test_both_stores_default_into_the_app_folder(app_dir):
    assert model_store.ollama_store() == app_dir / "models" / "ollama"
    assert model_store.hf_home() == app_dir / "models" / "huggingface"


def test_the_launch_env_points_a_spawned_backend_at_them(app_dir):
    env = model_store.launch_env({"PATH": "/usr/bin"})
    assert env["OLLAMA_MODELS"] == str(app_dir / "models" / "ollama")
    assert env["HF_HOME"] == str(app_dir / "models" / "huggingface")
    assert env["PATH"] == "/usr/bin", "the ambient environment is preserved, not replaced"


def test_the_directories_are_created_so_a_backend_never_starts_into_nothing(app_dir):
    model_store.launch_env()
    assert (app_dir / "models" / "ollama").is_dir()
    assert (app_dir / "models" / "huggingface").is_dir()


# --------------------------------------------------------------------------- #
#  An explicit operator choice wins -- the negative-space twin of the default
# --------------------------------------------------------------------------- #
def test_an_operator_set_store_is_used_untouched(app_dir, monkeypatch, tmp_path):
    """Silently relocating several GB because an app preferred its own folder is not
    a default, it is a surprise."""
    elsewhere = tmp_path / "big-drive" / "ollama"
    monkeypatch.setenv("OLLAMA_MODELS", str(elsewhere))
    assert model_store.ollama_store() == elsewhere
    assert model_store.launch_env()["OLLAMA_MODELS"] == str(elsewhere)


def test_an_operator_set_hf_home_is_used_untouched(app_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    assert model_store.hf_home() == tmp_path / "hf"


def test_hf_hub_cache_is_normalised_to_its_home(app_dir, monkeypatch, tmp_path):
    """``HF_HUB_CACHE`` points AT the hub dir while ``HF_HOME`` contains it. Callers
    get one meaning rather than two."""
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf" / "hub"))
    assert model_store.hf_home() == tmp_path / "hf"


def test_an_unwritable_data_dir_still_yields_a_usable_environment(app_dir, monkeypatch):
    """Falling back to the backend's own default beats refusing to start."""

    def _boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(model_store.Path, "mkdir", _boom)
    env = model_store.launch_env({"PATH": "/usr/bin"})
    assert env["PATH"] == "/usr/bin"


# --------------------------------------------------------------------------- #
#  THE AGREEMENT PROPERTY
# --------------------------------------------------------------------------- #
def test_the_probe_and_the_spawn_resolve_the_same_hf_directory(app_dir):
    """A drift here makes the probe report "not downloaded" for weights that ARE
    downloaded, and the activation guard then refuses a start that would have worked."""
    from src.llm.vllm_lifecycle import hf_cache_dir

    assert hf_cache_dir() == model_store.hf_home() / "hub"
    spawn_home = model_store.launch_env()["HF_HOME"]
    assert hf_cache_dir().parent == type(app_dir)(spawn_home)


def test_the_download_env_agrees_with_both(app_dir, tmp_path):
    from src.llm.vllm_lifecycle import _install_env

    env = _install_env(tmp_path / "pipbuild")
    assert env["HF_HOME"] == model_store.launch_env()["HF_HOME"]
    assert env["TMPDIR"] == str(tmp_path / "pipbuild"), "the TMPDIR fix is not lost"


def test_an_explicit_hf_home_moves_all_three_together(app_dir, monkeypatch, tmp_path):
    """The twin: agreement must hold under an override too, or the operator's own
    directory becomes the one place they disagree."""
    monkeypatch.setenv("HF_HOME", str(tmp_path / "mine"))
    from src.llm.vllm_lifecycle import _install_env, hf_cache_dir

    assert hf_cache_dir() == tmp_path / "mine" / "hub"
    assert _install_env(tmp_path / "t")["HF_HOME"] == str(tmp_path / "mine")


# --------------------------------------------------------------------------- #
#  Reporting: configured is not the same claim as actual
# --------------------------------------------------------------------------- #
def test_the_report_flags_a_store_the_app_setting_cannot_reach(app_dir, monkeypatch):
    """A systemd-started daemon has its own environment. Saying "models are in the app
    folder" while they are in ~/.ollama would leave the operator no way to tell why."""
    legacy = app_dir / "home" / ".ollama" / "models"
    legacy.mkdir(parents=True)
    monkeypatch.setattr("src.backup.ollama_models.default_store", lambda: legacy)

    rep = model_store.store_report()
    assert rep["ollama"]["in_app_folder"] is False
    assert rep["ollama"]["detected"] == str(legacy)
    assert "systemd" in rep["ollama"]["note"]


def test_and_says_nothing_when_the_store_is_where_it_should_be(app_dir, monkeypatch):
    """The negative-space twin: a permanent warning would train the operator to
    ignore it."""
    monkeypatch.setattr(
        "src.backup.ollama_models.default_store", lambda: model_store.ollama_store()
    )
    rep = model_store.store_report()
    assert rep["ollama"]["in_app_folder"] is True
    assert "note" not in rep["ollama"]


# --------------------------------------------------------------------------- #
#  Migration
# --------------------------------------------------------------------------- #
def _seed_store(root, *, ref=("registry.ollama.ai", "library", "mini"), tag="v1", blobs=None):
    """A minimal but REAL Ollama store: manifests/<host>/<ns>/<model>/<tag> naming
    blobs/sha256-<hex>."""
    blobs = blobs or {"sha256-aaa": b"weights-a", "sha256-bbb": b"weights-b"}
    mdir = root / "manifests" / ref[0] / ref[1] / ref[2]
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / tag).write_text(
        json.dumps(
            {
                "config": {"digest": "sha256:aaa"},
                "layers": [{"digest": "sha256:bbb"}],
            }
        )
    )
    bdir = root / "blobs"
    bdir.mkdir(parents=True, exist_ok=True)
    for name, data in blobs.items():
        (bdir / name).write_bytes(data)
    return root


def test_migration_copies_manifests_and_blobs(app_dir):
    src = _seed_store(app_dir / "legacy")
    out = model_store.migrate_ollama_store(src)
    assert out["ok"] is True
    assert out["copied"] == 2
    dst = model_store.ollama_store()
    assert (dst / "blobs" / "sha256-aaa").read_bytes() == b"weights-a"
    assert (dst / "manifests" / "registry.ollama.ai" / "library" / "mini" / "v1").is_file()


def test_migration_leaves_the_source_alone_unless_asked(app_dir):
    src = _seed_store(app_dir / "legacy")
    model_store.migrate_ollama_store(src)
    assert (src / "blobs" / "sha256-aaa").is_file(), "a copy is not a move"


def test_deleting_the_source_is_a_separate_explicit_step(app_dir):
    src = _seed_store(app_dir / "legacy")
    out = model_store.migrate_ollama_store(src, delete_source=True)
    assert out["ok"] is True and out["removed"] >= 2
    assert not (src / "blobs" / "sha256-aaa").exists()


def test_an_existing_blob_is_skipped_never_re_copied(app_dir):
    """Content addressing means a name collision PROVES the contents match, so
    skipping can never lose data -- and re-copying would be gigabytes of pointless
    I/O."""
    src = _seed_store(app_dir / "legacy")
    model_store.migrate_ollama_store(src)
    again = model_store.migrate_ollama_store(src)
    assert again["copied"] == 0
    assert again["skipped"] == 2


def test_migrating_onto_itself_is_a_no_op_not_a_deletion(app_dir):
    """With ``delete_source`` this would otherwise remove the files it just "copied"
    onto themselves."""
    store = model_store.ollama_store()
    _seed_store(store)
    out = model_store.migrate_ollama_store(store, store, delete_source=True)
    assert out["ok"] is True and out["removed"] == 0
    assert (store / "blobs" / "sha256-aaa").is_file()


def test_an_absent_or_unreadable_source_is_a_reason_not_a_crash(app_dir):
    out = model_store.migrate_ollama_store(app_dir / "nope")
    assert out["ok"] is False
    assert "no model store" in out["reason"]

    empty = app_dir / "empty"
    empty.mkdir()
    out2 = model_store.migrate_ollama_store(empty)
    assert out2["ok"] is False
    assert "no readable models" in out2["reason"]
    assert "never elevates" in out2["reason"], "the protected-store case is named"


def test_a_partial_copy_leaves_the_source_completely_intact(app_dir, monkeypatch):
    """"Move" on a multi-GB store, interrupted halfway, is how an operator loses both
    copies. The delete only runs after the whole copy succeeded."""
    src = _seed_store(app_dir / "legacy")
    real = model_store.shutil.copy2
    calls = {"n": 0}

    def _flaky(a, b, *args, **kw):
        calls["n"] += 1
        if calls["n"] > 2:
            raise OSError("disk full")
        return real(a, b, *args, **kw)

    monkeypatch.setattr(model_store.shutil, "copy2", _flaky)
    out = model_store.migrate_ollama_store(src, delete_source=True)
    assert out["ok"] is False and out["removed"] == 0
    assert (src / "blobs" / "sha256-aaa").is_file()
    assert (src / "blobs" / "sha256-bbb").is_file()
