"""Is the data folder the app's own, or a folder it shares with other files? (R711)

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The emergency erase ends by removing the whole data folder, and the secure uninstall does the same. That is right for a
folder the app chose itself: the default location, or the ``OOS data`` folder the first-launch step creates. It is wrong for
a folder an operator pointed ``OO_DATA_DIR`` at by hand that holds their own files too: their home folder, a drive root, a
mount point, a projects folder. There the erase must still destroy everything the app owns, and must not touch the rest.

So this module answers, by NAME only (nothing is opened or read):

* :func:`folder_scope` -- is this folder shared, and why (a ``reason`` code the UI translates). OWNERSHIP IS DECIDED BY WHERE
  THE APP PUT THE FOLDER, never by the app's own files in it: the app writes ``session_state.json`` at every start, so "holds
  a file of ours" is true of any folder the app has ever started in and protected nothing (the security read's finding).
* :func:`is_app_owned` -- is this top-level entry one the app writes (a known name, a database's side file, a copy or
  staging pattern, an atomic-write temp or a lock beside one of those).
* :func:`owned_spec` -- the same rules as plain lists for the uninstall watcher, which cannot import the app. In a shared
  folder it leaves out the app's COMMON names (``models``, ``cache``, ``keys``...): an operator's own folder can carry one of
  them, so an erase there leaves it and names it rather than destroy what may be theirs.

The name list is kept complete by ``tests/test_data_scope.py``, which reads every name the code joins onto ``data_dir()``
(directly, through a module constant, or through a helper that takes the name) and fails on one this module does not know.
"""

from __future__ import annotations

import os
import re
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
    "calendar_autoimport.json", "calendar_feed_attempts.json", "calendar_feed_checks.json", "calendar_feed_imports.json",
    "calendar_feeds.yml", ".oos-volume",
})

#: Top-level FOLDERS the app writes into its data folder.
APP_DIRS: frozenset[str] = frozenset({
    "annotations", "bench", "bulletin", "cache", "diagnostics", "duckdb_tmp", "import_reports", "ip_geo", "keys",
    "leases", "models", "osm_borders", "osm_regions", "osm_work", "rings", "run_logs", "runtime", "triage",
    "vllm_failed_starts", "vllm_venv", "weather_context", "wiki_dumps", ".oo_scrub",
})

#: The app's names an operator's own entry can also carry. In a SHARED folder these are left and named in the report, never
#: destroyed: the erase cannot tell the app's ``models`` folder from the operator's. (In a folder of the app's own, they go.)
#: Only names whose app contents are re-downloadable or carry nothing about the corpus (model weights, compute caches,
#: process leases, the runtime folder): the app's ``annotations`` (the operator's notes), ``triage`` (AI-run logs about corpus
#: items), ``bench``, ``bulletin`` and ``diagnostics`` hold what the erase exists to destroy, so they always go; ``keys`` keeps
#: the operator's files but loses every key of the app's (crypto_erase.py).
COMMON_NAMES: frozenset[str] = frozenset({"cache", "keys", "leases", "models", "runtime"})

#: Endings the app adds to one of its names: an atomic write's temp (``<name>.tmp`` and ``file_lock.temp_name``'s
#: ``<name>.tmp.<pid>.<thread>``), a lock sidecar (``file_lock._SIDECAR``), a damaged or partial copy. Stripped before the
#: name is looked up, so ``app_settings.json.tmp`` is the app's because ``app_settings.json`` is.
STRIP_RE = r"(?:\.tmp(?:\.\d+\.\d+)?|\.lock|\.damaged|\.part|\.partial|\.unreadable)+$"

#: Databases whose ``-wal``, ``-shm`` and ``-journal`` are the app's too (the lane files are added at run time).
_DB_NAMES = ("open_omniscience.db", "custody_log.db", "anchors.db")

#: Name shapes the app gives its copies and staging: a retained pre-restore snapshot, a pre-encryption copy, a repair's
#: salvage and damaged copies, a backup or restore staging folder, a reassembling archive part, a free-space scrub file.
_PREFIXES = ("pre-restore-", "pre-encrypt-", ".bak-build-", ".restore-", ".oo-vllm-pip-build", ".oo-backup-", ".oo_scrub_", ".merge-probe-",
             "oo-osm-reference-run-")
_INFIXES = (".salvage-", ".damaged-")
_SUFFIXES = (".oopart", ".reassembling")


def _lane_names() -> tuple[str, ...]:
    try:
        from src.versioned.lanes import all_lanes

        return tuple(spec.filename for spec in all_lanes())
    except Exception:  # noqa: BLE001 - the registry is read by name; a failed import must not make the scope unknowable
        return ("wiki.db", "law.db", "osm.db")


