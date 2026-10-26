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
import math
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import log_failure
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
# ``.oo-backup-`` (src/api/database.py:_BACKUP_DIR_PREFIX) joins 2026-10-26 (0.5.1
# item 40): the snapshot dir of GET /api/database/backup holds a PLAINTEXT copy of the
# whole corpus as ``snapshot.db``, removed when the response ends and by an exit hook;
# a kill (SIGKILL, power) runs neither, so a copy found here is a run that did not
# finish. A download in flight is listed too, as any live staging dir is.
_STAGING_DIR_PREFIXES = (".bak-build-", ".restore-", ".oo-vllm-pip-build", ".oo-backup-")
_PART_SUFFIX = ".oopart"

# Field diagnostics 2026-09-11 (C2). The forensics export printed "orphaned
# backup/restore staging: none found" and then, a few lines later, listed
# `pre-restore-20260906T065744Z.db` and `pre-restore-20260906T222535Z.db` at 25.8 GB
# EACH -- 51.6 GB in an 80.8 GB data folder holding a 25.8 GB corpus, with no account of
# where it had gone.
#
# THE SCANNER WAS RIGHT NOT TO CALL THEM ORPHANS, AND WRONG TO SAY NOTHING. They are a
# deliberately RETAINED safety net with a real policy behind them (`_SNAPSHOT_KEEP = 3`
# count-based, plus `prune_pre_restore_snapshots_by_age`'s 168 h time-driven backstop,
# swept at boot and off-peak), so folding them in with `.bak-build-`/`.restore-` crash
# residue would be dishonest in the OTHER direction -- it would invite an operator to
# delete a working safety net. Both snapshots here were five days old, i.e. inside the
# retention window and correctly kept.
#
# What was actually wrong is that they were silently swept into `other_bytes`, which is
# the "everything else" bucket nobody reads. So they get their OWN named category,
# itemised, with the policy that governs them stated -- the operator can then see 51.6 GB
# of safety net and decide, rather than discovering it as an unexplained gap.
_PRE_RESTORE_SNAPSHOT_RE = re.compile(r"^pre-restore-(\d{8}T\d{6}Z)\.db$")
_PLAINTEXT_MEMBER_NAMES = ("corpus.db", "custody_log.db", "snapshot.db")

_DB_NAME = "open_omniscience.db"


def _state_path() -> Path:
    return data_dir() / "session_state.json"


# The reason a degraded part of the report gives: a type and one sentence. What it protects: the report is
# read at a glance and an engine's text can be a page long.
_REASON_CHARS = 200
# The lines of an earlier unclean end's trace the plain-text report prints under its summary line (the first line of the
# trace IS the summary, so it is skipped). What it protects: the text is pasted into a chat, with up to ten earlier ends
# (``exit_evidence.EARLIER_ENDS_LIMIT``) in it; the 8 lines are the fatal-error header's neighbours and the crashing thread's
# innermost frames, which faulthandler writes first. It shortens what is printed: the summary line names ``lines_total``,
# and the structured report in the zip carries every line it kept.
_EARLIER_TRACE_LINES_PRINTED = 8


def _why(exc: BaseException) -> str:
    """``Type: message`` for a part of the report that could not be built, with the passphrase, a key
    literal and the person's folders taken out of the whole text before it is cut (the one scrub the
    diagnostics runs use). A scrub that itself fails names the type only."""
    try:
        from src.monitoring.diagnostics_runs import tidy_error

        return tidy_error(exc, _REASON_CHARS)  # an exception is written by ``exc_line``, which never raises
    except Exception:  # noqa: BLE001 - a reason is never the thing that fails the report
        return type(exc).__name__


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
        "pre_restore_snapshots": [],
        "totals": {},
        "method": (
            "Recursive on-disk sizes of the data folder's top-level entries, symlinks "
            "never followed, file contents never read. suspect_staging lists orphaned "
            "backup/restore temp dirs by the exact name patterns the backup code uses "
            "(.bak-build-*/.restore-*/*.oopart) — present only after a crashed run. "
            "plaintext_snapshot means the dir CONTAINS a decrypted corpus snapshot by "
            "member NAME; treat it as sensitive and remove it deliberately. "
            "pre_restore_snapshots is a SEPARATE list of pre-restore-<ts>.db safety nets, "
            "which are retained on purpose and are never counted as orphaned staging nor "
            "folded into other_bytes — see pre_restore_policy. Local "
            "diagnostics only; nothing is transmitted."
        ),
    }
    if not root.is_dir():
        out["note"] = "data dir does not exist (fresh install / custom OO_DATA_DIR)"
        return out

    entries: list[dict[str, Any]] = []
    db_bytes = wal_bytes = shm_bytes = staging_bytes = pre_restore_bytes = 0
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
        snap = _PRE_RESTORE_SNAPSHOT_RE.match(name)
        if snap:
            # Itemised as its own kind, NEVER as "orphaned staging" (it is retained on
            # purpose) and never left to `other_bytes` (C2).
            entry["kind"] = "pre_restore_snapshot"
            pre_restore_bytes += size
            out["pre_restore_snapshots"].append(
                {"name": name, "bytes": size, "taken_at": snap.group(1)}
            )
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
        # Retained safety nets, counted apart from BOTH orphaned staging and the
        # everything-else bucket -- "51.6 GB of deliberate safety net" and "51.6 GB of
        # unexplained other" are different facts and only one of them is true (C2).
        "pre_restore_snapshot_bytes": pre_restore_bytes,
        "other_bytes": max(
            0, total - db_bytes - wal_bytes - shm_bytes - staging_bytes - pre_restore_bytes
        ),
    }
    out["pre_restore_snapshots"].sort(key=lambda e: str(e["taken_at"]), reverse=True)
    # Imported HERE rather than at module scope: forensics is on the boot path and
    # src.backup.merge is a large module this does not otherwise need.
    from src.backup.merge import _SNAPSHOT_KEEP, _SNAPSHOT_MAX_AGE_HOURS_DEFAULT

    out["pre_restore_policy"] = (
        "pre-restore-<ts>.db files are the restore safety net and are RETAINED ON "
        "PURPOSE, not orphaned: the newest "
        f"{_SNAPSHOT_KEEP} are kept whenever a later restore prunes, and "
        f"{_SNAPSHOT_MAX_AGE_HOURS_DEFAULT:.0f}h is the time-driven backstop swept at "
        "boot and off-peak (OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS). They are listed "
        "here so their size is accounted for, never to suggest deleting them."
    )
    return out


# --------------------------------------------------------------------------- #
# Clean-shutdown sentinel + previous-session verdict                           #
# --------------------------------------------------------------------------- #

_PREV_AT_BOOT: dict[str, Any] | None = None
_PREV_LOADED = False
_OOM_AT_BOOT: dict[str, Any] | None = None  # the kill counters read at this boot
_BOOT_ID_AT_BOOT: str | None = None
# This boot's -wal reading, taken before any connection can exist (S0.1).
_WAL_AT_BOOT: dict[str, Any] | None = None
# A reading taken by ``take_boot_wal_reading`` before the lifespan runs, for the start (``serve``) that opens the store itself
# before the lifespan can: ``record_session_start`` uses it instead of probing again.
_EARLY_WAL: dict[str, Any] | None = None
# The database file's size in pages against its header's, read at boot with the -wal (PR B; src/monitoring/page_reading.py).
_PAGES_AT_BOOT: dict[str, Any] | None = None
_EARLY_PAGES: dict[str, Any] | None = None
# When THIS process stamped itself running, and the monotonic reading beside it.
#
# Deliberately in-process rather than read back from session_state.json: that file is
# written by every session, so a reader that took ``started_at`` from disk would
# attribute the PREVIOUS process's start to this one whenever this one never stamped
# itself -- the exact misattribution ``session_hwm`` exists to prevent. Absent here
# means "this process never called record_session_start", which is a state a caller
# must be able to see rather than a number it can guess.
_SESSION_STARTED_AT: str | None = None
_SESSION_STARTED_MONO: float | None = None


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
    except OSError as exc:
        log_failure(_LOG, "could not persist session_state.json", exc, level=logging.WARNING)


