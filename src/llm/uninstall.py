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
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import record_text

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


#: R786: a name whose presence ANYWHERE inside a folder means it holds more than model weights -- the
#: app's database, its instance or data-volume marker, a backup's manifest or an export folder's record,
#: an encrypted volume, key material. A folder holding one is never removed whole by this module.
_NOT_MODELS_NAMES = frozenset({
    "open_omniscience.db", ".oo-instance-id", ".oos-volume", "volumes.json", "oo-folder-backup.json",
    "oo-export-request.json",
})
_NOT_MODELS_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".db-wal", ".ooenc", ".pem", ".key")

#: The prefix every guard refusal carries, so the page says WHY a folder is kept.
_NOT_REMOVABLE = "not removable by the app: "


def _real(path: Path | str) -> Path | None:
    """``path`` made absolute and resolved (links followed), or None when that cannot be done."""
    try:
        raw = os.path.expanduser(os.fspath(path))
        if not raw or not os.path.isabs(raw):
            return None
        return Path(os.path.realpath(raw))
    except (OSError, ValueError):
        return None


def _holds_more_than_models(root: Path, *, names_only: bool = False) -> str | None:
    """The first sign that ``root`` holds something other than model weights, or None. Walked
    without following links (a link cannot make a folder look clean), and a folder that cannot be
    walked fully is not called clean either: fail closed. ``names_only`` looks for the app's own
    marker names alone (the vLLM environment, whose packages legitimately carry ``.pem`` bundles,
    ``.db`` fixtures and folders named ``keys``)."""
    failed: list[OSError] = []
    try:
        for _cur, dirs, files in os.walk(root, onerror=failed.append, followlinks=False):
            for name in [*dirs, *files]:
                low = name.lower()
                if low in _NOT_MODELS_NAMES or (
                        not names_only and (low.endswith(_NOT_MODELS_SUFFIXES) or low == "keys")):
                    return "it holds files that are not model weights (the app's data, a backup, or keys)"
    except OSError:
        return "it could not be looked through completely"
    if failed and not all(isinstance(e, FileNotFoundError) for e in failed):
        return "it could not be looked through completely"
    return None


def removal_refusal(path: Path | str, *, others: Sequence[Path | str] = (), look_inside: bool | str = True) -> str | None:
    """See :func:`_removal_refusal`. Never raises: a question it cannot answer (no home folder, a data
    folder whose drive is gone) is a refusal, so a half-done uninstall still reports what it did."""
    try:
        return _removal_refusal(path, others=others, look_inside=look_inside)
    except Exception:  # noqa: BLE001 - fail closed, and keep the partial result reportable
        return _NOT_REMOVABLE + "its location could not be worked out"


