"""Uninstalling the local AI removes what this app installed, and nothing else.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The tests that matter here are the NEGATIVE ones. A deletion path is easy to prove
works and easy to get catastrophically wrong in the other direction, so most of what
follows drives paths the app must REFUSE to touch: a store the operator pointed
somewhere themselves, Hugging Face's own cache, the Ollama program, and a vLLM whose
server is still running.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.llm import uninstall as U


@pytest.fixture()
def app_dir(tmp_path, monkeypatch):
    """An app data directory, with the model stores under it."""
    root = tmp_path / "appdata"
    (root / "models" / "ollama").mkdir(parents=True)
    (root / "models" / "huggingface").mkdir(parents=True)
    monkeypatch.setattr("src.paths.data_dir", lambda: root)
    # AND on the CONSUMER, because `model_store` does a module-level
    # `from src.paths import data_dir`: that binds the function OBJECT into its own
    # namespace at import time, so patching `src.paths.data_dir` afterwards does not
    # reach it. Whether it reached it was decided by collection order — run this file
    # alone and `model_store` is first imported while the patch is live, so it binds
    # the lambda and everything passes; run anything that imports it first (CI does)
    # and `ollama_store()` answers with the REAL data dir while `_owned_by_app` checks
    # against this one, so an app-owned store reports itself unremovable. Same family
    # as the `sys.modules` note in `_patch_vllm` below: patch where the name is READ.
    monkeypatch.setattr("src.llm.model_store.data_dir", lambda: root)
    # The store resolvers read the env first, so clear any inherited choice: this
    # fixture is about the DEFAULT (app-owned) locations.
    monkeypatch.delenv("OLLAMA_MODELS", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    return root


def _patch_vllm(monkeypatch, *, stop: dict, pip_tmpdir=None):
    """Patch the REAL vllm_lifecycle's functions, never swap the module object.

    ``monkeypatch.setitem(sys.modules, ...)`` only wins while the submodule has not yet
    been attribute-bound on its package: ``from src.llm import vllm_lifecycle`` reads
    ``src.llm.vllm_lifecycle`` as an ATTRIBUTE once anything has imported it for real.
    So a module swap passed alone and silently stopped taking effect once another test
    in the file had triggered the import -- which is a fixture that works or not
    depending on collection order, and is exactly how a guard ends up proving nothing.
    """
    import src.llm.vllm_lifecycle as VL

    monkeypatch.setattr(VL, "stop", lambda: stop)
    monkeypatch.setattr(VL, "process_alive", lambda: False)
    if pip_tmpdir is not None:
        monkeypatch.setattr(VL, "pip_tmpdir", lambda: pip_tmpdir)


def _no_backends(monkeypatch):
    """Neither backend installed, so store tests are not about backend state."""
    monkeypatch.setattr(U, "_vllm_state", lambda: {"backend": "vllm", "installed": False})
    monkeypatch.setattr(
        U,
        "_ollama_state",
        lambda: {"backend": "ollama", "installed": False},
    )


# --------------------------------------------------------------------------- #
#  Ownership: the one test that decides whether anything may be deleted.
# --------------------------------------------------------------------------- #
def test_a_path_inside_the_app_folder_is_ours_and_one_outside_is_not(app_dir, tmp_path):
    assert U._owned_by_app(app_dir / "models" / "ollama") is True
    assert U._owned_by_app(tmp_path / "elsewhere") is False


def test_a_sibling_whose_name_merely_extends_the_data_dir_is_not_ours(app_dir):
    """The string-prefix trap, and the reason this is a components comparison.

    ``str.startswith`` says yes to ``…/open-omniscience-old`` for a data dir at
    ``…/open-omniscience`` — a DIFFERENT directory, quite possibly the operator's own
    copy of a previous install, claimed as ours and deleted. Nothing about the name
    makes it ours; only containment does.
    """
    sibling = app_dir.parent / (app_dir.name + "-old")
    sibling.mkdir()
    assert str(sibling).startswith(str(app_dir)), "the trap this test exists for"
    assert U._owned_by_app(sibling) is False
    assert U._owned_by_app(sibling / "models" / "ollama") is False


def test_the_ownership_test_raises_on_a_broken_import_rather_than_saying_not_ours(
    app_dir, monkeypatch
):
    """The first cut imported data_dir from the wrong module and swallowed the error.

    Every path on the machine then came back "not ours", so the uninstall button removed
    NOTHING while reporting, politely and falsely, that the operator had chosen all of
    these locations themselves. Failing safe is not the same as working: a guard that
    cannot tell "outside the data dir" from "I could not look" is not a guard, and this
    pins that it no longer pretends to be one.
    """
    def _boom():
        raise RuntimeError("data_dir is unavailable")

    monkeypatch.setattr("src.paths.data_dir", _boom)
    with pytest.raises(RuntimeError):
        U._owned_by_app(app_dir / "models" / "ollama")


# --------------------------------------------------------------------------- #
#  Model stores.
# --------------------------------------------------------------------------- #
def test_an_app_owned_store_is_removable_and_is_actually_removed(app_dir, monkeypatch):
    _no_backends(monkeypatch)
    store = app_dir / "models" / "ollama"
    (store / "manifests").mkdir()
    (store / "manifests" / "x").write_bytes(b"0" * 32)

    kinds = {s["kind"]: s for s in U.model_stores()}
    assert kinds["ollama"]["removable"] is True

    out = U.uninstall(backends=["vllm"], delete_models=True)
    assert not store.exists(), "an app-owned store must actually be deleted"
    assert any(r.get("what") == "ollama models" for r in out["removed"])


def test_a_store_the_operator_chose_is_reported_and_never_deleted(
    app_dir, tmp_path, monkeypatch
):
    """The negative space, and the one that would be unforgivable to get wrong."""
    _no_backends(monkeypatch)
    theirs = tmp_path / "big-external-drive" / "ollama"
    theirs.mkdir(parents=True)
    (theirs / "weights.bin").write_bytes(b"0" * 64)
    monkeypatch.setenv("OLLAMA_MODELS", str(theirs))

    kinds = {s["kind"]: s for s in U.model_stores()}
    assert kinds["ollama"]["removable"] is False
    assert "yours rather than this app" in (kinds["ollama"]["kept_reason"] or "")

    out = U.uninstall(backends=["vllm"], delete_models=True)
    assert theirs.exists() and (theirs / "weights.bin").exists()
    assert any(k.get("what") == "ollama models" for k in out["kept"])
    assert out["complete"] is False, "keeping something means the uninstall was partial"


def test_hugging_faces_own_cache_is_reported_not_removed(app_dir, tmp_path, monkeypatch):
    _no_backends(monkeypatch)
    legacy = tmp_path / "home-cache" / "huggingface"
    legacy.mkdir(parents=True)
    (legacy / "blob").write_bytes(b"0" * 16)
    monkeypatch.setattr(U, "_dir_bytes", lambda p: 16)
    monkeypatch.setattr("src.llm.model_store.legacy_hf_home", lambda: legacy)

    kinds = {s["kind"]: s for s in U.model_stores()}
    assert "huggingface-legacy" in kinds
    assert kinds["huggingface-legacy"]["removable"] is False

    U.uninstall(backends=["vllm"], delete_models=True)
    assert legacy.exists()


def test_models_are_left_alone_unless_delete_models_was_asked_for(app_dir, monkeypatch):
    _no_backends(monkeypatch)
    store = app_dir / "models" / "ollama"
    (store / "keep-me").write_bytes(b"0" * 8)
    U.uninstall(backends=["vllm"], delete_models=False)
    assert (store / "keep-me").exists()


# --------------------------------------------------------------------------- #
#  Sizes.
# --------------------------------------------------------------------------- #
def test_a_symlink_is_counted_as_a_link_not_as_the_weights_it_points_at(tmp_path):
    """An HF snapshot is mostly symlinks into blobs/, so following them would report
    roughly twice the disk a store actually uses."""
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    (blobs / "sha").write_bytes(b"0" * 10_000)
    snap = tmp_path / "snapshots"
    snap.mkdir()
    os.symlink(blobs / "sha", snap / "model.safetensors")

    total = U._dir_bytes(tmp_path)
    assert total is not None
    assert total < 12_000, f"the blob was counted twice: {total}"


def test_an_unreadable_directory_reports_unknown_rather_than_zero(tmp_path, monkeypatch):
    """None is not zero. Printing 0 GB beside a folder holding twenty would be the
    fabricated measurement this project refuses everywhere else."""
    monkeypatch.setattr(U.Path, "is_dir", lambda self: (_ for _ in ()).throw(OSError("nope")))
    assert U._dir_bytes(tmp_path) is None


# --------------------------------------------------------------------------- #
#  Backends.
# --------------------------------------------------------------------------- #
def test_ollama_is_always_kept_with_the_reason_and_the_commands(app_dir, monkeypatch):
    """The program was installed on the system with administrator rights. This app can
    no more delete it than it can kill a daemon it did not spawn."""
    monkeypatch.setattr(U, "_vllm_state", lambda: {"backend": "vllm", "installed": False})
    monkeypatch.setattr(
        U,
        "_ollama_state",
        lambda: {
            "backend": "ollama",
            "installed": True,
            "running": False,
            "removable": False,
            "kept_reason": "the Ollama program itself was installed on your system",
            "manual_removal": list(U.OLLAMA_MANUAL_REMOVAL),
        },
    )
    out = U.uninstall(backends=["ollama"], delete_models=False)
    assert out["removed"] == []
    kept = [k for k in out["kept"] if k["what"] == "ollama"]
    assert kept and kept[0]["manual_removal"] == list(U.OLLAMA_MANUAL_REMOVAL)
    assert out["complete"] is False


def test_a_running_vllm_that_cannot_be_stopped_is_not_deleted_under_its_own_server(
    app_dir, monkeypatch
):
    """Deleting the environment out from under a live server leaves it serving from
    files that no longer exist — a worse state than not uninstalling at all."""
    venv = app_dir / "vllm_venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text("home = /usr", encoding="utf-8")
    monkeypatch.setattr(
        U,
        "_vllm_state",
        lambda: {
            "backend": "vllm",
            "installed": True,
            "running": True,
            "path": str(venv),
            "bytes": 100,
            "removable": True,
        },
    )
    monkeypatch.setattr(U, "_ollama_state", lambda: {"backend": "ollama", "installed": False})

    _patch_vllm(monkeypatch, stop={"stopped": False, "reason": "not a server this app spawned"})
    out = U.uninstall(backends=["vllm"], delete_models=False)
    assert venv.exists(), "the venv must survive a server this app could not stop"
    kept = [k for k in out["kept"] if k["what"] == "vllm"]
    assert kept and "still running" in kept[0]["reason"]


def test_a_stopped_vllm_is_removed_and_the_freed_bytes_are_reported(app_dir, monkeypatch):
    """The positive twin: with nothing serving, the environment this app created goes."""
    venv = app_dir / "vllm_venv"
    (venv / "lib").mkdir(parents=True)
    (venv / "lib" / "big").write_bytes(b"0" * 2048)
    monkeypatch.setattr(
        U,
        "_vllm_state",
        lambda: {
            "backend": "vllm",
            "installed": True,
            "running": False,
            "path": str(venv),
            "bytes": 2048,
            "removable": True,
        },
    )
    monkeypatch.setattr(U, "_ollama_state", lambda: {"backend": "ollama", "installed": False})

    _patch_vllm(monkeypatch, stop={"stopped": True})
    out = U.uninstall(backends=["vllm"], delete_models=False)
    assert not venv.exists()
    assert out["freed_bytes"] == 2048
    assert out["complete"] is True


def test_an_unknown_backend_name_is_refused_rather_than_ignored(app_dir, monkeypatch):
    _no_backends(monkeypatch)
    out = U.uninstall(backends=["gpt5"], delete_models=False)
    assert any(k["what"] == "gpt5" for k in out["kept"])
    assert out["complete"] is False


def test_the_plan_computes_both_installed_rather_than_leaving_it_to_the_ui(
    app_dir, monkeypatch
):
    monkeypatch.setattr(
        U, "_vllm_state", lambda: {"backend": "vllm", "installed": True, "removable": True}
    )
    monkeypatch.setattr(
        U, "_ollama_state", lambda: {"backend": "ollama", "installed": True, "removable": False}
    )
    plan = U.uninstall_plan()
    assert plan["both_installed"] is True
    assert sorted(plan["installed"]) == ["ollama", "vllm"]

    monkeypatch.setattr(U, "_ollama_state", lambda: {"backend": "ollama", "installed": False})
    assert U.uninstall_plan()["both_installed"] is False


def test_uninstall_plan_removes_nothing(app_dir, monkeypatch):
    """Read-only means read-only: the plan is what an operator is shown BEFORE they
    consent, so it must be safe to call from a panel that loads on every refresh."""
    _no_backends(monkeypatch)
    store = app_dir / "models" / "ollama"
    (store / "still-here").write_bytes(b"0")
    U.uninstall_plan()
    assert (store / "still-here").exists()


def test_removing_the_pip_build_dir_never_reaches_outside_the_app_folder(
    app_dir, tmp_path, monkeypatch
):
    """The build dir is cleaned as a courtesy, and courtesies are exactly where an
    unchecked path slips through."""
    venv = app_dir / "vllm_venv"
    venv.mkdir()
    outside = tmp_path / "not-ours"
    outside.mkdir()
    (outside / "precious").write_bytes(b"0")
    monkeypatch.setattr(
        U,
        "_vllm_state",
        lambda: {
            "backend": "vllm",
            "installed": True,
            "running": False,
            "path": str(venv),
            "bytes": 0,
            "removable": True,
        },
    )
    monkeypatch.setattr(U, "_ollama_state", lambda: {"backend": "ollama", "installed": False})

    _patch_vllm(monkeypatch, stop={"stopped": True}, pip_tmpdir=outside)
    U.uninstall(backends=["vllm"], delete_models=False)
    assert (outside / "precious").exists(), "a build dir outside the app folder is not ours"


def test_the_real_ollama_probe_reports_not_removable_with_its_reason(app_dir, monkeypatch):
    """Drives ``_ollama_state`` itself rather than a stand-in for it.

    The test above monkeypatches that function, so it proves what the uninstall LOOP
    does with a state dict and nothing about how the dict is built — a mutation setting
    ``removable: True`` there passed all sixteen tests. The loop would still not delete
    the binary, but the PLAN would tell the operator it was going to, and the confirm
    would quote a size for something that is not going anywhere. That is the lie this
    pins shut.
    """

    import src.llm.ollama_lifecycle as OL

    monkeypatch.setattr(OL, "is_installed", lambda: True)
    monkeypatch.setattr(OL, "is_running", lambda: False)
    monkeypatch.setattr(OL, "binary_path", lambda: "/usr/local/bin/ollama")
    monkeypatch.setattr(OL, "owns_daemon", lambda: False)
    state = U._ollama_state()
    assert state["installed"] is True
    assert state["removable"] is False, "the Ollama program is never this app's to delete"
    assert state["manual_removal"] == list(U.OLLAMA_MANUAL_REMOVAL)
    assert "administrator rights" in state["kept_reason"]


def test_the_real_vllm_probe_only_calls_its_venv_removable_when_it_is_ours(
    app_dir, tmp_path, monkeypatch
):
    """The positive and negative of the same probe, for the same reason as above."""

    import src.llm.vllm_lifecycle as VL

    monkeypatch.setattr(VL, "is_installed", lambda: True)
    monkeypatch.setattr(VL, "is_running", lambda: False)

    monkeypatch.setattr(VL, "venv_dir", lambda: app_dir / "vllm_venv")
    assert U._vllm_state()["removable"] is True

    monkeypatch.setattr(VL, "venv_dir", lambda: tmp_path / "somewhere-else")
    assert U._vllm_state()["removable"] is False


def test_the_documented_ollama_removal_is_a_list_of_commands_not_a_script(app_dir):
    """Carried so the UI can SHOW them. Running them is refused deliberately: the same
    commands are wrong on a machine where Ollama came from a package manager, and this
    app cannot tell the two apart."""
    assert all(c.startswith("sudo ") for c in U.OLLAMA_MANUAL_REMOVAL)
    src = Path("src/llm/uninstall.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "Popen"):
        assert forbidden not in src, f"{forbidden}: this module must never execute anything"


# --------------------------------------------------------------------------- #
#  The endpoint contract.
# --------------------------------------------------------------------------- #
def test_the_endpoint_refuses_without_an_explicit_confirmation(app_dir):
    """There is no undo, so the confirmation is part of the contract rather than a
    frontend courtesy that a script could skip."""
    from fastapi import HTTPException

    from src.api.llm import UninstallRequest, llm_uninstall

    with pytest.raises(HTTPException) as exc:
        llm_uninstall(UninstallRequest(backends=["vllm"], confirm=False))
    assert exc.value.status_code == 400
    assert "undoable" in str(exc.value.detail)


def test_the_endpoint_refuses_when_no_backend_was_named(app_dir):
    from fastapi import HTTPException

    from src.api.llm import UninstallRequest, llm_uninstall

    with pytest.raises(HTTPException) as exc:
        llm_uninstall(UninstallRequest(backends=[], confirm=True))
    assert exc.value.status_code == 400


def test_the_uninstall_endpoints_are_not_gated_on_egress(app_dir):
    """Deleting files reaches no network, and refusing it under airplane mode would
    block the one operation an offline operator has every reason to run. Behavioural,
    not a source grep: the guard would be an early raise, so driving it is the check."""
    from src.api.llm import UninstallRequest, llm_uninstall, llm_uninstall_plan
    from src.ingest import activate_kill_switch, clear_kill_switch

    activate_kill_switch()
    try:
        assert "backends" in llm_uninstall_plan()
        out = llm_uninstall(UninstallRequest(backends=["vllm"], confirm=True))
        assert "removed" in out and "kept" in out
    finally:
        clear_kill_switch()
