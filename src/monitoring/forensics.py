"""Session forensics + data-dir inventory — the "automate what I need from you" slice.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Born from the 2026-07-09 field event (a 4-day run that died silently of OOM, a
"130 GB database" that turned out to be an 11.7 GB DB plus ~120 GB of something
else, and a 981 s unlock), where root-causing needed THREE manual commands from
the maintainer. This module makes the app answer those questions ITSELF, so every
future diagnostics export carries them:

1. ``data_dir_inventory`` — what the data folder actually holds: per-entry sizes,
   the DB / ``-wal`` / ``-shm`` called out, and DETECTION of orphaned backup/restore
   staging (``.bak-build-*`` / ``.restore-*`` dirs, ``*.oopart`` temps). A crashed
   backup orphans a staging dir CONTAINING A PLAINTEXT corpus snapshot — that is
   both the prime disk-bloat suspect and an at-rest-encryption violation, so it is
   surfaced loudly. Sizes and app-owned names only; file CONTENTS are never read.
2. A clean-shutdown SENTINEL — ``session_state.json`` is stamped "running" at boot
   and "clean" at shutdown; the next boot reports whether the previous session
   ended cleanly, paired with the last recorded RSS from ``collect_perf.jsonl``.
   An unclean end with RSS near the machine's RAM is CONSISTENT WITH an external
   OOM kill — reported as exactly that: an inference, never a kernel-log fact.
3. Unlock timing — the unlock path records the ``-wal`` size BEFORE the database
   is opened plus per-phase durations, so "why was unlock slow" answers itself
   (WAL recovery vs migration/self-heal vs upkeep) on every boot.

Everything here is best-effort and local-only: a failure returns a structured
note (degrade loudly, never a 500), and nothing is transmitted by the app.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

# Orphaned-staging name patterns, grounded in the backup/restore code (never guessed):
# backup builds stage into ``.bak-build-<hex>`` (src/backup/artifact.py:418) with a
# PLAINTEXT ``corpus.db`` snapshot inside (:290); restores stage into
# ``.restore-<hex>`` (:515); the folder backup's in-progress temps are ``*.oopart``
# (src/backup/folder_backup.py:48). All are cleaned on success — their presence
# means a CRASHED run left them behind.
_STAGING_DIR_PREFIXES = (".bak-build-", ".restore-")
_PART_SUFFIX = ".oopart"
_PLAINTEXT_MEMBER_NAMES = ("corpus.db", "custody_log.db")

_DB_NAME = "open_omniscience.db"


def _state_path() -> Path:
    return data_dir() / "session_state.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _tree_size(root: Path) -> tuple[int, int]:
    """(bytes, files) under root — never follows symlinks out of the tree, never
    reads contents; unreadable entries are skipped (counted via best-effort)."""
    total = 0
    files = 0
    try:
        if root.is_symlink():
            return 0, 0  # a symlink is a pointer, not data held HERE — never followed
        if root.is_file():
            return root.stat().st_size, 1
        for p in root.rglob("*"):
            try:
                if p.is_symlink() or not p.is_file():
                    continue
                total += p.stat().st_size
                files += 1
            except OSError:
                continue
    except OSError:
        pass
    return total, files


def data_dir_inventory(max_entries: int = 60) -> dict[str, Any]:
    """Top-level inventory of the data folder: name, kind, recursive size.

    Answers "what IS the 130 GB" without a terminal: the DB triple is called out,
    orphaned backup/restore staging is detected by the exact prefixes the backup
    code uses, and a staging dir that contains a plaintext corpus snapshot is
    flagged as such (name check only — contents are never read). Counts and
    sizes only; no score."""
    root = data_dir()
    out: dict[str, Any] = {
        "data_dir": str(root),
        "generated_at": _now(),
        "entries": [],
        "suspect_staging": [],
        "totals": {},
        "method": (
            "Recursive on-disk sizes of the data folder's top-level entries, symlinks "
            "never followed, file contents never read. suspect_staging lists orphaned "
            "backup/restore temp dirs by the exact name patterns the backup code uses "
            "(.bak-build-*/.restore-*/*.oopart) — present only after a crashed run. "
            "plaintext_snapshot means the dir CONTAINS a decrypted corpus snapshot by "
            "member NAME; treat it as sensitive and remove it deliberately. Local "
            "diagnostics only; nothing is transmitted."
        ),
    }
    if not root.is_dir():
        out["note"] = "data dir does not exist (fresh install / custom OO_DATA_DIR)"
        return out

    entries: list[dict[str, Any]] = []
    db_bytes = wal_bytes = shm_bytes = staging_bytes = 0
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        out["note"] = f"data dir unreadable: {exc.__class__.__name__}"
        return out

    for child in children:
        size, files = _tree_size(child)
        kind = "dir" if child.is_dir() and not child.is_symlink() else "file"
        name = child.name
        if name == _DB_NAME:
            kind = "db"
            db_bytes = size
        elif name == f"{_DB_NAME}-wal":
            kind = "wal"
            wal_bytes = size
        elif name == f"{_DB_NAME}-shm":
            kind = "shm"
            shm_bytes = size
        entry: dict[str, Any] = {"name": name, "kind": kind, "bytes": size, "files": files}
        is_staging = (kind == "dir" and name.startswith(_STAGING_DIR_PREFIXES)) or name.endswith(
            _PART_SUFFIX
        )
        if is_staging:
            staging_bytes += size
            suspect = dict(entry)
            if kind == "dir":
                try:
                    members = {p.name for p in child.iterdir()}
                except OSError:
                    members = set()
                suspect["plaintext_snapshot"] = any(
                    m in members for m in _PLAINTEXT_MEMBER_NAMES
                )
            out["suspect_staging"].append(suspect)
        entries.append(entry)

    entries.sort(key=lambda e: -int(e["bytes"]))
    out["entries"] = entries[:max_entries]
    out["entries_truncated"] = max(0, len(entries) - max_entries)
    total = sum(int(e["bytes"]) for e in entries)
    out["totals"] = {
        "total_bytes": total,
        "db_bytes": db_bytes,
        "wal_bytes": wal_bytes,
        "shm_bytes": shm_bytes,
        "orphaned_staging_bytes": staging_bytes,
        "other_bytes": max(0, total - db_bytes - wal_bytes - shm_bytes - staging_bytes),
    }
    return out


# --------------------------------------------------------------------------- #
# Clean-shutdown sentinel + previous-session verdict                           #
# --------------------------------------------------------------------------- #

_PREV_AT_BOOT: dict[str, Any] | None = None
_PREV_LOADED = False


def _read_state() -> dict[str, Any] | None:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_state(state: dict[str, Any]) -> None:
    try:
        tmp = _state_path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(tmp, _state_path())
    except OSError:
        _LOG.warning("could not persist session_state.json", exc_info=True)


def record_session_start() -> dict[str, Any] | None:
    """Stamp this session 'running'; returns the PREVIOUS session's state (the
    forensic input). Call once at process start; best-effort."""
    global _PREV_AT_BOOT, _PREV_LOADED
    prev = _read_state()
    if not _PREV_LOADED:
        _PREV_AT_BOOT = prev
        _PREV_LOADED = True
    _write_state(
        {
            "state": "running",
            "started_at": _now(),
            "pid": os.getpid(),
            # carry the last unlock record forward so one boot's timing survives
            # into the next export even if the next unlock is fast
            "last_unlock": (prev or {}).get("last_unlock"),
        }
    )
    return prev


def record_clean_shutdown() -> None:
    """Flip the sentinel to 'clean'. Called from the lifespan shutdown; a session
    that dies without reaching this reads as UNCLEAN on the next boot."""
    state = _read_state() or {}
    state["state"] = "clean"
    state["ended_at"] = _now()
    _write_state(state)


def _last_collect_perf_sample() -> dict[str, Any] | None:
    """The last collect_perf JSONL line (the collector's own RSS/memory record) —
    the closest thing to a flight recorder for an externally-killed process."""
    path = data_dir() / "collect_perf.jsonl"
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if line:
            try:
                d = json.loads(line)
                return {
                    "ts": d.get("ts"),
                    "rss_mb": d.get("rss_mb"),
                    "mem_avail_mb": d.get("mem_avail_mb"),
                    "elapsed_s": d.get("elapsed_s"),
                    "pass_id": d.get("pass_id"),
                }
            except ValueError:
                return None
    return None


def record_unlock_timing(record: dict[str, Any]) -> None:
    """Persist the unlock path's own timing record (wal bytes before open,
    per-phase ms, total) into the sentinel file. Best-effort."""
    state = _read_state() or {"state": "running", "started_at": _now(), "pid": os.getpid()}
    state["last_unlock"] = {**record, "at": _now()}
    _write_state(state)


def wal_bytes_before_open() -> int | None:
    """The -wal file size, intended to be read BEFORE the DB is first opened —
    a large value predicts WAL-recovery time inside the first connection."""
    try:
        return (data_dir() / f"{_DB_NAME}-wal").stat().st_size
    except OSError:
        return None


def previous_session_report() -> dict[str, Any]:
    """The forensic verdict on the PREVIOUS session, computed from the sentinel
    captured at THIS boot + the collector's last flight-recorder sample."""
    prev = _PREV_AT_BOOT if _PREV_LOADED else _read_state()
    out: dict[str, Any] = {
        "generated_at": _now(),
        "method": (
            "A clean-shutdown sentinel (session_state.json stamped 'running' at boot, "
            "'clean' at shutdown) + the collector's last self-recorded RSS sample. An "
            "unclean end whose last RSS approaches the machine's RAM is CONSISTENT WITH "
            "an external OOM kill — an INFERENCE from the app's own records, never a "
            "kernel-log fact; confirm with the host's journal if it matters."
        ),
    }
    if prev is None:
        out["previous_session"] = "unknown"
        out["note"] = "no sentinel yet (first boot with forensics, or the file was removed)"
        return out
    state = str(prev.get("state"))
    out["previous_session"] = {
        "running": "unclean-end",  # died without reaching the shutdown hook
        "clean": "clean",
    }.get(state, f"unknown({state})")
    out["started_at"] = prev.get("started_at")
    out["ended_at"] = prev.get("ended_at")
    out["last_unlock"] = prev.get("last_unlock")
    if out["previous_session"] == "unclean-end":
        out["last_collector_sample"] = _last_collect_perf_sample()
    return out


