"""Why Windows will not let the restore replace the corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-08-23, twice from the same Windows 11 machine: a ten-minute
import reached its final step and died with ``[WinError 32] ... -wal``. The
retry that was added after the first report waited and still lost, which means
the holder is not the transient handle the retry was designed for -- and the OS
refusal names the file without naming who holds it, so two rounds produced no
way to tell a bug in this app from a program the operator could simply close.

This answers that question directly, and changes nothing while it does:

* an EXCLUSIVE-open probe on each corpus file. Windows lets you ask for a handle
  no one else may share; if that succeeds, nothing else holds the file and the
  swap would have worked. It is the same condition unlink and MoveFileEx need,
  asked without touching a byte -- the handle is opened for read and closed.
* our OWN process's open handles, which is the only half that separates "this
  app has a bug" from "close the other program".
* whether real-time antivirus is scanning the data folder, which is the usual
  Windows holder and the one with an actionable remedy.

Every probe degrades to a stated reason rather than a guess: a missing optional
dependency, a refused privilege and a non-Windows machine are three different
answers and none of them is "the file is fine".
"""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess  # nosec B404 - fixed argv, no shell, Windows-only, read-only cmdlets
import sys
import time
from pathlib import Path
from typing import Any

__all__ = ["windows_lock_report"]

# Windows CreateFileW constants. Named here rather than imported so this module
# parses and imports on every platform -- the whole report has to exist on Linux
# too, or the all-diagnostics bundle would be missing a member off Windows.
_GENERIC_READ = 0x80000000
_OPEN_EXISTING = 3
_FILE_SHARE_NONE = 0  # the point: no other handle may exist

# INVALID_HANDLE_VALUE is (HANDLE)-1, and CreateFileW is declared to return a
# HANDLE (a c_void_p), so ctypes hands back the UNSIGNED representation --
# 0xFFFFFFFFFFFFFFFF on 64-bit. Comparing the result against a literal -1 is
# therefore False on every failed call, which would read a REFUSED open as a
# success: the exact inversion this module exists to detect. c_void_p(-1).value
# is the platform-correct value on both 32- and 64-bit.
_INVALID_HANDLE = ctypes.c_void_p(-1).value

_PS_TIMEOUT_S = 20.0

# Enumerating every process's handles is slow on Windows and this rides the
# all-diagnostics bundle, so the sweep is bounded and says what it did not reach.
_HOLDER_SWEEP_BUDGET_S = 25.0

# Windows sharing/lock refusals. 32 = ERROR_SHARING_VIOLATION, 33 = ERROR_LOCK_VIOLATION.
_SHARING_ERRORS = (32, 33)


def _path_is_within(child: str, parent: str) -> bool:
    """Containment by path COMPONENT, never by string prefix.

    ``C:\\Users\\me\\Open-Omniscience-old`` starts with
    ``C:\\Users\\me\\Open-Omniscience`` and is a different folder. Reporting it
    as excluded would tell an operator they had already applied a remedy they had
    not -- a fabricated reassurance, which is the direction that costs here.

    Pure string work on both separators, so it is testable off Windows.
    """
    # .lower() explicitly rather than os.path.normcase: normcase is the IDENTITY
    # on Linux, so deferring to it would make this function behave differently
    # under a guard than it does in production. These are Windows paths, which
    # are case-insensitive by definition, whatever host is inspecting them.
    c = child.lower().replace("/", "\\").rstrip("\\")
    p = parent.lower().replace("/", "\\").rstrip("\\")
    if not p or not c:
        return False
    return c == p or c.startswith(p + "\\")


