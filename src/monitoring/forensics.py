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
# ``.oo-vllm-pip-build`` (src/llm/vllm_lifecycle.py:pip_tmpdir) joins the list
# 2026-07-29: it is pip's unpack area for the vLLM install and holds up to ~10 GB of
# half-unpacked torch/CUDA wheels. It is removed in a ``finally``, but that does not
# run when the process is KILLED -- SIGKILL, OOM, or the app's own SIGTERM shutdown
# (the install worker sits on a daemon thread, abandoned at interpreter exit). It
# previously lived in the ambient /tmp, which the OS clears; it now lives on real
# disk beside the venv, where nothing did. Same class as the others: present == a
# run that did not finish cleanly.
_STAGING_DIR_PREFIXES = (".bak-build-", ".restore-", ".oo-vllm-pip-build")
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
# This boot's -wal reading, taken before any connection can exist (S0.1).
_WAL_AT_BOOT: dict[str, Any] | None = None


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
    forensic input). Call once at process start; best-effort.

    THE -wal READING HAPPENS HERE, AND THAT PLACEMENT IS THE POINT (S0.1). Any
    connection that opens and closes the store unlinks the -wal, so a reading taken
    later describes the prober, not the previous session. Taking it inside this
    function — which the lifespan calls before anything can open the database —
    makes the ordering a property of the code rather than a convention a future
    caller has to remember, and it also survives the case a reorder inside
    ``unlock()`` cannot cover: a WRONG-passphrase attempt deletes the -wal too, so
    every retry after the first would otherwise be blind."""
    global _PREV_AT_BOOT, _PREV_LOADED, _WAL_AT_BOOT
    # Read the -wal FIRST: before the previous state is even parsed, so nothing
    # between here and the probe can grow into a database open.
    boot_reading = wal_state_before_open()
    _WAL_AT_BOOT = boot_reading
    prev = _read_state()
    if not _PREV_LOADED:
        _PREV_AT_BOOT = prev
        _PREV_LOADED = True
    _write_state(
        {
            "state": "running",
            "started_at": _now(),
            "pid": os.getpid(),
            # What the PREVIOUS session left on disk, measured before this one could
            # touch it. It describes that session, not this one.
            "wal_at_boot": boot_reading,
            # carry the last unlock record forward so one boot's timing survives
            # into the next export even if the next unlock is fast
            "last_unlock": (prev or {}).get("last_unlock"),
        }
    )
    return prev


def wal_at_boot() -> dict[str, Any] | None:
    """This boot's -wal reading (see ``record_session_start``), or None if the boot
    read never ran. Reads the module global first so a later probe — which would by
    then have destroyed the evidence — can never be mistaken for it."""
    if _WAL_AT_BOOT is not None:
        return _WAL_AT_BOOT
    st = _read_state() or {}
    got = st.get("wal_at_boot")
    return got if isinstance(got, dict) else None


# The signal that initiated this stop, if any (set by install_signal_handlers).
_STOP_SIGNAL: str | None = None


def note_stop_signal(name: str) -> None:
    """Record which signal initiated the stop, so a deliberate stop can never be
    rendered as a crash. Called from the signal handler, before the graceful path."""
    global _STOP_SIGNAL
    _STOP_SIGNAL = name


def record_shutdown_phase(phase: str, *, reason: str | None = None) -> None:
    """Advance the sentinel through the teardown (S0.2).

    Before this, the sentinel had two states -- 'running' and 'clean' -- so a death
    DURING teardown was indistinguishable from a death long before it. The teardown
    is not instant (it stops the scheduler thread and disposes the pool, which
    checkpoints an encrypted store), so that window is real. Each step stamps its own
    phase, and a session that dies inside one reads as e.g. 'shutting-down' on the
    next boot: it was asked to stop and did not finish, which is a different fact from
    'it was killed mid-collection'.

    ``reason`` names WHY the stop began (a signal, the in-app power button); it is
    recorded once, on the first phase, and carried forward."""
    state = _read_state() or {}
    state["state"] = phase
    state["shutdown_phase_at"] = _now()
    if reason and not state.get("shutdown_reason"):
        state["shutdown_reason"] = reason
    if _STOP_SIGNAL and not state.get("stop_signal"):
        state["stop_signal"] = _STOP_SIGNAL
    _write_state(state)


def record_clean_shutdown() -> None:
    """Flip the sentinel to 'clean'. Called from the lifespan shutdown; a session
    that dies without reaching this reads as UNCLEAN on the next boot."""
    state = _read_state() or {}
    state["state"] = "clean"
    state["ended_at"] = _now()
    if _STOP_SIGNAL and not state.get("stop_signal"):
        state["stop_signal"] = _STOP_SIGNAL
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
    a large value predicts WAL-recovery time inside the first connection.

    TWO-state by design (present -> size, everything else -> None). Callers that
    must tell "there was no WAL" apart from "the size could not be read" read
    ``wal_state_before_open`` instead; see its docstring for why that matters.
    """
    try:
        return (data_dir() / f"{_DB_NAME}-wal").stat().st_size
    except OSError:
        return None