def _ollama_store_bytes() -> tuple[str | None, int, int]:
    """(store path, bytes, files) of the Ollama model store — which lives OUTSIDE data_dir
    (~/.ollama/models or $OLLAMA_MODELS / the systemd store), so data_dir_inventory misses
    it entirely. Best-effort: a protected/unreadable store degrades to whatever _tree_size
    could stat (never a crash), and a missing store is (path, 0, 0)."""
    try:
        from src.backup.ollama_models import default_store

        store = default_store()
    except Exception:  # noqa: BLE001 - the store path helper is optional
        return None, 0, 0
    if store is None or not store.is_dir():
        return (str(store) if store else None), 0, 0
    nbytes, files = _tree_size(store)
    return str(store), nbytes, files


def storage_footprint() -> dict[str, Any]:
    """The COMPLETE on-disk footprint of the app across ALL stores, ITEMIZED per component
    (maintainer field 2026-07-10, A12b): the reported "database size" must cover EVERYTHING,
    not just data_dir. data_dir_inventory answers "what is inside the data folder", but the
    Ollama model store lives OUTSIDE data_dir, so its bytes were absent from any single total.

    Components (each an explicit line, bytes only, symlinks never followed, contents never
    read): the database triple (db / -wal / -shm), wiki_dumps, osm_regions, backup/restore
    staging (orphaned = a crashed run), any other data-dir contents, AND the external Ollama
    model store. ``grand_total_bytes`` sums them all. Best-effort per component; no score."""
    inv = data_dir_inventory()
    totals = inv.get("totals", {})
    entries = {str(e.get("name")): int(e.get("bytes", 0)) for e in inv.get("entries", [])}
    db_name = _DB_NAME

    def _dir_bytes(name: str) -> int:
        return int(entries.get(name, 0))

    data_dir_bytes = int(totals.get("total_bytes", 0))
    other = int(totals.get("other_bytes", 0))
    # wiki_dumps / osm_regions are top-level dirs counted inside other_bytes; itemize them
    # out so the "other" line is the genuine remainder.
    wiki = _dir_bytes("wiki_dumps")
    osm = _dir_bytes("osm_regions")
    staging = int(totals.get("orphaned_staging_bytes", 0))
    other_remainder = max(0, other - wiki - osm)

    components: list[dict[str, Any]] = [
        {"name": "database", "kind": "db", "bytes": int(totals.get("db_bytes", 0)),
         "detail": db_name, "outside_data_dir": False},
        {"name": "database WAL", "kind": "wal", "bytes": int(totals.get("wal_bytes", 0)),
         "detail": f"{db_name}-wal", "outside_data_dir": False},
        {"name": "database SHM", "kind": "shm", "bytes": int(totals.get("shm_bytes", 0)),
         "detail": f"{db_name}-shm", "outside_data_dir": False},
        {"name": "wiki dumps", "kind": "wiki_dumps", "bytes": wiki, "outside_data_dir": False},
        {"name": "OSM regions", "kind": "osm_regions", "bytes": osm, "outside_data_dir": False},
        {"name": "backup/restore staging", "kind": "staging", "bytes": staging,
         "detail": "orphaned = a crashed backup/restore left it (see suspect_staging)",
         "outside_data_dir": False},
        {"name": "other (data folder)", "kind": "other", "bytes": other_remainder,
         "outside_data_dir": False},
    ]
    ollama_path, ollama_bytes, ollama_files = _ollama_store_bytes()
    components.append(
        {"name": "Ollama model store", "kind": "ollama_models", "bytes": ollama_bytes,
         "files": ollama_files, "detail": ollama_path, "outside_data_dir": True}
    )
    grand_total = data_dir_bytes + ollama_bytes
    components.sort(key=lambda c: -int(c["bytes"]))
    return {
        "generated_at": _now(),
        "data_dir": str(data_dir()),
        "ollama_store": ollama_path,
        "components": components,
        "totals": {
            "data_dir_bytes": data_dir_bytes,
            "ollama_models_bytes": ollama_bytes,
            "grand_total_bytes": grand_total,
        },
        "method": (
            "Recursive on-disk sizes of every app store, itemized per component. The database "
            "triple + wiki_dumps + osm_regions + staging live in the data folder; the Ollama "
            "model store lives OUTSIDE it (so it was missing from any data-dir-only total). "
            "grand_total_bytes is the true on-disk footprint. Symlinks never followed, file "
            "contents never read, counts/bytes only — no score. Best-effort per component."
        ),
    }


