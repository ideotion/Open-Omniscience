"""Ollama lifecycle: is it INSTALLED, is it RUNNING, and can we launch it?

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-29: "Ollama and vLLM installations should be detectable even
when they have not been started. A 'launch' button would then be made available to
the user to start either service."

vLLM already had this shape (``vllm_lifecycle.is_installed`` is a pure filesystem
check, so it answers truthfully while the server is down, and ``start()`` exists).
Ollama had NEITHER half:

  * the only Ollama predicate anywhere in the availability path was an HTTP probe of
    the RUNNING daemon (``OllamaClient.is_available``), so a stopped-but-installed
    Ollama was indistinguishable from an absent one -- ``backend.py``'s own docstring
    already named this as a known gap;
  * ``installer.ollama_present()`` (a ``shutil.which`` check) DID exist, but nothing
    outside the installer's own status payload ever called it, so the two halves of
    the answer were never combined;
  * and nothing in ``src/`` started an Ollama server at all (no ``ollama serve``, no
    systemctl, no launchctl) -- the red AI pill's "click to start" could only ever
    start vLLM and fell through silently for Ollama.

This module supplies the missing half and is deliberately NARROWER than its vLLM
sibling, because the two are not symmetric: vLLM is installed BY this app into a venv
it owns, whereas Ollama is a system-wide binary that is very often already managed by
systemd/launchd. See ``stop`` (absent, on purpose) below.

AIRPLANE MODE: starting the daemon is ALLOWED while the kill switch is engaged, and
that is a deliberate reading of the existing split rather than an exception to it.
The ruled position is that loopback generate/list are permitted offline while
pull/remove are refused, because a pull's egress happens inside the separate Ollama
process where the in-process socket guard cannot see it. ``ollama serve`` binds a
loopback port; it is the thing that makes the permitted offline inference possible at
all, so refusing to start it would make that allowance unusable exactly when it
matters. The honest caveat -- that Ollama is a separate process outside this app's
socket guard -- is the same one the pull refusal already rests on, and is surfaced to
the user rather than assumed.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

_LOG = logging.getLogger("llm.ollama_lifecycle")

# How long ``start`` waits for the daemon to answer before reporting back. A cold
# Ollama start is typically well under a second; this is generous enough not to
# report a false negative and short enough not to hang a UI click.
_READY_TIMEOUT_S = 12.0
_READY_POLL_S = 0.25

#: The daemon THIS process spawned, or None. Ownership is the whole basis on which
#: ``stop`` is allowed to exist at all (see its docstring and the note at the foot of
#: this file), so it is tracked rather than inferred: a PID discovered by scanning for
#: an ``ollama`` process would be indistinguishable from the operator's own.
_proc: subprocess.Popen | None = None


class OllamaLifecycleError(RuntimeError):
    """A launch could not even be attempted (not installed / already running is NOT
    this -- that is a normal, reported outcome)."""


def binary_path() -> str | None:
    """Absolute path of the ``ollama`` binary, or None when it is not on PATH.

    This is the INSTALLED question, and it is answered without touching the network
    or the daemon -- which is the entire point: it stays truthful while the server
    is stopped.
    """
    return shutil.which("ollama")


def is_installed() -> bool:
    return binary_path() is not None


def is_running(*, timeout: float = 2.0) -> bool:
    """Live loopback probe of the daemon. Mirrors ``vllm_lifecycle.is_running``:
    never inferred from a tracked subprocess handle, because the daemon is usually
    NOT ours (systemd/launchd, or a terminal the operator opened)."""
    try:
        from src.llm.ollama import OllamaClient

        return OllamaClient(timeout=timeout).is_available()
    except Exception:  # noqa: BLE001 - a probe must never crash a caller
        return False


def owns_daemon() -> bool:
    """True when the running daemon is one THIS process spawned and it is still alive.

    Deliberately narrow. An ``ollama`` process found by scanning the process table
    could equally be systemd's, launchd's, or one the operator started in a terminal
    they are using for something else -- and nothing about the process itself
    distinguishes those from ours. So ownership is only ever claimed for a handle we
    hold, and every other case is reported as not-ours rather than guessed at.
    """
    return _proc is not None and _proc.poll() is None


def state() -> dict:
    """The three-way answer the UI needs, in ONE payload.

    ``installed`` and ``running`` are INDEPENDENT facts, and the combination that
    used to be unrepresentable -- installed True, running False -- is precisely the
    one that now earns a Launch button. ``can_launch`` is derived here rather than in
    the frontend so the rule lives in one place.
    """
    installed = is_installed()
    running = is_running()
    return {
        "installed": installed,
        "running": running,
        "path": binary_path(),
        "can_launch": installed and not running,
        # OURS to stop, or the machine's? Published because it is the difference
        # between a control that will work and one that will honestly refuse, and a
        # caller that has to try the call to find out will show a button that does
        # nothing on most machines.
        "owned": owns_daemon(),
        "can_stop": owns_daemon() and running,
    }


def start(*, wait: bool = True, timeout: float = _READY_TIMEOUT_S) -> dict:
    """Launch ``ollama serve`` as a detached background process.

    Idempotent by probe, not by bookkeeping: if the daemon already answers we report
    ``started: False, reason: "already running"`` and spawn nothing. That matters
    because the daemon is frequently started by systemd rather than by us, so an
    ownership flag would be wrong more often than right.

    Returns a dict; raises :class:`OllamaLifecycleError` only when the launch could
    not be ATTEMPTED (binary absent, or the spawn itself failed).
    """
    path = binary_path()
    if path is None:
        raise OllamaLifecycleError(
            "Ollama is not installed (no 'ollama' binary on PATH). Install it first."
        )
    if is_running():
        return {"started": False, "reason": "already running", "path": path}

    # Detached, output discarded. stdout/stderr go to DEVNULL rather than a pipe on
    # purpose: nothing reads them, and an unread pipe fills its buffer and wedges the
    # daemon -- the same reason vllm_lifecycle spawns with DEVNULL.
    #
    # OLLAMA_MODELS points the daemon at the app's own model folder (2026-08-04
    # maintainer ask), so a model pulled through a daemon WE started lands inside the
    # app directory instead of ~/.ollama. It reaches only daemons we spawn -- a
    # systemd/launchd one has its own environment and keeps its own store, which
    # ``model_store.store_report()`` reports rather than papers over. An operator who
    # set OLLAMA_MODELS themselves keeps their value untouched.
    from src.llm.model_store import launch_env

    global _proc
    env = launch_env()
    try:
        popen_kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": env,
        }
        if hasattr(os, "setsid"):
            # Own process group, so the daemon outlives this app's own shutdown
            # signal -- a server the user launched should not die because they
            # later stopped the app.
            popen_kwargs["start_new_session"] = True
        _proc = subprocess.Popen([path, "serve"], **popen_kwargs)  # noqa: S603  # nosec B603 - fixed argv, absolute path from shutil.which, no shell
    except OSError as exc:
        raise OllamaLifecycleError(f"could not launch 'ollama serve': {exc}") from exc

    if not wait:
        return {"started": True, "ready": False, "path": path, "note": "not waited for"}

    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if is_running():
            return {"started": True, "ready": True, "path": path}
        time.sleep(_READY_POLL_S)

    # Spawned but not answering yet. Reported HONESTLY rather than as a success:
    # the caller shows "launching…" and re-polls, instead of claiming a ready server
    # the user would then find unreachable.
    _LOG.info("ollama serve spawned but not reachable within %.1fs", timeout)
    return {
        "started": True,
        "ready": False,
        "path": path,
        "note": (
            f"launched, but the daemon did not answer within {timeout:.0f}s -- it may "
            "still be starting. Re-check in a moment."
        ),
    }


def release_vram(*, timeout: float = 8.0) -> dict:
    """Ask Ollama to release every model it is holding in memory, WITHOUT stopping it.

    THE POINT: on a single-GPU machine both backends want the same card, and nothing
    sequenced them -- so a vLLM start would size its budget for an 8 GB card while
    Ollama sat on 4 of those gigabytes, and die (field report 2026-08-05). This is the
    release half of that fix.

    IT IS NOT A ``stop()``, and the distinction is the whole reason this is allowed to
    exist beside the comment below. Killing a daemon this app usually does not own is
    out of bounds; asking a running daemon to drop model RESIDENCY is a request it
    already exposes, is reversed by Ollama itself on the next request, and costs at
    worst one model-load latency. Nothing the operator started is stopped.

    Returns what was actually released -- names and the VRAM each held -- so the caller
    can report a real number rather than "freed some memory". An unreachable or
    uninstalled Ollama is a clean no-op with a stated reason, never an error: the
    post-condition wanted is "Ollama is not holding the card", and that already holds.
    """
    if not is_installed():
        return {"released": [], "reason": "Ollama is not installed", "attempted": False}
    try:
        from src.llm.ollama import OllamaClient

        client = OllamaClient(timeout=timeout)
        if not client.is_available():
            return {"released": [], "reason": "Ollama is not running", "attempted": False}
        loaded = client.loaded_models()
        if not loaded:
            return {"released": [], "reason": "Ollama was holding nothing", "attempted": True}
        released: list[dict] = []
        for entry in loaded:
            if client.unload(entry["model"]):
                released.append(entry)
        return {
            "released": released,
            "attempted": True,
            "reason": None if released else "Ollama declined to unload",
        }
    except Exception as exc:  # noqa: BLE001 - a courtesy release must never block a start
        _LOG.info("could not ask Ollama to release VRAM: %s", exc)
        return {"released": [], "reason": str(exc), "attempted": True}


def stop(*, timeout: float = 10.0) -> dict:
    """Stop a daemon THIS process started. Refuses, by name, to touch any other.

    THE RULING THIS NARROWS RATHER THAN REVERSES. There was no ``stop`` here for a
    stated reason: an Ollama daemon is usually a system service or the operator's own
    terminal process, shared with everything else on the machine, and killing it would
    reach outside anything this app owns. That reasoning is about a daemon we did not
    start, and it still holds for one -- so the refusal is kept and made explicit
    instead of being expressed as an absent function.

    What changed is that the automated bench (2026-08-10) has to hand one GPU from one
    backend to the other, which needs an answer to "stop holding the card". For a
    daemon we spawned, terminating our own subprocess is that answer. For every other
    daemon it is NOT, and :func:`release_vram` is -- it drops model residency through
    an API Ollama already exposes, costs at worst one model load, and stops nothing the
    operator started. Callers that want the card free should ask for THAT; this exists
    so a bench that started its own daemon can tidy up after itself.

    Never raises: a stop that cannot be made is a reported outcome, not an error.
    """
    global _proc
    if not owns_daemon():
        running = is_running()
        return {
            "stopped": False,
            "owned": False,
            "running": running,
            "reason": (
                "this Ollama daemon was not started by this app (it is a system service "
                "or the operator's own process), so stopping it is not ours to do. To "
                "free the GPU without stopping anything, use release_vram()."
                if running
                else "no Ollama daemon is running"
            ),
        }
    proc = _proc
    assert proc is not None  # noqa: S101  # nosec B101 - owns_daemon() just proved it
    try:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except OSError as exc:
        return {"stopped": False, "owned": True, "reason": f"{type(exc).__name__}: {exc}"}
    _proc = None
    return {"stopped": True, "owned": True}
