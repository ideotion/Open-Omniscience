"""Which native libraries a session ran on (question: which library did the SIGABRT happen in?).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The crash trace (``faulthandler``) names PYTHON frames only: an abort inside libxml2, SQLCipher or DuckDB shows the Python call that
entered it and nothing of the library. What can be said is which versions the process was running, and which shared objects were mapped.
Read once at each session start and kept in the session sentinel, so the NEXT start can report the previous session's libraries beside
its crash trace.

WHAT IS RECORDED, AND WHAT IS NOT. The runtime versions (libxml2/libxslt as lxml loaded them, the SQLite library, the installed distribution
versions of the extension packages) and the BASE NAMES of the mapped shared objects that belong to a family worth naming (a path can carry
the user's home directory and name, so no directory is ever kept; the whole maps file is never copied). Every other mapped file is
counted, never listed, so the cut is stated: ``mapped_total`` against ``listed``. A version that cannot be read is named with its reason,
never left out silently.
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import scrubbed

#: the extension packages whose native code runs inside this process. Their INSTALLED version is read from the package metadata (no import).
_DISTRIBUTIONS = ("lxml", "trafilatura", "duckdb", "pyarrow", "numpy", "sqlcipher3", "sqlcipher3-binary", "cryptography", "psutil", "urllib3")
#: the families of mapped file worth naming: the XML stack, the database engines, TLS/crypto, compression, ICU, the C++ runtime, the allocator,
#: the columnar and numeric stacks.
_FAMILY = re.compile(
    r"(xml|xslt|sqlite|sqlcipher|crypto|ssl|libz\.|zlib|icu|stdc\+\+|gcc_s|libc\.|libm\.|malloc|arrow|parquet|duckdb|blas|lapack|gomp|etree|_cffi)",
    re.IGNORECASE,
)
_NAME_CLIP = 80
#: the serialised bytes the NAME LIST may take. It protects the size of the session sentinel (rewritten at each phase) and of the forensics
#: member (R119's 4 MB part limit): a process that maps hundreds of matching files lists the first of them and says how many it matched.
_FILES_BYTES = 6000


def _dist_version(name: str) -> str | dict[str, str]:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return {"unreadable": "not installed"}
    except Exception as exc:  # noqa: BLE001
        return {"unreadable": f"unreadable ({type(exc).__name__})"}


def _runtime_versions() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        import sqlite3

        out["sqlite_library"] = sqlite3.sqlite_version
    except Exception as exc:  # noqa: BLE001
        out["sqlite_library"] = {"unreadable": f"unreadable ({type(exc).__name__})"}
    try:
        from lxml import etree

        out["libxml2_runtime"] = ".".join(str(n) for n in etree.LIBXML_VERSION)
        out["libxml2_compiled_against"] = ".".join(str(n) for n in etree.LIBXML_COMPILED_VERSION)
        out["libxslt_runtime"] = ".".join(str(n) for n in etree.LIBXSLT_VERSION)
    except Exception as exc:  # noqa: BLE001 - lxml is an optional extra
        out["libxml2_runtime"] = {"unreadable": f"unreadable ({type(exc).__name__})"}
    out["python"] = sys.version.split()[0]
    return out


def _mapped(maps: Path) -> dict[str, Any]:
    try:
        lines = maps.read_bytes().decode("utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"unreadable": "absent (the file does not exist)" if isinstance(exc, FileNotFoundError) else "permission denied" if isinstance(exc, PermissionError) else "unreadable (OSError)"}
    names: dict[str, None] = {}
    for line in lines:
        fields = line.split(None, 5)
        if len(fields) == 6 and fields[5].startswith("/"):
            names[fields[5].removesuffix(" (deleted)").rsplit("/", 1)[-1]] = None
    matched = [scrubbed(n)[:_NAME_CLIP] for n in names if _FAMILY.search(n)]
    listed: list[str] = []
    spent = 2
    for n in matched:
        spent += len(n) + 4  # the quotes, the comma and an escape's slack
        if spent > _FILES_BYTES:
            break
        listed.append(n)
    return {"mapped_total": len(names), "matched": len(matched), "listed": len(listed), "files": listed}


def read(*, maps: Path | None = None) -> dict[str, Any]:
    """The native-library facts of this process now. Never raises."""
    try:
        return {
            "runtime": _runtime_versions(),
            "installed": {name: _dist_version(name) for name in _DISTRIBUTIONS},
            "mapped": _mapped(maps or Path("/proc/self/maps")),
        }
    except Exception as exc:  # noqa: BLE001 - evidence-gathering never raises into a boot
        return {"unreadable": f"unreadable ({type(exc).__name__})"}
