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


def legacy_hf_home() -> Path | None:
    """Hugging Face's OWN default cache home -- where weights downloaded before
    2026-08-04 still are.

    Pointing ``HF_HOME`` at the app folder moved where NEW weights land. It also, and
    this was not thought through, made every EXISTING download invisible: the probe and
    the activation guard both read the app folder, so a vLLM whose weights had been
    fetched months ago reported "not in the local model cache" and refused to start --
    several GB of real data on the disk, and an operator told they had never downloaded
    it. The 2026-08-04 field report ("vLLM doesn't seem to start", on a machine that had
    just been reinstalled) is exactly the shape this produces.

    Returns None when the operator set ``HF_HOME``/``HF_HUB_CACHE`` themselves: their
    choice IS the location, so there is no "legacy" elsewhere to reconcile with.
    """
    if (os.getenv("HF_HOME") or "").strip() or (os.getenv("HF_HUB_CACHE") or "").strip():
        return None
    xdg = (os.getenv("XDG_CACHE_HOME") or "").strip()
    base = Path(xdg) if xdg else Path.home() / ".cache"
    legacy = base / "huggingface"
    # If the app folder IS the default (an OO_DATA_DIR pointed there), there is nothing
    # to distinguish and reporting a "legacy" copy would be noise.
    return None if str(legacy) == str(hf_home()) else legacy


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
        # ``hub/`` too, not just HF_HOME: it is huggingface_hub's own subdirectory and
        # it would create it on the first download -- but the app ADVERTISES that path
        # as where weights belong (the activation blocker prints it, and an operator
        # moving an existing cache needs it to exist). A folder the app names should be
        # a folder the app has made.
        (h_home / "hub").mkdir(parents=True, exist_ok=True)
        env["OLLAMA_MODELS"] = str(o_store)
        env["HF_HOME"] = str(h_home)
    except OSError as exc:  # noqa: BLE001 - an unwritable data dir must not block a start
        # Falling back to the backend's own default is strictly better than refusing to
        # start. It is logged rather than silent, because the operator's models will
        # then land somewhere they did not choose either.
        _LOG.warning("could not prepare the app model store (%s); using backend defaults", exc)
    return env


def _ref_key(ref: str) -> str:
    """A manifest ref reduced to the name Ollama itself shows: ``model:tag``.

    On disk a manifest is ``<host>/<namespace>/<model>/<tag>``; ``/api/tags`` answers
    ``mistral:7b``. Comparing the two needs one common form, and the last component is
    the only part both always carry. Two models with the same name in different
    namespaces therefore collide — which is safe HERE, because a collision makes both
    stores claim the model and the caller's answer falls through to "cannot tell"
    rather than to a confident wrong store.
    """
    return ref.rsplit("/", 1)[-1].strip().lower()


def _store_keys(store: Path) -> set[str]:
    try:
        from src.backup.ollama_models import list_models

        return {_ref_key(m.ref) for m in list_models(store)}
    except Exception:  # noqa: BLE001 - a probe must never break the report
        return set()


