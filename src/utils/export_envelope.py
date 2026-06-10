"""
The versioned export envelope (0.0.8 part 2, WP2 / RM-15).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every machine-readable export carries the same self-describing wrapper so
downstream pipelines get a stable contract: what schema, which app version,
when, and the exact query that produced it. Provenance travels with the data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

EXPORT_SCHEMA = "oo-export-1"


def app_version() -> str:
    try:
        return version("open-omniscience")
    except PackageNotFoundError:  # pragma: no cover - source-tree edge
        return "unknown"


def envelope(*, kind: str, query: dict, count: int, payload) -> dict:
    """Wrap an export payload in the versioned, provenance-carrying envelope."""
    return {
        "export_schema": EXPORT_SCHEMA,
        "kind": kind,
        "app_version": app_version(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "query": {k: v for k, v in query.items() if v is not None},
        "count": count,
        ("articles" if kind == "articles" else "data"): payload,
    }


def envelope_headers(*, kind: str, query: dict) -> dict[str, str]:
    """The same provenance as HTTP headers — for CSV, whose body must stay
    plain columns (a comment line would break naive CSV readers)."""
    q = "&".join(f"{k}={v}" for k, v in query.items() if v is not None)
    return {
        "X-OO-Export-Schema": EXPORT_SCHEMA,
        "X-OO-Export-Kind": kind,
        "X-OO-App-Version": app_version(),
        "X-OO-Generated-At": datetime.now(UTC).isoformat(timespec="seconds"),
        "X-OO-Query": q,
    }
