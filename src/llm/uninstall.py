"""Removing the local AI again — only ever what this app installed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ask 2026-08-12: *"Add an 'uninstall AI' button which will uninstall the
currently set backend, add the deletion of the local model as an option. If both vLLM
and Ollama are installed, add the option to uninstall both."*

THE LINE THIS MODULE DOES NOT CROSS is the one :func:`ollama_lifecycle.stop` already
draws for processes: *only ever what this app itself put there*. Applied to files that
means three categories, and keeping them apart is the whole design:

* **OURS.** The vLLM venv, which this app creates at a path it chose, and the model
  stores under ``data_dir()``. These are removed.
* **THE OPERATOR'S.** A store they pointed at with ``OLLAMA_MODELS`` or ``HF_HOME``.
  Their choice is the location, so it is REPORTED with its size and never touched — the
  same posture the store panel already takes toward a legacy cache it will not move.
* **THE SYSTEM'S.** The Ollama binary. It was installed by Ollama's own installer with
  root, may be a systemd unit, and may equally have come from a package manager whose
  database an ``rm`` would silently corrupt. This app can no more remove it than it can
  kill a daemon it did not spawn, so what it does is say so and hand over the commands.

A PARTIAL UNINSTALL IS REPORTED AS PARTIAL. The tempting shape is a button that says
"Uninstalled." whatever happened; the honest one returns what was removed, what was
kept, and why each thing was kept — because an operator who thinks the binary is gone
and finds it still serving next boot has been told something false about their machine.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

#: The documented Linux removal for an Ollama installed by its own script. NOT run by
#: this app — see the module docstring — and carried here so the UI can show the
#: operator exactly what to type rather than sending them to search for it.
#:
#: Deliberately NOT a "scripted uninstall": the same commands are wrong on a machine
#: where Ollama came from a package manager, and this app cannot tell the two apart.
OLLAMA_MANUAL_REMOVAL: tuple[str, ...] = (
    "sudo systemctl stop ollama",
    "sudo systemctl disable ollama",
    "sudo rm /etc/systemd/system/ollama.service",
    "sudo rm $(which ollama)",
)


def _dir_bytes(path: Path) -> int | None:
    """Bytes under ``path``, or None when it cannot be walked.

    None is not zero: an unreadable directory is an unknown size, and printing 0 GB
    beside a folder that holds twenty would be the fabricated measurement this project
    refuses everywhere else.
    """
    try:
        if not path.is_dir():
            return 0 if not path.exists() else None
    except OSError:
        return None
    total = 0
    try:
        for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
            for name in files:
                fp = Path(root) / name
                try:
                    # lstat, so a symlink is counted as the link it is rather than as
                    # the megabytes it points at -- an HF snapshot is mostly symlinks
                    # into blobs/, and following them double-counts every weight.
                    total += fp.lstat().st_size
                except OSError:
                    continue
    except OSError:
        return None
    return total


def _owned_by_app(path: Path) -> bool:
    """Is ``path`` inside the app's own data directory?

    The single test that decides whether this module may delete something. A path the
    operator chose sits outside it by construction, which is what makes "we only remove
    what we put there" checkable rather than a promise.

    NOT wrapped in a bare try/except any more, and the reason is worth the line: the
    first cut imported ``data_dir`` from the wrong module, the except swallowed the
    ImportError, and every path on the machine came back "not ours" — an uninstall
    button that removed nothing while reporting, politely and falsely, that the
    operator had chosen all of these locations themselves. Failing safe is not the same
    as working, and a guard that cannot tell "outside the data dir" from "I could not
    look" is not a guard. Only the path resolution is guarded now; a broken import is
    a bug and raises like one.

    COMPARED BY PATH COMPONENTS, never as a string prefix. ``startswith`` — which this
    used at first — answers True for a SIBLING whose name merely extends the data
    dir's: ``…/open-omniscience-old`` starts with ``…/open-omniscience`` and would have
    been claimed as ours and deleted. ``is_relative_to`` compares the parts, so a
    sibling is a sibling however it is spelled, and the containment this whole module
    rests on is checkable rather than textual.
    """
    from src.paths import data_dir

    try:
        return path.resolve().is_relative_to(Path(data_dir()).resolve())
    except OSError:  # an unresolvable path is not ours
        return False


def _store_entry(kind: str, path: Path) -> dict:
    """One model store, described: where, how big, and whether we may remove it."""
    ours = _owned_by_app(path)
    exists = False
    try:
        exists = path.exists()
    except OSError:
        exists = False
    return {
        "kind": kind,
        "path": str(path),
        "exists": exists,
        "bytes": _dir_bytes(path) if exists else 0,
        "removable": bool(ours and exists),
        "kept_reason": (
            None
            if ours
            else (
                "you chose this location yourself, so it is yours rather than this "
                "app's to delete. Remove it by hand if you want the space back."
            )
        ),
    }


def model_stores() -> list[dict]:
    """Every model store this app knows about, app-owned or not."""
    from src.llm.model_store import hf_home, legacy_hf_home, ollama_store

    out = [_store_entry("ollama", ollama_store()), _store_entry("huggingface", hf_home())]
    legacy = legacy_hf_home()
    if legacy is not None:
        e = _store_entry("huggingface-legacy", legacy)
        if e["exists"]:
            # Hugging Face's own default cache. Never ours even though this app may have
            # filled it before the store moved, so it is reported rather than removed.
            e["removable"] = False
            e["kept_reason"] = (
                "Hugging Face's own cache, outside this app's folder. Weights "
                "downloaded before the model store moved are still here."
            )
            out.append(e)
    return out


def _vllm_state() -> dict:
    """What removing vLLM would involve, without removing anything."""
    try:
        from src.llm import vllm_lifecycle

        venv = vllm_lifecycle.venv_dir()
        installed = vllm_lifecycle.is_installed()
        running = vllm_lifecycle.is_running()
    except Exception as exc:  # noqa: BLE001 - an unreadable backend is not an installed one
        return {"backend": "vllm", "installed": False, "error": str(exc)[:200]}
    return {
        "backend": "vllm",
        "installed": bool(installed),
        "running": bool(running),
        "path": str(venv),
        "bytes": _dir_bytes(venv) if installed else 0,
        # Ours by construction: this app created the venv at a path it chose.
        "removable": bool(installed) and _owned_by_app(venv),
    }


def _ollama_state() -> dict:
    """What removing Ollama would involve. The binary is never ours."""
    try:
        from src.llm import ollama_lifecycle

        installed = ollama_lifecycle.is_installed()
        running = ollama_lifecycle.is_running()
        binary = ollama_lifecycle.binary_path()
        ours = ollama_lifecycle.owns_daemon()
    except Exception as exc:  # noqa: BLE001
        return {"backend": "ollama", "installed": False, "error": str(exc)[:200]}
    return {
        "backend": "ollama",
        "installed": bool(installed),
        "running": bool(running),
        "path": binary,
        # THE ONE FIELD THAT MATTERS HERE. The binary was installed with root by
        # Ollama's own installer, and may equally have come from a package manager. This
        # app removing it would be exactly the overreach that stop() refuses for
        # processes, so it says so and shows the commands instead.
        "removable": False,
        "we_spawned_the_daemon": bool(ours),
        "kept_reason": (
            "the Ollama program itself was installed on your system with administrator "
            "rights — by its own installer, or by your package manager. This app did "
            "not put it there and will not remove it; the commands to do it yourself "
            "are below."
        ),
        "manual_removal": list(OLLAMA_MANUAL_REMOVAL),
    }


def uninstall_plan() -> dict:
    """What an uninstall WOULD do, read-only.

    Read before acting, and separately, because the answer is what the operator is
    consenting to: which backends are here, how many bytes each would free, and which
    parts this app cannot remove at all.
    """
    backends = [_vllm_state(), _ollama_state()]
    installed = [b["backend"] for b in backends if b.get("installed")]
    return {
        "backends": backends,
        "installed": installed,
        # The maintainer's "if both are installed, offer to uninstall both" is a fact
        # about the machine, computed rather than left to the UI to infer.
        "both_installed": len(installed) > 1,
        "stores": model_stores(),
        "method": (
            "This removes only what this app installed: the vLLM environment it created "
            "and the model folders inside its own data directory. A store you pointed "
            "elsewhere, and the Ollama program itself, are reported rather than deleted."
        ),
    }


def _rmtree(path: Path) -> dict:
    """Delete a directory tree, reporting rather than raising."""
    try:
        shutil.rmtree(path)
        return {"path": str(path), "removed": True}
    except FileNotFoundError:
        return {"path": str(path), "removed": True, "note": "already gone"}
    except OSError as exc:
        return {"path": str(path), "removed": False, "error": str(exc)[:200]}


def uninstall(*, backends: list[str], delete_models: bool = False) -> dict:
    """Remove the named backends, and optionally the models, reporting what happened.

    ``backends`` is explicit rather than derived: "the current backend" is a question
    with three different answers in this codebase (routing, provisioning, activation),
    and a destructive action must act on the one the operator was actually shown.
    """
    wanted = {str(b).strip().lower() for b in backends or []}
    unknown = sorted(wanted - {"vllm", "ollama"})
    wanted &= {"vllm", "ollama"}
    removed: list[dict] = []
    kept: list[dict] = []
    for name in unknown:
        kept.append({"what": name, "reason": "not a backend this app installs"})

    if "vllm" in wanted:
        state = _vllm_state()
        if not state.get("installed"):
            kept.append({"what": "vllm", "reason": "not installed here"})
        elif not state.get("removable"):
            kept.append(
                {
                    "what": "vllm",
                    "reason": (
                        f"its environment is at {state.get('path')}, outside this app's "
                        "folder, so it is not this app's to delete."
                    ),
                }
            )
        else:
            # STOP BEFORE DELETING, or the venv goes out from under a running server and
            # what the operator gets is a process serving from deleted files rather than
            # a clean uninstall. A refusal to stop (a server this app did not spawn) is
            # a refusal to uninstall, for the same reason.
            stopped: dict[str, Any] = {}
            try:
                from src.llm import vllm_lifecycle

                if state.get("running") or vllm_lifecycle.process_alive():
                    stopped = vllm_lifecycle.stop()
            except Exception as exc:  # noqa: BLE001
                stopped = {"stopped": False, "reason": str(exc)[:200]}
            if state.get("running") and not stopped.get("stopped"):
                kept.append(
                    {
                        "what": "vllm",
                        "reason": (
                            "its server is still running and this app could not stop it"
                            + (f": {stopped.get('reason')}" if stopped.get("reason") else "")
                            + ". Deleting the environment under a live server would "
                            "leave it serving from files that no longer exist."
                        ),
                    }
                )
            else:
                result = _rmtree(Path(state["path"]))
                result["what"] = "vllm"
                result["freed_bytes"] = state.get("bytes") if result.get("removed") else 0
                (removed if result.get("removed") else kept).append(
                    result
                    if result.get("removed")
                    else {"what": "vllm", "reason": result.get("error") or "could not delete"}
                )
                # The pip build directory is ours too, and left behind it is several GB
                # of nothing.
                try:
                    from src.llm.vllm_lifecycle import pip_tmpdir

                    build = pip_tmpdir()
                    if build.exists() and _owned_by_app(build):
                        _rmtree(build)
                except Exception:  # noqa: BLE001 - a leftover build dir is not a failure
                    pass

    if "ollama" in wanted:
        state = _ollama_state()
        if not state.get("installed"):
            kept.append({"what": "ollama", "reason": "not installed here"})
        else:
            # Stop it ONLY if we spawned it. The daemon may be systemd's, and stopping
            # somebody else's service is the same overreach as deleting their binary.
            try:
                from src.llm import ollama_lifecycle

                if ollama_lifecycle.owns_daemon():
                    ollama_lifecycle.stop()
            except Exception:  # noqa: BLE001
                pass
            kept.append(
                {
                    "what": "ollama",
                    "reason": state["kept_reason"],
                    "manual_removal": state["manual_removal"],
                }
            )

    if delete_models:
        for store in model_stores():
            if store["removable"]:
                result = _rmtree(Path(store["path"]))
                result["what"] = f"{store['kind']} models"
                result["freed_bytes"] = store.get("bytes") if result.get("removed") else 0
                (removed if result.get("removed") else kept).append(
                    result
                    if result.get("removed")
                    else {
                        "what": f"{store['kind']} models",
                        "reason": result.get("error") or "could not delete",
                    }
                )
            elif store["exists"]:
                kept.append({"what": f"{store['kind']} models", "reason": store["kept_reason"]})

    freed = sum(int(r.get("freed_bytes") or 0) for r in removed)
    return {
        "removed": removed,
        "kept": kept,
        "freed_bytes": freed,
        # COMPLETE means nothing was left behind that the operator asked to remove. It
        # is computed, not asserted: an Ollama uninstall is never complete by this
        # definition, which is the honest answer rather than a comfortable one.
        "complete": not kept,
        "models_deleted": bool(delete_models),
    }


__all__ = [
    "OLLAMA_MANUAL_REMOVAL",
    "model_stores",
    "uninstall",
    "uninstall_plan",
]