def take_boot_wal_reading() -> None:
    """Take this boot's -wal reading NOW, for ``record_session_start`` to use. ``serve`` opens the store (``init_db``, the seeding)
    before the server's lifespan runs, and that connection makes a new -wal or deletes the leftover one, so a reading taken in the
    lifespan describes this process; call this first thing in ``serve``, before anything that can open the store. A server started
    by ``python -m uvicorn`` opens nothing before its lifespan and needs no call. Never raises."""
    global _EARLY_WAL, _EARLY_PAGES
    try:
        _EARLY_WAL = wal_state_before_open()
    except Exception as exc:  # noqa: BLE001 - a reading that cannot be taken is taken again in the lifespan
        _EARLY_WAL = None
        _LOG.warning("the early boot -wal reading could not be taken (%s); the lifespan takes it", type(exc).__name__)
    _EARLY_PAGES = pages_state_before_open()


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
    global _PREV_AT_BOOT, _PREV_LOADED, _WAL_AT_BOOT, _EARLY_WAL, _PAGES_AT_BOOT, _EARLY_PAGES
    global _SESSION_STARTED_AT, _SESSION_STARTED_MONO, _OOM_AT_BOOT, _BOOT_ID_AT_BOOT
    # Read the -wal FIRST: before the previous state is even parsed, so nothing
    # between here and the probe can grow into a database open.
    boot_reading = _EARLY_WAL if _EARLY_WAL is not None else wal_state_before_open()
    _EARLY_WAL = None
    _WAL_AT_BOOT = boot_reading
    # The size in pages, from the file's own bytes, at the same moment and for the same reason: no connection exists yet.
    _PAGES_AT_BOOT = _EARLY_PAGES if _EARLY_PAGES is not None else pages_state_before_open()
    _EARLY_PAGES = None
    prev = _read_state()
    if not _PREV_LOADED:
        _PREV_AT_BOOT = prev
        _PREV_LOADED = True
    started_at = _now()
    _SESSION_STARTED_AT = started_at
    _SESSION_STARTED_MONO = time.monotonic()
    state: dict[str, Any] = {
        "state": "running",
        "started_at": started_at,
        "pid": os.getpid(),
        # What the PREVIOUS session left on disk, measured before this one could
        # touch it. It describes that session, not this one.
        "wal_at_boot": boot_reading,
        # carry the last unlock record forward so one boot's timing survives
        # into the next export even if the next unlock is fast
        "last_unlock": (prev or {}).get("last_unlock"),
        # and the last large-log recovery, which an unlock with no log would otherwise erase
        "last_recovery": (prev or {}).get("last_recovery"),
        # and the per-step time of the last cold init_db (STORE-02), for a start with no unlock record
        "last_init_db": (prev or {}).get("last_init_db"),
    }
    # The two handles the NEXT boot needs to find this session's death in the host's
    # journal (2026-09-26): the machine boot it runs in, so the right boot is read by
    # id rather than guessed, and its cgroup, which is all systemd-oomd names when it
    # kills. Absent where the platform has neither -- never a placeholder.
    try:
        from src.monitoring.exit_evidence import own_cgroup
        from src.monitoring.session_history import machine_boot_id

        boot_id, cgroup = machine_boot_id(), own_cgroup()
        _BOOT_ID_AT_BOOT = boot_id
        if boot_id:
            state["boot_id"] = boot_id
        if cgroup:
            state["cgroup"] = cgroup
    except Exception as exc:  # noqa: BLE001 - a missing handle never breaks a boot
        log_failure(_LOG, "session sentinel: boot id / cgroup unavailable", exc, level=logging.DEBUG)
    # The kernel's kill counters at this start (question 22). The NEXT start compares its reading with this one, so a kill between two
    # starts is counted even where no log can be read. Integers and named absences only (``oom_counters.py``).
    try:
        from src.monitoring.native_libs import read as _read_native_libs

        state["native_libs"] = _read_native_libs()
    except Exception as exc:  # noqa: BLE001 - a missing reading never breaks a boot
        log_failure(_LOG, "session sentinel: native libraries unavailable", exc, level=logging.DEBUG)
    try:
        from src.monitoring.oom_counters import read as _read_oom_counters

        _OOM_AT_BOOT = _read_oom_counters()
        state["oom_counters"] = _OOM_AT_BOOT
    except Exception as exc:  # noqa: BLE001 - a missing reading never breaks a boot
        log_failure(_LOG, "session sentinel: kill counters unavailable", exc, level=logging.DEBUG)
    _write_state(state)
    # The session LEDGER (2026-09-18, maintainer-asked): the chronology across MANY
    # sessions that this one-sentinel file cannot hold -- restarts, stretches, the
    # last minute a dead session was seen. Best-effort, after the sentinel is written,
    # and it reads the sentinel's verdict rather than re-deriving one.
    try:
        from src.monitoring.session_history import record_boot

        record_boot(prev)
    except Exception as exc:  # noqa: BLE001 - the ledger never breaks a boot
        log_failure(_LOG, "session ledger: boot record failed", exc, level=logging.DEBUG)
    return prev


def pages_state_before_open() -> dict[str, Any]:
    """The store file's size in pages against its header's, from the file's own bytes (no engine). Never raises; see
    ``src.monitoring.page_reading`` for what each ``state`` means and why a difference is a fact and not a verdict."""
    from src.monitoring import page_reading

    try:
        return page_reading.read_header(data_dir() / _DB_NAME)
    except Exception as exc:  # noqa: BLE001 - a reading that cannot be taken is a reading that says so (the data folder may be missing)
        return {"source": "header-bytes", "state": "unreadable", "error": type(exc).__name__}


def pages_at_boot() -> dict[str, Any] | None:
    """This boot's page reading (``record_session_start`` takes it before any connection can exist), or ``None`` if the boot read
    never ran. It describes the file the PREVIOUS session left, like ``wal_at_boot``."""
    return _PAGES_AT_BOOT


def wal_at_boot() -> dict[str, Any] | None:
    """This boot's -wal reading (see ``record_session_start``), or None if the boot
    read never ran. Reads the module global first so a later probe — which would by
    then have destroyed the evidence — can never be mistaken for it."""
    if _WAL_AT_BOOT is not None:
        return _WAL_AT_BOOT
    st = _read_state() or {}
    got = st.get("wal_at_boot")
    return got if isinstance(got, dict) else None


def session_uptime() -> dict[str, Any]:
    """How long THIS process has been running, or why that cannot be said.

    ``seconds`` is elapsed monotonic time since ``record_session_start()`` stamped this
    process -- monotonic so a wall-clock correction mid-soak cannot inflate or shrink
    it. A process that never stamped itself (a test, a CLI entry point) reports
    ``measured: False`` with the reason; it does NOT fall back to the timestamp on
    disk, which belongs to whichever session wrote it last.
    """
    if _SESSION_STARTED_MONO is None:
        return {
            "measured": False,
            "started_at": None,
            "seconds": None,
            "reason": (
                "this process never called record_session_start(), so it has no start "
                "of its own to measure from"
            ),
        }
    return {
        "measured": True,
        "started_at": _SESSION_STARTED_AT,
        "seconds": round(time.monotonic() - _SESSION_STARTED_MONO, 1),
    }


# The signal that initiated this stop, if any (set by install_signal_handlers).
_STOP_SIGNAL: str | None = None


def note_stop_signal(name: str) -> None:
    """Record which signal initiated the stop, so a deliberate stop can never be
    rendered as a crash. Called from the signal handler, before the graceful path."""
    global _STOP_SIGNAL
    _STOP_SIGNAL = name


def record_shutdown_phase(phase: str, *, reason: str | None = None, facts: dict[str, Any] | None = None) -> None:
    """Advance the sentinel through the teardown (S0.2).

    Before this, the sentinel had two states -- 'running' and 'clean' -- so a death
    DURING teardown was indistinguishable from a death long before it. The teardown
    is not instant (it stops the scheduler thread and disposes the pool, which
    checkpoints an encrypted store), so that window is real. Each step stamps its own
    phase, and a session that dies inside one reads as e.g. 'shutting-down' on the
    next boot: it was asked to stop and did not finish, which is a different fact from
    'it was killed mid-collection'.

    ``reason`` names WHY the stop began (a signal, the in-app power button); it is
    recorded once, on the first phase, and carried forward. ``shutdown_began_at`` is stamped the same way, once, on the first phase:
    ``shutdown_phase_at`` moves with every phase and ``ended_at`` is the last, so without it the teardown's duration was not readable
    (the 10-10 session's last step and its end were the same second). ``facts`` are the few named values a phase learned
    (:func:`dispose_facts`), merged in as they are; only the keys in :data:`_DISPOSE_FACT_KEYS` are kept."""
    state = _read_state() or {}
    state["state"] = phase
    state["shutdown_phase_at"] = _now()
    if not state.get("shutdown_began_at"):
        state["shutdown_began_at"] = state["shutdown_phase_at"]
    if reason and not state.get("shutdown_reason"):
        state["shutdown_reason"] = reason
    if _STOP_SIGNAL and not state.get("stop_signal"):
        state["stop_signal"] = _STOP_SIGNAL
    if facts:
        state.update({k: v for k, v in facts.items() if k in _DISPOSE_FACT_KEYS})
    _write_state(state)


#: The one key the disposal step leaves in the sentinel, and ``previous_session_report`` reads back: :func:`dispose_facts`' answer. Only keys
#: named here are kept, whatever a caller hands ``record_shutdown_phase``.
_DISPOSE_FACT_KEYS = ("dispose",)

#: The largest log size the ``dispose`` member carries (just under 1 TB, twelve digits), the largest connection count (three digits) and the
#: longest teardown it calls a duration (an hour). WHAT THEY PROTECT: the byte room of the member in the session-forensics report
#: (tests/test_session_forensics_budget.py builds it at these cuts). A value past a cut is not a measurement, so the member says the reading was
#: unusable (``unreadable`` / ``unknown``) or leaves the duration out, never a number it cannot stand behind.
DISPOSE_WAL_MAX_BYTES = 10**12 - 1
DISPOSE_OUT_MAX = 999
DISPOSE_TOOK_MAX_S = 3600

#: What each code of the ``dispose`` member says in words (the stored record carries the short code; the text maps it back, as
#: :data:`DIED_REASON_WORDS` does for ``died_into_phase``). A code stands IN PLACE of a number it could not give, so an unknown is never a
#: ``0`` and its reason costs no field of its own: ``wal`` is a byte count or ``unreadable``; ``out`` a count or one of ``earlier`` · ``unknown``
#: · ``unasked``; ``step`` one of the outcomes below. ``copied`` is a ``busy`` answer after every frame of the log was written back. THE ``out`` AND
#: ``step`` CODES ARE SEVEN CHARACTERS AT MOST, and ``unreadable`` (ten) is the one ``wal`` code, because the member's worst case is paid out
#: of the 2,415 B room (tests/test_session_forensics_budget.py builds it from these tables, every code at every cut).
DISPOSE_WAL_WORDS = {"unreadable": "the -wal's size could not be read"}
DISPOSE_OUT_WORDS = {
    "earlier": "an earlier disposal replaced the pool",
    "unknown": "the pool did not say",
    "unasked": "the pool was not asked",
}
DISPOSE_STEP_WORDS = {
    "done": "the log was written back and truncated",
    "busy": "a reader, a writer or another checkpoint held the log, and the answer did not show all of it written back",
    "copied": "every frame was written back, but a reader with a recent snapshot or a writer in the middle of a write still held the log, "
    "so it was not truncated and keeps its size (what a writer commits afterwards is not written back)",
    "failed": "the write-back failed (its exception class is in the storage journal)",
    "locked": "the write-back did not run: the store is locked, this process never opened it",
    "fresh": "the write-back did not run: the store is new, this process never opened it",
    "no db": "the write-back did not run: there is no SQLite database file to write back into",
    "not run": "the write-back step did not run",
    "unknown": "the sentinel names a write-back result this build does not know",
}
#: A step ``why`` the write-back step reports, as the code the member keeps (``locked`` / ``fresh``; anything else, a missing file or another
#: backend, is ``no db``).
_SKIP_CODES = {"locked": "locked", "fresh": "fresh"}


