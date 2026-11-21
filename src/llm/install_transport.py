"""R763: the AI install's spawned and clearnet steps refuse protected mode, the same way the app update does.

Each of these steps downloads outside this app's process:
- the Ollama installer script
- ``pip`` / ``uv`` installing vLLM
- the Hugging Face snapshot
- a model pull by the Ollama daemon

None of them goes through the proxy that protected mode routes this app's own requests through, so running one would reveal this
machine's address to those hosts. That would be a silent transport downgrade (the non-negotiable "never silently downgrade
transport"), so the step is refused, with a reason that names why. The update helper's ``git fetch`` is refused the same way
(``src.maintenance.self_update.refuse_offline_or_protected``), and this module reuses that module's rule rather than a second
copy of it: protected mode is chosen, OR the settings cannot be read, which counts as protected (R117).

The in-process steps are NOT refused here. The installer's release lookup and download (``installer.prepare_installer``) go
through ``guarded_session``, which honours the proxy.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

AI_INSTALL_PROTECTED_REFUSAL = (
    "Protected mode is on: the AI install did not start. It downloads over a direct connection, not through your proxy, "
    "which would reveal this machine's address. Switch to standard mode to install, or install by hand through your proxy."
)


def ai_install_protected() -> bool:
    """True when an AI install step that runs outside this process must be refused: protected mode is chosen, or the settings
    cannot be read (R117). The update's own rule, the one function, so the two refusals cannot drift apart."""
    from src.maintenance.self_update import protected_mode_chosen

    return protected_mode_chosen()


def refuse_if_protected(exc_type: type[Exception]) -> None:
    """Raise ``exc_type(AI_INSTALL_PROTECTED_REFUSAL)`` when :func:`ai_install_protected`. Each caller passes its own module's
    error type, so the refusal reaches the user on the path that module already reports through."""
    if ai_install_protected():
        raise exc_type(AI_INSTALL_PROTECTED_REFUSAL)


# --------------------------------------------------------------------------- #
# R765: switching to protected mode stops an AI install that is already running. #
# --------------------------------------------------------------------------- #
# The refusals above only stop a step from STARTING. A step already running when the operator switches protected mode on (pip
# fetching wheels, the Hugging Face snapshot, the Ollama script, a daemon pull) would go on downloading over the direct
# connection the operator has just chosen to stop using. So the save that turns protected mode on stops them: the mode is written
# first, then each running step is asked to stop (a spawned child is terminated, waited for within a bound, then killed), and no
# later step starts because the refusals above now apply. The save never waits for the install and never fails because of it.

AI_INSTALL_STOPPED_NOTE = (
    "Stopped because protected mode was switched on: this download goes over a direct connection, not through your proxy. "
    "What it had downloaded is not used as finished. Switch protected mode off and start it again to finish."
)
AI_INSTALLER_STOPPED_NOTE = (
    "Stopped because protected mode was switched on: the Ollama installer downloads over a direct connection, not through your "
    "proxy. The install was interrupted and may be incomplete: switch protected mode off and run it again."
)

import threading as _threading  # noqa: E402 - kept beside the R765 block it serves

_STOP_LOCK = _threading.Lock()
_STOP_GENERATION = 0
_STOPPED_AT: dict[str, float] = {}
_PROCS: set = set()
_TERMINATE_WAIT_S = 10.0


def stop_generation() -> int:
    """A counter the stop raises by one. A running step reads it when it starts and again as it goes: a change means stop."""
    with _STOP_LOCK:
        return _STOP_GENERATION


def stopped_since(generation: int) -> bool:
    """True once a stop has been asked after ``generation`` was read."""
    return stop_generation() != generation


def stop_note(kind: str, started_at: float | None) -> str | None:
    """The stop note (:data:`AI_INSTALL_STOPPED_NOTE`, or :data:`AI_INSTALLER_STOPPED_NOTE` for the script) when the run of ``kind`` that started at ``started_at`` was stopped by the switch, else None."""
    with _STOP_LOCK:
        at = _STOPPED_AT.get(kind)
    if at is None or started_at is None or started_at > at:  # a run with no start time cannot be placed before the stop
        return None
    return AI_INSTALLER_STOPPED_NOTE if kind == "ollama-installer" else AI_INSTALL_STOPPED_NOTE


def register_child(proc) -> None:
    """A spawned install child the switch must be able to stop (the Ollama script runs outside any job)."""
    with _STOP_LOCK:
        _PROCS.add(proc)


def unregister_child(proc) -> None:
    with _STOP_LOCK:
        _PROCS.discard(proc)


def _terminate(proc) -> None:
    """SIGTERM, a bounded wait, then SIGKILL. Never raises."""
    import subprocess

    try:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=_TERMINATE_WAIT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    except Exception:  # noqa: BLE001, S110 - best effort: the child may already be gone
        pass


def stop_running_installs() -> list[str]:
    """Stop every AI-install step that is running, without waiting for any of them. Returns what was asked to stop (kinds only).

    Called after protected mode is saved. Never raises: the switch must not fail because of an install."""
    import time

    global _STOP_GENERATION
    stopped: list[str] = []
    now = time.time()
    with _STOP_LOCK:
        _STOP_GENERATION += 1
        procs = list(_PROCS)
    try:
        from src.jobs.background import get_job

        for kind in ("vllm-install", "vllm-model-download"):
            job = get_job(kind)
            if job is not None and job.status().get("running"):
                with _STOP_LOCK:
                    _STOPPED_AT[kind] = now
                job.cancel()  # its runner terminates the child (SIGTERM, bounded wait, SIGKILL) at its next poll
                stopped.append(kind)
    except Exception:  # noqa: BLE001, S110 - one source of installs never hides the others
        pass
    try:
        from src.llm.pull_queue import get_pull_manager

        if get_pull_manager().stop_all(AI_INSTALL_STOPPED_NOTE):
            stopped.append("ollama-pull")
    except Exception:  # noqa: BLE001, S110
        pass
    if procs:
        with _STOP_LOCK:
            _STOPPED_AT["ollama-installer"] = now
        stopped.append("ollama-installer")
        for proc in procs:
            _threading.Thread(target=_terminate, args=(proc,), name="ai-install-stop", daemon=True).start()
    return stopped
