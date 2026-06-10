"""Uninstall the local app installation (virtualenv + desktop launchers).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A GUI counterpart to ``./install.sh --uninstall`` for users who never open a terminal.
It removes the **virtualenv** and the **desktop launchers**, and **keeps your data** —
destroying the corpus/keys is a separate, deliberate act (Settings → Safety → Panic wipe).

Doing this safely from the running server is the tricky part: the server runs *from* the
venv we want to delete. So we don't delete in-process. Instead we hand a tiny **detached
watcher** (the system Python, not the venv) the server's PID; it waits for the server to
exit, *then* removes the venv and launchers. The endpoint arms a graceful shutdown so the
server actually exits. Everything is dependency-injected so tests never delete anything.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

_LOG = logging.getLogger(__name__)

APP_NAME = "open-omniscience"

# The watcher runs after the server exits, with the SYSTEM Python (the venv is being
# removed). Stdlib only. argv: <server_pid> <json:{files:[...], venv:str|None}>.
_WATCHER_SRC = (
    "import os,sys,json,time,shutil\n"
    "pid=int(sys.argv[1]); plan=json.loads(sys.argv[2])\n"
    "for _ in range(240):\n"
    "    try: os.kill(pid,0)\n"
    "    except OSError: break\n"
    "    time.sleep(0.5)\n"
    "for f in plan.get('files',[]):\n"
    "    try: os.remove(f)\n"
    "    except OSError: pass\n"
    "v=plan.get('venv')\n"
    "if v: shutil.rmtree(v, ignore_errors=True)\n"
)


def repo_root() -> Path:
    """The installed app directory (where install.sh and .venv live)."""
    return Path(__file__).resolve().parents[2]


def _desktop_dir() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True,
                             text=True, timeout=3)
        p = Path(out.stdout.strip())
        if out.returncode == 0 and str(p):
            return p
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def _launcher_paths() -> list[Path]:
    """Every launcher install.sh may have created, all OSes (incl. the retired
    Desk launcher from older installs, so uninstall cleans those up too)."""
    apps = Path.home() / ".local" / "share" / "applications"
    desk = _desktop_dir()
    mac = Path.home() / "Desktop"
    stems = (APP_NAME, f"{APP_NAME}-desk", f"{APP_NAME}-uninstall")
    out: list[Path] = []
    for stem in stems:
        out.append(apps / f"{stem}.desktop")
        out.append(desk / f"{stem}.desktop")
    out += [mac / "Open Omniscience.command",
            mac / "Open Omniscience — Desk.command",
            mac / "Uninstall Open Omniscience.command"]
    return out


def plan_uninstall(src_dir: Path | None = None) -> dict:
    """Discover what an uninstall would remove (pure; deletes nothing). Data is never listed."""
    root = Path(src_dir) if src_dir else repo_root()
    venv = root / ".venv"
    launchers = [p for p in _launcher_paths() if p.exists()]
    try:
        from src.paths import data_dir as _data_dir
        data = str(_data_dir())
    except Exception:  # pragma: no cover - paths always importable in practice
        data = None
    install_script = root / "install.sh"
    return {
        "src_dir": str(root),
        "venv": str(venv) if venv.exists() else None,
        "launchers": [str(p) for p in launchers],
        "data_dir": data,           # reported for honesty; NEVER removed here
        "install_script": str(install_script) if install_script.exists() else None,
        "removable": bool(venv.exists() or launchers),
    }


def _system_python() -> str:
    """A Python that will survive the venv removal (prefer the OS one)."""
    for cand in ("/usr/bin/python3", "/usr/local/bin/python3"):
        if Path(cand).exists():
            return cand
    return shutil.which("python3") or sys.executable


def _default_spawn(plan: dict, server_pid: int) -> None:
    """Launch the detached watcher that removes venv+launchers after the server exits."""
    payload = {"files": plan["launchers"], "venv": plan["venv"]}
    log_path = None
    if plan.get("data_dir"):
        try:
            log_path = Path(plan["data_dir"]) / "uninstall.log"
        except OSError:
            log_path = None
    logf = open(log_path, "ab") if log_path else subprocess.DEVNULL  # noqa: SIM115
    subprocess.Popen(
        [_system_python(), "-c", _WATCHER_SRC, str(server_pid), json.dumps(payload)],
        stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
        start_new_session=True,           # detach: surviving our own shutdown
    )


def _default_arm_shutdown(delay: float = 2.0) -> None:
    """Ask the server to exit gracefully so the watcher can proceed."""
    def _stop() -> None:
        time.sleep(delay)
        _LOG.warning("uninstall: stopping the server (SIGTERM to self)")
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_stop, daemon=True).start()


def request_uninstall(*, confirm: bool, src_dir: Path | None = None,
                      _spawn=_default_spawn, _arm_shutdown=_default_arm_shutdown) -> dict:
    """Schedule removal of the venv + launchers (keeps data), then stop the server.

    Requires ``confirm=True``. Returns the plan; the actual deletion happens in a detached
    watcher *after* this process exits. ``_spawn``/``_arm_shutdown`` are injected in tests.
    """
    if not confirm:
        raise PermissionError("request_uninstall requires confirm=True")
    plan = plan_uninstall(src_dir)
    if not plan["removable"]:
        return {**plan, "scheduled": False,
                "note": "Nothing to remove (no virtualenv or launchers found). "
                        "Delete the app folder manually if needed."}
    _spawn(plan, os.getpid())
    _arm_shutdown()
    _LOG.warning("uninstall scheduled: venv=%s launchers=%d (data kept)",
                 plan["venv"], len(plan["launchers"]))
    return {**plan, "scheduled": True, "data_kept": True,
            "note": ("The app will stop in a moment; the virtualenv and desktop launchers "
                     "are then removed. Your data is kept — use Panic wipe to destroy it. "
                     "To remove the app folder entirely, delete it manually afterwards.")}