def dispose_facts(disposed: dict[str, Any] | None, checkpoint: dict[str, Any] | None) -> dict[str, Any]:
    """The facts the disposal step records, as the sentinel's one ``dispose`` key: the log still on disk (``wal``, read NOW, after the engine
    was disposed), what the pool held (``out``) and what the write-back before it did (``step``). An unknown is a CODE in place of the number
    (see :data:`DISPOSE_OUT_WORDS`), never ``0``. ``disposed`` is :func:`~src.database.session.dispose_engine`'s return and ``checkpoint`` is
    :func:`~src.database.shutdown_checkpoint.checkpoint_before_dispose`'s; either may be ``None`` (the step did not run). Never raises."""
    out: dict[str, Any] = {}
    try:
        # the log of the file the write-back step looked at, so the step and this record cannot read different files
        wal_path = checkpoint.get("wal_path") if isinstance(checkpoint, dict) else None
        wal = wal_state_before_open(Path(wal_path) if wal_path else None)
        if wal.get("state") == "present" and isinstance(wal.get("bytes"), int):
            out["wal"] = wal["bytes"]
        elif wal.get("state") == "absent":
            out["wal"] = 0
        else:
            out["wal"] = "unreadable"
    except Exception:  # noqa: BLE001 - forensics never blocks a shutdown
        out["wal"] = "unreadable"
    if isinstance(disposed, dict):
        n = disposed.get("checked_out")
        if isinstance(n, int):
            out["out"] = n
        else:
            try:
                from src.database.session import EARLIER_DISPOSAL

                earlier = disposed.get("checked_out_why") == EARLIER_DISPOSAL
            except Exception:  # noqa: BLE001
                earlier = False
            out["out"] = "earlier" if earlier else "unknown"
    else:
        out["out"] = "unasked"
    if isinstance(checkpoint, dict) and checkpoint.get("outcome"):
        step = str(checkpoint["outcome"])
        if step == "busy" and checkpoint.get("copied_all"):
            step = "copied"
        elif step == "skipped":
            step = _SKIP_CODES.get(str(checkpoint.get("why")), "no db")
        out["step"] = step
    else:
        out["step"] = "not run"
    return {"dispose": out}


def _clean_dispose(raw: Any, took: int | None) -> dict[str, Any] | None:
    """The sentinel's ``dispose`` record as the report carries it, rebuilt field by field: the file is on disk and anything may have written
    it, so a number is kept only inside its cut (:data:`DISPOSE_WAL_MAX_BYTES`, :data:`DISPOSE_OUT_MAX`), a code only when it is one the tables
    know, and anything else becomes the code that says the reading was unusable (``unreadable`` / ``unknown``: for ``step`` that is
    ``unknown``, never ``not run``, which would claim the step did not run). ``took`` (seconds from the teardown's first step to the
    session's end, computed by the caller) is added when it is a credible duration. ``None`` when the sentinel holds no such record (a
    build before this one): the report then says nothing."""
    if not isinstance(raw, dict):
        return None

    def number(value: Any, cut: int, codes: dict[str, str], other: str) -> Any:
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= cut:
            return value
        return value if isinstance(value, str) and value in codes else other

    out: dict[str, Any] = {}
    if "wal" in raw:
        out["wal"] = number(raw["wal"], DISPOSE_WAL_MAX_BYTES, DISPOSE_WAL_WORDS, "unreadable")
    if "out" in raw:
        out["out"] = number(raw["out"], DISPOSE_OUT_MAX, DISPOSE_OUT_WORDS, "unknown")
    if "step" in raw:
        out["step"] = raw["step"] if isinstance(raw["step"], str) and raw["step"] in DISPOSE_STEP_WORDS else "unknown"
    if isinstance(took, int) and 0 <= took <= DISPOSE_TOOK_MAX_S:
        out["took"] = took
    return out


def record_clean_shutdown() -> None:
    """Flip the sentinel to 'clean'. Called from the lifespan shutdown; a session
    that dies without reaching this reads as UNCLEAN on the next boot."""
    state = _read_state() or {}
    state["state"] = "clean"
    state["ended_at"] = _now()
    if _STOP_SIGNAL and not state.get("stop_signal"):
        state["stop_signal"] = _STOP_SIGNAL
    _write_state(state)
    # The ledger's own end line for this session (2026-09-18); the sentinel above is
    # still the verdict the next boot reads.
    try:
        from src.monitoring.session_history import record_end

        record_end(clean=True, reason=state.get("shutdown_reason") or _STOP_SIGNAL)
    except Exception as exc:  # noqa: BLE001 - never in the way of a shutdown
        log_failure(_LOG, "session ledger: end record failed", exc, level=logging.DEBUG)


def _last_collect_perf_sample() -> dict[str, Any] | None:
    """The last collect_perf JSONL line (the collector's own RSS/memory record) —
    the closest thing to a flight recorder for an externally-killed process."""
    path = data_dir() / "collect_perf.jsonl"
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    # The newest TICK line. A pass ends with a "summary" line whose rss_mb is a
    # {first, last, max} curve and which carries no available-memory reading; taking
    # it as the sample printed "rss {'first': 587.2, ...} MB, available None MB" in the
    # field export of 2026-09-26. The tick just before it holds the real reading.
    for line in reversed(raw.splitlines()[-200:]):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue  # a line cut short by the very death being explained
        if not isinstance(d, dict) or d.get("kind") == "summary":
            continue
        if not isinstance(d.get("rss_mb"), (int, float)):
            continue
        return {
            "ts": d.get("ts"),
            "rss_mb": d.get("rss_mb"),
            "mem_avail_mb": d.get("mem_avail_mb"),
            "since_pass_start_s": _seconds_between(d.get("pass_id"), d.get("ts")),
            "pass_id": d.get("pass_id"),
        }
    return None


def _seconds_between(start: Any, end: Any) -> float | None:
    """``end`` minus ``start`` in seconds, both ISO-8601 strings, or ``None`` when either is missing, unreadable or the two
    cannot be compared (never a ``0``, which would read as "the pass had just begun").

    The collect-perf tick used to carry ``elapsed_s`` (seconds since the monitor was built); it no longer does, to pay for the
    extraction-lock block, and a tick's ``pass_id`` is the pass's own start (``runner.py`` stamps it before the sources are
    chosen), so the time into the pass is ``ts`` minus ``pass_id``. That is a slightly different quantity from the old
    ``elapsed_s`` (it includes the seconds the pass spent choosing its sources before the monitor existed), which is why the
    key is named for what it holds and the old name is gone."""
    try:
        a = datetime.fromisoformat(str(start))
        b = datetime.fromisoformat(str(end))
        return round((b - a).total_seconds(), 1)
    except (TypeError, ValueError):
        return None


#: The unlock step that holds the verify connection's recovery and its checkpoint-on-close. The
#: phase's name is the record's key, so the writer (``api/unlock.py``) and the reader below use ONE
#: constant.
UNLOCK_VERIFY_PHASE = "passphrase verify + WAL recovery + checkpoint-on-close"

#: The unlock step that runs ``init_db``. Named once for the same reason as the verify phase: the writer
#: (``api/unlock.py``) and the reader that names its slowest step (``p0_validation``) share ONE constant.
UNLOCK_INIT_DB_PHASE = "init_db (schema self-heal + migrations + WAL recovery)"

#: The smallest log whose unlock COULD be read as a rate (the floor in force is
#: :func:`recovery_floor_bytes`: this, or one byte above the resting ceiling when that is larger).
#: Below it the keyed open's own fixed cost (the key derivation alone measured 0.2 to 0.4 s here)
#: is most of the step, so seconds per GiB would be a statement about the KDF, not about the log;
#: it is also about the smallest log a person could watch (a recovery that ends within a second or
#: two is gone before the sentence can be read).
RECOVERY_RATE_MIN_BYTES = 64 * 1024 * 1024


def recovery_floor_bytes() -> int:
    """The log size from which an unlock is read as a recovery (a sentence, a measured rate): the
    larger of ``RECOVERY_RATE_MIN_BYTES`` and ONE BYTE MORE than the ``-wal`` resting ceiling
    (``journal_size_limit``, 64 MiB by default). A log that ever grew past the ceiling is truncated
    back to exactly the ceiling and rests there holding almost nothing (measured by the Opus read
    of #1293: 67,108,864 bytes, one valid frame, 0.39 s to recover), so a log AT the ceiling carries
    no information about pending writes: it used to be read as "64 MB to apply" and stored ~6 s/GiB
    of key-derivation time as this machine's recovery rate."""
    try:
        from src.database.session import wal_size_limit_bytes

        limit = wal_size_limit_bytes()
    except Exception:  # noqa: BLE001 - no ceiling known: the plain floor applies
        limit = -1
    return max(RECOVERY_RATE_MIN_BYTES, limit + 1 if limit > 0 else 0)