def wal_state_before_open() -> dict[str, Any]:
    """The -wal file's state at the moment of the call, in THREE states.

    READ THIS BEFORE INTERPRETING THE RESULT (2026-09-02, S0.1). What the call
    measures depends entirely on WHEN it runs, because *any* SQLite connection
    that opens and closes the store checkpoints and unlinks the -wal — including
    a passphrase-verify connection, and including one opened by a WRONG-passphrase
    attempt. The old reading of ``absent`` ("the previous shutdown was clean")
    was therefore an artifact of the measurement order, not a fact: on an
    encrypted store the unlock route verified the passphrase with its own
    connect/close *before* this ran, so the answer was ``absent`` whatever had
    happened. Reproduced with stdlib sqlite3: a crashed store with an 840 KB
    -wal, one connect()/close(), and the file is gone.

    So the honest readings are:

    * ``present``  — a -wal existed at this moment. Read AT BOOT (before anything
      can open the store) that means the previous session's last SQLite
      connection was never cleanly closed. That includes a lifespan teardown that
      still had a connection checked out, so it is evidence of an unclean *close*,
      not proof of a crash.
    * ``absent``   — no -wal at this moment. NOTHING can be concluded from it: a
      clean close, a wrong-passphrase attempt, an earlier probe, or a fresh store
      that never had one all produce it.
    * ``unreadable`` — the size could not be read. Unmeasured, never reported as
      zero.

    The load-bearing call site is ``record_session_start()``, which takes the
    reading at boot before any connection can exist and persists it as
    ``wal_at_boot``. A reading taken later (the unlock timer) describes the unlock
    path's own timing, not the previous session.
    """
    p = data_dir() / f"{_DB_NAME}-wal"
    try:
        return {
            "bytes": p.stat().st_size,
            "state": "present",
            "reason": (
                "a -wal file was present — its frames are replayed inside the next "
                "connection, so that recovery is part of whatever this reading times. "
                "Read AT BOOT it also means the previous session's last SQLite "
                "connection was never cleanly closed"
            ),
        }
    except FileNotFoundError:
        return {
            "bytes": 0,
            "state": "absent",
            "reason": (
                "no -wal file at this moment, so there is no WAL recovery in this "
                "timing. NOTHING can be concluded about how the previous session "
                "ended: a clean close, a wrong-passphrase attempt, an earlier probe "
                "and a fresh store all leave the file absent"
            ),
        }
    except OSError as exc:
        return {
            "bytes": None,
            "state": "unreadable",
            "reason": (
                f"the -wal size could not be read ({type(exc).__name__}) — "
                "unmeasured, never reported as zero"
            ),
        }


