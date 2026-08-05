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
        ),
        encoding="utf-8",
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


# --------------------------------------------------------------------------- #
#  Weights that were already on the disk must not become invisible
# --------------------------------------------------------------------------- #
def test_the_legacy_hf_cache_is_reported_when_it_holds_anything(app_dir, monkeypatch):
    """Moving the store into the app folder changed where NEW weights land -- and, not
    thought through at the time, made every EARLIER download invisible. Several GB of
    real data, and the operator told they had never downloaded it."""
    legacy = app_dir / "xdg" / "huggingface"
    (legacy / "hub").mkdir(parents=True)
    (legacy / "hub" / "blob").write_bytes(b"x" * 32)
    monkeypatch.setenv("XDG_CACHE_HOME", str(app_dir / "xdg"))

    hf = model_store.store_report()["huggingface"]
    assert hf["legacy"] == str(legacy)
    assert hf["legacy_bytes"] == 32
    assert "still usable" in hf["note"]
    assert "Nothing is moved or deleted for you" in hf["note"]


def test_an_empty_legacy_cache_is_not_mentioned_at_all(app_dir, monkeypatch):
    """The twin: a permanent note about an empty directory is noise, and noise is how
    a real one gets ignored."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(app_dir / "xdg"))
    hf = model_store.store_report()["huggingface"]
    assert "legacy" not in hf and "note" not in hf


def test_an_operator_set_hf_home_has_no_legacy_to_reconcile(app_dir, monkeypatch, tmp_path):
    """Their choice IS the location. Announcing a "legacy" elsewhere would invent a
    problem out of a deliberate decision."""
    monkeypatch.setenv("HF_HOME", str(tmp_path / "mine"))
    assert model_store.legacy_hf_home() is None


def test_the_probe_finds_a_model_in_either_location(app_dir, monkeypatch):
    """The activation guard is built on this probe, so a location it does not read is
    a start it refuses for a reason that is not true."""
    from src.llm.vllm_lifecycle import model_cache_state

    monkeypatch.setenv("XDG_CACHE_HOME", str(app_dir / "xdg"))
    repo = "models--org--Model-3B"

    assert model_cache_state("org/Model-3B")["cached"] is False

    legacy_snap = app_dir / "xdg" / "huggingface" / "hub" / repo / "snapshots" / "abc"
    legacy_snap.mkdir(parents=True)
    (legacy_snap / "config.json").write_text("{}", encoding="utf-8")
    found = model_cache_state("org/Model-3B")
    assert found["cached"] is True
    assert found["location"] == "legacy", "and it must SAY which, since they are not equivalent"

    app_snap = model_store.hf_home() / "hub" / repo / "snapshots" / "abc"
    app_snap.mkdir(parents=True)
    (app_snap / "config.json").write_text("{}", encoding="utf-8")
    assert model_cache_state("org/Model-3B")["location"] == "app", "the configured one wins"


def test_a_started_download_is_still_not_a_cached_model(app_dir, monkeypatch):
    """The pre-existing rule, re-pinned across the new two-location walk: huggingface_hub
    creates the tree as soon as a download STARTS, so an existence check would call a
    half-downloaded model ready."""
    from src.llm.vllm_lifecycle import model_cache_state

    monkeypatch.setenv("XDG_CACHE_HOME", str(app_dir / "xdg"))
    (app_dir / "xdg" / "huggingface" / "hub" / "models--org--M" / "snapshots").mkdir(parents=True)
    assert model_cache_state("org/M")["cached"] is False


# --------------------------------------------------------------------------- #
#  The store IN USE, with the size that belongs to it
#
#  Field report 2026-08-04: "when going inside the .ollama/models folder, I still see
#  several models. It seems the app downloaded the models into this folder." It did
#  not -- an `ollama pull` is served by the DAEMON, which writes to its own
#  OLLAMA_MODELS, and a systemd-managed daemon never sees the app's. The panel said
#  so in prose while its headline line printed the configured path and the configured
#  size, so the numbers pointed away from the answer.
# --------------------------------------------------------------------------- #
def test_the_report_sizes_the_store_that_is_actually_in_use(tmp_path, monkeypatch):
    from src.llm import model_store

    app = tmp_path / "app"
    foreign = tmp_path / "home" / ".ollama" / "models"
    (foreign / "blobs").mkdir(parents=True)
    (foreign / "blobs" / "sha256-abc").write_bytes(b"x" * 4096)
    monkeypatch.setattr(model_store, "data_dir", lambda: app)
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setattr("src.backup.ollama_models.default_store", lambda: foreign)

    r = model_store.store_report()["ollama"]
    assert r["in_app_folder"] is False
    assert r["detected"] == str(foreign)
    assert r["detected_bytes"] == 4096, "the size of the store that HOLDS the models"
    assert r["bytes"] in (0, None), "the app folder is empty, and says so"
    assert "Migrate the store" in r["note"]


def test_and_one_store_reports_one_size(tmp_path, monkeypatch):
    """The twin: when the app folder IS the store, the two numbers are the same fact
    and a second differing figure would invent a distinction that does not exist."""
    from src.llm import model_store

    app = tmp_path / "app"
    monkeypatch.setattr(model_store, "data_dir", lambda: app)
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    store = app / "models" / "ollama"
    (store / "blobs").mkdir(parents=True)
    (store / "blobs" / "sha256-def").write_bytes(b"y" * 2048)
    monkeypatch.setattr("src.backup.ollama_models.default_store", lambda: store)

    r = model_store.store_report()["ollama"]
    assert r["in_app_folder"] is True
    assert r["detected_bytes"] == r["bytes"] == 2048
    assert "note" not in r, "nothing to explain when there is nothing to reconcile"