def owned_spec(lanes: tuple[str, ...] | None = None, *, shared: bool = False) -> dict:
    """Every rule :func:`is_app_owned` applies, as plain lists: the exact ``names``, the ``prefixes``, the ``suffixes`` and the
    ``strip`` pattern. With ``shared`` (a folder the app does not own) the :data:`COMMON_NAMES` are left out. The uninstall
    watcher (stdlib only, the app gone) is handed this, so both erasers apply ONE definition."""
    dbs = (*_DB_NAMES, *(lanes if lanes is not None else _lane_names()))
    names = APP_FILES | APP_DIRS | set(dbs) | {db + s for db in dbs for s in ("-wal", "-shm", "-journal")}
    if shared:
        names = names - COMMON_NAMES
    prefixes = [*_PREFIXES]
    for db in dbs:
        stem = db.rsplit(".", 1)[0]
        # a repair's salvage and damaged copies (src/database/repair.py) and an encryption's in-progress copy (encrypt_tool.py)
        prefixes += [stem + i for i in _INFIXES] + [db + ".enc-"]
    return {"names": sorted(names), "prefixes": prefixes, "suffixes": list(_SUFFIXES), "strip": STRIP_RE}


def is_app_owned(name: str, *, lanes: tuple[str, ...] | None = None, spec: dict | None = None, shared: bool = False) -> bool:
    """Whether a top-level entry called ``name`` is one the app writes. By name only: nothing is opened."""
    spec = spec if spec is not None else owned_spec(lanes, shared=shared)
    names, prefixes, suffixes = spec["names"], tuple(spec["prefixes"]), tuple(spec["suffixes"])
    for candidate in dict.fromkeys((name, re.sub(spec["strip"], "", name))):
        if candidate and (candidate in names or candidate.startswith(prefixes) or candidate.endswith(suffixes)):
            return True
    return False


#: The folders of a home folder that hold a person's own files, on Linux, macOS and Windows.
_HOME_FOLDERS = ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos", "Movies", "Public", "OneDrive")

#: What an operating system or a file manager leaves in any folder; never a sign that the folder holds a person's files.
_OS_CLUTTER = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", "lost+found", ".directory", ".localized"})


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def chosen_by_app(base: Path) -> bool:
    """Whether the app chose this folder itself: the first-launch step's ``OOS data`` folder, or the default location (no
    ``OO_DATA_DIR``), which is a folder of the app's own name."""
    from src.safety.data_location import DATA_SUBDIR

    try:
        name = Path(os.path.realpath(base)).name  # a link called "OOS data" says nothing about the folder it leads to
    except (OSError, ValueError):
        return False
    if name == DATA_SUBDIR:
        return True
    if os.getenv("OO_DATA_DIR"):
        return False
    try:
        from src.paths import data_dir

        return _same(base, data_dir())
    except Exception:  # noqa: BLE001 - an unanswerable question is answered "not chosen": the erase then keeps to the app's names
        return False


def _first_other(base: Path) -> bool | None:
    """Whether ``base`` holds an entry the app does not own (stopping at the first: a home folder may hold a million), None
    when it cannot be listed. A COMMON name (``models``, ``cache``...) counts as not the app's here too: a folder holding an
    operator's own ``models`` beside the app's files must never be removed whole."""
    spec = owned_spec(shared=True)
    try:
        it = os.scandir(base)
    except FileNotFoundError:
        return False
    except OSError:
        return None
    return _scan_for_other(it, spec)


def _scan_for_other(it, spec: dict) -> bool | None:
    try:
        with it:
            for entry in it:
                if entry.name in _OS_CLUTTER or is_app_owned(entry.name, spec=spec):
                    continue
                return True
    except OSError:
        return None
    return False


def folder_scope(base: Path) -> dict:
    """``{"broad": bool, "reason": code | None}`` for the data folder ``base``, read on the folder the path leads to (a link to
    a drive root is a drive root).

    Broad when it is the root of a drive, the home folder, a folder above it or one of its standard folders (Documents,
    Desktop...), a mount point, or, unless the app chose it (:func:`chosen_by_app`), a folder holding any entry the app does
    not own. A folder that cannot be listed is broad. Never raises."""
    try:
        real = Path(os.path.realpath(base))
    except (OSError, ValueError):
        real = Path(base)
    reason: str | None = None
    try:
        if real == Path(real.anchor):
            reason = "drive_root"
    except (OSError, ValueError):
        pass
    try:
        home = Path.home()
    except (RuntimeError, OSError):
        home = None
    if reason is None and home is not None:
        if _same(real, home):
            reason = "home"
        elif any(_same(real, p) for p in home.parents):
            reason = "above_home"
        elif any(_same(real, home / d) for d in _HOME_FOLDERS):
            reason = "home_folder"
    if reason is None:
        try:
            if os.path.ismount(real):
                reason = "mount_point"
        except (OSError, ValueError):
            pass
    if reason is None and not chosen_by_app(base):
        other = _first_other(real)
        if other is None:
            reason = "unlistable"
        elif other:
            reason = "shared_folder"
    return {"broad": reason is not None, "reason": reason}


#: The startup warning, in English for the log and the terminal; the UI writes it from ``reason`` in its own language.
REASON_TEXT = {
    "home": "your home folder",
    "above_home": "a folder that contains your home folder",
    "home_folder": "one of your own folders (such as Documents or Desktop)",
    "drive_root": "the root of a drive",
    "mount_point": "the top of a mounted drive",
    "shared_folder": "a folder that also holds files this app did not write",
    "unlistable": "a folder the app cannot list",
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
