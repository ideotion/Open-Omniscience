"""Is the data folder the app's own, or a folder it shares with other files? (R711)

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The emergency erase ends by removing the whole data folder, and the secure uninstall does the same. That is right
for the folder the first-launch step creates (it always ends in ``OOS data``), and wrong for a folder an operator
pointed ``OO_DATA_DIR`` at by hand: their home folder, a drive root, a mount point, or any folder that holds no
trace of the app. There the erase must still destroy everything the app owns, and must not touch the rest.

So this module answers two questions, both by NAME only (nothing is opened or read):

* :func:`folder_scope` -- is this folder too broad to remove whole, and why (a ``reason`` code the UI translates).
* :func:`is_app_owned` -- is this top-level entry one the app writes (a known file or folder name, a sidecar of an
  app database, a staging or copy pattern).

The name list is long because the app writes many small files at the top of its folder. It is kept complete by
``tests/test_data_scope.py``, which reads every ``data_dir() / "name"`` in ``src`` and fails on a name this module
does not know. A name built at run time that the test cannot read is the stated limit; the erase reports every
top-level entry it left, by name, so one of ours left behind is visible rather than silent.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Top-level FILES the app writes into its data folder.
APP_FILES: frozenset[str] = frozenset({
    "open_omniscience.db", "custody_log.db", "anchors.db",
    "analytics.duckdb", "analytics.duckdb.kdf", "analytics.duckdb.wal", ".oo_columnar_probe.duckdb",
    "activity_ledger.jsonl", "app_errors.jsonl", "app_settings.json", "archive_backfill.json",
    "article-indexes-attempt.json", "backup-temp-dests.json", "bench-anchors.json", "bench_progress_state.json",
    "briefing_cache.json", "briefing_dismiss_reasons.json", "briefing_dismissed.json", "briefing_draft.json",
    "collect_capacity.json", "collect_perf.jsonl", "criteria_calibration_cursor.json", "custody_pending.jsonl",
    "custody_pending.unreadable", "custody_settings.json", "database-damage.json", "database-repair-attempt.json",
    "expedition.json", "feed_preflight.jsonl", "field_test.jsonl", "frozen-batch.json", "hazards_snapshot.json",
    "host_schedule.json", "import_queue.json", "import_results.jsonl", "incremental_vacuum.json",
    "integrity_collapse.json", "keyword-coverage.json", "keyword_cleanup.json", "keyword_filter.json",
    "keyword_fold_job.json", "keyword_fold_report.json", "keyword_rings_local.yml", "langdetect_state.json",
    "legal_consent.json", "memory_stop.json", "narration_progress_state.json", "native_inflight.bin",
    "newsletter_import.json", "oo-export-request.json", "oo-folder-backup.json", "pass_journal.jsonl",
    "perception_extract_progress_state.json", "quarantine_job.json", "reindex_backlog.json", "reindex_job.json",
    "robots_cache.json", "rollup_build.json", "rollup_stopped.json", "runs.jsonl", "safety_settings.json",
    "scheduler_runs.jsonl", "scheduler_settings.json", "search_reindex_job.json", "search_reindex_report.json",
    "search_timing.jsonl", "search_timing_browse.jsonl", "session_history.jsonl", "session_hwm.json",
    "session_liveness.json", "session_pressure.json", "session_pressure_light.json", "session_state.json",
    "source_enrich.json", "source_preflight.jsonl", "source_tags_progress_state.json", "stoplist_recompute.json",
    "storage_events.json", "translation-sweep-coverage.json", "triage_progress_state.json", "update-plan.json",
    "update-result.json", "update.lock", "vitals_history.json", "vllm_start_attempts.jsonl", "volumes.json",
    "volumes.building.json", "volumes-readme.json", "weather_signals.json", "world_discovery.json",
})

#: Top-level FOLDERS the app writes into its data folder.
APP_DIRS: frozenset[str] = frozenset({
    "annotations", "bench", "bulletin", "cache", "diagnostics", "duckdb_tmp", "import_reports", "ip_geo", "keys",
    "leases", "models", "osm_borders", "osm_regions", "osm_work", "rings", "run_logs", "runtime", "triage",
    "vllm_failed_starts", "vllm_venv", "weather_context", "wiki_dumps",
})

#: Databases whose ``-wal``, ``-shm`` and ``-journal`` are the app's too (the lane files are added at run time).
_DB_NAMES = ("open_omniscience.db", "custody_log.db", "anchors.db")

#: Name shapes the app gives its copies and staging: a retained pre-restore snapshot, a pre-encryption copy, a repair's
#: salvage and damaged copies, a backup or restore staging folder, a reassembling archive part, a free-space scrub file.
_PREFIXES = ("pre-restore-", "pre-encrypt-", ".bak-build-", ".restore-", ".oo-vllm-pip-build", ".oo-backup-", ".oo_scrub_",
             "oo-osm-reference-run-")
_INFIXES = (".salvage-", ".damaged-")
_SUFFIXES = (".oopart",)


def _lane_names() -> tuple[str, ...]:
    try:
        from src.versioned.lanes import all_lanes

        return tuple(spec.filename for spec in all_lanes())
    except Exception:  # noqa: BLE001 - the registry is read by name; a failed import must not make the scope unknowable
        return ("wiki.db", "law.db", "osm.db")


def owned_spec(lanes: tuple[str, ...] | None = None) -> dict:
    """Every rule :func:`is_app_owned` applies, as plain lists: the exact ``names``, the ``prefixes`` and the ``suffixes``. The
    uninstall watcher (stdlib only, the app gone) is handed this, so both erasers apply ONE definition."""
    dbs = (*_DB_NAMES, *(lanes if lanes is not None else _lane_names()))
    names = APP_FILES | APP_DIRS | set(dbs) | {db + s for db in dbs for s in ("-wal", "-shm", "-journal")}
    prefixes = [*_PREFIXES]
    for db in dbs:
        stem = db.rsplit(".", 1)[0]
        # a repair's salvage and damaged copies (src/database/repair.py) and an encryption's in-progress copy (encrypt_tool.py)
        prefixes += [stem + i for i in _INFIXES] + [db + ".enc-"]
    return {"names": sorted(names), "prefixes": prefixes, "suffixes": list(_SUFFIXES)}


def is_app_owned(name: str, *, lanes: tuple[str, ...] | None = None, spec: dict | None = None) -> bool:
    """Whether a top-level entry called ``name`` is one the app writes. By name only: nothing is opened."""
    spec = spec if spec is not None else owned_spec(lanes)
    return name in spec["names"] or name.startswith(tuple(spec["prefixes"])) or name.endswith(tuple(spec["suffixes"]))


#: The folders of a home folder that hold a person's own files, on Linux, macOS and Windows.
_HOME_FOLDERS = ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos", "Movies", "Public", "OneDrive")

#: The markers whose presence says the app has used this folder.
_MARKERS = ("open_omniscience.db", "custody_log.db", "anchors.db", "keys", "legal_consent.json", "app_settings.json",
            "session_state.json", "session_history.jsonl")


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def folder_scope(base: Path) -> dict:
    """``{"broad": bool, "reason": code | None, "other_entries": int}`` for the data folder ``base``.

    Broad when it is the home folder, a folder above it or one of its standard folders (Documents, Desktop...), the
    root of a drive, a mount point, or a folder with entries the app does not own and none of the app's markers. Never
    raises: a check that cannot be made is skipped, and a folder that cannot be listed counts as holding others."""
    base = Path(base)
    reason: str | None = None
    try:
        absolute = Path(os.path.abspath(base))
        if absolute == Path(absolute.anchor):
            reason = "drive_root"
    except (OSError, ValueError):
        pass
    try:
        home = Path.home()
    except (RuntimeError, OSError):
        home = None
    if reason is None and home is not None:
        if _same(base, home):
            reason = "home"
        elif any(_same(base, p) for p in home.parents):
            reason = "above_home"
        elif any(_same(base, home / d) for d in _HOME_FOLDERS):
            reason = "home_folder"
    if reason is None:
        try:
            if os.path.ismount(base):
                reason = "mount_point"
        except (OSError, ValueError):
            pass
    lanes = _lane_names()
    spec = owned_spec(lanes)
    others = 0
    marked = False
    try:
        names = [e.name for e in os.scandir(base)]  # ``list`` ends the scan, which closes it
    except FileNotFoundError:
        names = []
    except OSError:
        names, others = [], 1
    for name in names:
        if name in _MARKERS or name in lanes:
            marked = True
        if not is_app_owned(name, spec=spec):
            others += 1
    if reason is None and others and not marked:
        reason = "not_app_folder"
    return {"broad": reason is not None, "reason": reason, "other_entries": others}


#: The startup warning, in English for the log and the terminal; the UI writes it from ``reason`` in its own language.
REASON_TEXT = {
    "home": "your home folder",
    "above_home": "a folder that contains your home folder",
    "home_folder": "one of your own folders (such as Documents or Desktop)",
    "drive_root": "the root of a drive",
    "mount_point": "the top of a mounted drive",
    "not_app_folder": "a folder that holds other files and no sign of this app",
}


def startup_warning(base: Path) -> str | None:
    """The sentence logged and printed at start when the data folder is broad, else None."""
    scope = folder_scope(base)
    if not scope["broad"]:
        return None
    return (
        f"The data folder ({base}) is {REASON_TEXT.get(scope['reason'], 'not a folder of its own')}. "
        "The app keeps working, but an emergency wipe or a secure uninstall will remove only the app's own files there "
        "and leave everything else, so the folder itself is not removed. Point OO_DATA_DIR at a folder of its own "
        "(for example a new 'OOS data' folder inside it) to keep the app's data apart."
    )