def record_unlock_timing(record: dict[str, Any]) -> None:
    """Persist the unlock path's own timing record (wal bytes before open,
    per-phase ms, total) into the sentinel file. Best-effort.

    Also keeps ``last_recovery``: the most recent unlock that actually recovered a log at or above
    :func:`recovery_floor_bytes`. ``last_unlock`` is overwritten by every unlock, including
    the ones with no log, so on its own it could not answer "how long did this machine take the
    last time it had a large log to recover".

    It also stamps WHEN the unlock finished (``unlock_marker``): every finished unlock passes
    through here, and the request-latency and search-timing logs measure each call's distance
    from that moment. Stamped first, so a sentinel file that cannot be written (the very
    condition this log exists to diagnose) does not also lose the stamp."""
    try:
        from src.monitoring.unlock_marker import note_unlock_done

        note_unlock_done()
    except Exception as exc:  # noqa: BLE001 - a stamp must never break the unlock it describes
        log_failure(_LOG, "could not stamp the unlock", exc, level=logging.DEBUG)
    state = _read_state() or {"state": "running", "started_at": _now(), "pid": os.getpid()}
    state["last_unlock"] = {**record, "at": _now()}
    recovery = _recovery_from_record(record)
    if recovery is not None:
        state["last_recovery"] = {**recovery, "at": _now()}
    _write_state(state)


def record_init_db(record: dict[str, Any]) -> None:
    """Persist the per-step time of this process's first ``init_db`` into the sentinel as ``last_init_db``.

    The unlock path carries the same record inside ``last_unlock`` (``init_db_steps``); a start with no
    unlock (a plaintext store, ``serve``, ``python -m uvicorn``) has no such record, and the field's slow
    ``init_db`` (STORE-02) was read on starts of both kinds. Best-effort: forensics never blocks a boot.
    """
    try:
        state = _read_state() or {"state": "running", "started_at": _now(), "pid": os.getpid()}
        state["last_init_db"] = record
        _write_state(state)
    except Exception as exc:  # noqa: BLE001 - a record that cannot be kept is not worth a failed boot
        log_failure(_LOG, "could not record the init_db steps", exc, level=logging.DEBUG)


def _recovery_from_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """The measured recovery inside an unlock timing record, or None when the record has no log
    at or above :func:`recovery_floor_bytes` or no verify step to time it by."""
    wal = record.get("wal_bytes_before_open")
    if not isinstance(wal, (int, float)) or isinstance(wal, bool) or wal < recovery_floor_bytes():
        return None
    for ph in record.get("phases") or []:
        if not isinstance(ph, dict) or ph.get("phase") != UNLOCK_VERIFY_PHASE:
            continue
        ms = ph.get("ms")
        if isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms > 0:
            gib = float(wal) / (1024**3)
            return {"wal_bytes": int(wal), "seconds": round(float(ms) / 1000.0, 1),
                    "seconds_per_gib": round(float(ms) / 1000.0 / gib, 2)}
    return None


def last_recovery() -> dict[str, Any] | None:
    """This machine's last measured recovery of a large log (see ``record_unlock_timing``), or
    None when it has none. Read from the plaintext sentinel, so it is available while the store is
    still locked."""
    rec = (_read_state() or {}).get("last_recovery")
    if not isinstance(rec, dict):
        return None
    per_gib = rec.get("seconds_per_gib")
    if not isinstance(per_gib, (int, float)) or isinstance(per_gib, bool) or per_gib <= 0:
        return None
    return rec


def recovery_estimate(wal_bytes: int) -> tuple[float | None, dict[str, float] | None]:
    """``(eta_s, basis)`` for recovering a ``wal_bytes`` log on THIS machine, from its own last
    measured recovery: that recovery's seconds per GiB times this log's GiB. ``(None, None)`` when
    the machine has no earlier measurement -- an estimate from another machine's speed would be a
    guess with a number on it (the field's own per-GiB figures ran from 5.0 to 39.2 s, so no
    constant is honest). ``basis`` is the measurement it came from, so the page can say so."""
    rec = last_recovery()
    # A size that is not a real, positive number (a damaged reading, a bool) is no size: the
    # estimate stays absent rather than raising into the unlock that asked for it.
    if (
        rec is None
        or isinstance(wal_bytes, bool)
        or not isinstance(wal_bytes, (int, float))
        or not math.isfinite(wal_bytes)
        or wal_bytes <= 0
    ):
        return None, None
    per_gib = float(rec["seconds_per_gib"])
    basis = {"wal_bytes": float(rec.get("wal_bytes") or 0), "seconds": float(rec.get("seconds") or 0)}
    return round(per_gib * (float(wal_bytes) / (1024**3)), 1), basis


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