# --------------------------------------------------------------------------- #
# Data-dir persistence: is the corpus on a volatile (disposable) filesystem?    #
# --------------------------------------------------------------------------- #
_VOLATILE_FS = frozenset({"tmpfs", "ramfs"})  # RAM-backed: definitely cleared on restart


def _filesystem_type(path: Path) -> str | None:
    """The filesystem type backing ``path`` via Linux ``/proc/mounts`` (longest mount-point
    prefix wins). ``None`` off Linux / when /proc is unavailable — honest unknown, never a
    guess. Best-effort, cheap (a small text read)."""
    try:
        target = str(path.resolve())
    except OSError:
        target = str(path)
    best_len, best_fs = -1, None
    try:
        with open("/proc/mounts", encoding="utf-8") as f:
            for line in f:
                cols = line.split()
                if len(cols) < 3:
                    continue
                mp = cols[1].replace("\\040", " ")  # octal-escaped space
                fstype = cols[2]
                if target == mp or mp == "/" or target.startswith(mp.rstrip("/") + "/"):
                    if len(mp) > best_len:
                        best_len, best_fs = len(mp), fstype
    except OSError:
        return None
    return best_fs


def _qubes_disposable() -> bool | None:
    """True/False if we can PROVE Qubes disposability, else None (unknown — never a guess).

    Reads the qubesdb persistence key via ``qubesdb-read`` (``none`` == disposable). Absent
    on non-Qubes / when the tool is not present -> None. Never nags an ordinary AppVM (whose
    $HOME IS persistent) on a false positive."""
    if not Path("/etc/qubes-release").exists():
        return None
    import shutil as _sh
    import subprocess  # noqa: S404 - reading a local qubesdb key, no shell, no user input

    exe = _sh.which("qubesdb-read")
    if not exe:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [exe, "/qubes-vm-persistence"], capture_output=True, text=True, timeout=3
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() == "none"


