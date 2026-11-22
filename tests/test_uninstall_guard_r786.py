"""R786: the AI uninstall never removes the app's data folder, a home folder, or anything that is not models.

Reproduced on main before the fix (temp data folder, never a real one): with
``HF_HUB_CACHE=<data>/hub``, ``hf_home()`` answered the PARENT -- the data folder itself -- which is
inside the data folder, so "ours", so listed as the removable "huggingface" store; "Uninstall,
delete models" then removed the whole data folder, the database and the keys with it. Now the store
is the hub cache folder itself, and an independent guard refuses any folder that is, or holds, the
data folder, a home folder, a drive, the database, another store, or files that are not models.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.llm import model_store
from src.llm import uninstall as U


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """A temp data folder with a database and keys, and no backend installed."""
    root = tmp_path / "appdata"
    (root / "keys").mkdir(parents=True)
    (root / "open_omniscience.db").write_bytes(b"corpus")
    (root / "keys" / "signing.pem").write_bytes(b"key")
    (root / "models" / "ollama").mkdir(parents=True)
    monkeypatch.setattr("src.paths.data_dir", lambda: root)
    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: root)  # patched where it is READ
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    for v in ("OLLAMA_MODELS", "HF_HOME", "HF_HUB_CACHE", "DATABASE_URL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(U, "_vllm_state", lambda: {"backend": "vllm", "installed": False})
    monkeypatch.setattr(U, "_ollama_state", lambda: {"backend": "ollama", "installed": False})
    import src.llm.vllm_lifecycle as VL

    monkeypatch.setattr(VL, "venv_dir", lambda: root / "vllm-venv")
    return root


def _hf(stores):
    return next(s for s in stores if s["kind"] == "huggingface")


def _intact(root: Path) -> bool:
    return (root / "open_omniscience.db").read_bytes() == b"corpus" and (root / "keys" / "signing.pem").exists()


def test_hf_hub_cache_at_data_hub_never_offers_the_data_folder(app, monkeypatch):
    """THE REPRODUCED ONE: the flag, then the actual removal."""
    monkeypatch.setenv("HF_HUB_CACHE", str(app / "hub"))
    (app / "hub" / "models--a--b").mkdir(parents=True)
    (app / "hub" / "models--a--b" / "w.bin").write_bytes(b"w" * 10)
    hf = _hf(U.model_stores())
    assert hf["path"] == str(app / "hub"), "the hub cache folder itself, never its parent"
    assert hf["bytes"] == 10, "sized alone"
    assert hf["removable"] is True
    out = U.uninstall(backends=[], delete_models=True)
    assert _intact(app), "the data folder, database and keys survive"
    assert not (app / "hub").exists() and any(r["what"] == "huggingface models" for r in out["removed"])


def test_hf_hub_cache_under_models_removes_only_that_folder(app, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(app / "models" / "x"))
    (app / "models" / "x" / "models--a--b").mkdir(parents=True)
    (app / "models" / "sibling").mkdir()
    U.uninstall(backends=[], delete_models=True)
    assert not (app / "models" / "x").exists()
    assert (app / "models" / "sibling").is_dir() and (app / "models").is_dir() and _intact(app)


@pytest.mark.parametrize("var", ["HF_HUB_CACHE", "OLLAMA_MODELS"])
def test_a_store_that_is_the_data_folder_itself_is_never_removable(app, monkeypatch, var):
    monkeypatch.setenv(var, str(app))
    stores = U.model_stores()
    s = next(x for x in stores if x["path"] == str(app))
    assert s["removable"] is False and "data folder" in s["kept_reason"]
    U.uninstall(backends=[], delete_models=True)
    assert _intact(app)


def test_a_store_outside_the_data_folder_is_kept(app, monkeypatch, tmp_path):
    (tmp_path / "mine" / "models--a--b").mkdir(parents=True)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "mine"))
    hf = _hf(U.model_stores())
    assert hf["removable"] is False and "you chose this location" in hf["kept_reason"]
    U.uninstall(backends=[], delete_models=True)
    assert (tmp_path / "mine" / "models--a--b").is_dir()


def test_the_guard_refuses_what_ownership_alone_would_allow(app, tmp_path, monkeypatch):
    home = Path(os.path.realpath(tmp_path / "home"))
    assert U.removal_refusal(home) and "home" in U.removal_refusal(home)
    assert "home" in U.removal_refusal(tmp_path)  # holds the home folder (and the data folder)
    assert "drive" in U.removal_refusal(Path(Path.cwd().anchor))
    assert "worked out" in U.removal_refusal("relative/models")
    assert "data folder" in U.removal_refusal(app)
    # Another store inside, or the same folder as another store.
    (app / "models" / "huggingface" / "hub").mkdir(parents=True)
    assert "another" in U.removal_refusal(app / "models", others=[app / "models" / "huggingface" / "hub"])
    assert "another" in U.removal_refusal(app / "models" / "ollama", others=[app / "models" / "ollama"])
    # Something that is not models, anywhere inside.
    (app / "models" / "ollama" / "deep").mkdir()
    (app / "models" / "ollama" / "deep" / "export.sqlite").write_bytes(b"x")
    assert "not model weights" in U.removal_refusal(app / "models" / "ollama")
    # The database wherever DATABASE_URL puts it.
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'elsewhere' / 'corpus.db'}")
    assert "database" in U.removal_refusal(tmp_path / "elsewhere")
    # A clean models folder passes.
    (app / "models" / "clean" / "models--a--b").mkdir(parents=True)
    assert U.removal_refusal(app / "models" / "clean") is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX links")
def test_a_link_cannot_make_a_folder_look_clean(app, tmp_path):
    (app / "models" / "huggingface" / "hub").mkdir(parents=True)
    os.symlink(app, app / "models" / "huggingface" / "hub" / "sneaky")
    # followed by realpath for the folder itself, never walked into: the walk does not follow links,
    # and a link INSIDE is removed as a link by rmtree, never its target.
    assert U.removal_refusal(app / "models" / "huggingface" / "hub") is None
    os.symlink(app, tmp_path / "linked-store")
    assert "data folder" in U.removal_refusal(tmp_path / "linked-store")


def test_the_guard_is_checked_again_just_before_the_delete(app, monkeypatch):
    """A database copied into the store after the plan was read is still refused."""
    monkeypatch.setenv("HF_HUB_CACHE", str(app / "hub"))
    (app / "hub").mkdir()
    stores = U.model_stores()
    assert _hf(stores)["removable"] is True
    monkeypatch.setattr(U, "model_stores", lambda: stores)  # the plan as it was read
    (app / "hub" / "open_omniscience.db").write_bytes(b"copy")
    out = U.uninstall(backends=[], delete_models=True)
    assert (app / "hub" / "open_omniscience.db").exists()
    assert any("not removable by the app" in k["reason"] for k in out["kept"]) and out["complete"] is False


def test_one_resolver_for_the_cache_folder(monkeypatch, tmp_path):
    import src.llm.vllm_lifecycle as VL

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HF_HUB_CACHE", "~/c")
    assert model_store.hf_hub_cache() == tmp_path / "c" == VL.hf_cache_dir()
    monkeypatch.delenv("HF_HUB_CACHE")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "h"))
    assert model_store.hf_hub_cache() == tmp_path / "h" / "hub" == VL.hf_cache_dir()


def test_the_storage_report_sizes_the_cache_folder_only(app, monkeypatch, tmp_path):
    (tmp_path / "u" / "big-personal-file").parent.mkdir(parents=True)
    (tmp_path / "u" / "big-personal-file").write_bytes(b"p" * 1000)
    (tmp_path / "u" / "my-models" / "models--a").mkdir(parents=True)
    (tmp_path / "u" / "my-models" / "models--a" / "w").write_bytes(b"w" * 7)
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "u" / "my-models"))
    hf = model_store.store_report()["huggingface"]
    assert hf["configured"] == str(tmp_path / "u" / "my-models") and hf["bytes"] == 7


def test_launch_makes_the_cache_folder_hf_will_use_not_a_stray_hub_beside_it(app, monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "disk" / "my-models"))
    model_store.launch_env({})
    assert (tmp_path / "disk" / "my-models").is_dir() and not (tmp_path / "disk" / "hub").exists()


def test_the_vllm_environment_is_checked_by_path_not_by_contents(app):
    """A venv carries certifi's cacert.pem; that must not make the app's own environment unremovable,
    while the path checks still refuse a venv that IS the data folder."""
    (app / "vllm-venv" / "lib").mkdir(parents=True)
    (app / "vllm-venv" / "lib" / "cacert.pem").write_bytes(b"c")
    assert U.removal_refusal(app / "vllm-venv", look_inside=False) is None
    assert "data folder" in U.removal_refusal(app, look_inside=False)
