#!/usr/bin/env python3
"""Apply a checked update after the app has exited, then start it again. Standard library only (it runs while the app's own environment is mid-swap).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Started detached by ``src/maintenance/self_update.py:launch_helper`` with one argument, the plan file ``{ref, sha, kind, pid, root, python, port}``.
Steps, each of which refuses by leaving the install exactly as it was:

1. wait for the app's process to exit (up to ``WAIT_S``, 30 min; if it does not, touch NOTHING and say so: this never kills the app);
2. the checkout must be on ``main``, clean, with ``origin`` = this repository over https;
3. ``git fetch`` the named ref, and require the fetched commit to equal the planned ``sha`` byte for byte;
4. ``git merge --ff-only`` it (cannot discard a local commit);
5. when ``requirements.lock`` or ``pyproject.toml`` changed, ``pip install --require-hashes -r requirements.lock`` then ``pip install -e . --no-deps``;
   if that fails, ``git reset --hard`` back to the old commit (safe: the tree was clean and only this script moved it) AND the old lock is installed
   again, so the old code never starts on the new packages (``rollback_incomplete`` when even that fails: re-run the installer);
6. start the launcher again, and write ``update-result.json`` in the data directory (read by Settings -> Advanced after the restart).

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
LOCK_FILE = "update.lock"
RESULT_FILE = "update-result.json"


def _run(root: Path, *argv: str, timeout: int = GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    """Run one fixed argv. A timeout or a missing program is a FAILED step (returncode 124/127), never an exception that would kill the helper
    between steps and leave the checkout moved with nothing recorded."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, cwd=str(root), capture_output=True, text=True, timeout=timeout, check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
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


def _install_deps(root: Path, py: str, run) -> bool:
    ok = run(root, py, "-m", "pip", "install", "--require-hashes", "-r", "requirements.lock", timeout=PIP_TIMEOUT_S).returncode == 0
    return ok and run(root, py, "-m", "pip", "install", "-e", ".", "--no-deps", timeout=PIP_TIMEOUT_S).returncode == 0


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
    changed = git(root, "diff", "--name-only", f"{old}..{sha}").stdout.split()
    if any(f in ("requirements.lock", "pyproject.toml") for f in changed):
        py = plan.get("python") or sys.executable
        if os.name == "nt":
            time.sleep(3)  # the console-script launcher may still hold its own .exe for a moment after the Python process exits
        if not _install_deps(root, py, run):
            # Put BOTH back: the checkout, then the environment from the old lock, so the old code does not start on the new packages.
            if git(root, "reset", "--hard", old).returncode != 0:
                return "rollback_incomplete", old
            if not _install_deps(root, py, run):
                return "rollback_incomplete", old
            return "dependencies_failed_rolled_back", old
    return "updated", old


def relaunch(root: Path, *, popen=subprocess.Popen) -> None:
    quiet = subprocess.DEVNULL
    if os.name == "nt":
        # A console of its own: the launcher says "close this window to stop the app", so it needs a window (never DETACHED_PROCESS here).
        # No std handle redirected: passing any one makes Popen hand the console ALL of this helper's (NUL) handles, and the window is blank.
        popen(["cmd", "/c", str(root / "scripts" / "launch.cmd")], cwd=str(root), creationflags=0x00000010)  # noqa: S603
    else:
        popen(["bash", str(root / "scripts" / "launch.sh")], stdin=quiet, stdout=quiet, stderr=quiet, cwd=str(root), start_new_session=True)  # noqa: S603


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


def lock_holder_alive(lock: Path, *, alive=pid_alive, now=time.time) -> tuple[int, int] | None:
    """The ``(app pid, helper pid)`` of a lock whose helper is still running and which is younger than :data:`LOCK_STALE_S`, else None."""
    owner_app, owner_helper = _lock_owner(lock)
    try:
        fresh = now() - lock.stat().st_mtime < LOCK_STALE_S
    except OSError:
        return None
    if fresh and owner_helper and owner_helper != os.getpid() and alive(owner_helper):
        return (owner_app, owner_helper)
    return None


def take_lock(lock: Path, app_pid: int, *, alive=pid_alive, now=time.time) -> bool:
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
    if not take_lock(lock, int(plan["pid"])):
        holder = lock_holder_alive(lock)
        if holder is None or holder[0] == int(plan["pid"]):
            return 1  # a live helper already serves this same shutdown: it applies and relaunches; this one touches nothing
        # The holder serves an EARLIER app run (the server checks the lock before stopping, so this is a race). This helper touches nothing,
        # but the app it was started for is stopping: wait for the holder to finish, then start the launcher so the app is not left down.
        if wait_for_exit(int(plan["pid"])):
            wait_for_exit(holder[1], LOCK_STALE_S)
            relaunch(root)
        return 1
    try:
        # Recorded FIRST, so a helper that dies part-way leaves "started" behind rather than an older attempt's "updated".
        write_result(plan, "started", "", data_dir)
        if not wait_for_exit(int(plan["pid"])):
            write_result(plan, "app_did_not_stop", "", data_dir)
            return 1  # the app is still running and untouched; nothing was changed
        status, old = apply(plan)
        write_result(plan, status, old, data_dir)
        with contextlib.suppress(OSError):
            plan_path.unlink()
        relaunch(root)
        return 0 if status in ("updated", "already_current") else 1
    finally:
        release_lock(lock)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