def serving_store(*, timeout: float = 2.0) -> dict:
    """Which store the RUNNING daemon is actually reading — measured, not inferred.

    WHY THIS IS NOT A PATH COMPARISON. Ownership cannot answer it: a daemon this app
    spawned in an earlier run is still alive after a restart and is correctly reported
    as not-ours, yet it reads the app folder. Nor can "which directory has models",
    now that both usually do. And getting it wrong in the optimistic direction is the
    expensive one — claiming the app folder is in use while the operator's pulls land
    in ``~/.ollama`` is precisely the split this whole module exists to expose.

    So it is decided by EVIDENCE: ask the daemon what it has, and see which store
    holds a model the other one does not. That is conclusive when the stores differ
    and honestly inconclusive when they do not — a daemon serving two identical stores
    is a distinction without a difference, and an empty daemon proves nothing at all.

    ``{"store": str | None, "certain": bool, "basis": str}``.
    """
    app = ollama_store()
    others = []
    try:
        from src.backup.ollama_models import candidate_stores

        others = [p for p in candidate_stores() if str(p) != str(app)]
    except Exception:  # noqa: BLE001
        others = []

    try:
        from src.llm.ollama import OllamaClient

        served = {_ref_key(n) for n in OllamaClient(timeout=timeout).list_installed()}
    except Exception as exc:  # noqa: BLE001 - a stopped daemon is a normal answer
        return {
            "store": None,
            "certain": False,
            "basis": f"no running daemon to ask ({type(exc).__name__})",
        }
    if not served:
        return {
            "store": None,
            "certain": False,
            "basis": "the running daemon has no models, so it cannot say which store it reads",
        }

    # Every store paired with its keys, the app's included, so "unique to this one" is
    # one expression rather than two. Doing it as app-vs-the-rest got the arithmetic
    # wrong the moment two NON-app stores shared a model: subtracting a store's own
    # keys from the union of the others also removed the copy that made it non-unique,
    # so a model present in both ~/.ollama and the service store read as unique to each.
    all_stores: list[tuple[Path, set[str]]] = [(app, _store_keys(app))]
    all_stores += [(p, _store_keys(p)) for p in others]

    matches: list[Path] = []
    for i, (p, keys) in enumerate(all_stores):
        elsewhere: set[str] = set()
        for j, (_, other) in enumerate(all_stores):
            if j != i:
                elsewhere |= other
        if served & (keys - elsewhere):
            matches.append(p)

    if len(matches) == 1:
        store = matches[0]
        return {
            "store": str(store),
            "certain": True,
            "basis": (
                "the running daemon lists a model that only this store holds, so this "
                "is the store it is reading"
            ),
        }
    if len(matches) > 1:
        return {
            "store": None,
            "certain": False,
            "basis": (
                "the running daemon lists models unique to more than one store, which "
                "no single store explains"
            ),
        }
    return {
        "store": None,
        "certain": False,
        "basis": (
            "the stores hold the same models, so what the daemon lists cannot "
            "distinguish them"
        ),
    }


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
        on_disk = ollama_detected()
    except Exception:  # noqa: BLE001 - detection must never break the report
        on_disk = configured_ollama

    # Measured first, inferred second. The path heuristic answers "which store holds
    # models", which stopped being the same question as "which store is being read"
    # the moment the app folder became a candidate: with both populated it names the
    # app folder whatever the running daemon is doing, and reporting that as the live
    # answer would turn a real split into a clean bill of health.
    serving = serving_store()
    detected = Path(serving["store"]) if serving.get("store") else on_disk
    same = str(detected) == str(configured_ollama)
    out: dict = {
        "root": str(app_models_root()),
        "ollama": {
            "configured": str(configured_ollama),
            "detected": str(detected),
            "in_app_folder": same,
            "bytes": _store_size(configured_ollama),
            # The size of the store ACTUALLY IN USE, which is a different number
            # whenever a foreign daemon owns it -- and the interesting one, because
            # the configured folder is then near-empty while the real store holds
            # every model. Reporting only the configured size next to a path label
            # reads as "you have no models" to an operator who has twenty GB of them.
            "detected_bytes": _store_size(configured_ollama) if same else _store_size(detected),
            "legacy_bytes": None if same else _store_size(detected),
            "operator_override": bool((os.getenv("OLLAMA_MODELS") or "").strip()),
            # HOW the answer above was reached, published rather than implied. An
            # operator deciding whether to migrate several GB deserves to know whether
            # the app measured which store is in use or merely found models in one.
            "serving": serving,
            "on_disk": str(on_disk),
            "basis": (
                "measured — " + serving["basis"]
                if serving.get("store")
                else "inferred from which store holds models (" + serving["basis"] + ")"
            ),
        },
        "huggingface": {
            "configured": str(configured_hf),
            "bytes": _store_size(configured_hf),
            "operator_override": bool(
                (os.getenv("HF_HOME") or "").strip() or (os.getenv("HF_HUB_CACHE") or "").strip()
            ),
        },
    }
    # Weights downloaded before the store moved into the app folder are still on the
    # disk, and until this was reported nothing said so -- the probe read one directory
    # and answered "not downloaded" about the other.
    legacy_hf = legacy_hf_home()
    legacy_hf_bytes = _store_size(legacy_hf) if legacy_hf else 0
    if legacy_hf and legacy_hf_bytes:
        out["huggingface"]["legacy"] = str(legacy_hf)
        out["huggingface"]["legacy_bytes"] = legacy_hf_bytes
        out["huggingface"]["note"] = (
            f"There are also model weights at {legacy_hf}, from before the store moved "
            f"into the app folder. They are still usable — move them into "
            f"{configured_hf / 'hub'} (that is where the server looks), or set HF_HOME "
            f"back to {legacy_hf} and let future downloads land there too. Nothing is "
            "moved or deleted for you."
        )
    # Every store that actually holds models, so a split is VISIBLE rather than
    # something the operator has to notice in a file manager (which is how the
    # 2026-08-11 report reached us). One list, one look.
    stores: list[dict] = []
    try:
        from src.backup.ollama_models import candidate_stores, list_models

        for p in candidate_stores():
            models = list_models(p)
            if not models:
                continue
            stores.append(
                {
                    "path": str(p),
                    "models": len(models),
                    "bytes": _store_size(p),
                    "is_app_folder": str(p) == str(configured_ollama),
                }
            )
    except Exception:  # noqa: BLE001 - an inventory must never break the report
        stores = []
    out["ollama"]["stores"] = stores

    if len(stores) > 1:
        where = ", ".join(f"{s['path']} ({s['models']})" for s in stores)
        out["ollama"]["split_note"] = (
            f"Models are in more than one place: {where}. Copying them into the app "
            "folder puts every model where a daemon this app starts will find it; the "
            "copy leaves the originals untouched and removing them stays your own "
            "separate step."
        )
    if not same:
        # The EVIDENCE clause differs with how the answer was reached; the ADVICE does
        # not, and must not go quiet just because the measurement was inconclusive.
        # Splitting the whole note by certainty left the commonest case of all — a
        # foreign daemon and a store with no manifests we can read — saying nothing at
        # all, which is the one outcome an operator cannot act on.
        if serving.get("certain"):
            evidence = (
                f"Models are being read from {detected}, not the app folder — measured, "
                "not assumed: the running daemon lists a model only that store holds."
            )
        else:
            evidence = (
                f"Models were found at {detected} rather than in the app folder, and "
                "which store the daemon is reading could not be measured "
                f"({serving['basis']})."
            )
        out["ollama"]["note"] = evidence + (
            " That happens when the Ollama daemon was started by something other than "
            "this app (systemd, launchd, or a terminal) — its environment is its own, so "
            "the app's setting cannot reach it. Migrate the store, or stop that daemon "
            "and let the app start one."
        )
    return out


