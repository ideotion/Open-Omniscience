#!/usr/bin/env python3
"""Apply a checked update after the app has exited, then start it again. Standard library only (it runs while the app's own environment is mid-swap).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Started detached by ``src/maintenance/self_update.py:launch_helper`` with one argument, the plan file ``{ref, sha, kind, pid, root, python, port}``.
Steps, each of which refuses by leaving the install exactly as it was:

1. wait for the app's process to exit (up to ``WAIT_S``; if it does not, touch NOTHING and say so: this never kills the app);
2. the checkout must be on ``main``, clean, with ``origin`` = this repository over https;
3. ``git fetch`` the named ref, and require the fetched commit to equal the planned ``sha`` byte for byte;
4. ``git merge --ff-only`` it (cannot discard a local commit);
5. when ``requirements.lock`` or ``pyproject.toml`` changed, ``pip install --require-hashes -r requirements.lock`` then ``pip install -e . --no-deps``;
   if that fails, ``git reset --hard`` back to the old commit (safe: the tree was clean and only this script moved it);
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

WAIT_S = 240
ORIGIN_OK = "https://github.com/ideotion/open-omniscience"
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _run(root: Path, *argv: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv, cwd=str(root), capture_output=True, text=True, timeout=timeout, check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _git(root: Path, *args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return _run(root, "git", "-C", str(root), *args, timeout=timeout)


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
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


def apply(plan: dict, *, git=_git, run=_run) -> tuple[str, str]:
    """Do steps 2-5. Returns ``(status, old_head)``; ``status`` is ``updated`` or one fixed refusal word."""
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
    refspec = f"refs/tags/{ref}" if ref != "main" else "refs/heads/main"
    if git(root, "fetch", "--no-tags", "origin", refspec).returncode != 0:
        return "fetch_failed", old
    fetched = git(root, "rev-parse", "FETCH_HEAD^{commit}")
    if fetched.returncode != 0 or fetched.stdout.strip() != sha:
        return "commit_mismatch", old
    if git(root, "merge", "--ff-only", sha).returncode != 0:
        return "not_a_fast_forward", old
    changed = git(root, "diff", "--name-only", f"{old}..{sha}").stdout.split()
    if any(f in ("requirements.lock", "pyproject.toml") for f in changed):
        py = plan.get("python") or sys.executable
        ok = run(root, py, "-m", "pip", "install", "--require-hashes", "-r", "requirements.lock").returncode == 0
        ok = ok and run(root, py, "-m", "pip", "install", "-e", ".", "--no-deps").returncode == 0
        if not ok:
            git(root, "reset", "--hard", old)
            return "dependencies_failed_rolled_back", old
    return "updated", old


def relaunch(root: Path, *, popen=subprocess.Popen) -> None:
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "cwd": str(root)}
    if os.name == "nt":
        argv = ["cmd", "/c", str(root / "scripts" / "launch.cmd")]
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        argv = ["bash", str(root / "scripts" / "launch.sh")]
        kwargs["start_new_session"] = True
    popen(argv, **kwargs)  # noqa: S603 - fixed argv, no shell


def write_result(plan: dict, status: str, old: str, data_dir: Path) -> None:
    body = {"status": status, "ref": plan.get("ref"), "from": old[:9], "to": plan.get("sha", "")[:9], "at": time.time()}
    with contextlib.suppress(OSError):
        (data_dir / "update-result.json").write_text(json.dumps(body), encoding="utf-8")


def main(argv: list[str]) -> int:
    plan_path = Path(argv[1])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    data_dir = plan_path.parent
    root = Path(plan["root"])
    if not wait_for_exit(int(plan["pid"])):
        write_result(plan, "app_did_not_stop", "", data_dir)
        return 1  # the app is still running and untouched; nothing was changed
    status, old = apply(plan)
    write_result(plan, status, old, data_dir)
    with contextlib.suppress(OSError):
        plan_path.unlink()
    relaunch(root)
    return 0 if status == "updated" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