def previous_session_report() -> dict[str, Any]:
    """The forensic verdict on the PREVIOUS session, computed from the sentinel
    captured at THIS boot + the collector's last flight-recorder sample."""
    prev = _PREV_AT_BOOT if _PREV_LOADED else _read_state()
    out: dict[str, Any] = {
        "generated_at": _now(),
        "method": (
            "A clean-shutdown sentinel (session_state.json stamped 'running' at boot, "
            "'clean' at shutdown), the PREVIOUS session's own high-water memory marks, "
            "and the -wal state read at this boot before any connection existed. An "
            "unclean end whose peak RSS approaches the machine's RAM is CONSISTENT WITH "
            "an external OOM kill — an INFERENCE from the app's own records, never a "
            "kernel-log fact; confirm with the host's journal if it matters. Note what "
            "the app CANNOT tell apart from its own data: an OOM kill, a host reset, a "
            "SIGHUP from a closed terminal and a native fatal all leave this same "
            "record."
        ),
    }
    # What the PREVIOUS session left on disk, measured at THIS boot before any
    # connection could exist (S0.1). Reported for EVERY verdict — including the
    # no-sentinel one, where a -wal present with no sentinel is itself a fact (the
    # sentinel file was removed, or this build predates it) — because "absent" is now
    # an honest non-answer rather than a claim of a clean shutdown.
    out["wal_at_boot"] = wal_at_boot()
    if prev is None:
        out["previous_session"] = "unknown"
        out["note"] = "no sentinel yet (first boot with forensics, or the file was removed)"
        return out
    state = str(prev.get("state"))
    out["previous_session"] = {
        "running": "unclean-end",  # died without reaching the shutdown hook
        # S0.2: a death DURING teardown. It was asked to stop and did not finish —
        # a different fact from being killed mid-collection, and one the two-state
        # sentinel could not express.
        "shutting-down": "unclean-end-during-shutdown",
        "dispose-done": "unclean-end-after-dispose",
        "clean": "clean",
    }.get(state, f"unknown({state})")
    out["started_at"] = prev.get("started_at")
    out["ended_at"] = prev.get("ended_at")
    out["last_unlock"] = prev.get("last_unlock")
    for key in ("shutdown_reason", "stop_signal", "shutdown_phase_at"):
        if prev.get(key):
            out[key] = prev[key]
    if out["previous_session"] == "unclean-end":
        # The previous session's OWN peaks (S0.4). ``last_collector_sample`` reads the
        # last line of a file EVERY session appends to, so once this process starts
        # collecting it reports the survivor's numbers, not the crashed run's — which
        # is how an OOM was once "inferred" from the wrong process. The sidecar is
        # scoped to one session and is snapshotted at boot, so it cannot drift.
        out["previous_session_peaks"] = _previous_peaks()
        sample = _last_collect_perf_sample()
        if sample is not None:
            sample = dict(sample)
            sample["attribution"] = (
                "the last line of collect_perf.jsonl, which EVERY session appends to — "
                "once this session starts collecting these are ITS numbers, not the "
                "previous one's. Use previous_session_peaks for the crashed run."
            )
        out["last_collector_sample"] = sample
    return out


def _previous_peaks() -> dict[str, Any] | None:
    """The previous session's own high-water marks, or a stated absence."""
    try:
        from src.monitoring.session_hwm import previous

        got = previous()
    except Exception:  # noqa: BLE001 - forensics degrades, never raises
        return None
    if not got:
        return {
            "available": False,
            "reason": (
                "no per-session high-water record from the previous run (it predates "
                "this instrument, or the file was removed) — unmeasured, not zero"
            ),
        }
    out = dict(got)
    out["available"] = True
    out["method"] = (
        "peak RSS / minimum available memory / peak swap-used sampled by the previous "
        "session itself and snapshotted at this boot. A field that could not be "
        "measured is ABSENT rather than zero."
    )
    return out


def pass_tail_journal() -> dict[str, Any]:
    """The collector pass tail's own phase journal (S0.5), or a stated absence."""
    try:
        from src.scheduler.pass_journal import report

        return report()
    except Exception as exc:  # noqa: BLE001 - forensics degrades, never raises
        return {
            "available": False,
            "reason": f"the pass journal could not be read ({type(exc).__name__})",
        }


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


def _mb(n: Any) -> str:
    """Bytes at a sensible magnitude. An unmeasured size says so; it never renders 0."""
    if not isinstance(n, (int, float)):
        return "not measured"
    v = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} TB"


