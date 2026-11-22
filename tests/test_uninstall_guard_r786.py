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
    """THE REPRODUCED ONE: the flag, then the actual removal. The store is the hub folder itself, sized
    alone; it sits outside the app's models folder, so it is kept with its reason, and nothing of the
    data folder is touched."""
    monkeypatch.setenv("HF_HUB_CACHE", str(app / "hub"))
    (app / "hub" / "models--a--b").mkdir(parents=True)
    (app / "hub" / "models--a--b" / "w.bin").write_bytes(b"w" * 10)
    hf = _hf(U.model_stores())
    assert hf["path"] == str(app / "hub"), "the hub cache folder itself, never its parent"
    assert hf["bytes"] == 10, "sized alone"
    assert hf["removable"] is False and "not in its models folder" in hf["kept_reason"]
    out = U.uninstall(backends=[], delete_models=True)
    assert _intact(app), "the data folder, database and keys survive"
    assert (app / "hub" / "models--a--b" / "w.bin").exists()
    assert [r["what"] for r in out["removed"]] == ["ollama models"]  # the app's own store still goes


@pytest.mark.parametrize("name", ["osm_regions", "keys", "backups"])
def test_a_store_pointed_at_other_app_data_is_never_removed(app, monkeypatch, name):
    (app / name).mkdir(exist_ok=True)
    (app / name / "europe.pbf").write_bytes(b"map")
    monkeypatch.setenv("HF_HUB_CACHE", str(app / name))
    assert _hf(U.model_stores())["removable"] is False
    U.uninstall(backends=[], delete_models=True)
    assert (app / name / "europe.pbf").exists() and _intact(app)