def wal_state_before_open(path: Path | None = None) -> dict[str, Any]:
    """The -wal file's state at the moment of the call, in THREE states. ``path`` is the log to look at (the shutdown write-back names the
    file its step looked at, so the facts that follow read the same one); by default the data folder's own.

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
    p = path if path is not None else data_dir() / f"{_DB_NAME}-wal"
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
    # The host's own account. It is the ONLY source that separates an OOM kill from a
    # host reset from a signal from a native fault — the app's records cannot.
    out["kernel_evidence"] = kernel_evidence()
    # The EARLIER unclean ends and what the crash trace holds for each (finding D, 2026-10-01): the
    # entry below reads the previous session's pid only, so on a crash loop every earlier stack
    # stayed on the machine and in no bundle. Reported for EVERY verdict: an earlier crash followed
    # by a clean session still happened.
    try:
        from src.monitoring.exit_evidence import earlier_unclean_ends

        out["earlier_unclean_ends"] = earlier_unclean_ends(prev)
    except Exception as exc:  # noqa: BLE001 - forensics degrades, never raises
        out["earlier_unclean_ends"] = {"available": False, "reason": _why(exc)}
    # The clean stop (B2): a session the app ended itself because memory stayed exhausted says so, whatever the sentinel's verdict
    # (a stop that finished reads "clean", one the kernel cut short reads "during shutdown"). Numbers and step names only.
    out["memory_stop"] = previous_memory_stop()
    out["oom_counters"] = _oom_counters_between(prev)
    # The libraries the previous session ran on, for reading a crash trace that names only Python frames (``native_libs.py``).
    out["previous_session_native_libs"] = (prev or {}).get("native_libs") or {"unreadable": "the previous session's sentinel holds no reading"}
    if prev is None:
        out["previous_session"] = "unknown"
        out["note"] = "no sentinel yet (first boot with forensics, or the file was removed)"
        return _with_answers(out)
    state = str(prev.get("state"))
    out["previous_session"] = {
        "running": "unclean-end",  # died without reaching the shutdown hook
        # S0.2: a death DURING teardown. It was asked to stop and did not finish —
        # a different fact from being killed mid-collection, and one the two-state
        # sentinel could not express.
        "shutting-down": "unclean-end-during-shutdown",
        # the write-back before the disposal can take as long as the write-back itself (about 90 s for 1.4 GB), so a death inside it is its own fact
        "writing-back": "unclean-end-during-write-back",
        "dispose-done": "unclean-end-after-dispose",
        "clean": "clean",
    }.get(state, f"unknown({state})")
    out["started_at"] = prev.get("started_at")
    out["ended_at"] = prev.get("ended_at")
    out["last_unlock"] = prev.get("last_unlock")
    for key in ("shutdown_reason", "stop_signal", "shutdown_phase_at"):
        if prev.get(key):
            out[key] = prev[key]
    # What that session's disposal left behind, as ONE member (R201: the headroom above the diagnostics floor is spent member by member, and
    # this one is registered in HEADROOM_MEMBERS with its worst case measured). A ``0`` is a fact (no log), so it is carried when PRESENT, not
    # when truthy; a sentinel written by a build before this one has none, and the report then says nothing rather than "empty". The
    # teardown's start is not copied (a timestamp is 45 B): the seconds from it to the end are computed here.
    dispose = _clean_dispose(prev.get("dispose"), _whole_seconds_between(prev.get("shutdown_began_at"), prev.get("ended_at")))
    if dispose is not None:
        out["dispose"] = dispose
    if out["previous_session"] != "clean":
        # How it ENDED, from the witnesses outside the process (2026-09-26): the
        # launcher's exit status, the user-space memory killers' journal lines and the
        # native crash trace -- beside the kernel's account above, never instead of it.
        out["exit_evidence"] = _exit_evidence_report(prev)
        out["how_it_ended"] = _how_it_ended(out["kernel_evidence"], out["exit_evidence"], prev.get("started_at"))
    if out["previous_session"] == "unclean-end":
        # The previous session's OWN peaks (S0.4). ``last_collector_sample`` reads the
        # last line of a file EVERY session appends to, so once this process starts
        # collecting it reports the survivor's numbers, not the crashed run's — which
        # is how an OOM was once "inferred" from the wrong process. The sidecar is
        # scoped to one session and is snapshotted at boot, so it cannot drift.
        out["previous_session_peaks"] = _previous_peaks()
        if isinstance(out.get("how_it_ended"), dict):
            out["how_it_ended"]["died_into_phase"] = _died_into_phase(out["previous_session_peaks"])
        sample = _last_collect_perf_sample()
        if sample is not None:
            sample = dict(sample)
            sample["attribution"] = (
                "the last line of collect_perf.jsonl, which EVERY session appends to — "
                "once this session starts collecting these are ITS numbers, not the "
                "previous one's. Use previous_session_peaks for the crashed run."
            )
        out["last_collector_sample"] = sample
    return _with_answers(out)


#: The members of the session-forensics report that spend the 2,415 B headroom above the diagnostics floor. A member joins this tuple in the
#: commit that adds it, together with a worst-case builder in tests/test_session_forensics_budget.py (that test is red while the two differ,
#: and while a ``*_BYTES`` cap exists in the monitoring modules that no member claims).
HEADROOM_MEMBERS = ("crashing_thread_kind", "launcher_stderr", "died_into_phase", "native_in_flight", "last_thread_census", "stack", "dispose")

#: What each ``died_into_phase`` reason code says in words (the stored record carries the short code; every reader maps it back, so the report
#: reads as it did before the codes). tools/diag_reader.py carries the same table for the triage.
DIED_REASON_WORDS = {
    "no peaks": "no high-water record",
    "no phase": "no phase was recorded",
    "no phase start": "phase start not recorded (older build)",
    "clock moved": "clock moved",
}


def _died_into_phase(peaks: dict[str, Any] | None) -> dict[str, Any]:
    """Seconds from the first sighting of the previous session's last phase to its last record.

    WHICH phase is not repeated here: it is ``previous_session_peaks.phase`` in the same report, and the seconds are only ever
    given when that field is present (the byte room is the reason it is not copied). The last record is the last ``observe``
    call, not the moment of death, so the figure is a lower bound. Where the phase or its start was not recorded the seconds are
    ``None`` with a reason, never ``0`` (a 0 would read as "died the instant it began"). The reasons are short codes (no peaks · no phase ·
    no phase start · clock moved): the longest the member can be is measured in tests/test_session_forensics_budget.py."""
    out: dict[str, Any] = {"seconds_in_peaks_phase": None}
    if not isinstance(peaks, dict) or peaks.get("available") is False:
        out["reason"] = "no peaks"
        return out
    if not isinstance(peaks.get("phase"), str) or not peaks["phase"]:
        out["reason"] = "no phase"
        return out
    try:
        began = datetime.fromisoformat(str(peaks["phase_since"]))
        last = datetime.fromisoformat(str(peaks["last_ts"]))
        secs = (last - began).total_seconds()
    except (KeyError, ValueError, TypeError):
        out["reason"] = "no phase start"
        return out
    if secs < 0:
        out["reason"] = "clock moved"
        return out
    out["seconds_in_peaks_phase"] = round(secs, 1)
    return out


def _with_answers(out: dict[str, Any]) -> dict[str, Any]:
    """``out`` with the evidence state of the open questions (``can_answer.py``). Never raises."""
    try:
        from src.monitoring.can_answer import assess

        out["can_answer"] = assess(out)
    except Exception as exc:  # noqa: BLE001 - forensics degrades, never raises
        out["can_answer"] = {"unavailable": f"unreadable ({type(exc).__name__})"}
    return out


def _oom_counters_between(prev: dict[str, Any] | None) -> dict[str, Any]:
    """The kernel's kill counters at the previous session's start and at this one, and the kills counted between (question 22). Never raises."""
    try:
        from src.monitoring.oom_counters import compare

        before = (prev or {}).get("oom_counters")
        prev_boot = (prev or {}).get("boot_id")
        same_boot = None if not prev_boot or not _BOOT_ID_AT_BOOT else prev_boot == _BOOT_ID_AT_BOOT
        return {
            "previous_session_start": before,
            "this_session_start": _OOM_AT_BOOT,
            "between": compare(before, _OOM_AT_BOOT, same_boot=same_boot),
            "note": (
                "Counters the kernel keeps, read once at each session start: 'between' is the kills counted from the previous session's "
                "start to this one's. It covers the previous session AND the gap, and a count of zero is a count only where the reading "
                "exists (an unreadable counter is named, never zero)."
            ),
        }
    except Exception as exc:  # noqa: BLE001 - forensics degrades, never raises
        return {"unavailable": f"unreadable ({type(exc).__name__})"}


def previous_memory_stop() -> dict[str, Any] | None:
    """The record of the clean stop that ended the previous session, or ``None`` when it did not end that way: read through the
    allow-list with the size it was (``scheduler.memstop.read_record``), and only when it names the ledger's id for the previous
    session. Never raises."""
    try:
        from src.monitoring.session_history import previous_session_id
        from src.scheduler.memstop import read_record

        return read_record(previous_session_id())
    except Exception:  # noqa: BLE001 - forensics degrades, never raises
        return None


def _previous_peaks() -> dict[str, Any] | None:
    """The previous session's own high-water marks, or a stated absence. The marks are the previous SESSION's only when they carry the
    ledger's id for it (the way the ledger's end record decides, ``session_history._hwm_last_seen``): a sidecar of another session, or
    one that names none, is no evidence, and what is copied has every release-ladder record rebuilt from the allow-list."""
    try:
        from src.monitoring.release_view import scrub_marks
        from src.monitoring.session_history import previous_session_id
        from src.monitoring.session_hwm import previous_why

        got, why = previous_why()
        if got:
            ident, want = got.get("session_id"), previous_session_id()
            if not isinstance(ident, str) or not ident or not want:
                got, why = None, "no identity"
            elif ident != want:
                got, why = None, "another session"
            else:
                got, failed = scrub_marks(got)
                if got is None:
                    why = f"scrub failed ({failed})"
    except Exception:  # noqa: BLE001 - forensics degrades, never raises
        return None
    if not got:
        return {
            "available": False,
            "reason": (
                "no per-session high-water record from the previous run (it predates "
                "this instrument, or the file was removed) — unmeasured, not zero"
                if why in (None, "absent")
                else (
                    f"the previous session's high-water record was read and could not be scrubbed ({why[len('scrub failed ('):-1]}) — unmeasured, not zero"
                    if why.startswith("scrub failed (")
                    else f"the high-water record on disk is not this run's previous session's ({why}) — unmeasured, not zero"
                )
            ),
        }
    out = dict(got)
    out["available"] = True
    out["method"] = (
        "peak RSS / minimum available memory / peak swap-used sampled by the previous "
        "session itself and snapshotted at this boot, with what the memory was made of "
        "at the RSS peak (at_peak: /proc/self/status, glibc mallinfo2, CPython's block "
        "count), the newest peak that read glibc's heap when the last one could not "
        "(heap_at_peak: a peak taken with memory already short skips that walk) and, "
        "when available memory ran short, the moment the memory guard engaged, and every "
        "300 s while memory stayed short or the guard stayed engaged, what every thread was "
        "doing (pressure: name, CPU time and stack, the newest snapshots kept; a snapshot "
        "taken while the guard was engaged carries a guard block) and, at most every 15 s while "
        "memory was within 1.5 times the guard's line, a light snapshot of the threads that "
        "spent the most CPU since the previous one, among the first 16 working threads found "
        "(pressure_light; the pairing with the Python blocks gained is an inference, memory is "
        "not measured per thread). allocator is "
        "which C allocator the session ran on and whether its malloc arenas were capped "
        "(R114), read from the environment the process started with; memory_budget is "
        "the memory tier the session was resolved to (tier, RAM total, logical CPUs, whether the "
        "in-memory rollup is on by default, and when: resolved once per process); a record "
        "written before either was kept has none. A field that could not be measured is "
        "ABSENT rather than zero."
    )
    return out


_KERNEL_EVIDENCE: dict[str, Any] | None = None


def start_kernel_evidence_read(prev: dict[str, Any] | None) -> None:
    """Kick the host kernel-log read for the PREVIOUS session, on a background thread.

    RULED always-on and local-only (2026-09-02). Off the lifespan's critical path by
    construction: a hung ``journalctl`` must never delay a boot, so it runs on a daemon
    thread and the report simply says the read has not finished if it is asked first."""
    global _KERNEL_EVIDENCE
    if prev is None:
        _KERNEL_EVIDENCE = {
            "verdict": "not-applicable",
            "reason": "no previous session recorded, so there is nothing to look up",
        }
        return

    def _work() -> None:
        global _KERNEL_EVIDENCE, _JOURNAL_EXIT_EVIDENCE
        pid = prev.get("pid")
        pid = int(pid) if isinstance(pid, int) else None
        try:
            from src.monitoring.kernel_log import read_kernel_evidence

            kwargs: dict[str, Any] = {"since": prev.get("started_at")}
            if prev.get("boot_id"):
                # Only a sentinel written since 2026-09-26 carries it.
                kwargs["boot"] = prev["boot_id"]
            _KERNEL_EVIDENCE = read_kernel_evidence(pid, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a forensic read never raises upward
            _KERNEL_EVIDENCE = {
                "verdict": "unavailable",
                "reason": f"the kernel-log read failed ({type(exc).__name__})",
            }
        # The user-space killers log to the ordinary journal, not the kernel's
        # (2026-09-26): read only for a session that did not end cleanly, since a clean
        # end is already accounted for by its own shutdown hook.
        if str(prev.get("state")) == "clean":
            return
        got: dict[str, Any] = {}
        try:
            from src.monitoring.exit_evidence import read_userspace_killers, running_killers

            got["userspace_killers"] = read_userspace_killers(
                pid, since=prev.get("started_at"), boot=prev.get("boot_id"), cgroup=prev.get("cgroup")
            )
            got["running_killers"] = running_killers()
        except Exception as exc:  # noqa: BLE001 - a forensic read never raises upward
            got["userspace_killers"] = {
                "verdict": "unavailable",
                "reason": f"the journal read failed ({type(exc).__name__})",
            }
        _JOURNAL_EXIT_EVIDENCE = got

    import threading

    threading.Thread(target=_work, name="oo-kernel-evidence", daemon=True).start()


def kernel_evidence() -> dict[str, Any]:
    """The kernel's account of the previous session, or an honest not-yet/never."""
    if _KERNEL_EVIDENCE is not None:
        return _KERNEL_EVIDENCE
    return {
        "verdict": "not-read",
        "reason": (
            "the background kernel-log read has not completed (or was never started, "
            "e.g. outside the app's own boot path) — unmeasured, not 'clean'"
        ),
    }


# The journal half of the exit evidence, filled by the same background read as the
# kernel's account (a journalctl call must never delay a boot).
_JOURNAL_EXIT_EVIDENCE: dict[str, Any] | None = None


