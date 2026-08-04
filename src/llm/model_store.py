"""Where local model weights live -- inside the app's own folder, by default.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer, 2026-08-04: "Make sure all local models are stored in the
Open-Omniscience directory. Currently Ollama models are stored in '.ollama' in
/user/home, move them to the app's folder."

Both backends already honour an environment variable for this -- Ollama reads
``OLLAMA_MODELS``, Hugging Face reads ``HF_HOME``/``HF_HUB_CACHE`` -- so the app does
not need to fight either one. It needs to set them, and to be honest about the one
case where setting them does nothing.

THE HONEST LIMIT, stated first because it is the thing most easily fabricated: an
environment variable reaches a process THIS APP SPAWNS. An Ollama daemon started by
systemd or launchd, or by the operator in their own terminal, has its own
environment and keeps using its own store. So:

  * models pulled through a daemon this app started land in the app folder;
  * a daemon someone else started keeps its own store, and :func:`store_report`
    says which store is ACTUALLY in effect rather than claiming the move happened.

Reporting the configured path as though it were the live one would be exactly the
"a setting that looks applied" defect -- the operator would see the app folder,
find their models still in ``~/.ollama``, and have no way to tell why.

AN EXPLICIT OPERATOR CHOICE ALWAYS WINS. If ``OLLAMA_MODELS`` or ``HF_HOME`` is
already set in the environment, that value is used untouched. Someone who has put
their weights on a second drive did so deliberately, and silently relocating several
GB because an app preferred its own folder is not a default, it is a surprise.

MIGRATION IS A COPY, NOT A MOVE, UNTIL IT IS VERIFIED. Ollama's store is
content-addressed (``blobs/sha256-<hex>``), so "never overwrite a differing file" is
automatic -- same name means identical content -- and a copy that is interrupted
leaves the source intact. Deleting the source is a separate, explicit step, and it
only runs over blobs that were confirmed present at the destination.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from src.paths import data_dir

_LOG = logging.getLogger("llm.model_store")

_MANIFESTS = "manifests"
_BLOBS = "blobs"


def app_models_root() -> Path:
    """The app-owned root for every locally downloaded model artifact."""
    return data_dir() / "models"


def ollama_store() -> Path:
    """Where Ollama should keep its models: the operator's ``OLLAMA_MODELS`` if they
    set one, else the app's own folder."""
    env = (os.getenv("OLLAMA_MODELS") or "").strip()
    if env:
        return Path(env)
    return app_models_root() / "ollama"


def hf_home() -> Path:
    """Where Hugging Face should cache weights for vLLM.

    ``HF_HOME`` rather than ``HF_HUB_CACHE`` because HF puts more than the hub cache
    under it (tokenizers, locks), and pointing the whole home at the app folder keeps
    those together instead of scattering half of it back into ``~/.cache``.
    """
    for var in ("HF_HUB_CACHE", "HF_HOME"):
        env = (os.getenv(var) or "").strip()
        if env:
            # HF_HUB_CACHE points AT the hub dir; HF_HOME contains it. Normalise to the
            # home so callers have one meaning.
            return Path(env).parent if var == "HF_HUB_CACHE" else Path(env)
    return app_models_root() / "huggingface"


def launch_env(base: dict | None = None) -> dict:
    """The environment to spawn a backend with, pointing both stores at the app folder.

    Returns a full environment (a copy of ``base``, default ``os.environ``) rather than
    just the overlay, because that is what ``subprocess`` wants and building it here
    keeps the "which variables matter" knowledge in one place.

    An operator-set value is preserved: :func:`ollama_store` and :func:`hf_home`
    already resolve to it, so re-exporting it is a no-op rather than an override.
    """
    env = dict(base if base is not None else os.environ)
    try:
        o_store = ollama_store()
        h_home = hf_home()
        o_store.mkdir(parents=True, exist_ok=True)
        h_home.mkdir(parents=True, exist_ok=True)
        env["OLLAMA_MODELS"] = str(o_store)
        env["HF_HOME"] = str(h_home)
    except OSError as exc:  # noqa: BLE001 - an unwritable data dir must not block a start
        # Falling back to the backend's own default is strictly better than refusing to
        # start. It is logged rather than silent, because the operator's models will
        # then land somewhere they did not choose either.
        _LOG.warning("could not prepare the app model store (%s); using backend defaults", exc)
    return env


def _store_size(store: Path) -> int | None:
    """Total bytes under ``store``, or None when it cannot be walked."""
    try:
        if not store.is_dir():
            return 0
        return sum(f.stat().st_size for f in store.rglob("*") if f.is_file())
    except (OSError, PermissionError):
        return None


