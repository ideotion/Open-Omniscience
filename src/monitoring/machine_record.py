"""The machine record of a Diagnostics build: what the process runs on and under, read once.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (R119, the 2026-10-06 plan, section 6, the ``machine`` row; the release-candidate
thread's ask, ``needs/rc.md`` sections 1 and 2). Every question about a crashed machine starts with
the same few facts, and the bundles carried them in four places or not at all: the build (the
commit, which an update changes without changing ``app_version``), the versions of the libraries a
crash lives in (DuckDB, SQLite, SQLCipher, the C library), the memory tier the process was resolved
to beside the tier the machine would give NOW (a virtual machine whose memory is ballooned moves
between tiers: the 2026-09-30 machine ran the rollup off at 07:15 and on at 21:15), and the
allocator setting. They are read ONCE per build, at its start, and written into the manifest header,
so a member that is declined or fails still leaves them in the archive. Nothing here is repeated in
``debug-bundle.json``, ``session-forensics.json`` or ``soak-window.json``.

WHAT IT DOES NOT CARRY, and why. The Wikipedia transport (proxy, pool or direct) is a property of
each hour of the lane, so it rides ``wiki-lane-history.json`` per hour and has no second copy here.
Whether a launcher started the app is not a fact the process can read about itself; the launcher's
own line about how the previous process ended is already in ``session-forensics.json``. The hardware
(CPU, cores, RAM total, swap, drive) is ``run.hardware`` of the same manifest.

NOTHING LEAVES THE MACHINE AND NO SECRET IS READ: the environment section lists the NAMES of the
``OO_*`` variables that are set, never a value (one of them is the passphrase's own variable, and
its value is not read here), and the SQLCipher version is asked of a throwaway in-memory connection
that is never given a key. Every section is its own reading: one that cannot be taken says so with
its reason, and is never written as an empty or a zero. Never raises.
"""

from __future__ import annotations

import os
import platform
import sqlite3
import sys
from datetime import UTC, datetime
from typing import Any

#: The record's own version, so a reader of an old archive knows which fields to expect.
MACHINE_RECORD_VERSION = 1

#: Names only, and only this prefix: the app's own switches. A variable of the operator's other
#: software is none of a diagnostic's business.
_ENV_PREFIX = "OO_"


def _unavailable(exc: BaseException) -> dict[str, Any]:
    return {"unavailable": f"{type(exc).__name__}"}


def _build() -> dict[str, Any]:
    """The build as THIS PROCESS read it at its start (so a ``git pull`` since does not rename the
    code that is running), beside the version the package declares."""
    out: dict[str, Any] = {}
    try:
        from src.utils.export_envelope import app_version

        out["app_version"] = app_version()
    except Exception as exc:  # noqa: BLE001 - a missing reading is a reason, never a failure
        out["app_version"] = _unavailable(exc)
    try:
        from src.monitoring.build_marker import process_markers

        out["code"] = process_markers()
    except Exception as exc:  # noqa: BLE001
        out["code"] = _unavailable(exc)
    return out


def _process() -> dict[str, Any]:
    """The process: its id and when it began (the clock the OS keeps, not one the app wrote)."""
    out: dict[str, Any] = {"pid": os.getpid()}
    try:
        import psutil

        began = psutil.Process().create_time()
        out["started_at"] = datetime.fromtimestamp(began, UTC).isoformat(timespec="seconds")
        out["uptime_s"] = round(max(0.0, datetime.now(UTC).timestamp() - began), 1)
    except Exception as exc:  # noqa: BLE001
        out["started_at"] = _unavailable(exc)
    return out


def _sqlcipher_version() -> Any:
    """The SQLCipher LIBRARY's version, asked of a throwaway in-memory connection that is never
    keyed: the version of the code the encrypted store is read by, which a crash read needs."""
    try:
        from sqlcipher3 import dbapi2 as sqc
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": f"the sqlcipher3 driver is not importable ({type(exc).__name__})"}
    try:
        conn = sqc.connect(":memory:")
        try:
            row = conn.execute("PRAGMA cipher_version").fetchone()
        finally:
            conn.close()
        return row[0] if row and row[0] else {"unavailable": "the library did not report a version"}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def _duckdb_version() -> Any:
    try:
        import duckdb

        return str(duckdb.__version__)
    except Exception as exc:  # noqa: BLE001
        return {"unavailable": f"duckdb is not importable ({type(exc).__name__})"}


def _libc() -> Any:
    """The C library, as the library itself names it (``glibc 2.39``), or the interpreter's own
    answer on a platform where it does not say."""
    try:
        from src.monitoring.session_hwm import _glibc_version

        got = _glibc_version()
        if got:
            return got
    except Exception:  # noqa: BLE001 - fall through to the platform's answer
        pass
    try:
        name, version = platform.libc_ver()
        return f"{name} {version}".strip() if name else {"unavailable": "no C library name reported"}
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def _versions() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "sqlcipher": _sqlcipher_version(),
        "duckdb": _duckdb_version(),
        "libc": _libc(),
    }


def _memory() -> dict[str, Any]:
    """The memory tier the process was resolved to, beside the one the machine gives now, and the
    memory available now. A difference is a measured fact about the machine and no verdict on which
    reading is right (``memory_budget.reading_vs_now`` says so in its own caveat)."""
    out: dict[str, Any] = {}
    try:
        from src.config.memory_budget import reading_vs_now

        out.update(reading_vs_now())
    except Exception as exc:  # noqa: BLE001
        out["reading_vs_now"] = _unavailable(exc)
    try:
        import psutil

        out["available_now_mb"] = round(psutil.virtual_memory().available / (1024 * 1024), 1)
    except Exception as exc:  # noqa: BLE001
        out["available_now_mb"] = _unavailable(exc)
    return out


def _allocator() -> Any:
    try:
        from src.monitoring.session_hwm import allocator_setting

        return allocator_setting()
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def _environment() -> dict[str, Any]:
    """The NAMES of the app's switches that are set, sorted. Never a value: a switch's value can be
    a path or a secret, and what a reader needs is which switches this process ran under."""
    try:
        names = sorted(k for k in os.environ if k.startswith(_ENV_PREFIX))
        return {
            "set_names": names,
            "count": len(names),
            "method": f"the names of the environment variables beginning with {_ENV_PREFIX}; "
                      "no value is read into this record",
        }
    except Exception as exc:  # noqa: BLE001
        return _unavailable(exc)


def machine_block() -> dict[str, Any]:
    """The whole record: taken once, at the start of a build. Never raises."""
    try:
        return {
            "version": MACHINE_RECORD_VERSION,
            "taken_at": datetime.now().isoformat(timespec="seconds"),
            "build": _build(),
            "process": _process(),
            "versions": _versions(),
            "memory": _memory(),
            "allocator": _allocator(),
            "environment": _environment(),
            "not_here": (
                "the Wikipedia transport rides wiki-lane-history.json per hour; the hardware is "
                "run.hardware of this manifest; how the previous process ended is "
                "session-forensics.json"
            ),
        }
    except Exception as exc:  # noqa: BLE001 - the one read a build cannot afford to lose its header over
        return {"version": MACHINE_RECORD_VERSION, "unavailable": type(exc).__name__}