def _removal_refusal(path: Path | str, *, others: Sequence[Path | str], look_inside: bool | str) -> str | None:
    """Why the folder ``path`` must NEVER be removed whole by this app, or None (R786).

    Independent of :func:`_owned_by_app`, and checked on every removal: being inside the data folder
    is what makes a store the app's, and is no proof that the folder is only models. ``HF_HUB_CACHE``
    pointed at ``<data>/hub`` made the old ``hf_home()`` answer the data folder ITSELF -- inside it, so
    "ours", so offered for deletion as "the Hugging Face models", database and keys with it.

    Refused: a folder that cannot be resolved; a whole drive; the home folder or a folder holding it;
    the app's data folder or a folder holding it; a folder holding the app's database (wherever
    ``DATABASE_URL`` puts it) or any OTHER store in ``others`` (or the same folder as one); and a
    folder whose contents show it holds more than models (:func:`_holds_more_than_models`). The content
    look is narrowed (``look_inside="names"``) for the vLLM environment, and skipped (``False``) for its
    build folder, which the app made itself; the path checks apply to both."""
    real = _real(path)
    if real is None:
        return _NOT_REMOVABLE + "its location could not be worked out"
    try:
        given = os.path.expanduser(os.fspath(path))
        if os.path.lexists(given) and not os.path.exists(given):
            return _NOT_REMOVABLE + "it is a link that leads nowhere"  # dangling, or a loop
        present, folder = os.path.lexists(real), real.is_dir()
    except (OSError, ValueError):
        return _NOT_REMOVABLE + "it could not be looked at"
    if present and not folder:
        # A file (the database itself, pointed at by a variable), a link that leads nowhere or loops.
        return _NOT_REMOVABLE + "it is not a folder"
    if real == Path(real.anchor):
        return _NOT_REMOVABLE + "it is a whole drive"
    home = _real(Path.home())
    if home is None or real == home or home.is_relative_to(real):
        return _NOT_REMOVABLE + "it is your home folder, or holds it"
    from src.paths import data_dir

    data = _real(data_dir())
    if data is None or real == data or data.is_relative_to(real):
        return _NOT_REMOVABLE + "it is the app's own data folder, or holds it"
    db_url = os.getenv("DATABASE_URL") or ""
    if db_url.startswith("sqlite:///"):
        # A relative file is relative to the folder the app started in, as SQLite reads it.
        db = _real(os.path.join(os.getcwd(), os.path.expanduser(db_url.removeprefix("sqlite:///"))))
        if db is None:
            return _NOT_REMOVABLE + "where the app's database is could not be worked out"
        if db.is_relative_to(real):
            return _NOT_REMOVABLE + "it holds the app's database"
    for other in others:
        o = _real(other)
        if o is None:
            continue  # an unresolvable other store cannot be inside this one by any path we can see
        if o == real or o.is_relative_to(real):
            return _NOT_REMOVABLE + "it is, or holds, another of the app's folders"
    why = (_holds_more_than_models(real, names_only=look_inside == "names")
           if look_inside and folder else None)
    return None if why is None else _NOT_REMOVABLE + why


def _store_paths() -> list[tuple[str, Path]]:
    from src.llm.model_store import hf_home, hf_hub_cache, ollama_store

    # R786: the hub cache folder ITSELF, never ``hf_home()`` (the PARENT of HF_HUB_CACHE).
    out = [("ollama", ollama_store()), ("huggingface", hf_hub_cache())]
    if not (os.getenv("HF_HUB_CACHE") or "").strip():
        # The download chunk cache recent huggingface_hub keeps beside ``hub`` (it can hold GBs) -- a
        # store of its own, guarded like the others, so "delete models" still frees it. Only when the
        # cache is under HF_HOME: with HF_HUB_CACHE set, the parent is not a Hugging Face home.
        out.append(("huggingface-xet", hf_home() / "xet"))
    return out


def _other_folders(own: Path) -> list[Path]:
    """Every folder this module knows besides ``own``: the other stores and the vLLM environment."""
    out = [p for _k, p in _store_paths() if p != own]
    from src.llm.model_store import legacy_hf_home

    legacy = legacy_hf_home()
    if legacy is not None and legacy != own:
        out.append(legacy)  # Hugging Face's own cache is never removed, so never removed from inside either
    try:
        from src.llm import vllm_lifecycle

        venv = vllm_lifecycle.venv_dir()
        if venv != own:
            out.append(venv)
    except Exception:  # noqa: BLE001 - a missing backend has no folder to protect
        pass
    return out


def _store_not_ours(path: Path) -> str | None:
    """Why a model store is NOT the app's to remove, or None (R786).

    Inside the data folder is not enough: a store is the app's only BELOW its models folder
    (``<data>/models``), so a variable pointed at ``<data>/osm_regions`` or ``<data>/keys`` is never
    removed as "models". And when the data folder IS the person's home folder, a drive, a standard home
    folder or a mount point (``data_scope.folder_scope``), nothing in it is called the app's models --
    there ``<data>/models`` may be theirs."""
    from src.llm.model_store import app_models_root
    from src.paths import data_dir
    from src.safety.data_scope import folder_scope

    if not _owned_by_app(path):
        return ("you chose this location yourself, so it is yours rather than this "
                "app's to delete. Remove it by hand if you want the space back.")
    models, real = _real(app_models_root()), _real(path)
    if models is None or real is None or real == models or not real.is_relative_to(models):
        return (_NOT_REMOVABLE + "it is inside the app's data folder but not in its models folder, "
                "so the app does not treat it as only models. Remove it by hand if you want the space back.")
    scope = folder_scope(data_dir())
    # Its LOCATION decides here (a drive, the home folder or above it, a standard home folder, a mount
    # point, or a folder that cannot be listed). "shared_folder" alone does not: it reads the app's own
    # ``models`` as possibly the person's, which would refuse every store of a data folder chosen with
    # OO_DATA_DIR -- and the store is already confined to ``<data>/models`` above.
    if scope.get("broad", True) and scope.get("reason") != "shared_folder":
        return (_NOT_REMOVABLE + "the app's data folder is also a folder of your own (your home folder, a drive...), so the app does "
                "not tell its models from yours there. Remove them by hand if you want the space back.")
    return None


