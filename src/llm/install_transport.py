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


#: R766: the refusal when the settings could not be read. Refused all the same (R117), but never said to be protected mode.
AI_INSTALL_SETTINGS_UNREADABLE_REFUSAL = (
    "The settings could not be read, so the AI install did not start: network actions are refused as if protected mode were "
    "on. Unlock the app if it is locked. If the saved choice is damaged, choose the network fetch mode and proxy again in "
    "Settings and save. Then try again."
)


def ai_install_block_reason() -> str | None:
    """``"protected"``, ``"settings_unreadable"`` or ``None``: the update's own :func:`protected_reason` (R766)."""
    from src.maintenance.self_update import protected_reason

    return protected_reason()


def ai_install_refusal() -> str | None:
    """The sentence an AI-install step is refused with, or ``None`` when it may run."""
    from src.maintenance.self_update import BLOCKED_SETTINGS_UNREADABLE

    reason = ai_install_block_reason()
    if reason is None:
        return None
    return AI_INSTALL_SETTINGS_UNREADABLE_REFUSAL if reason == BLOCKED_SETTINGS_UNREADABLE else AI_INSTALL_PROTECTED_REFUSAL


def ai_install_protected() -> bool:
    """True when an AI install step that runs outside this process must be refused: protected mode is chosen, or the settings
    cannot be read (R117). The update's own rule, the one function, so the two refusals cannot drift apart."""
    from src.maintenance.self_update import protected_mode_chosen

    return protected_mode_chosen()


def refuse_if_protected(exc_type: type[Exception]) -> None:
    """Raise ``exc_type(<refusal>)`` when :func:`ai_install_protected`, naming the real reason (R766). Each caller passes its own
    module's error type, so the refusal reaches the user on the path that module already reports through."""
    refusal = ai_install_refusal()
    if refusal is not None:
        raise exc_type(refusal)


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
_PROCS: dict = {}  # spawned install child -> True when it leads its own process group
_ACTIVE_PULLS = 0  # daemon pulls streaming now, through the queue or the direct route
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


def register_child(proc, *, group: bool = False) -> None:
    """A spawned install child the switch must be able to stop (the Ollama script runs outside any job). ``group``: the child leads
    its own process group, and the stop signals the whole group."""
    with _STOP_LOCK:
        _PROCS[proc] = group


def unregister_child(proc) -> None:
    with _STOP_LOCK:
        _PROCS.pop(proc, None)


def pull_started() -> None:
    """A daemon pull began streaming (``OllamaClient.pull``), so a stop can name it even when it did not come from the queue."""
    global _ACTIVE_PULLS
    with _STOP_LOCK:
        _ACTIVE_PULLS += 1


def pull_ended() -> None:
    global _ACTIVE_PULLS
    with _STOP_LOCK:
        _ACTIVE_PULLS = max(0, _ACTIVE_PULLS - 1)


def _signal(proc, sig, group: bool) -> None:
    import os

    if group and hasattr(os, "killpg"):
        try:
            os.killpg(proc.pid, sig)
            return
        except OSError:
            pass  # the group is gone or not ours: the child itself below
    proc.send_signal(sig)


def _terminate(proc, *, group: bool = False) -> None:
    """SIGTERM, a bounded wait, then SIGKILL; to the whole process group when ``group``. Never raises."""
    import contextlib
    import signal
    import subprocess

    try:
        if proc.poll() is not None and not group:
            return
        _signal(proc, signal.SIGTERM, group)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=_TERMINATE_WAIT_S)
        if group or proc.poll() is None:  # the leader may be gone while a child it was waiting on still downloads
            _signal(proc, getattr(signal, "SIGKILL", signal.SIGTERM), group)
            proc.wait(timeout=5)
    except Exception:  # noqa: BLE001, S110 - best effort: the child may already be gone
        pass


# An Ollama install the switch cut short may have unpacked part of the program. Until a run finishes, the binary it may have left
# is not reported as installed. The marker's time is compared with the binary's ctime (which unpacking sets and nothing can set
# back): a binary written after the marker came from a later install, by this app or by hand, and is believed.


def _interrupted_marker():
    from src.paths import data_dir

    return data_dir() / "ollama_install_interrupted"


def mark_ollama_install_interrupted() -> None:
    try:
        from src.safety.file_lock import atomic_replace

        marker = _interrupted_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        atomic_replace(marker, "stopped because protected mode was switched on\n")
    except OSError:
        pass  # the stop is said in the install's own note either way


def clear_ollama_install_interrupted() -> None:
    import contextlib

    with contextlib.suppress(OSError):
        _interrupted_marker().unlink(missing_ok=True)


def ollama_install_interrupted(binary: str | None) -> bool:
    """True while the binary at ``binary`` may be one a stopped install left half unpacked."""
    import os

    try:
        marked = _interrupted_marker().stat().st_mtime
    except OSError:
        return False
    if binary is None:
        return True
    try:
        return os.stat(binary).st_ctime <= marked
    except OSError:
        return True


def stop_running_installs() -> list[str]:
    """Stop every AI-install step that is running, without waiting for any of them. Returns what was asked to stop (kinds only).

    Called after protected mode is saved. Never raises: the switch must not fail because of an install."""
    import time

    global _STOP_GENERATION
    stopped: list[str] = []
    now = time.time()
    with _STOP_LOCK:
        _STOP_GENERATION += 1
        procs = list(_PROCS.items())
    try:
        from src.jobs.background import get_job

        for kind in ("vllm-install", "vllm-model-download"):
            job = get_job(kind)
            if job is not None and job.status().get("running"):
                if not job.stop_requested():  # a run the operator already cancelled keeps reading as theirs
                    with _STOP_LOCK:
                        _STOPPED_AT[kind] = now
                job.cancel()  # its runner terminates the child (SIGTERM, bounded wait, SIGKILL) at its next poll
                stopped.append(kind)
    except Exception:  # noqa: BLE001, S110 - one source of installs never hides the others
        pass
    try:
        from src.llm.pull_queue import get_pull_manager

        queued = get_pull_manager().stop_all(AI_INSTALL_STOPPED_NOTE)
    except Exception:  # noqa: BLE001, S110
        queued = False
    with _STOP_LOCK:
        streaming = _ACTIVE_PULLS > 0
    if queued or streaming:  # a pull on the direct route is stopped by the generation above and named here
        stopped.append("ollama-pull")
    if procs:
        with _STOP_LOCK:
            _STOPPED_AT["ollama-installer"] = now
        stopped.append("ollama-installer")
        for proc, group in procs:
            _threading.Thread(
                target=_terminate, args=(proc,), kwargs={"group": group}, name="ai-install-stop", daemon=True
            ).start()
    return stopped
