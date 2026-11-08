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
4. when the new version changes the app's DEPENDENCIES (``requirements.lock``, or in ``pyproject.toml`` the dependency lists, the extras,
   ``requires-python`` or the build system), refuse BEFORE swapping (``dependencies_changed``): the installers resolve packages per install
   (``install.sh`` uses the lock only when it covers the chosen extras and the Python version, ``install.ps1`` never does), so no single
   in-place pip run is right for every install, and the installer is the way to take such a release. So this helper NEVER downloads a
   package, and needs no host but github.com;
5. ``git merge --ff-only`` it (cannot discard a local commit);
6. when ``pyproject.toml`` changed (the version, every release), refresh the editable metadata with
   ``pip install --no-index --no-deps --no-build-isolation -e .``: no network at all; skipped when setuptools is not installed (the version
   shown then lags until the installer is re-run); a failed refresh puts the checkout back (``git reset --hard``, safe: the tree was clean and
   only this script moved it);
7. start the launcher again and watch it: when the launcher exits before the app ever answers on its port, the update is undone the same way
   (``start_failed_rolled_back``) and the launcher started once more on the old version. On Windows the launcher is started with
   ``OO_UPDATE_WATCH`` so its window ends with the server instead of waiting for a key (``scripts/launch.cmd``, which clears it before the
   server starts), and a window the person CLOSED (``STATUS_CONTROL_C_EXIT``) is their stop, never undone. A new version that changes the database code
   (``migrations/versions/`` or ``src/database/``) may have altered the store at start-up before failing (``init_db``'s ``create_all``,
   FTS tables and triggers, the ``ensure_*`` self-heals; alembic itself never runs against the live store at boot): it is still rolled back (a down app shows no message at all) and the result
   is ``start_failed_rolled_back_schema``, so Settings says to restore the last backup or re-run the installer if the app misbehaves. Every
   reset runs only while the checkout is still exactly as this helper left it (:func:`checkout_is`); write ``update-result.json`` in the data directory (read by Settings -> Advanced after the restart).

Every child (git, pip, the launcher) runs WITHOUT the passphrase variables (``SECRET_ENV``): the server already starts this helper without
them, and this strips them again, so a start that handed the app ``OO_DB_PASSPHRASE`` comes back locked. On Windows, git and pip run with no
console window of their own (the helper has none).

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
#: Where a change can alter the live store when the new version starts (migrations, and init_db's own schema code).
SCHEMA_PATHS = ("migrations/versions/", "src/database/")
LOCK_FILE = "update.lock"
RESULT_FILE = "update-result.json"