def _store_entry(kind: str, path: Path) -> dict:
    """One model store, described: where, how big, and whether we may remove it."""
    try:
        not_ours = _store_not_ours(path)
    except Exception:  # noqa: BLE001 - fail closed
        not_ours = _NOT_REMOVABLE + "its location could not be worked out"
    ours = not_ours is None
    exists = False
    try:
        exists = path.exists()
    except OSError:
        exists = False
    guard = removal_refusal(path, others=_other_folders(path)) if (ours and exists) else None
    return {
        "kind": kind,
        "path": str(path),
        "exists": exists,
        "bytes": _dir_bytes(path) if exists else 0,
        "removable": bool(ours and exists and guard is None),
        "kept_reason": guard if guard is not None else not_ours,
    }


def model_stores() -> list[dict]:
    """Every model store this app knows about, app-owned or not."""
    from src.llm.model_store import legacy_hf_home

    out = [_store_entry(kind, path) for kind, path in _store_paths()]
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
        return {"backend": "vllm", "installed": False, "error": record_text(exc, limit=200)}
    # R786: the path guard, by path only (a venv legitimately carries ``.pem`` certificate bundles).
    guard = None
    if installed and _owned_by_app(venv):
        guard = (removal_refusal(venv, others=[p for _k, p in _store_paths()], look_inside="names")
                 if (venv / "pyvenv.cfg").is_file() else _NOT_REMOVABLE + "it does not look like a Python environment")
    return {
        "backend": "vllm",
        "installed": bool(installed),
        "running": bool(running),
        "path": str(venv),
        "bytes": _dir_bytes(venv) if installed else 0,
        # Ours by construction: this app created the venv at a path it chose. R786: and never a folder
        # that is, or holds, the data folder, the home folder or a model store.
        "removable": bool(installed) and _owned_by_app(venv) and guard is None,
        "kept_reason": guard,
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
        return {"backend": "ollama", "installed": False, "error": record_text(exc, limit=200)}
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
            "elsewhere, and the Ollama program itself, are reported rather than deleted. "
            "A folder that is, or holds, the app's data folder, your home folder, the "
            "database or anything that is not models is never removed, wherever it is. "
            "A Hugging Face sign-in token, if you saved one, is kept."
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
        return {"path": str(path), "removed": False, "error": record_text(exc, limit=200)}


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
                        state.get("kept_reason")
                        or f"its environment is at {state.get('path')}, outside this app's "
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
                stopped = {"stopped": False, "reason": record_text(exc, limit=200)}
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
                    if build.exists() and _owned_by_app(build) and removal_refusal(
                            build, others=[p for _k, p in _store_paths()], look_inside=False) is None:
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
            # R786: looked at AGAIN just before the delete, so a folder that changed since the plan
            # was read (a database copied into it, a variable re-pointed) is still refused.
            again = removal_refusal(store["path"], others=_other_folders(Path(store["path"]))) if store["removable"] else None
            if again is not None:
                kept.append({"what": f"{store['kind']} models", "reason": again})
            elif store["removable"]:
                # The folder checked is the folder removed: its resolved path, not the spelling.
                result = _rmtree(_real(store["path"]) or Path(store["path"]))
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
    "removal_refusal",
    "uninstall",
    "uninstall_plan",
]