def prepare_ollama_pull() -> dict:
    """Make a pull land in the app folder — as far as that is ours to decide — and say
    where it will actually land when it is not.

    A pull is an HTTP call to whichever daemon answers the loopback port, and the store
    it writes into is that daemon's, decided by ITS environment when it started. So the
    only lever the app has is which daemon is serving, and there is exactly one case
    where it holds that lever: when none is running yet. Then it starts its own, which
    :func:`launch_env` points at the app folder, and every subsequent pull lands there.

    When a daemon someone else started is already serving, the app has no lever at all —
    ``ollama_lifecycle.stop`` refuses foreign daemons on purpose, and restarting the
    operator's service to change a download directory would be well outside what a model
    download is allowed to do. What it CAN do is stop the split being silent: this
    returns the store the pull will really use, so the caller records a destination
    rather than leaving the operator to find two folders later.

    Never raises, and never blocks a pull: every failure degrades to "we could not
    arrange it, here is what we know", because a model the operator asked for should
    download even when we cannot place it where we would prefer.
    """
    app = ollama_store()
    out: dict = {"app_store": str(app), "dest": None, "arranged": False}
    try:
        from src.llm import ollama_lifecycle as ol

        if not ol.is_running():
            if os.getenv("OO_LLM_AUTOSTART", "1").strip().lower() in ("0", "false", "no"):
                out["reason"] = (
                    "no Ollama daemon is running and automatic starts are off "
                    "(OO_LLM_AUTOSTART=0), so the pull will use whatever daemon you start"
                )
                return out
            started = ol.start()
            if started.get("ready"):
                # Ours, launched with OLLAMA_MODELS pointed at the app folder.
                out.update({"dest": str(app), "arranged": True, "started_daemon": True})
                return out
            out["reason"] = (
                "started an Ollama daemon for this pull, but it was not answering yet: "
                + str(started.get("note") or started.get("reason") or "no reason given")
            )
            return out
        if ol.owns_daemon():
            out.update({"dest": str(app), "arranged": True, "started_daemon": False})
            return out
    except Exception as exc:  # noqa: BLE001 - arranging is best-effort, pulling is not
        out["reason"] = f"could not arrange the store for this pull ({type(exc).__name__}: {exc})"
        return out

    # A daemon we did not start is serving. Measure where it reads rather than assuming
    # the worst: one this app started in an EARLIER run is reported as not-ours (the
    # handle does not survive a restart) and is nonetheless pointed at the app folder.
    serving = serving_store()
    if serving.get("store"):
        out["dest"] = serving["store"]
        out["arranged"] = serving["store"] == str(app)
        if not out["arranged"]:
            out["reason"] = (
                f"the running Ollama daemon reads {serving['store']}, so this download "
                "lands there and not in the app folder. It was started outside this app "
                "(systemd, launchd, or a terminal), and its environment is its own. Stop "
                "it and let the app start one to keep every model in the app folder."
            )
        return out
    out["reason"] = (
        "an Ollama daemon this app did not start is serving, and which store it reads "
        f"could not be measured ({serving['basis']}), so where this download lands is "
        "not known here"
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

    dst = Path(dest) if dest else ollama_store()

    if source is None:
        # EVERY other store that holds models, not ``default_store()``.
        #
        # It used to be ``default_store()``, and promoting the app folder to the front
        # of the candidate list turned that into a silent no-op in the one case this
        # button exists for: with models in both places the heuristic now names the app
        # folder, so source == dest and the answer became "nothing to do" while the
        # operator's other folder sat there untouched. Consolidating means reading every
        # store that is not the destination, which is also what the ask asked for —
        # "I'd prefer if all models were in the same place".
        from src.backup.ollama_models import candidate_stores

        sources = [p for p in candidate_stores() if str(p) != str(dst) and list_models(p)]
        if not sources:
            return {
                "source": None,
                "dest": str(dst),
                "copied": 0,
                "skipped": 0,
                "bytes": 0,
                "removed": 0,
                "ok": True,
                "reason": "every model is already in the app folder — nothing to copy",
            }
        merged: dict = {
            "dest": str(dst),
            "copied": 0,
            "skipped": 0,
            "bytes": 0,
            "removed": 0,
            "ok": True,
            "sources": [],
            "models": [],
        }
        for s in sources:
            one = migrate_ollama_store(s, dst, delete_source=delete_source)
            merged["sources"].append({"source": str(s), **one})
            for k in ("copied", "skipped", "bytes", "removed"):
                merged[k] += one.get(k, 0)
            merged["models"].extend(one.get("models") or [])
            if not one.get("ok"):
                # One unreadable store (the protected service dir) must not discard the
                # copies that DID succeed, nor be reported as a clean run.
                merged["ok"] = False
        merged["source"] = ", ".join(str(s) for s in sources)
        return merged

    src = Path(source)

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
