"""
Persisted Bulletin editions.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design record §9 ("two exits, one record") and §11 (naming). One JSON file per
edition under ``data_dir()/bulletin/editions/``, which is what makes an edition a
*record* rather than a render: the document is regenerated FROM it, never
hand-edited, so toggling a producer or re-rendering cannot change a number.

It rides the encrypted backup free — it is a small private file under data_dir,
exactly like the persisted import reports. The difference, and it is the point:
this one is wired on BOTH sides. Import reports are collected into the artifact
by ``artifact._collect_members`` and then have no handler in
``merge.merge_side_files``, so they are exported and silently never restored.
That is a recorded bug, not a precedent to copy.

Naming (§11 ruling 11): ``<YYYYMMDD>-OOS-<cadence>-<id>.json``, where the date is
the edition's LAST COVERED DAY, not the moment it was generated. An edition IS
its period; naming it by generation time would sort two re-runs of the same week
apart and file a Monday re-render of last week under Monday.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

_DIR = "bulletin"
_EDITIONS = "editions"

# A partial write is named with this suffix and swept. The import-report path
# unlinks its temp in a `finally`, which covers an exception but NOT a hard kill
# (SIGKILL, OOM, power) — so the directory is also swept on every write. The
# recorded P0.2 lesson: a temp file that only its own `finally` can reclaim is an
# orphan the moment the process dies instead of returning.
_TMP_SUFFIX = ".oopart"
_SWEEP_AGE_S = 6 * 3600

_NAME_RE = re.compile(r"^(\d{8})-OOS-([a-z]+)-([0-9a-f]{8})\.json$")


def editions_dir() -> Path:
    from src.paths import data_dir

    return data_dir() / _DIR / _EDITIONS


def edition_filename(period, *, edition_id: str | None = None) -> str:
    """``<YYYYMMDD>-OOS-<cadence>-<id>.json`` for one edition.

    The date is ``period.last_day`` — the last day the edition COVERS. The random
    id keeps two runs over the same period as two files rather than one silently
    overwriting the other: a re-run is a new edition of the same period, and which
    one you kept is a question the filename should not answer by deleting.
    """
    eid = edition_id or secrets.token_hex(4)
    cadence = re.sub(r"[^a-z]", "", str(period.cadence).lower()) or "period"
    return f"{period.last_day.strftime('%Y%m%d')}-OOS-{cadence}-{eid}.json"


def _sweep(d: Path) -> None:
    """Drop stale partial writes. Best-effort: a sweep that raises must never
    prevent the write it was cleaning up for."""
    try:
        cutoff = time.time() - _SWEEP_AGE_S
        for p in d.glob(f"*{_TMP_SUFFIX}"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            except OSError:
                continue
    except Exception:  # noqa: BLE001 - housekeeping, never fatal
        _LOG.debug("bulletin: edition temp sweep failed", exc_info=True)


def persist_edition(edition: dict[str, Any], period, *, edition_id: str | None = None) -> Path:
    """Write one edition atomically and return its path.

    Temp file + ``os.replace``, so a crash mid-write never leaves a half-written
    edition that later reads as a real one. UTF-8 explicit (the portability
    ratchet: on Windows the default encoding dies on the first non-ASCII byte, and
    an edition is full of non-ASCII by construction).
    """
    d = editions_dir()
    d.mkdir(parents=True, exist_ok=True)
    _sweep(d)

    eid = edition_id or secrets.token_hex(4)
    name = edition_filename(period, edition_id=eid)
    dest = d / name
    payload = dict(edition)
    payload.setdefault("schema", "oo-bulletin-edition-1")
    payload["edition_id"] = eid
    payload["filename"] = name
    payload.setdefault("generated_at", datetime.now(UTC).isoformat())
    payload.setdefault("state", "draft")

    tmp = dest.with_name(dest.name + _TMP_SUFFIX)
    try:
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def safe_edition_path(filename: str) -> Path | None:
    """Resolve ``filename`` under the editions dir, refusing traversal.

    The same resolve-and-contain check the folder-backup and import-report paths
    use. A name with a separator or ``..`` is rejected before the filesystem is
    touched at all — the recorded lesson is that EVERY name-to-path field needs
    this guard, not only the ones literally called "name".
    """
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return None
    base = editions_dir()
    candidate = base / filename
    try:
        base_r = base.resolve()
        cand_r = candidate.resolve()
    except OSError:
        return None
    if cand_r != base_r and base_r not in cand_r.parents:
        return None
    return candidate


def list_editions() -> list[dict[str, Any]]:
    """Every persisted edition, newest covered period first.

    Read-only. A missing directory is an empty list, never an error — a fresh
    install simply has no editions yet.
    """
    d = editions_dir()
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(d.glob("*.json")):
        try:
            stat = p.stat()
        except OSError:
            continue
        m = _NAME_RE.match(p.name)
        row: dict[str, Any] = {
            "filename": p.name,
            "size_bytes": stat.st_size,
            "written_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        }
        if m:
            row["covers_through"] = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"
            row["cadence"] = m.group(2)
            row["edition_id"] = m.group(3)
        else:
            # A file that does not match the scheme is LISTED with the mismatch
            # stated rather than hidden: a hidden file in a directory the operator
            # believes they can see is worse than an odd row.
            row["name_unrecognised"] = True
        out.append(row)
    out.sort(key=lambda r: (r.get("covers_through") or "", r["written_at"]), reverse=True)
    return out


def read_edition(filename: str) -> dict[str, Any]:
    """Read one edition by its exact filename.

    Raises ``FileNotFoundError`` for an unknown, invalid or traversal-attempting
    name — never silently returns a different file's contents.
    """
    p = safe_edition_path(filename)
    if p is None or not p.is_file():
        raise FileNotFoundError(filename)
    return json.loads(p.read_text(encoding="utf-8"))


def delete_edition(filename: str) -> bool:
    """Remove one edition. Returns False for an unknown or unsafe name."""
    p = safe_edition_path(filename)
    if p is None or not p.is_file():
        return False
    p.unlink()
    return True