def _exit_evidence_report(prev: dict[str, Any]) -> dict[str, Any]:
    """The witnesses outside the process, for a session that did not end cleanly.

    The launcher record and the crash trace are small local files and are read here;
    the journal reads come from the boot's background thread, or say they have not
    finished rather than stand in for a result."""
    pid = prev.get("pid")
    pid = int(pid) if isinstance(pid, int) else None
    boot = prev.get("boot_id") if isinstance(prev.get("boot_id"), str) else None
    out: dict[str, Any] = {}
    try:
        from src.monitoring.exit_evidence import launcher_exit, launcher_stderr, previous_trace

        out["launcher"] = launcher_exit(pid, boot, prev.get("started_at") if isinstance(prev.get("started_at"), str) else None)
        out["launcher_stderr"] = launcher_stderr(pid, boot, prev.get("started_at") if isinstance(prev.get("started_at"), str) else None)
        out["crash_trace"] = previous_trace(pid, boot, prev.get("started_at"))
        from src.monitoring.native_inflight import report as _native_report

        out["native_in_flight"] = _native_report(pid, boot)
    except Exception as exc:  # noqa: BLE001 - forensics degrades, never raises
        out["unavailable"] = _why(exc)
    if _JOURNAL_EXIT_EVIDENCE is not None:
        out.update(_JOURNAL_EXIT_EVIDENCE)
    else:
        out["userspace_killers"] = {
            "verdict": "not-read",
            "reason": (
                "the background journal read has not completed (or was never started) — "
                "unmeasured, not 'clean'"
            ),
        }
    return out


def _how_it_ended(
    kernel: dict[str, Any], evidence: dict[str, Any], started_at: str | None = None
) -> dict[str, Any]:
    try:
        from src.monitoring.exit_evidence import how_it_ended
        from src.safety.data_volume import last_disconnect_since

        return how_it_ended(
            launcher=evidence.get("launcher"),
            killers=evidence.get("userspace_killers"),
            kernel=kernel,
            trace=evidence.get("crash_trace"),
            drive=last_disconnect_since(started_at) if started_at else None,
        )
    except Exception as exc:  # noqa: BLE001
        return {"known": False, "summary": f"could not be assembled ({type(exc).__name__})"}


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


# What the memory was made of at the peak (session_hwm.composition), in reading order.
_AT_PEAK_FIELDS = (
    ("rss_anon_mb", "anonymous", " MB"),
    ("rss_file_mb", "file-backed", " MB"),
    ("rss_shmem_mb", "shared", " MB"),
    ("swapped_out_mb", "swapped out", " MB"),
    ("heap_in_use_mb", "C heap in use", " MB"),
    ("heap_free_held_mb", "C heap freed but held", " MB"),
    ("heap_mmapped_mb", "large C blocks", " MB"),
    ("py_alloc_blocks", "Python blocks", ""),
    ("threads", "threads", ""),
)


def _render_allocator(alloc: Any) -> list[str]:
    """Which C allocator the session ran on and whether its malloc arenas were capped
    (R114), as one line beside the peaks it explains: a heap that was freed but held reads
    differently with the cap (it did not return the memory) than without it."""
    if not isinstance(alloc, dict) or not alloc.get("note"):
        return []
    return [f"  - C allocator ({alloc.get('allocator') or 'not read'}): {alloc['note']}"]


def _render_memory_budget(reading: Any) -> list[str]:
    """The memory tier the session was resolved to, as one line beside the peaks it bounds:
    the pool and the page caches (unless the operator set them), DuckDB's limit and whether
    the in-memory keyword rollup runs by default were all decided from it, once, at start. The
    line states the tier's default and not an operator's own ``OO_COLUMNAR_SERVE`` choice, which
    only the session ledger records (``rollup_serve_mode``), and says so. A record written
    before it was kept has none,
    and one whose reading failed says so rather than leaving a hole."""
    if not isinstance(reading, dict):
        return []
    if reading.get("error"):
        return [f"  - memory tier: not read ({reading['error']})"]
    tier = reading.get("tier")
    if not tier:
        return []
    total = reading.get("total_ram_mb")
    seen = f"{total:,.1f} MiB read" if isinstance(total, (int, float)) else "RAM not readable"
    nominal = reading.get("nominal_ram_mb")
    if isinstance(nominal, (int, float)) and isinstance(total, (int, float)) and abs(nominal - total) >= 0.05:
        seen += f", a nominal {nominal:,.0f} MiB machine"
    cores = reading.get("cores")
    if isinstance(cores, int):
        seen += f", {cores} logical CPU{'' if cores == 1 else 's'}"
    when = f"; resolved at {reading['resolved_at']}" if reading.get("resolved_at") else ""
    serve = reading.get("columnar_serve_default")
    rollup = (
        "this tier leaves the in-memory keyword rollup on by default" if serve is True
        else "this tier leaves the in-memory keyword rollup off by default" if serve is False
        else "whether this tier leaves the in-memory keyword rollup on by default is not recorded"
    )
    return [
        f"  - memory tier ({tier}; {seen}{when}): {rollup} (an operator's own OO_COLUMNAR_SERVE "
        "choice is in chronology.json, not here); resolved once, when the process started, so a "
        "total that moved afterwards is not in it"
    ]


def _lowest_kept_snapshot(snaps: Any) -> tuple[float, str] | None:
    """The lowest ``avail_mb`` among the kept pressure snapshots and when it was read, or None."""
    best: tuple[float, str] | None = None
    for snap in snaps if isinstance(snaps, list) else []:
        if not isinstance(snap, dict):
            continue
        avail = snap.get("avail_mb")
        if isinstance(avail, int | float) and (best is None or avail < best[0]):
            best = (avail, str(snap.get("at") or "a time that was not recorded"))
    return best


def _render_rss_and_swap_apart(comp: dict) -> str | None:
    """RSS and the swapped-out pages on ONE line, RSS with its share of RAM and the swapped-out
    pages with none, and the statement that they are not added.

    A "footprint" that sums them (3,118.9 MB RSS + 671.9 MB swapped out = 96.6% of 3,924.7 MB in
    the field analysis) is not RAM use: a swapped-out page has LEFT RAM, and RSS alone read
    79.5%. They are listed apart, here and in the JSON, so nobody has to re-derive which is
    which. Only RSS is given as a share OF RAM: a share of RAM for pages that are not in RAM would
    invite exactly the sum this line forbids. A record whose figures are not numbers renders
    nothing here rather than raising (a forensic read degrades, never fails)."""
    rss, swapped, total = comp.get("rss_mb"), comp.get("swapped_out_mb"), comp.get("total_mb")
    if not isinstance(rss, int | float):
        return None
    share = (
        f" ({rss / total:.1%} of {total:g} MB of RAM)"
        if isinstance(total, int | float) and total > 0 else ""
    )
    line = f"  - at that peak: RSS {rss} MB{share}"
    if swapped is not None:
        line += f"; separately, {swapped} MB swapped out"
    return (
        line
        + " -- kept apart on purpose: swapped-out pages are not resident in RAM, so the two are "
        "never added into one footprint"
    )


def _render_at_peak(comp: Any, heap_peak: Any = None) -> list[str]:
    """The composition at the RSS peak and, when that peak could not read the C heap,
    the newest earlier peak that did, on its own line with its own size and time: the
    two readings are never merged into one, because they describe different moments."""
    if not isinstance(comp, dict):
        return []

    def _parts(c: dict) -> list[str]:
        return [f"{label} {c[key]}{unit}" for key, label, unit in _AT_PEAK_FIELDS if c.get(key) is not None]

    parts = _parts(comp)
    if comp.get("heap_in_use_mb") is None:
        why = comp.get("heap_skipped") or "memory was already short, or not glibc"
        parts.append(f"C heap not read ({why})")
    lines = [f"  - made of, at {comp.get('rss_mb')} MB ({comp.get('at')}): {', '.join(parts)}"]
    apart = _render_rss_and_swap_apart(comp)
    if apart:
        lines.append(apart)
    if (
        comp.get("heap_in_use_mb") is None
        and isinstance(heap_peak, dict)
        and heap_peak.get("heap_in_use_mb") is not None
    ):
        lines.append(
            f"  - C heap last read at an earlier peak, {heap_peak.get('rss_mb')} MB "
            f"({heap_peak.get('at')}): {', '.join(_parts(heap_peak))}"
        )
    return lines


# The threads that were WORKING when memory ran short are listed; the waiting ones (the
# snapshot marks them) are counted, so the few are not buried under forty idle ones.
_PRESSURE_THREADS_SHOWN = 8


def _snap_seconds(at: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(at)).timestamp()
    except ValueError:
        return None