def store_report() -> dict:
    """Where model weights live, configured AND actual.

    The two differ exactly when a backend process was started by something other than
    this app, which is the common case for a systemd-managed Ollama. Saying so is the
    whole point of this function: an operator whose models are still in ``~/.ollama``
    needs to know it is because the daemon is not ours, not because the setting failed.
    """
    from src.backup.ollama_models import default_store as ollama_detected

    configured_ollama = ollama_store()
    configured_hf = hf_home()
    try:
        detected = ollama_detected()
    except Exception:  # noqa: BLE001 - detection must never break the report
        detected = configured_ollama

    same = str(detected) == str(configured_ollama)
    out: dict = {
        "root": str(app_models_root()),
        "ollama": {
            "configured": str(configured_ollama),
            "detected": str(detected),
            "in_app_folder": same,
            "bytes": _store_size(configured_ollama),
            "legacy_bytes": None if same else _store_size(detected),
            "operator_override": bool((os.getenv("OLLAMA_MODELS") or "").strip()),
        },
        "huggingface": {
            "configured": str(configured_hf),
            "bytes": _store_size(configured_hf),
            "operator_override": bool(
                (os.getenv("HF_HOME") or "").strip() or (os.getenv("HF_HUB_CACHE") or "").strip()
            ),
        },
    }
    if not same:
        out["ollama"]["note"] = (
            f"Models are being read from {detected}, not the app folder. That happens when "
            "the Ollama daemon was started by something other than this app (systemd, "
            "launchd, or a terminal) — its environment is its own, so the app's setting "
            "cannot reach it. Migrate the store, or stop that daemon and let the app start "
            "one."
        )
    return out


def migrate_ollama_store(
    source: Path | None = None,
    dest: Path | None = None,
    *,
    delete_source: bool = False,
) -> dict:
    """Copy an existing Ollama store into the app folder.

    Content-addressed, so this is safe by construction: a blob's filename IS its
    sha256, meaning a name collision is proof the contents match, and skipping an
    existing file can never lose data. Manifests are small JSON and are overwritten,
    which is also safe -- a manifest names the same blobs either way.

    ``delete_source`` removes ONLY the files this call confirmed present at the
    destination, and only after the whole copy succeeded. A partial copy therefore
    leaves the source completely intact; that is deliberate, because "move" on a
    multi-GB store interrupted halfway is how an operator loses both copies.

    Never raises for an ordinary problem: an unreadable source (the protected
    systemd store) comes back as a refusal with a reason.
    """
    from src.backup.ollama_models import list_models

    src = Path(source) if source else None
    if src is None:
        from src.backup.ollama_models import default_store

        src = default_store()
    dst = Path(dest) if dest else ollama_store()

    out: dict = {
        "source": str(src),
        "dest": str(dst),
        "copied": 0,
        "skipped": 0,
        "bytes": 0,
        "removed": 0,
        "ok": False,
    }
    if str(src) == str(dst):
        out["reason"] = "the source and the destination are the same folder — nothing to do"
        out["ok"] = True
        return out
    if not src.is_dir():
        out["reason"] = f"no model store at {src}"
        return out

    models = list_models(src)
    if not models:
        out["reason"] = (
            f"no readable models at {src}. A service-owned store (root/ollama-user) is "
            "readable only with its own permissions — this app never elevates."
        )
        return out

    copied_files: list[Path] = []
    try:
        (dst / _BLOBS).mkdir(parents=True, exist_ok=True)
        (dst / _MANIFESTS).mkdir(parents=True, exist_ok=True)
        for entry in models:
            mf_src = src / _MANIFESTS / entry.manifest_rel
            mf_dst = dst / _MANIFESTS / entry.manifest_rel
            mf_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(mf_src, mf_dst)
            copied_files.append(mf_src)
            for blob in entry.blobs:
                b_src = src / _BLOBS / blob
                b_dst = dst / _BLOBS / blob
                if not b_src.is_file():
                    continue
                if b_dst.is_file():
                    # Same sha256 name means same bytes. Skipping is correct, and
                    # re-copying would be several GB of pointless I/O.
                    out["skipped"] += 1
                    copied_files.append(b_src)
                    continue
                tmp = b_dst.with_suffix(b_dst.suffix + ".oopart")
                shutil.copy2(b_src, tmp)
                tmp.replace(b_dst)  # atomic: a killed copy never leaves a short blob
                out["copied"] += 1
                out["bytes"] += b_dst.stat().st_size
                copied_files.append(b_src)
    except (OSError, PermissionError) as exc:
        out["reason"] = f"copy failed: {exc}"
        return out

    out["ok"] = True
    out["models"] = [m.ref for m in models]
    if delete_source:
        for f in copied_files:
            try:
                f.unlink()
                out["removed"] += 1
            except OSError:  # noqa: PERF203 - a file we cannot remove is reported, not fatal
                continue
    return out
