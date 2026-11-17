"""Is a process with this pid still running? ONE answer for every platform, and never a signal on Windows.

``os.kill(pid, 0)`` is the POSIX liveness test, and on Windows it is something else entirely: CPython maps every signal there
but the two console events to ``TerminateProcess(handle, sig)``, so the "test" ends the process with exit code 0, with no
handler, no lifespan and no clean close of the database (the state that leaves a ``-wal`` beside the corpus). Against a
process that has ended but whose handle another process still holds, it "succeeds" instead, so a wait loop built on it waits
its whole budget. Both were measured on the Windows legs (row 98): the uninstall watcher's wait for the server ran 120 s.

On Windows the process object is asked instead: ``OpenProcess(SYNCHRONIZE)`` (a right to WAIT on it, never to end it) and a
zero-timeout ``WaitForSingleObject``: ``WAIT_TIMEOUT`` means running, a signalled object means ended, and no handle means no
such process (or one this user may not wait on, which a caller with a deadline treats as gone).

STANDARD LIBRARY ONLY, and :func:`pid_alive` refers to nothing outside its own body but ``os``: the uninstall watcher runs
with ``python -c`` after the app's environment is removed and cannot import ``src``, so it carries this function's SOURCE
(``inspect.getsource``, ``src/safety/uninstall.py``), and ``scripts/apply_update.py`` runs while the checkout is mid-swap and
keeps a copy that ``tests/test_pid_probe.py`` pins byte-identical to this one. Every other caller imports it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os


def pid_alive(pid):
    """True while a process with this pid runs; never sends it anything (row 98: on Windows ``os.kill`` is TerminateProcess).
    When the answer cannot be had, it is "running": every caller waits on this before it erases or changes files, and a wait
    has a deadline, where a wrong "ended" would act while the process still writes."""
    if not isinstance(pid, int) or pid <= 0 or pid > 0xFFFFFFFF:
        return False  # not a process id (0 and negatives name process GROUPS on POSIX)
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]  # Windows only
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE: may wait on it, may not end it
        if not handle:
            return ctypes.get_last_error() != 87  # type: ignore[attr-defined]  # ERROR_INVALID_PARAMETER: no such process; any other refusal: running
        try:
            return k32.WaitForSingleObject(handle, 0) != 0  # WAIT_OBJECT_0: ended; WAIT_TIMEOUT or WAIT_FAILED: running
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists; it is another user's
    except OSError:
        return True  # no answer: running (see above)
    # A zombie (ended, not reaped yet) still answers signal 0; on Linux its state letter in /proc says so.
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as f:
            if f.read().rsplit(")", 1)[1].split()[0] == "Z":
                return False
    except (OSError, IndexError):
        pass
    return True