def test_a_data_folder_that_is_the_home_folder_removes_no_models(tmp_path, monkeypatch):
    """R711 allows the data folder to be a home folder; there "inside the data folder" proves nothing."""
    home = tmp_path / "home"
    (home / "models" / "ollama" / "blobs").mkdir(parents=True)
    (home / "Documents").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("src.paths.data_dir", lambda: home)
    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: home)
    for v in ("OLLAMA_MODELS", "HF_HOME", "HF_HUB_CACHE", "DATABASE_URL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(U, "_vllm_state", lambda: {"backend": "vllm", "installed": False})
    monkeypatch.setattr(U, "_ollama_state", lambda: {"backend": "ollama", "installed": False})
    stores = U.model_stores()
    assert not any(s["removable"] for s in stores)
    U.uninstall(backends=[], delete_models=True)
    assert (home / "models" / "ollama" / "blobs").is_dir()


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
    monkeypatch.setenv("HF_HUB_CACHE", str(app / "models" / "hub2"))
    (app / "models" / "hub2").mkdir()
    stores = U.model_stores()
    assert _hf(stores)["removable"] is True
    monkeypatch.setattr(U, "model_stores", lambda: stores)  # the plan as it was read
    (app / "models" / "hub2" / "open_omniscience.db").write_bytes(b"copy")
    out = U.uninstall(backends=[], delete_models=True)
    assert (app / "models" / "hub2" / "open_omniscience.db").exists()
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
    env = model_store.launch_env({"HF_HUB_CACHE": str(tmp_path / "disk" / "my-models"), "HF_HOME": "/theirs"})
    assert (tmp_path / "disk" / "my-models").is_dir() and not (tmp_path / "disk" / "hub").exists()
    assert env["HF_HOME"] == "/theirs", "the person's own HF_HOME is never overridden with the cache's parent"


def test_the_vllm_environment_is_checked_by_path_not_by_contents(app):
    """A venv carries certifi's cacert.pem; that must not make the app's own environment unremovable,
    while the path checks still refuse a venv that IS the data folder."""
    (app / "vllm-venv" / "lib").mkdir(parents=True)
    (app / "vllm-venv" / "lib" / "cacert.pem").write_bytes(b"c")
    assert U.removal_refusal(app / "vllm-venv", look_inside=False) is None
    assert "data folder" in U.removal_refusal(app, look_inside=False)


def test_a_store_variable_pointing_at_a_file_is_never_offered(app, monkeypatch):
    """OLLAMA_MODELS at the database file: the plan offered the database as a store to delete."""
    (app / "models" / "corpus-copy.db").write_bytes(b"copy")
    monkeypatch.setenv("OLLAMA_MODELS", str(app / "models" / "corpus-copy.db"))
    s = next(x for x in U.model_stores() if x["kind"] == "ollama")
    assert s["removable"] is False and "not a folder" in s["kept_reason"]
    U.uninstall(backends=[], delete_models=True)
    assert _intact(app)


@pytest.mark.skipif(os.name == "nt", reason="POSIX links")
def test_a_looping_or_dangling_link_is_refused_by_the_guard_itself(app, tmp_path):
    os.symlink(app / "loopb", app / "loopa")
    os.symlink(app / "loopa", app / "loopb")
    os.symlink(tmp_path / "nowhere", app / "dangling")
    for p in (app / "loopa", app / "dangling"):
        assert U.removal_refusal(p) is not None, p


def test_the_hf_download_chunk_cache_is_a_store_too_and_the_token_is_kept(app):
    hf = app / "models" / "huggingface"
    (hf / "hub" / "models--a").mkdir(parents=True)
    (hf / "xet" / "chunks").mkdir(parents=True)
    (hf / "xet" / "chunks" / "c").write_bytes(b"c" * 5)
    (hf / "token").write_text("t", encoding="utf-8")
    kinds = {s["kind"]: s for s in U.model_stores()}
    assert kinds["huggingface-xet"]["removable"] is True and kinds["huggingface-xet"]["bytes"] == 5
    U.uninstall(backends=[], delete_models=True)
    assert not (hf / "hub").exists() and not (hf / "xet").exists() and (hf / "token").exists()
    assert "token" in U.uninstall_plan()["method"]


def test_the_legacy_hf_cache_is_never_removed_from_inside_another_store(app, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(app / "models" / "cache"))
    (app / "models" / "cache" / "huggingface" / "hub").mkdir(parents=True)
    monkeypatch.setenv("OLLAMA_MODELS", str(app / "models" / "cache"))
    s = next(x for x in U.model_stores() if x["kind"] == "ollama")
    assert s["removable"] is False and "another" in s["kept_reason"]


def test_a_refused_vllm_environment_says_the_guard_s_reason(app, monkeypatch):
    import src.llm.vllm_lifecycle as VL

    monkeypatch.undo()  # drop the stubbed _vllm_state, keep nothing else from the fixture
    monkeypatch.setattr("src.paths.data_dir", lambda: app)
    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: app)
    monkeypatch.setattr(VL, "venv_dir", lambda: app)
    (app / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    monkeypatch.setattr(VL, "is_installed", lambda: True)
    monkeypatch.setattr(VL, "is_running", lambda: False)
    st = U._vllm_state()
    assert st["removable"] is False and "more than a Python environment" in st["kept_reason"]
    # Even a data folder holding ONLY an environment's shape is refused by the path check.
    bare = app / "models" / "bare"
    (bare / "bin").mkdir(parents=True)
    (bare / "pyvenv.cfg").write_text("x", encoding="utf-8")
    monkeypatch.setattr("src.paths.data_dir", lambda: bare)
    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: bare)
    monkeypatch.setattr(VL, "venv_dir", lambda: bare)
    assert "data folder" in U._vllm_state()["kept_reason"]
    monkeypatch.setattr("src.paths.data_dir", lambda: app)
    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: app)
    # And a folder that is not a Python environment at all is never removed as vLLM's.
    (app / "pyvenv.cfg").unlink()
    (app / "models" / "venvish").mkdir()
    monkeypatch.setattr(VL, "venv_dir", lambda: app / "models" / "venvish")
    assert "Python environment" in U._vllm_state()["kept_reason"]
    # A backup folder the variable points at is refused by its contents, even shaped like a venv.
    (app / "backups").mkdir()
    (app / "backups" / "pyvenv.cfg").write_text("x", encoding="utf-8")
    (app / "backups" / "oo-folder-backup.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(VL, "venv_dir", lambda: app / "backups")
    assert U._vllm_state()["removable"] is False


def test_the_guard_never_raises_into_a_half_done_uninstall(app, monkeypatch):
    """No home folder (RuntimeError) is a refusal, never an exception that loses what was removed."""
    def boom():
        raise RuntimeError("no home")
    monkeypatch.setattr(U.Path, "home", staticmethod(boom))
    assert "worked out" in U.removal_refusal(app / "models" / "ollama")


def test_a_relative_database_address_is_resolved_where_sqlite_reads_it(app, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "here").mkdir()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///here/rel.db")
    assert "database" in U.removal_refusal(tmp_path / "here")


@pytest.mark.parametrize("marker", ["volumes.json", "oo-folder-backup.json", "vol-00001.ooenc", "keys",
                                    "analytics.duckdb", "part.oopart"])
def test_a_store_holding_a_backup_keys_or_app_data_is_never_removed(app, marker):
    store = app / "models" / "ollama"
    (store / "deep").mkdir(parents=True, exist_ok=True)
    (store / "deep" / marker).mkdir() if marker == "keys" else (store / "deep" / marker).write_bytes(b"x")
    assert next(s for s in U.model_stores() if s["kind"] == "ollama")["removable"] is False
    U.uninstall(backends=[], delete_models=True)
    assert (store / "deep" / marker).exists()


def test_a_dataset_repo_s_own_files_do_not_block_the_hugging_face_store(app):
    hub = app / "models" / "huggingface" / "hub"
    (hub / "datasets--x--y" / "snapshots" / "abc").mkdir(parents=True)
    (hub / "datasets--x--y" / "snapshots" / "abc" / "index.sqlite").write_bytes(b"d")
    (hub / "models--a--b" / "snapshots" / "r" / "keys").mkdir(parents=True)
    assert _hf(U.model_stores())["removable"] is True
    (hub / "models--a--b" / "snapshots" / "r" / "oo-folder-backup.json").write_text("{}", encoding="utf-8")
    assert _hf(U.model_stores())["removable"] is False, "the app's own marker names count everywhere"


def test_a_folder_that_cannot_be_walked_is_not_called_clean(app, monkeypatch):
    def walk(root, onerror=None, followlinks=False):
        onerror(PermissionError(13, "denied"))
        return iter(())
    monkeypatch.setattr(U.os, "walk", walk)
    assert "looked through" in U.removal_refusal(app / "models" / "ollama")


def test_two_stores_at_one_folder_protect_each_other(app, monkeypatch):
    (app / "models" / "shared").mkdir()
    monkeypatch.setenv("OLLAMA_MODELS", str(app / "models" / "shared"))
    monkeypatch.setenv("HF_HUB_CACHE", str(app / "models" / "shared"))
    assert not any(s["removable"] for s in U.model_stores() if s["kind"] in ("ollama", "huggingface"))


def test_the_columnar_store_is_protected_wherever_it_is(app, monkeypatch):
    monkeypatch.setenv("OO_COLUMNAR_DIR", str(app / "models" / "ollama" / "col"))
    assert next(s for s in U.model_stores() if s["kind"] == "ollama")["removable"] is False


@pytest.mark.parametrize("extra", ["custody_ed25519.pem", "vol-00001.ooenc", "keys"])
def test_a_venv_variable_pointed_at_keys_or_backups_never_removes_them(app, monkeypatch, extra):
    import src.llm.vllm_lifecycle as VL

    monkeypatch.undo()
    monkeypatch.setattr("src.paths.data_dir", lambda: app)
    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: app)
    target = app / "somewhere"
    (target / "bin").mkdir(parents=True)
    (target / "pyvenv.cfg").write_text("x", encoding="utf-8")
    (target / extra).mkdir() if extra == "keys" else (target / extra).write_bytes(b"k")
    monkeypatch.setattr(VL, "venv_dir", lambda: target)
    monkeypatch.setattr(VL, "is_installed", lambda: True)
    monkeypatch.setattr(VL, "is_running", lambda: False)
    st = U._vllm_state()
    assert st["removable"] is False and "more than a Python environment" in st["kept_reason"]
    out = U.uninstall(backends=["vllm"])
    assert (target / extra).exists() and any(k["what"] == "vllm" for k in out["kept"])


def test_a_used_vllm_environment_is_still_removable(app, monkeypatch):
    """The app's own files at the environment's top (log, journals, install record) are part of it."""
    import src.llm.vllm_lifecycle as VL

    venv = app / "vllm_venv"
    for d in ("bin", "lib", "include"):
        (venv / d).mkdir(parents=True)
    for f in ("pyvenv.cfg", ".gitignore", ".oo_vllm_installed.json", "install_attempts.jsonl", "server.log",
              "server.log.1", "start_attempts.jsonl"):
        (venv / f).write_text("x", encoding="utf-8")
    monkeypatch.undo()
    monkeypatch.setattr("src.paths.data_dir", lambda: app)
    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: app)
    monkeypatch.setattr(VL, "venv_dir", lambda: venv)
    monkeypatch.setattr(VL, "is_installed", lambda: True)
    monkeypatch.setattr(VL, "is_running", lambda: False)
    assert U._vllm_state()["removable"] is True


def test_the_columnar_folder_helper_the_guard_imports_exists():
    from src.analytics.columnar import _store_dir

    assert callable(_store_dir), "renamed: the uninstall guard would silently lose the columnar store"
