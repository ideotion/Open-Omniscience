#!/usr/bin/env python3
"""Apply a checked update after the app has exited, then start it again. Standard library only (it runs while the app's own environment is mid-swap).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Started detached by ``src/maintenance/self_update.py:launch_helper`` with one argument, the plan file ``{ref, sha, kind, pid, root, python, port}``.
Steps, each of which refuses by leaving the install exactly as it was:

1. wait for the app's process to exit (up to ``WAIT_S``, 30 min; if it does not, touch NOTHING and say so: this never kills the app);
   then, when something already answers on the app's port (the person or a supervisor started it again), refuse and touch nothing;
2. the checkout must be on ``main``, clean, with ``origin`` = this repository over https;
3. ``git fetch`` the named ref, and require the fetched commit to equal the planned ``sha`` byte for byte;
4. ``git merge --ff-only`` it (cannot discard a local commit);
5. when ``requirements.lock`` or ``pyproject.toml`` changed, ``pip install --require-hashes -r requirements.lock``, then (``pyproject.toml`` changed,
   and setuptools is already installed) ``pip install -e . --no-deps --no-build-isolation``, which refreshes the version metadata with NOTHING
   downloaded (build isolation would fetch the build backend from PyPI with no hash; without setuptools the refresh is skipped and the
   version shown can lag until the installer is re-run); if the install fails, ``git reset --hard`` back to the old commit (safe: the tree was clean and only this script moved it) AND the old lock is installed
   again, so the old code never starts on the new packages (``rollback_incomplete`` when even that fails: re-run the installer);
6. start the launcher again and watch it: when the launcher exits before the app ever answers on its port, the update is undone the same way
   (``start_failed_rolled_back``) and the launcher started once more on the old version. On Windows the launcher is started with
   ``OO_UPDATE_WATCH`` so its window ends with the server instead of waiting for a key (``scripts/launch.cmd``), and a window the person CLOSED
   (``STATUS_CONTROL_C_EXIT``) is their stop, never undone. A new version that migrated the database before failing is rolled back onto that
   database: the old code then runs on the newer schema, which works only as far as that migration added rather than changed (stated, not
   checked here); the result says the start failed, and re-running the installer on the new version is the way forward; write ``update-result.json`` in the data directory
   (read by Settings -> Advanced after the restart).

Every child (git, pip, the build step, the launcher) runs WITHOUT the passphrase variables (``SECRET_ENV``): the server already starts this
helper without them, and this strips them again, so a start that handed the app ``OO_DB_PASSPHRASE`` comes back locked.

The result file holds a fixed ``status`` word, the two versions' commit prefixes and nothing else: no path to a secret, no command output.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

#: How long to wait for the app to exit. The app's own graceful shutdown is bounded at 30 s; a long WAL checkpoint can take longer, and an app that
#: stops later must still be started again, so this waits generously rather than giving up and leaving it down.
WAIT_S = 1800
GIT_TIMEOUT_S = 600
PIP_TIMEOUT_S = 3600
ORIGIN_OK = "https://github.com/ideotion/open-omniscience"
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
#: How long the restarted app gets to answer on its port before its start is called unconfirmed (a first boot after an update can migrate).
BOOT_WAIT_S = 900
#: The passphrase variables (``src/monitoring/secret_scrub.py:HELD_ENV_VARS``; a test pins the two equal). No child of this helper gets them.
SECRET_ENV = ("OO_DB_PASSPHRASE", "OO_KEY_PASSPHRASE")
LOCK_FILE = "update.lock"
RESULT_FILE = "update-result.json"


def child_env() -> dict[str, str]:
    """This process's environment without :data:`SECRET_ENV`, and with git never prompting."""
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run(root: Path, *argv: str, timeout: int = GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    """Run one fixed argv. A timeout or a missing program is a FAILED step (returncode 124/127), never an exception that would kill the helper
    between steps and leave the checkout moved with nothing recorded."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, cwd=str(root), capture_output=True, text=True, timeout=timeout, check=False,
            env=child_env(),
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", "timeout")
    except OSError:
        return subprocess.CompletedProcess(argv, 127, "", "not runnable")


def _git(root: Path, *args: str, timeout: int = GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    return _run(root, "git", "-C", str(root), *args, timeout=timeout)


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return k32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_exit(pid: int, limit: float = WAIT_S, *, alive=pid_alive, sleep=time.sleep) -> bool:
    deadline = time.monotonic() + limit
    while alive(pid):
        if time.monotonic() >= deadline:
            return False
        sleep(0.5)
    return True


def _install_deps(root: Path, py: str, run, *, refresh_metadata: bool = True) -> bool:
    """The hash-pinned lock, then (``refresh_metadata``) the editable metadata with no build isolation, so nothing unhashed is downloaded."""
    if run(root, py, "-m", "pip", "install", "--require-hashes", "-r", "requirements.lock", timeout=PIP_TIMEOUT_S).returncode != 0:
        return False
    if not refresh_metadata or run(root, py, "-c", "import setuptools").returncode != 0:
        return True  # nothing else to do, or no local build backend: skip the refresh rather than fetch one unhashed
    return run(root, py, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", ".", timeout=PIP_TIMEOUT_S).returncode == 0


def changed_files(root: Path, old: str, new: str, *, git=_git) -> list[str]:
    return git(root, "diff", "--name-only", f"{old}..{new}").stdout.split()


def roll_back(root: Path, old: str, changed: list[str], py: str, *, git=_git, run=_run) -> bool:
    """Put the checkout back on ``old`` (safe: it was clean and only this helper moved it) and, when the update changed the dependencies, the
    environment from the old lock too, so the old code never starts on the new packages. False when either step failed."""
    if git(root, "reset", "--hard", old).returncode != 0:
        return False
    if any(f in ("requirements.lock", "pyproject.toml") for f in changed):
        return _install_deps(root, py, run, refresh_metadata="pyproject.toml" in changed)
    return True


def apply(plan: dict, *, git=_git, run=_run) -> tuple[str, str]:
    """Do steps 2-5. Returns ``(status, old_head)``; ``status`` is ``updated``, ``already_current`` or one fixed refusal word."""
    root = Path(plan["root"])
    ref, sha = plan["ref"], plan["sha"]
    if not SHA_RE.match(sha) or not (TAG_RE.match(ref) or ref == "main"):
        return "bad_plan", ""
    origin = git(root, "config", "--get", "remote.origin.url")
    if origin.returncode != 0 or origin.stdout.strip().removesuffix(".git").lower() != ORIGIN_OK:
        return "origin_not_this_repository", ""
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch.returncode != 0 or branch.stdout.strip() != "main":
        return "not_on_main", ""
    dirty = git(root, "status", "--porcelain")
    if dirty.returncode != 0 or dirty.stdout.strip():
        return "local_changes", ""
    old = git(root, "rev-parse", "HEAD").stdout.strip()
    if old == sha:
        return "already_current", old
    refspec = f"refs/tags/{ref}" if ref != "main" else "refs/heads/main"
    if git(root, "fetch", "--no-tags", "origin", refspec).returncode != 0:
        return "fetch_failed", old
    fetched = git(root, "rev-parse", "FETCH_HEAD^{commit}")
    if fetched.returncode != 0 or fetched.stdout.strip() != sha:
        return "commit_mismatch", old
    if git(root, "merge-base", "--is-ancestor", sha, old).returncode == 0:
        return "already_current", old  # the checkout already contains that version (a pull without a reinstall, a tag behind main)
    if git(root, "merge", "--ff-only", sha).returncode != 0:
        return "not_a_fast_forward", old
    changed = changed_files(root, old, sha, git=git)
    if any(f in ("requirements.lock", "pyproject.toml") for f in changed):
        py = plan.get("python") or sys.executable
        if os.name == "nt":
            time.sleep(3)  # the console-script launcher may still hold its own .exe for a moment after the Python process exits
        if not _install_deps(root, py, run, refresh_metadata="pyproject.toml" in changed):
            if not roll_back(root, old, changed, py, git=git, run=run):
                return "rollback_incomplete", old
            return "dependencies_failed_rolled_back", old
    return "updated", old


def server_answers(port: int) -> bool:
    """Something is listening on the app's loopback port (a TCP connect, no request sent)."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def wait_for_server(port: int, limit: float = 120.0, *, answers=server_answers, sleep=time.sleep) -> bool:
    deadline = time.monotonic() + limit
    while not answers(port):
        if time.monotonic() >= deadline:
            return False
        sleep(2)
    return True


def relaunch(root: Path, *, popen=subprocess.Popen, watched: bool = False):
    """Start the launcher again; returns its process (``None`` when it could not be started). ``watched``: the Windows launcher ends with its
    server instead of waiting for a key, so :func:`watch_start` can see a failed start."""
    quiet = subprocess.DEVNULL
    env = child_env()
    if watched:
        env["OO_UPDATE_WATCH"] = "1"
    try:
        if os.name == "nt":
            # A console of its own: the launcher says "close this window to stop the app", so it needs a window (never DETACHED_PROCESS here).
            # No std handle redirected: passing any one makes Popen hand the console ALL of this helper's (NUL) handles, and the window is blank.
            return popen(["cmd", "/c", str(root / "scripts" / "launch.cmd")], cwd=str(root), env=env, creationflags=0x00000010)  # noqa: S603
        return popen(  # noqa: S603 - fixed argv, no shell
            ["bash", str(root / "scripts" / "launch.sh")], stdin=quiet, stdout=quiet, stderr=quiet, cwd=str(root), env=env, start_new_session=True,
        )
    except OSError:
        return None


#: The exit status of a console process whose window was closed (or that got Ctrl-C), as Python reports it on Windows, unsigned and signed.
CLOSED_BY_PERSON = (0xC000013A, -1073741510)


def watch_start(proc, port: int, limit: float = BOOT_WAIT_S, *, answers=server_answers, sleep=time.sleep) -> str:
    """``up`` once the app answers on its port; ``exited`` when the launcher ended (or never started) before it did, which is a failed start;
    ``closed`` when it ended because the person closed its window (their stop, never undone); ``unknown`` when nothing happened within ``limit``
    (a long first boot): never undone then either, because the new version may be mid-migration."""
    deadline = time.monotonic() + limit
    while True:
        if answers(port):
            return "up"
        code = None if proc is None else proc.poll()
        if proc is None or code is not None:
            if answers(port):
                return "up"
            return "closed" if code in CLOSED_BY_PERSON else "exited"
        if time.monotonic() >= deadline:
            return "unknown"
        sleep(2)


def write_result(plan: dict, status: str, old: str, data_dir: Path) -> None:
    body = {"status": status, "ref": plan.get("ref"), "from": old[:9], "to": plan.get("sha", "")[:9], "at": time.time()}
    with contextlib.suppress(OSError):
        (data_dir / RESULT_FILE).write_text(json.dumps(body), encoding="utf-8")


def _lock_owner(lock: Path) -> tuple[int, int]:
    """``(app pid, helper pid)`` recorded in ``lock``, ``(0, 0)`` when it cannot be read."""
    try:
        app, helper = (int(x) for x in lock.read_text(encoding="utf-8").split())
    except (OSError, ValueError):
        return (0, 0)
    return (app, helper)


#: A lock older than this is stale whoever it names: longer than any real run (a 30 min wait, four pip runs of up to an hour, the git steps),
#: so only a helper pid that a reboot recycled could still look alive at that age.
LOCK_STALE_S = 8 * 3600


def lock_holder_alive(lock: Path, *, alive=None, now=time.time) -> tuple[int, int] | None:
    """The ``(app pid, helper pid)`` of a lock whose helper is still running and which is younger than :data:`LOCK_STALE_S`, else None."""
    alive = alive or pid_alive
    owner_app, owner_helper = _lock_owner(lock)
    try:
        fresh = now() - lock.stat().st_mtime < LOCK_STALE_S
    except OSError:
        return None
    if fresh and owner_helper and owner_helper != os.getpid() and alive(owner_helper):
        return (owner_app, owner_helper)
    return None


def take_lock(lock: Path, app_pid: int, *, alive=None, now=time.time) -> bool:
    """Create ``lock`` naming the app process this helper serves and this helper, or take over a stale one. False while a LIVE helper holds a
    fresh lock, whichever app it served: it may be mid-pip for an earlier app while the person started the app again by hand, and two
    helpers on one checkout would undo each other. A lock whose helper is gone, or older than :data:`LOCK_STALE_S`, is taken over. The
    content is written beside the lock and hard-linked into place, so a reader never sees an empty lock where hard links exist (on a
    filesystem without them the exclusive create is followed by the write: a short window, stated)."""
    mine = f"{app_pid} {os.getpid()}"
    tmp = lock.with_name(f"{lock.name}.{os.getpid()}.tmp")
    tmp.write_text(mine, encoding="utf-8")
    try:
        for _ in range(3):
            try:
                os.link(tmp, lock)
                return True
            except FileExistsError:
                pass
            except OSError:  # no hard links on this filesystem: the plain exclusive create, then the content
                try:
                    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    pass
                else:
                    os.write(fd, mine.encode())
                    os.close(fd)
                    return True
            if lock_holder_alive(lock, alive=alive, now=now) is not None:
                return False
            with contextlib.suppress(OSError):
                lock.unlink()
        return False
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def release_lock(lock: Path) -> None:
    """Remove ``lock`` only while it is still this process's (a helper that lost it to a take-over must not delete the new owner's)."""
    if _lock_owner(lock)[1] == os.getpid():
        with contextlib.suppress(OSError):
            lock.unlink()


def main(argv: list[str]) -> int:
    plan_path = Path(argv[1])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    data_dir = plan_path.parent
    root = Path(plan["root"])
    # One helper at a time on a checkout: a live helper's fresh lock is obeyed; a lock whose helper is gone, or that is older than any run, is
    # taken over.
    lock = data_dir / LOCK_FILE
    holder = None
    for _ in range(3):
        if take_lock(lock, int(plan["pid"])):
            break
        holder = lock_holder_alive(lock)
        if holder is not None:
            break  # a live holder, read once: decide on THIS reading
        # the holder let go between the two reads: try to take the lock again
    else:
        holder = (0, 0)  # could neither take nor read it three times: behave as for an earlier run's holder
    if holder is not None:
        if holder[0] == int(plan["pid"]):
            return 1  # a live helper serves this same shutdown: it applies and relaunches; this one touches nothing and starts nothing
        # The holder serves an EARLIER app run (a race the server's own check narrows). Its relaunch may land while this app is still up and be
        # a no-op, so this helper, which touches nothing in the install, makes sure the app comes back: after this app and the holder have
        # both exited it gives the holder's launcher time to bring a server up, and starts the launcher only if none answers.
        if wait_for_exit(int(plan["pid"])):
            if holder[1]:
                wait_for_exit(holder[1], LOCK_STALE_S)
            if not wait_for_server(int(plan.get("port") or 8000)):
                relaunch(root)
        return 1
    try:
        # Recorded FIRST, so a helper that dies part-way leaves "started" behind rather than an older attempt's "updated".
        write_result(plan, "started", "", data_dir)
        if not wait_for_exit(int(plan["pid"])):
            write_result(plan, "app_did_not_stop", "", data_dir)
            return 1  # the app is still running and untouched; nothing was changed
        port = int(plan.get("port") or 8000)
        if server_answers(port):
            # Started again already (by hand, or a supervisor): swapping files under a running app would mix two versions. Touch nothing.
            write_result(plan, "app_running_again", "", data_dir)
            return 1
        status, old = apply(plan)
        write_result(plan, status, old, data_dir)
        with contextlib.suppress(OSError):
            plan_path.unlink()
        if status == "updated" and server_answers(port):
            # Somebody started the app while the files were being swapped: it may have loaded some of each version. Say so; do not start a second.
            write_result(plan, "app_started_during_update", old, data_dir)
            return 1
        proc = relaunch(root, watched=status == "updated")
        if status == "updated":
            started = watch_start(proc, port)
            if started == "exited" and not server_answers(port):
                # The new version did not come up: undo it and start the old one, which ran a minute ago.
                changed = changed_files(root, old, plan["sha"])
                ok = roll_back(root, old, changed, plan.get("python") or sys.executable)
                status = "start_failed_rolled_back" if ok else "rollback_incomplete"
                write_result(plan, status, old, data_dir)
                relaunch(root)
            elif started != "up":
                status = "start_unconfirmed"
                write_result(plan, status, old, data_dir)
        return 0 if status in ("updated", "already_current", "start_unconfirmed") else 1
    finally:
        release_lock(lock)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