def child_env() -> dict[str, str]:
    """This process's environment without :data:`SECRET_ENV`, and with git never prompting."""
    # OO_UPDATE_WATCH too: it is for the one launcher a watched relaunch starts, never inherited by anything after it.
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV and k != "OO_UPDATE_WATCH"}
    if env.get("OO_ARENA_MAX_DEFAULTED") == "1":
        # launch.sh's own malloc default (R114), not the operator's: dropped, or the relaunched launcher would take it as a choice.
        env.pop("OO_ARENA_MAX_DEFAULTED", None)
        env.pop("MALLOC_ARENA_MAX", None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run(root: Path, *argv: str, timeout: int = GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    """Run one fixed argv. A timeout or a missing program is a FAILED step (returncode 124/127), never an exception that would kill the helper
    between steps and leave the checkout moved with nothing recorded."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, cwd=str(root), capture_output=True, text=True, timeout=timeout, check=False,
            env=child_env(), creationflags=0x08000000 if os.name == "nt" else 0,  # CREATE_NO_WINDOW: no console window per git/pip step
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


def _setuptools_floor(root: Path) -> int:
    """The major version ``[build-system] requires`` asks of setuptools (``setuptools>=77`` -> 77), 0 when it names none."""
    import tomllib

    try:
        reqs = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get("build-system", {}).get("requires", [])
    except (OSError, ValueError):
        return 0
    for req in reqs if isinstance(reqs, list) else []:
        m = re.match(r"^\s*setuptools\s*>=\s*(\d+)", str(req))
        if m:
            return int(m.group(1))
    return 0


def refresh_metadata(root: Path, py: str, run) -> bool:
    """Re-register the editable install's metadata (version, entry points) with NOTHING downloaded: no index, no dependencies, no build
    isolation. True when done or skipped: no local setuptools, or one older than the build system asks for (a build with it would fail
    on every release); the version shown then lags until the installer is re-run."""
    probe = f"import setuptools, sys; sys.exit(0 if int(setuptools.__version__.split('.')[0]) >= {_setuptools_floor(root)} else 1)"
    if run(root, py, "-c", probe).returncode != 0:
        return True
    argv = (py, "-m", "pip", "install", "--no-index", "--no-deps", "--no-build-isolation", "-e", ".")
    return run(root, *argv, timeout=PIP_TIMEOUT_S).returncode == 0


#: The parts of ``pyproject.toml`` that decide which packages an install holds. A change to any of them is a dependency change.
_DEP_KEYS = (("project", "dependencies"), ("project", "optional-dependencies"), ("project", "requires-python"), ("build-system",))


def _dependency_view(root: Path, rev: str, git) -> object:
    import tomllib

    shown = git(root, "show", f"{rev}:pyproject.toml")
    if shown.returncode != 0:
        return ("no pyproject.toml",)  # absent (or unreadable) at that commit: equal only to the same answer at the other
    try:
        data = tomllib.loads(shown.stdout)
    except (tomllib.TOMLDecodeError, ValueError):
        return ("unreadable", shown.stdout)
    view = []
    for path in _DEP_KEYS:
        node: object = data
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
        view.append(node)
    return view


def dependencies_changed(root: Path, old: str, new: str, *, git=_git) -> bool:
    """True when ``new`` changes the dependency lock or the dependency parts of ``pyproject.toml`` (anything unreadable counts as changed)."""
    lock = git(root, "diff", "--quiet", old, new, "--", "requirements.lock")
    if lock.returncode != 0:
        return True
    return _dependency_view(root, old, git) != _dependency_view(root, new, git)


def changed_files(root: Path, old: str, new: str, *, git=_git) -> list[str]:
    return git(root, "diff", "--name-only", f"{old}..{new}").stdout.split()


def checkout_is(root: Path, head: str, *, git=_git) -> bool:
    """The checkout is still exactly where this helper left it: HEAD is ``head``, on ``main``, with nothing changed in the tree. Asked
    before every reset, so a reset can never discard an edit, or move a branch, that somebody else made since."""
    now = git(root, "rev-parse", "HEAD")
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    dirty = git(root, "status", "--porcelain")
    return (
        now.returncode == 0 and now.stdout.strip() == head
        and branch.returncode == 0 and branch.stdout.strip() == "main"
        and dirty.returncode == 0 and not dirty.stdout.strip()
    )


def roll_back(root: Path, old: str, changed: list[str], py: str, *, new: str = "", git=_git, run=_run) -> bool:
    """Put the checkout back on ``old`` and, when ``pyproject.toml`` had changed, try its metadata too (best effort: it only names the
    version; when it fails the version shown lags until the installer is re-run). No package was installed by the update, so there is no
    environment to restore. ONLY while the checkout is still exactly as the update left it (``new``, on ``main``, clean): an edit or a
    branch switch made since (the new version may have run for many minutes) is never reset; False then, the tree untouched, and False
    when the reset itself failed."""
    if new and not checkout_is(root, new, git=git):
        return False
    if git(root, "reset", "--hard", old).returncode != 0:
        return False
    if "pyproject.toml" in changed:
        refresh_metadata(root, py, run)
    return True


def apply(plan: dict, *, git=_git, run=_run) -> tuple[str, str]:
    """Do steps 2-6. Returns ``(status, old_head)``; ``status`` is ``updated``, ``already_current`` or one fixed refusal word."""
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
    if dependencies_changed(root, old, sha, git=git):
        return "dependencies_changed", old  # nothing swapped: the installer takes this release
    if os.name == "nt":
        # The old window's launcher wrapper may still be finishing after the server's process exited, and cmd.exe resumes launch.cmd by byte
        # offset when it returns: give it a moment before the checkout (and so launch.cmd) can change; the console-script .exe is freed too.
        time.sleep(5)
    # Clean AGAIN, right before the swap: the fetch can take minutes, and an edit made meanwhile must stop the update rather than meet the
    # reset below (which would discard it).
    dirty = git(root, "status", "--porcelain")
    if dirty.returncode != 0 or dirty.stdout.strip():
        return "local_changes", old
    merged = git(root, "merge", "--ff-only", sha)
    if merged.returncode != 0:
        if merged.returncode == 124 and os.name != "nt":
            # killed by the timeout mid-checkout: on POSIX the killed git is reaped before this line, so its index lock is stale (and this
            # helper holds update.lock, so no other git of ours runs here). NOT on Windows: killing Git for Windows' cmd\git.exe wrapper can
            # leave the real git running and holding that lock, so it is left alone and the reset below fails: rollback_incomplete, said.
            with contextlib.suppress(OSError):
                (root / ".git" / "index.lock").unlink()
        head = git(root, "rev-parse", "HEAD")
        branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
        if head.stdout.strip() != old or branch.stdout.strip() != "main":
            return "rollback_incomplete", old  # not where this helper left it: reset nothing
        # git writes the new files one by one BEFORE it moves HEAD: a merge that stopped part-way (a file held open, a path too long, the
        # timeout) leaves some files new under the old HEAD. Put the tree back; safe, as it was clean and HEAD is still the old commit.
        if git(root, "reset", "--hard", old).returncode != 0:
            return "rollback_incomplete", old
        return "not_a_fast_forward", old
    changed = changed_files(root, old, sha, git=git)
    if "pyproject.toml" in changed:
        py = plan.get("python") or sys.executable
        if not refresh_metadata(root, py, run):
            ok = roll_back(root, old, changed, py, new=sha, git=git, run=run)
            return ("install_failed_rolled_back" if ok else "rollback_incomplete"), old
    return "updated", old


def server_answers(port: int) -> bool:
    """Something is listening on the app's loopback port (a TCP connect, no request sent), on IPv4 or IPv6 loopback (``OO_HOST=::1``)."""
    import socket

    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            continue
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


def _port(plan: dict) -> int:
    try:
        return int(plan.get("port") or 8000)
    except (TypeError, ValueError):
        return 8000


def _pid(plan: dict) -> int:
    try:
        return int(plan.get("pid") or 0)
    except (TypeError, ValueError):
        return 0


def main(argv: list[str]) -> int:
    """Run the update, and whatever goes wrong inside it, make sure the app comes back: the app has already been asked to stop when this
    starts, so a helper that died on an unexpected error (a full data drive, an unreadable plan) would otherwise leave it down."""
    plan_path = Path(argv[1])
    data_dir = plan_path.parent
    plan: dict = {}
    root = Path(__file__).resolve().parents[1]  # this script's own checkout, until the plan names one
    try:
        loaded = json.loads(plan_path.read_text(encoding="utf-8"))
        plan = loaded if isinstance(loaded, dict) else {}
        root = Path(plan["root"])
        return _main(plan_path, plan, data_dir, root)
    except Exception:  # noqa: BLE001 - the one place that must not let any failure leave the app down
        if not plan.get("_applied"):
            write_result(plan, "helper_failed", "", data_dir)  # after the swap the result already written says what happened: kept
        pid = _pid(plan)
        if not plan.get("_relaunched") and (not pid or wait_for_exit(pid)) and not server_answers(_port(plan)):
            relaunch(root)
        return 1


def _main(plan_path: Path, plan: dict, data_dir: Path, root: Path) -> int:
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
            if not wait_for_server(_port(plan)):
                relaunch(root)
        return 1
    try:
        # Recorded FIRST, so a helper that dies part-way leaves "started" behind rather than an older attempt's "updated".
        write_result(plan, "started", "", data_dir)
        if not wait_for_exit(int(plan["pid"])):
            # Nothing was changed. The app has closed its port and engaged the kill switch, so it must not stay down when it does stop:
            # keep waiting (no update), then start it again unless something already answers.
            write_result(plan, "app_did_not_stop", "", data_dir)
            if wait_for_exit(int(plan["pid"]), LOCK_STALE_S) and not server_answers(_port(plan)):
                relaunch(root)
            return 1
        port = _port(plan)
        if server_answers(port):
            # Started again already (by hand, or a supervisor): swapping files under a running app would mix two versions. Touch nothing.
            write_result(plan, "app_running_again", "", data_dir)
            return 1
        status, old = apply(plan)
        write_result(plan, status, old, data_dir)
        plan["_applied"] = status
        with contextlib.suppress(OSError):
            plan_path.unlink()
        if status == "updated" and server_answers(port):
            # Somebody started the app while the files were being swapped: it may have loaded some of each version. Say so; do not start a second.
            write_result(plan, "app_started_during_update", old, data_dir)
            return 1
        proc = relaunch(root, watched=status == "updated")
        plan["_relaunched"] = True  # main()'s last-resort handler must not start a second launcher after this
        if status == "updated":
            started = watch_start(proc, port)
            if started == "exited" and not server_answers(port):
                # The new version did not come up: undo it and start the old one, which ran a minute ago.
                changed = changed_files(root, old, plan["sha"])
                ok = roll_back(root, old, changed, plan.get("python") or sys.executable, new=plan["sha"])
                # A new version whose database code changed may have altered the store at start-up (init_db: create_all, FTS tables and
                # triggers, the ensure_* self-heals) before failing: the old code then starts on that store. It is still started (a down app
                # shows no message at all), and the result names the case so Settings can say so.
                schema = any(f.startswith(SCHEMA_PATHS) for f in changed)
                status = ("start_failed_rolled_back_schema" if schema else "start_failed_rolled_back") if ok else "rollback_incomplete"
                write_result(plan, status, old, data_dir)
                relaunch(root)
            elif started == "unknown":
                status = "start_unconfirmed"
                write_result(plan, status, old, data_dir)
            # "closed": the person closed the new window themselves; the update stands, "updated" is the truth
        return 0 if status in ("updated", "already_current", "start_unconfirmed") else 1
    finally:
        release_lock(lock)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
