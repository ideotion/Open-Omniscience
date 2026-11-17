"""The system variables a child Python needs on Windows, for tests that start one with a stripped environment.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A child started on Windows without ``SYSTEMROOT`` cannot seed its random numbers, load the socket provider
(``import asyncio`` fails with WinError 10106) or run ``cmd`` (``platform.uname`` shells out), so it dies before the
code under test runs. The app's own launcher always inherits them. These are carried through when the parent has them;
on POSIX none is set and the result is empty, so the child's environment there is exactly what each test wrote.
"""

from __future__ import annotations

import os

_WINDOWS_SYSTEM = ("SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA")


def windows_system_env() -> dict[str, str]:
    """The Windows system variables the parent has, to merge into a child's stripped environment (empty off Windows)."""
    if os.name != "nt":
        return {}
    return {name: os.environ[name] for name in _WINDOWS_SYSTEM if name in os.environ}