def data_dir_persistence() -> dict[str, Any]:
    """Honest, best-effort assessment of whether the corpus survives a restart, so the app can
    NUDGE a user on a likely-EPHEMERAL root toward an opt-in persistent ``OO_DATA_DIR`` (the
    2026-07-09 field event: a disposable-VM crash vaporized a ~60K-article corpus).

    HONESTY: it signals only what it can PROVE — a RAM-backed (tmpfs) data folder is
    definitely volatile; a Qubes disposable VM is provable via qubesdb; everything else is
    ``unknown`` (never a guess). It NEVER says "stop using disposable VMs" — only "here is how
    to keep your corpus across restarts." When ``OO_DATA_DIR`` is set the user chose the
    location, so we only remind them to ensure it is persistent."""
    dd = data_dir()
    override = os.getenv("OO_DATA_DIR")
    fstype = _filesystem_type(dd)
    volatile_fs = (fstype in _VOLATILE_FS) if fstype else None
    disposable = _qubes_disposable()

    if volatile_fs:
        at_risk: bool | None = True
        reason = (
            f"the data folder is on a {fstype} (RAM-backed) filesystem, which is cleared "
            "when this machine restarts."
        )
    elif disposable:
        at_risk = True
        reason = "this is a Qubes disposable VM — its storage is discarded on shutdown."
    elif override:
        at_risk = False
        reason = "OO_DATA_DIR is set to an explicit location (ensure it is a persistent path)."
    else:
        at_risk = None
        reason = "could not prove whether this location survives a restart (unknown)."

    note = None
    if at_risk is True:
        note = (
            f"Your corpus is being written to {dd}, which {reason} To keep it across restarts, "
            "set OO_DATA_DIR to a persistent path (a bind-mounted folder or an external drive) "
            "before launching, or copy the encrypted data folder off this machine. Your corpus "
            "is reconstitutable from the web, but re-scraping is slow — this one-time setup "
            "avoids that."
        )
    return {
        "data_dir": str(dd),
        "explicit_override": bool(override),
        "filesystem": fstype,
        "volatile_filesystem": volatile_fs,
        "qubes": Path("/etc/qubes-release").exists(),
        "qubes_disposable": disposable,
        "at_risk": at_risk,
        "reason": reason,
        "note": note,
        "how_to_persist": (
            "Set OO_DATA_DIR=/path/on/a/persistent/or/bind-mounted/volume before launching "
            "(the installer accepts it too); the corpus, keys and custody log then live there."
        ),
        "method": (
            "tmpfs/ramfs data folder = provably volatile; Qubes disposability read from "
            "qubesdb; otherwise honest 'unknown'. Local read-only checks; no network, no score."
        ),
    }


def session_forensics() -> dict[str, Any]:
    """The one-call diagnostic block: inventory + previous-session verdict + the last unlock
    timing + the complete storage footprint + the data-dir persistence assessment. Rides the
    debug bundle / the all-diagnostics zip."""
    cur = _read_state() or {}
    return {
        "inventory": data_dir_inventory(),
        "storage_footprint": storage_footprint(),
        "data_dir_persistence": data_dir_persistence(),
        "previous_session": previous_session_report(),
        "last_unlock": cur.get("last_unlock"),
    }