def _render_light(snaps: Any, taken: Any = None) -> list[str]:
    """The LIGHT snapshots taken while memory was near the memory guard's line (``session_hwm``): each
    one's readings and the busiest threads by CPU since the previous one. The pairing of the Python
    blocks gained with a thread is an inference and says so: memory is not measured per thread."""
    snaps = [x for x in snaps if isinstance(x, dict)] if isinstance(snaps, list) else []
    if not snaps:
        if isinstance(taken, int) and taken > 0:
            return [
                f"  - near the memory guard's line: {taken} light snapshot(s) were taken, but "
                "their file (session_pressure_light.json) was not found"
            ]
        return []
    count = f"{len(snaps)} snapshot(s)"
    if isinstance(taken, int) and taken > len(snaps):
        count += f" of {taken} taken, the newest kept"
    out = [
        f"  - near the memory guard's line, {count}, one every 15 s at most (the threads that spent the "
        "most CPU since the previous one, among the first 16 working threads found; memory is not "
        "measured per thread, so which thread allocated the blocks gained is an inference):"
    ]
    for snap in snaps:
        mem = snap.get("memory") or {}
        bits = []
        if snap.get("avail_mb") is not None:
            bits.append(f"{snap['avail_mb']} MB available")
        if snap.get("rss_mb") is not None:
            bits.append(f"RSS {snap['rss_mb']} MB")
        if mem.get("py_alloc_blocks") is not None:
            bits.append(f"{mem['py_alloc_blocks']:,} Python blocks")
        if isinstance(snap.get("blocks_gained"), int):
            bits.append(f"{snap['blocks_gained']:+,} in {snap.get('over_s')} s")
        if snap.get("took_ms") is not None:
            bits.append(f"took {snap['took_ms']} ms")
        out.append(f"    - {snap.get('at')}, {snap.get('why') or 'near the line'}: {', '.join(bits) or 'no reading'}")
        unreadable = snap.get("thread_cpu")
        if unreadable:
            out.append(f"      - thread CPU time: {unreadable}")
        for t in snap.get("threads") or []:
            if not isinstance(t, dict):
                continue
            cpu = t.get("cpu_delta_s")
            over = f" in {snap['over_s']} s" if cpu is not None and snap.get("over_s") is not None else ""
            if cpu is not None:
                note = f" (+{cpu} s of CPU{over})"
            elif unreadable:
                note = " (CPU time not readable here)"
            else:
                note = " (no earlier reading to compare)"
            out.append(f"      - {t.get('name')}{note}: {' <- '.join(t.get('stack') or [])}")
    return out


def _render_pressure(snaps: Any, taken: Any = None) -> list[str]:
    """Each snapshot's readings, then the threads that were WORKING, busiest first.

    Busiest means CPU spent since the previous snapshot (a thread the previous one did
    not see counts all of its CPU), because a thread's lifetime total says what it did
    since boot, not what it was doing while the memory went."""
    snaps = [x for x in snaps if isinstance(x, dict)] if isinstance(snaps, list) else []
    if not snaps:
        if isinstance(taken, int) and taken > 0:
            return [
                f"  - what every thread was doing: {taken} snapshot(s) were taken, but "
                "their file (session_pressure.json) was not found"
            ]
        return []
    why: dict[str, int] = {}
    for snap in snaps:
        label = str(snap.get("why") or "memory short")
        why[label] = why.get(label, 0) + 1
    reasons = []
    if why.get("memory short"):
        line = next((x.get("line_mb") for x in snaps if x.get("line_mb") is not None), None)
        below = f" below {line} MB available" if line is not None else ""
        reasons.append(f"{why.pop('memory short')} when memory ran short{below}")
    if why.get("allocation burst"):
        reasons.append(f"{why.pop('allocation burst')} at a burst of Python allocation")
    if why.get("memory guard engaged"):
        reasons.append(f"{why.pop('memory guard engaged')} when the memory guard engaged")
    if why.get("memory still short"):
        reasons.append(f"{why.pop('memory still short')} while memory stayed short")
    reasons += [f"{n} {label}" for label, n in why.items()]
    count = f"{len(snaps)} snapshot(s)"
    if isinstance(taken, int) and taken > len(snaps):
        count += f" of {taken} taken, the newest kept"
    out = [
        f"  - what every thread was doing, {count} ({'; '.join(reasons)}); every thread "
        "is in session-forensics.json:"
    ]
    before: dict[Any, float] = {}
    before_at: float | None = None
    for snap in snaps:
        mem = snap.get("memory") or {}
        bits = []
        if snap.get("avail_mb") is not None:
            bits.append(f"{snap['avail_mb']} MB available")
        if snap.get("rss_mb") is not None:
            bits.append(f"RSS {snap['rss_mb']} MB")
        if mem.get("swapped_out_mb") is not None:
            bits.append(f"swapped out {mem['swapped_out_mb']} MB")
        if mem.get("py_alloc_blocks") is not None:
            bits.append(f"{mem['py_alloc_blocks']:,} Python blocks")
        head = f"{snap.get('at')}, {snap.get('why') or 'memory short'}"
        guard = snap.get("guard")
        if isinstance(guard, dict) and guard.get("engaged"):
            head += f" (memory guard engaged since {guard.get('since') or 'an unknown time'})"
        if isinstance(snap.get("blocks_gained"), int):
            head += f" (+{snap['blocks_gained']:,} Python blocks in {snap.get('over_s')} s)"
        out.append(f"    - {head}: {', '.join(bits) or 'no reading'}")
        now_at = _snap_seconds(snap.get("at"))
        span = (
            round(now_at - before_at)
            if now_at is not None and before_at is not None and now_at >= before_at
            else None
        )
        threads = [t for t in snap.get("threads") or [] if isinstance(t, dict)]
        working = []
        for t in threads:
            if t.get("sampler") or t.get("waiting"):
                continue
            cpu = t.get("cpu_s")
            recent = None
            if isinstance(cpu, int | float):
                prior = before.get(t.get("tid")) if span is not None else None
                recent = round(cpu - prior, 1) if prior is not None else cpu
            working.append((recent, t))
        working.sort(key=lambda rt: -(rt[0] or 0.0))
        for recent, t in working[:_PRESSURE_THREADS_SHOWN]:
            cpu_bits = []
            if t.get("cpu_s") is not None:
                cpu_bits.append(f"cpu {t['cpu_s']} s")
                if span is not None and recent is not None and t.get("tid") in before:
                    cpu_bits.append(f"+{recent} s in the {span} s before")
            cpu = f" ({', '.join(cpu_bits)})" if cpu_bits else ""
            out.append(f"      - {t.get('name')}{cpu}: {' <- '.join(t.get('stack') or [])}")
        rest = len(threads) - min(len(working), _PRESSURE_THREADS_SHOWN)
        if rest > 0:
            out.append(f"      - {rest} more thread(s) waiting or not listed")
        before = {
            t.get("tid"): float(t["cpu_s"])
            for t in threads
            if t.get("tid") is not None and isinstance(t.get("cpu_s"), int | float)
        }
        before_at = now_at
    return out


def _render_exit_evidence(ev: Any) -> list[str]:
    """The witnesses outside the process, each on its own line and each absence named."""
    if not isinstance(ev, dict) or not ev:
        return []
    out = ["- witnesses outside the process:"]
    if ev.get("unavailable"):
        out.append(f"  - unavailable: {ev['unavailable']}")
    launcher = ev.get("launcher")
    if isinstance(launcher, dict) and launcher.get("kind") == "unreadable":
        out.append(f"  - launcher: record file unreadable — {launcher.get('unparsed_lines')} lines, none a row; this is not a record that nothing was seen")
    elif isinstance(launcher, dict):
        how = launcher.get("signal") or f"exit status {launcher.get('status')}"
        out.append(f"  - launcher: {how} at {launcher.get('at')} — {launcher.get('meaning')}")
    elif "launcher" in ev:
        out.append(
            "  - launcher: no record (started another way, by an older launcher, or "
            "stopped from the launcher's own window)"
        )
    killers = ev.get("userspace_killers")
    if isinstance(killers, dict):
        out.append(f"  - memory killers' journal: {killers.get('verdict', 'unknown')}")
        if killers.get("reason"):
            out.append(f"    - {killers['reason']}")
        if killers.get("cgroup_note"):
            out.append(f"    - {killers['cgroup_note']}")
        for ln in (killers.get("lines") or [])[:6]:
            out.append(f"    - journal: {ln}")
    running = ev.get("running_killers")
    if isinstance(running, dict):
        if running.get("known"):
            active = ", ".join(running.get("active") or []) or "none"
            out.append(f"  - memory killers running on this machine now: {active}")
        else:
            out.append(f"  - memory killers running now: unknown ({running.get('reason')})")
    trace = ev.get("crash_trace")
    if isinstance(trace, dict):
        out.append(
            f"  - crash trace: {trace.get('summary')} "
            f"({trace.get('lines_total')} lines in {trace.get('source')})"
        )
        for ln in (trace.get("lines") or [])[1:13]:
            out.append(f"    | {ln}")
    elif "crash_trace" in ev:
        out.append(
            "  - crash trace: none for that session (no native fault or uncaught exception "
            "was recorded; a SIGKILL leaves none)"
        )
    return out


def _render_earlier_ends(ev: Any) -> list[str]:
    """The earlier unclean ends and their traces, in words (finding D). Each session says what
    it ended by and either shows the head of its trace or why there is none."""
    if not isinstance(ev, dict):
        return []
    if ev.get("available") is False:
        return [f"- earlier unclean ends: unavailable ({ev.get('reason', 'no reason recorded')})"]
    out = [
        f"- earlier unclean ends in the session ledger: {ev.get('unclean_ends_in_ledger', 0)} "
        f"(newest {ev.get('shown', 0)} listed"
        + (f", {ev['older_not_shown']} older not listed" if ev.get("older_not_shown") else "") + ")"
    ]
    for row in ev.get("sessions") or []:
        sig = row.get("signal") or (
            f"exit status {row['status']}" if row.get("status") is not None else "no signal recorded"
        )
        out.append(f"  - pid {row.get('pid')}, started {row.get('started_at')}, ended {row.get('ended_at')}: {sig}")
        trace = row.get("trace")
        if isinstance(trace, dict):
            out.append(f"    trace: {trace.get('summary')} ({trace.get('lines_total')} lines)")
            for ln in (trace.get("lines") or [])[1 : 1 + _EARLIER_TRACE_LINES_PRINTED]:
                out.append(f"    | {ln}")
        elif row.get("why_no_trace"):
            out.append(f"    no trace: {row['why_no_trace']}")
    return out


def _whole_seconds_between(begin: Any, end: Any) -> int | None:
    """Whole seconds from one ISO timestamp to another, or ``None`` when either is missing, unparseable or the order is reversed
    (a clock set back mid-teardown is not a negative duration)."""
    try:
        seconds = (datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(begin))).total_seconds()
    except (TypeError, ValueError):
        return None
    return int(seconds) if seconds >= 0 else None