def render_text(d: dict[str, Any] | None = None) -> str:
    """A plain-text rendering of the session forensics, built to be READABLE WHEN
    PASTED INTO A CHAT — the channel this file exists for. Mirrors
    ``expedition.render_text``: no colour, no wide tables, and every absence stated in
    words rather than as a blank or a zero.

    The expedition log is appended because the two answer one question together — what
    happened to this instance while nobody was watching — and because that is the pair
    an operator actually sends. Its own "nothing armed yet" line is kept rather than
    suppressed: an absence stated is worth more than a section that silently vanishes."""
    d = d if d is not None else session_forensics()
    lines: list[str] = ["# Open Omniscience — Session Forensics", ""]

    prev = d.get("previous_session") or {}
    verdict = prev.get("previous_session")
    lines.append("## Previous session")
    lines.append("")
    lines.append(f"- ended: {verdict or 'unknown'}")
    if prev.get("started_at"):
        lines.append(f"- started: {prev['started_at']}")
    if prev.get("ended_at"):
        lines.append(f"- ended at: {prev['ended_at']}")
    if prev.get("stop_signal"):
        lines.append(f"- stop initiated by: {prev['stop_signal']}")
    if prev.get("shutdown_reason"):
        lines.append(f"- shutdown reason: {prev['shutdown_reason']}")
    if prev.get("shutdown_phase_at"):
        lines.append(f"- last teardown step at: {prev['shutdown_phase_at']}")
    if prev.get("last_rss_mb") is not None:
        lines.append(f"- collector's last RSS sample: {prev['last_rss_mb']} MB")
    wal_boot = prev.get("wal_at_boot") or {}
    if wal_boot.get("state"):
        nbytes = wal_boot.get("bytes")
        size = f"{int(nbytes):,} bytes" if isinstance(nbytes, int) else "size unmeasured"
        lines.append(f"- -wal at this boot: {wal_boot['state']} ({size})")
        if wal_boot.get("reason"):
            lines.append(f"  - {wal_boot['reason']}")
    peaks = prev.get("previous_session_peaks") or {}
    if peaks:
        lines.append("- that session's own peaks:")
        if peaks.get("available") is False:
            lines.append(f"  - unavailable: {peaks.get('reason', 'no reason recorded')}")
        else:
            for key, label, unit in (
                ("rss_max_mb", "peak RSS", "MB"),
                ("avail_min_mb", "minimum available memory", "MB"),
                ("swap_used_max_mb", "peak swap used", "MB"),
            ):
                if peaks.get(key) is None:
                    lines.append(f"  - {label}: not measured (omitted, never zero)")
                else:
                    lines.append(f"  - {label}: {peaks[key]} {unit}")
            if peaks.get("phase"):
                lines.append(f"  - last phase seen: {peaks['phase']}")
            if peaks.get("last_ts"):
                lines.append(f"  - last recorded at: {peaks['last_ts']}")
    sample = prev.get("last_collector_sample") or {}
    if sample:
        lines.append(
            f"- last collect_perf line (see attribution): rss {sample.get('rss_mb')} MB, "
            f"available {sample.get('mem_avail_mb')} MB, at {sample.get('ts')}"
        )
        if sample.get("attribution"):
            lines.append(f"  - {sample['attribution']}")
    if prev.get("method"):
        lines.append(f"- how this is known: {prev['method']}")

    journal = d.get("pass_tail_journal") or {}
    if journal:
        lines += ["", "## Collector pass tail", ""]
        if journal.get("available") is False:
            lines.append(f"- unavailable: {journal.get('reason', 'no reason recorded')}")
        elif journal.get("records"):
            lines.append(f"- phase records: {journal['records']}")
            if journal.get("last_record_at"):
                lines.append(f"- last record at: {journal['last_record_at']}")
            died = journal.get("died_during")
            if died:
                lines.append(f"- **a phase was never finished: {died.get('phase')}**")
                lines.append(f"  - began: {died.get('ts')}")
                if died.get("rss_mb") is not None:
                    lines.append(f"  - RSS at that moment: {died['rss_mb']} MB")
                if died.get("mem_avail_mb") is not None:
                    lines.append(f"  - available at that moment: {died['mem_avail_mb']} MB")
                if died.get("basis"):
                    lines.append(f"  - basis: {died['basis']}")
            else:
                lines.append("- every recorded phase has a matching end")
            for row in journal.get("slowest_phases") or []:
                lines.append(f"- slowest: {row.get('phase')} — {row.get('ms')} ms ({row.get('ts')})")
        else:
            lines.append(f"- {journal.get('note', 'nothing recorded yet')}")

    unlock = d.get("last_unlock") or {}
    lines += ["", "## Last unlock", ""]
    if not unlock:
        lines.append("- no unlock has been recorded on this machine yet.")
    else:
        total = unlock.get("synchronous_total_ms")
        lines.append(
            f"- synchronous total: {total} ms" if total is not None
            else "- synchronous total: not recorded"
        )
        phases = unlock.get("phases") or []
        if phases:
            lines.append(
                "- phases: "
                + " · ".join(f"{p.get('phase')} ({p.get('ms')} ms)" for p in phases)
            )
        wal = unlock.get("wal_state_before_open") or {}
        if wal:
            lines.append(f"- WAL before open: {wal.get('state')} ({_mb(wal.get('bytes'))})")
            if wal.get("reason"):
                lines.append(f"  {wal['reason']}")
        if unlock.get("at"):
            lines.append(f"- measured at: {unlock['at']}")

    inv = d.get("inventory") or {}
    tot = inv.get("totals") or {}
    lines += ["", "## Data folder", ""]
    lines.append(f"- path: {inv.get('data_dir') or 'unknown'}")
    lines.append(
        f"- total on disk: {_mb(tot.get('total_bytes'))} "
        f"(database {_mb(tot.get('db_bytes'))} · WAL {_mb(tot.get('wal_bytes'))} · "
        f"other {_mb(tot.get('other_bytes'))})"
    )
    suspect = inv.get("suspect_staging") or []
    if suspect:
        # An orphaned staging tree from an ENCRYPTED corpus holds a PLAINTEXT copy, so
        # this is an at-rest-encryption finding, not a housekeeping one. Say it loudly.
        lines.append(
            f"- ⚠ ORPHANED STAGING: {len(suspect)} leftover backup/restore "
            f"director(ies), {_mb(tot.get('orphaned_staging_bytes'))} — on an encrypted "
            "corpus these hold a PLAINTEXT copy."
        )
        for e in suspect[:10]:
            lines.append(f"    {e.get('name')} — {_mb(e.get('bytes'))}")
    else:
        lines.append("- orphaned backup/restore staging: none found")
    for e in (inv.get("entries") or [])[:12]:
        lines.append(f"    {e.get('name')} {e.get('kind') or ''} {_mb(e.get('bytes'))}")
    if inv.get("entries_truncated"):
        lines.append(f"    … and {inv['entries_truncated']} more entries not listed")

    persist = d.get("data_dir_persistence") or {}
    if persist:
        lines += ["", "## Does this data folder survive a restart?", ""]
        at_risk = persist.get("at_risk")
        lines.append(
            "- at risk: unknown" if at_risk is None
            else f"- at risk: {'YES' if at_risk else 'no'}"
        )
        if persist.get("reason"):
            lines.append(f"- {persist['reason']}")
        if persist.get("filesystem"):
            lines.append(f"- filesystem: {persist['filesystem']}")
        if at_risk and persist.get("how_to_persist"):
            lines.append(f"- {persist['how_to_persist']}")

    lines += ["", "---", ""]
    try:
        from src.monitoring import expedition

        lines.append(expedition.render_text())
    except Exception:  # noqa: BLE001 - the forensics file must survive a broken sidecar
        _LOG.debug("session forensics: expedition log unavailable", exc_info=True)
        lines.append("The expedition log could not be read for this report.")

    return "\n".join(lines)


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
        # Where a pass got to in its tail (S0.5) — the window the field's S2 session
        # died in, from which nothing survived because record_run sits below it.
        "pass_tail_journal": pass_tail_journal(),
    }