def _corpus_paths() -> list[Path]:
    from src.backup.sqlite_backup import live_db_path

    db = Path(live_db_path())
    return [db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")]


def _exclusive_open_probe(path: Path) -> dict[str, Any]:
    """Can this file be opened with NO sharing? That is what the swap needs.

    Read-only by construction: GENERIC_READ, OPEN_EXISTING, and the handle is
    closed immediately. It creates nothing, truncates nothing and writes nothing.
    A success is not a promise about the next millisecond -- a handle can be
    taken the instant this closes -- so it is reported as an observation with its
    own timestamp, never as a guarantee.
    """
    if not sys.platform.startswith("win"):
        return {"probed": False, "reason": "not Windows — sharing rules do not apply here"}
    if not path.exists():
        # An ABSENT -wal is the healthy answer, not a gap: a clean SQLite close
        # checkpoints and removes it, so its absence means nothing is open.
        return {"probed": False, "reason": "file does not exist"}
    try:
        from ctypes import wintypes

        # use_last_error=True is what makes ctypes.get_last_error() OURS: without
        # it the call returns 0 and any read of GetLastError() can already have
        # been clobbered by an intervening call, so the reported code would be a
        # different call's error wearing this one's name.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        create = kernel32.CreateFileW
        create.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create.restype = wintypes.HANDLE
        handle = create(
            str(path), _GENERIC_READ, _FILE_SHARE_NONE, None, _OPEN_EXISTING, 0, None
        )
        if handle is None or handle == _INVALID_HANDLE:
            err = int(ctypes.get_last_error())
            return {
                "probed": True,
                "exclusive_open": False,
                "winerror": err,
                "meaning": (
                    "another handle on this file exists — the swap would be refused"
                    if err in _SHARING_ERRORS
                    else "refused for a reason other than sharing"
                ),
            }
        kernel32.CloseHandle(handle)
        return {
            "probed": True,
            "exclusive_open": True,
            "meaning": "nothing else holds this file — the swap would succeed right now",
        }
    except Exception as exc:  # noqa: BLE001 - a diagnostic never replaces the failure
        return {"probed": False, "reason": f"probe unavailable: {exc}"}


def _our_own_handles(paths: list[Path]) -> dict[str, Any]:
    """Which of the corpus files does THIS process still hold open?

    The decisive half. If we hold it, no amount of closing other programs helps
    and the bug is ours; if we do not, the operator has something to act on.
    """
    try:
        import psutil
    except Exception:  # noqa: BLE001 - optional extra
        return {"available": False, "reason": "psutil is not installed (an optional extra)"}
    try:
        wanted = {os.path.normcase(os.path.abspath(str(p))): str(p) for p in paths}
        held = sorted(
            {
                wanted[key]
                for f in psutil.Process().open_files()
                if (key := os.path.normcase(os.path.abspath(f.path))) in wanted
            }
        )
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"could not read our own handles: {exc}"}
    return {"available": True, "held_by_this_process": held, "n": len(held)}


def _other_holders(paths: list[Path]) -> dict[str, Any]:
    """Which OTHER processes hold them. Usually refused, and that is reported.

    Enumerating another process's handles needs privileges this app does not ask
    for, so AccessDenied is the NORMAL answer and is stated as such rather than
    being reported as "nothing else holds it" -- which is the opposite claim.
    """
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return {"available": False, "reason": "psutil is not installed (an optional extra)"}
    wanted = {os.path.normcase(os.path.abspath(str(p))) for p in paths}
    holders: list[dict[str, Any]] = []
    refused = 0
    scanned = 0
    unreached = 0
    deadline = time.monotonic() + _HOLDER_SWEEP_BUDGET_S
    try:
        procs = list(psutil.process_iter(["pid", "name"]))
        for i, proc in enumerate(procs):
            if time.monotonic() > deadline:
                # Never silently truncate: the count of what was NOT looked at is
                # the difference between "nothing else holds it" and "we ran out
                # of time before finding out".
                unreached = len(procs) - i
                break
            scanned += 1
            try:
                for f in proc.open_files():
                    if os.path.normcase(os.path.abspath(f.path)) in wanted:
                        holders.append(
                            {
                                "pid": proc.info["pid"],
                                "name": proc.info["name"],
                                "path": f.path,
                            }
                        )
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                refused += 1
            except Exception:  # noqa: BLE001 - one bad process never aborts the sweep
                refused += 1
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"could not enumerate processes: {exc}"}
    return {
        "available": True,
        "holders": holders,
        "processes_scanned": scanned,
        "processes_that_refused_inspection": refused,
        "processes_not_reached_within_budget": unreached,
        "budget_s": _HOLDER_SWEEP_BUDGET_S,
        "complete": unreached == 0 and refused == 0,
        "caveat": (
            "a refused or unreached process is NOT a process that was cleared — listing "
            "another process's handles needs privileges this app does not ask for, so an "
            "empty list beside a non-zero refused/unreached count means 'not visible', "
            "never 'not there'."
        ),
    }