def _render_log_left(prev: dict[str, Any]) -> list[str]:
    """The line that keeps a ``clean`` end from reading as a clean log: ``clean`` says the teardown ran to its last step, not that the
    ``-wal`` was written back into the database, and the next open may pay that write-back. Said whenever the disposal left a log (its size,
    what the pool held, what the write-back before it did), and also when it left none or could not be read; silent only for a session
    that did not record the value (a build before this one)."""
    d = prev.get("dispose")
    if not isinstance(d, dict) or "wal" not in d:
        return []
    left, held, step = d.get("wal"), d.get("out"), d.get("step")
    held_text = (
        f"{held} connection(s) still checked out when the pool was disposed"
        if isinstance(held, int)
        else f"checked-out connections not counted ({DISPOSE_OUT_WORDS.get(str(held), 'no reason recorded')})"
    )
    wrote_text = (
        f"the write-back before it: {DISPOSE_STEP_WORDS.get(step, step)}" if step else "no write-back recorded (no reason recorded)"
    )
    if isinstance(left, int) and left > 0:
        lines = [
            f"- the -wal was LEFT by that session's end: {left:,} bytes were still on disk after the pool was disposed ({held_text}; {wrote_text})"
        ]
        if prev.get("previous_session") == "clean":
            lines.append(
                "  - 'clean' above means the teardown ran to its end, not that this log was written back; the -wal at the next boot "
                "(wal_at_boot) says what that open found"
            )
        return lines
    if left == 0:
        return [f"- the -wal was empty after that session's pool was disposed ({held_text}; {wrote_text})"]
    return [
        f"- the -wal after that session's disposal was not measured ({DISPOSE_WAL_WORDS.get(str(left), 'no reason recorded')}; {held_text}; {wrote_text})"
    ]


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
    if isinstance(prev.get("dispose"), dict):
        took = prev["dispose"].get("took")
        lines.append(
            f"- the teardown took {took} s from its first step to the end"
            if isinstance(took, int)
            else "- the teardown's duration was not readable (its first step or its end was not recorded)"
        )
    lines += _render_log_left(prev)
    if prev.get("last_rss_mb") is not None:
        lines.append(f"- collector's last RSS sample: {prev['last_rss_mb']} MB")
    wal_boot = prev.get("wal_at_boot") or {}
    if wal_boot.get("state"):
        nbytes = wal_boot.get("bytes")
        size = f"{int(nbytes):,} bytes" if isinstance(nbytes, int) else "size unmeasured"
        lines.append(f"- -wal at this boot: {wal_boot['state']} ({size})")
        if wal_boot.get("reason"):
            lines.append(f"  - {wal_boot['reason']}")
    how = prev.get("how_it_ended") or {}
    if how.get("summary"):
        lines.append(f"- how it ended: {how['summary']}")
    dip = how.get("died_into_phase")
    if isinstance(dip, dict):
        secs = dip.get("seconds_in_peaks_phase")
        which = (prev.get("previous_session_peaks") or {}).get("phase") or "unknown"
        lines.append(
            f"  - the last phase seen (previous_session_peaks.phase: {which}): "
            + (f"{secs} s from its start to the last record" if secs is not None else f"duration unmeasured ({DIED_REASON_WORDS.get(str(dip.get('reason')), dip.get('reason'))})")
        )
    cen = (prev.get("previous_session_peaks") or {}).get("last_thread_census")
    if isinstance(cen, dict):
        if cen.get("unavailable"):
            lines.append(f"  - native thread census: unavailable ({cen['unavailable']})")
        else:
            made = ", ".join(f"{k} x{v}" for k, v in (cen.get("non_python") or {}).items()) or "none"
            lines.append(
                f"  - native threads at the LAST census (a lower bound in time: a pool started after it is not here): "
                f"{cen.get('os_threads')} OS threads, {cen.get('python_threads')} started by Python; not by Python: {made}"
                + (f" (+{cen['other_comms']} more names)" if cen.get("other_comms") else "")
            )
    kern = prev.get("kernel_evidence") or {}
    if kern:
        lines.append(f"- host kernel evidence: {kern.get('verdict', 'unknown')}")
        if kern.get("reason"):
            lines.append(f"  - {kern['reason']}")
        for note in ("storage_note", "permission_note"):
            if kern.get(note):
                lines.append(f"  - {kern[note]}")
        for why in kern.get("unread") or []:
            lines.append(f"  - not read: {why}")
        for ln in (kern.get("lines") or [])[:6]:
            lines.append(f"  - kernel: {ln}")
    lines += _render_exit_evidence(prev.get("exit_evidence"))
    lines += _render_earlier_ends(prev.get("earlier_unclean_ends"))
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
                    # A lifetime mark, so it says WHEN it was set: without a time it cannot be
                    # placed beside a burst or a snapshot. A record from a build that did not
                    # stamp it says so, rather than leaving the reader to assume "at the end".
                    at = peaks.get(key.removesuffix("_mb") + "_at")
                    when = f" at {at}" if at else " (time not recorded: a record from a build that did not stamp it)"
                    lines.append(f"  - {label}: {peaks[key]} {unit}{when}")
            low = _lowest_kept_snapshot(peaks.get("pressure"))
            if low is not None:
                lines.append(
                    f"  - lowest available memory inside the kept snapshots below: {low[0]} MB "
                    f"at {low[1]} (the snapshots are a sample of the session; the minimum above "
                    "was set by a reading that may not be among them)"
                )
            if peaks.get("phase"):
                lines.append(f"  - last phase seen: {peaks['phase']}")
            if peaks.get("last_ts"):
                lines.append(f"  - last recorded at: {peaks['last_ts']}")
            lines += _render_allocator(peaks.get("allocator"))
            lines += _render_memory_budget(peaks.get("memory_budget"))
            lines += _render_at_peak(peaks.get("at_peak"), peaks.get("heap_at_peak"))
            lines += _render_pressure(peaks.get("pressure"), peaks.get("pressure_taken"))
            lines += _render_light(peaks.get("pressure_light"), peaks.get("pressure_light_taken"))
    sample = prev.get("last_collector_sample") or {}
    if sample:
        rss = sample.get("rss_mb")
        if isinstance(rss, dict):  # an export written before the summary-line fix
            rss = rss.get("last")
        avail = sample.get("mem_avail_mb")
        lines.append(
            "- last collect_perf line (see attribution): "
            f"rss {f'{rss} MB' if rss is not None else 'not recorded'}, "
            f"available {f'{avail} MB' if avail is not None else 'not recorded'}, "
            f"at {sample.get('ts')}"
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
    # C2: this export said "none found" and then listed two 25.8 GB pre-restore-*.db
    # files it had quietly folded into other_bytes -- 51.6 GB of an 80.8 GB folder with
    # no account of where it went. They are retained ON PURPOSE, so they are named as
    # such rather than as orphans, but they are never silent again.
    snaps = inv.get("pre_restore_snapshots") or []
    if snaps:
        lines.append(
            f"- pre-restore safety-net snapshots: {len(snaps)}, "
            f"{_mb(tot.get('pre_restore_snapshot_bytes'))} — RETAINED ON PURPOSE, "
            "not orphaned (see the retention policy below)."
        )
        for e in snaps[:10]:
            lines.append(f"    {e.get('name')} — {_mb(e.get('bytes'))} (taken {e.get('taken_at')})")
        if inv.get("pre_restore_policy"):
            lines.append(f"    policy: {inv['pre_restore_policy']}")
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

        # The payload's own copy when it has one, so the text is a rendering of the JSON and nothing
        # else: every fact the plain-text file holds is in `session_forensics()["expedition"]`.
        lines.append(expedition.render_text(d.get("expedition") if isinstance(d.get("expedition"), dict) else None))
    except Exception as exc:  # noqa: BLE001 - the forensics file must survive a broken sidecar
        log_failure(_LOG, "session forensics: expedition log unavailable", exc, level=logging.DEBUG)
        lines.append("The expedition log could not be read for this report.")

    return "\n".join(lines)


def _expedition_digest() -> dict[str, Any]:
    """The expedition log's digest (a plain file read, O(1) in corpus size), or a stated absence. An
    exception's TEXT is not recorded: the type is enough to say what failed, and a report that is
    shared must not carry text a lower layer composed."""
    try:
        from src.monitoring import expedition

        return expedition.digest()
    except Exception as exc:  # noqa: BLE001 - the forensics block must survive a broken sidecar
        return {"available": False, "reason": f"the expedition log could not be read ({type(exc).__name__})"}


def session_forensics() -> dict[str, Any]:
    """The one-call diagnostic block: inventory + previous-session verdict + the last unlock
    timing + the complete storage footprint + the data-dir persistence assessment. Rides the
    debug bundle / the all-diagnostics zip."""
    cur = _read_state() or {}
    return {
        # The unattended-run log: the one part of the plain-text rendering that was not already in this
        # payload (R119: the stand-alone text file goes, so what it held must be here).
        "expedition": _expedition_digest(),
        "inventory": data_dir_inventory(),
        "storage_footprint": storage_footprint(),
        "data_dir_persistence": data_dir_persistence(),
        "previous_session": previous_session_report(),
        "last_unlock": cur.get("last_unlock"),
        # The speed of this machine's last large-log recovery: the estimate the next unlock page
        # shows is built from it, so a report that explains a slow unlock carries it too.
        "last_recovery": cur.get("last_recovery"),
        # The per-step time of this machine's last cold init_db (STORE-02): which of its 37 steps the
        # time went on, beside the one number the unlock record keeps for the whole call.
        "last_init_db": cur.get("last_init_db"),
        # Where a pass got to in its tail (S0.5) — the window the field's S2 session
        # died in, from which nothing survived because record_run sits below it.
        "pass_tail_journal": pass_tail_journal(),
    }
