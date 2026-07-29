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
    env = dict(os.environ)
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
        subprocess.Popen([path, "serve"], **popen_kwargs)  # noqa: S603  # nosec B603 - fixed argv, absolute path from shutil.which, no shell
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


# NO stop(). Deliberate, not an oversight: unlike vLLM -- which this app installs into
# a venv it owns and starts as a subprocess it tracks -- an Ollama daemon is usually a
# system service (systemd/launchd) or a process the operator started in their own
# terminal, shared with everything else on the machine. Killing it would reach outside
# anything this app owns. Launching one that is not running is additive and reversible
# by the operator's own tooling; stopping one is not ours to do.