def _powershell(script: str) -> tuple[bool, str]:
    """Run one read-only PowerShell expression. Fixed argv, no shell, bounded."""
    exe = "powershell.exe"
    try:
        out = subprocess.run(  # nosec B603 - fixed argv, no shell, read-only cmdlet
            [exe, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return False, "powershell.exe not found"
    except subprocess.TimeoutExpired:
        return False, f"powershell did not answer within {_PS_TIMEOUT_S:.0f}s"
    except Exception as exc:  # noqa: BLE001
        return False, f"powershell failed: {exc}"
    if out.returncode != 0:
        return False, (out.stderr or out.stdout or "powershell returned an error").strip()[:400]
    return True, out.stdout.strip()


def _antivirus(data_dir: Path) -> dict[str, Any]:
    """Is Defender's real-time scanner watching the data folder?

    The actionable one. A real-time scanner opens a multi-gigabyte database the
    moment the merge finishes writing it, and holds it while it reads -- which is
    exactly the shape of the failure this module exists for. If it is on and the
    folder is not excluded, the operator has a concrete remedy.

    Only Defender is probed. Third-party suites expose no common interface, so
    the honest answer for those is that we cannot see them, and it is said.
    """
    if not sys.platform.startswith("win"):
        return {"probed": False, "reason": "not Windows"}
    ok, realtime = _powershell(
        "(Get-MpComputerStatus).RealTimeProtectionEnabled"
    )
    if not ok:
        return {"probed": False, "reason": realtime}
    ok2, excluded = _powershell("(Get-MpPreference).ExclusionPath -join ';'")
    paths = [p.strip() for p in excluded.split(";") if p.strip()] if ok2 else []
    here = str(data_dir)
    covered = any(_path_is_within(here, p) for p in paths)
    return {
        "probed": True,
        "defender_realtime_enabled": realtime.strip().lower() == "true",
        "exclusion_paths": paths if ok2 else None,
        "data_dir_excluded": covered if ok2 else None,
        "caveat": (
            "only Microsoft Defender is visible here. A third-party antivirus is not "
            "probed and its absence from this report says nothing about it."
        ),
    }


def _reading(report: dict[str, Any], files: list[dict[str, Any]]) -> str:
    """One sentence a person can act on -- with UNMEASURED kept distinct from FREE.

    The trap this exists to avoid: reading a probe that did not run as an
    all-clear. "Nothing holds the corpus" and "we could not find out" are opposite
    answers, and only one of them means a restore is safe to retry.
    """
    if not report["applicable"]:
        return (
            "This machine is not Windows, so none of this applies: POSIX unlinks and "
            "replaces a file whatever else has it open."
        )

    def _name(entry: dict[str, Any]) -> str:
        # Split on BOTH separators rather than via Path: this branch only runs on
        # Windows, where Path would be correct, but a guard driving it off-platform
        # must see the same string production does.
        return str(entry["path"]).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]

    present = [f for f in files if f.get("exists")]
    if not present:
        return (
            "No corpus file exists at this path, so there is nothing here to hold open. "
            "Note that an absent -wal beside an existing database is the healthy state, "
            "not a missing file."
        )

    held = [f for f in present if f["exclusive_open_probe"].get("exclusive_open") is False]
    unmeasured = [f for f in present if "exclusive_open" not in f["exclusive_open_probe"]]

    if held:
        ours = report["this_process"].get("held_by_this_process") or []
        who = (
            " THIS APP is one of the holders, which is a bug in the app rather than "
            "something for you to close."
            if ours
            else " This app is not holding them, so the holder is another program — the "
            "processes and antivirus sections above are where to look."
        )
        return (
            f"Held open right now: {', '.join(_name(f) for f in held)}. A restore "
            f"attempted at this moment would be refused." + who
        )

    if unmeasured:
        return (
            "Could not be measured: "
            + ", ".join(f"{_name(f)} ({f['exclusive_open_probe'].get('reason', 'no reason given')})"
                        for f in unmeasured)
            + ". That is not an all-clear — it means the question was not answered."
        )

    return (
        "Every corpus file that exists was probed and nothing else holds it, so a "
        "restore attempted now would not be refused for a file lock. This is an "
        "observation at one instant, not a promise about the next one."
    )


def windows_lock_report() -> dict[str, Any]:
    """The whole picture, read-only, no network, nothing modified."""
    from src.database.session import data_dir

    started = time.monotonic()
    ddir = Path(data_dir())
    paths = _corpus_paths()

    files: list[dict[str, Any]] = []
    for p in paths:
        entry: dict[str, Any] = {"path": str(p), "exists": p.exists()}
        if p.exists():
            st = p.stat()
            entry["bytes"] = st.st_size
            entry["modified"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime))
        entry["exclusive_open_probe"] = _exclusive_open_probe(p)
        files.append(entry)

    report: dict[str, Any] = {
        "applicable": sys.platform.startswith("win"),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "data_dir": str(ddir),
        "swap_wait_budget_s": None,
        "files": files,
        "this_process": _our_own_handles(paths),
        "other_processes": _other_holders(paths),
        "antivirus": _antivirus(ddir),
        "method": (
            "Read-only. Each corpus file is opened for READ with sharing disabled and "
            "closed immediately — the same exclusivity unlink and MoveFileEx need, asked "
            "without modifying anything. Nothing here writes, creates or deletes a file."
        ),
        "caveat": (
            "A probe is an observation at one instant, not a guarantee: a handle can be "
            "taken the moment it closes. And an absent -wal is the HEALTHY answer, not a "
            "missing measurement — a clean SQLite close removes it."
        ),
    }
    try:
        from src.backup.merge import _SWAP_HANDLE_WAIT_S

        report["swap_wait_budget_s"] = _SWAP_HANDLE_WAIT_S
    except Exception as exc:  # noqa: BLE001
        report["swap_wait_budget_s_unavailable"] = str(exc)

    report["reading"] = _reading(report, files)
    report["elapsed_s"] = round(time.monotonic() - started, 3)
    return report
