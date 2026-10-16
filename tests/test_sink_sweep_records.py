"""A record the scheduler or the wiki lane keeps, serves or hands to the diagnostics bundle names the failure's CLASS and nothing
else; the words go to the ``log_failure`` line every handler already has.

The log guard (``test_no_raw_exc_info``) reads log calls. This is the stored half: it reuses the strict AST reading of
``tests/test_runs_log_sinks.py::_leaks`` (a handler's bound exception may only reach ``type()``, ``isinstance()`` or ``log_failure``
as its third argument) over the whole of ``src/scheduler``, ``src/wiki`` and the unlock module, so ``f"{exc}"``, ``repr``,
``.format``, a dict value, ``.append`` and ``exception_text`` in a record all fail. The few lines that tell the person who just
asked the failure's words (a response that is not stored) are the table below, counted like ``_BUNDLE_ALLOWED``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.test_runs_log_sinks import _enclosing_function, _leaks

ROOT = Path(__file__).resolve().parents[1]
#: The calls that may be handed a caught exception: the class, and the scrubbing line. ``note_error``/``log_failure_once`` are the
#: storage guard's own entry points (they log through ``log_failure`` and keep a per-path dedupe key in memory only);
#: ``refusal_text``/``is_damaged`` are the settings store's class-only refusal and its damaged-value test; ``refusal_token``/
#: ``refusal_detail``/``retry_after_of`` are the wiki walk's class (and HTTP status) classifiers, which never read the message;
#: ``is_corruption`` answers a bool from the driver's ``sqlite_errorcode`` (``damage.corruption_of`` keeps a fixed label, never the text).
CALLS = {"type", "isinstance", "log_failure", "note_error", "log_failure_once", "refusal_text", "is_damaged", "refusal_token", "refusal_detail", "retry_after_of",
         "record_text", "record_traceback", "unicode_note", "is_driver_error","quotes_a_driver","is_locked_error","_is_integrity_error", "restore_failure_text", "http_detail", "is_driver_text", "_all_diag_err_str", "_err_str", "_record_text", "_restore_error", "bounded_error", "engine_text", "is_pool_timeout", "is_corruption"}
MODULES = sorted(
    p.relative_to(ROOT).as_posix()
    for entry in ("src/scheduler", "src/wiki")
    for p in (ROOT / entry).rglob("*.py")
) + sorted(
    p.relative_to(ROOT).as_posix() for entry in ("src/backup", "src/ingest", "src/database") for p in (ROOT / entry).rglob("*.py")
) + sorted(
    p.relative_to(ROOT).as_posix() for p in (ROOT / "src/monitoring").rglob("*.py") if p.name != "secret_scrub.py"
) + sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "src/api").rglob("*.py"))
#: Slice 5: every OTHER package of ``src/`` and the top-level modules (the sweep reads the whole program). ``static`` holds no Python; a module
#: added to any package is read from its first commit.
_SWEEP_DONE = {"scheduler", "wiki", "backup", "ingest", "database", "monitoring", "api", "static", "__pycache__"}
_S5_MODULES: set[str] = set()
MODULES += sorted(
    p.relative_to(ROOT).as_posix()
    for p in (ROOT / "src").rglob("*.py")
    if p.relative_to(ROOT / "src").parts[0] not in _SWEEP_DONE
)
_S5_MODULES.update(m for m in MODULES if m.split('/')[1] not in _SWEEP_DONE)

#: Pre-existing constructs the reading reports that are not records: a non-constant ``getattr`` name on a settings object, and the
#: storage guard's choice of ``_LOG.warning`` or ``_LOG.info`` for one summary line. Matched by exact message and COUNTED, so a
#: second one in the same file is reported.
NOT_RECORDS: dict[str, dict[str, int]] = {
    "src/ingest/__init__.py": {"the caught exception 'cause' is used outside a scrubbing call": 2},  # RobotsUnavailable's own ``cause`` word, not an exception
    "src/ingest/airplane.py": {"a ** mapping handed to a log call can carry exc_info": 1},  # the socks connect's own kwargs
    "src/ingest/batch.py": {"deriv.error is kept as a name, a log call the scan cannot read": 1},  # a precompute's error flag
    "src/ingest/fetch_release.py": {
        "getattr reaches name, a way round the scan of the log calls": 2,
        "a ** mapping handed to a log call can carry exc_info": 1,
    },  # the session-releasing proxy forwards attributes of the fetcher
    "src/ingest/seed_sources.py": {"getattr reaches field, a way round the scan of the log calls": 2},  # a model field name
    "src/scheduler/settings.py": {"getattr reaches key, a way round the scan of the log calls": 1},
    "src/scheduler/storage_guard.py": {"_LOG.warning is kept as a name, a log call the scan cannot read": 1,
                                       "_LOG.info is kept as a name, a log call the scan cannot read": 1},
    "src/wiki/lane_search.py": {"getattr reaches how, a way round the scan of the log calls": 1},
    "src/backup/runlog.py": {"getattr reaches attr, a way round the scan of the log calls": 1},
}

#: Functions that take a caught exception to CLASSIFY it (a bool, an enum, an int, a class name) or to build an in-memory dedupe
#: key, and return no record text. Allowed LINE BY LINE (function plus exact line text, counted), never by function name, so a new
#: line in one of them, or a same-named method elsewhere, is read like any other code. Each line was read in the code.
CLASSIFIED: dict[str, dict[tuple[str, str], int]] = {
    "src/ingest/email.py": {("_is_integrity_error", "for e in (exc, exc.__cause__, exc.__context__):"): 3},
    "src/scheduler/plan_cache.py": {
        ('PlanPreviewCache._label', 'if err is not None:'): 1,
        ('PlanPreviewCache._label', 'out["refresh_error"] = err'): 1,
    },
    "src/scheduler/storage_guard.py": {
        ('_text_head', 'return str(exc).split("\\n[SQL:", 1)[0]'): 1,
        ('is_disk_full', 'cur = exc'): 1,
        ('_dbapi_cause', 'cur = exc'): 1,
        ('is_io_error', 'cur = exc'): 1,
        ('_os_error_behind', 'cur = exc'): 1,
        ('_first_line_detail', 'if exc is None:'): 1,
        ('_first_line_detail', 'orig = _dbapi_cause(exc)'): 1,
        ('_first_line_detail', 'os_error = _os_error_behind(exc)'): 1,
        ('_first_line_detail', 'shown, text = exc, quoted'): 1,
        ('_first_line_detail', 'quoted = _text_head(exc).rpartition("Original exception was: ")[2]'): 1,
        ('_io_error_detail', 'return _first_line_detail(exc)'): 1,
        ('_disk_full_detail', 'return _first_line_detail(exc, quote_head=True)'): 1,
        ('StorageGuard.note_error', 'if is_disk_full(exc):'): 1,
        ('StorageGuard.note_error', 'return self.note_io_error(exc, where)'): 1,
        ('StorageGuard.note_error', 'self.note_disk_full(f"{where + \': \' if where else \'\'}{_disk_full_detail(exc)}")'): 1,
        ('StorageGuard.note_io_error', 'if not is_io_error(exc):'): 1,
        ('StorageGuard.note_io_error', '"detail": _io_error_detail(exc),'): 1,
        ('StorageGuard.log_failure_once', 'first = (str(exc).splitlines() or [""])[0][:80]'): 1,
    },
    "src/wiki/history.py": {
        ('retry_after_of', 'response = getattr(exc, "response", None)'): 1,
    },
    "src/wiki/walk.py": {
        ('_http_status', 'status = getattr(getattr(exc, "response", None), "status_code", None)'): 1,
        ('_is_json_error', 'return isinstance(exc, json.JSONDecodeError) or (hasattr(exc, "doc") and hasattr(exc, "pos"))'): 2,
        ('refusal_token', 'status = _http_status(exc)'): 1,
        ('refusal_token', 'if isinstance(exc, ValueError) and (not isinstance(exc, OSError) or _is_json_error(exc)):'): 1,
        ('refusal_token', 'raise exc'): 1,
        ('refusal_detail', 'status = _http_status(exc)'): 1,
    },
    # Backup: the restore classifier reads the real text to CLASSIFY (a missing table, a locked file) and WRITES ``shown``, which is the
    # class only for a database driver's exception (``record_text``); the lock probes read an attribute and no text.
    "src/backup/merge.py": {
        ("_file_is_locked", 'return getattr(exc, "winerror", None) in (32, 33)'): 1,
        ("_lock_holder_note", 'name = getattr(exc, "filename", None)'): 1,
        ("classify_restore_error", "msg = str(exc)"): 1,
        ("classify_restore_error", "if _file_is_locked(exc):"): 1,
        ("classify_restore_error", 'f"{_lock_holder_note(exc)} Waited {_SWAP_HANDLE_WAIT_S:.0f}s for it to be "'): 1,
        ("_retry_while_locked", "if not _file_is_locked(exc) or time.monotonic() >= deadline:"): 1,
        # BackupError is ``validate_sqlite_file``'s own error; its text is fixed words plus ``record_text`` (class only for a driver).
        ("prepare_staged_corpus", "raise MergeError(str(exc)) from None  # BackupError: validate_sqlite_file's own fixed words, no driver text"): 1,
        # A comparison with the one known engine message that means "no rows yet"; nothing is written.
        ("_incoming_group_rows", 'if str(exc).lower() != f"no such table: cnt.{table}":'): 1,
    },
    # ``PendingRulingError`` is the attribution module's own error: fixed words naming the missing ruling.
    "src/backup/export_summary.py": {("export_facts", "attribution, attribution_error = [], str(exc)"): 1},
    # ``_ExportRefused`` is this module's own refusal with fixed words (_NO_SPACE and the like); any other failure is its class.
    "src/backup/newsletter_export.py": {("drop_newsletters_encrypted", "reason = str(exc) if refused else type(exc).__name__"): 1},
    # ``refused`` is a RestoreRefused: its ``served_text`` is a fixed sentence the code wrote, naming the holder of a lock.
    "src/backup/volume_job.py": {("VolumeBackupManager._run_backup", 'self._state, self._error = "error", refused.served_text'): 1},
}

#: Operator-facing text that nothing stores: a dump lookup's HTTP
#: answer, a tracker error that only reaches ``log_failure``, a malformed-query refusal. The words are scrubbed (``exception_text``);
#: a record written from the same function is not in this table.
KEPT: dict[str, dict[tuple[str, str], int]] = {
    "src/wiki/dumpread.py": {
        ("find_page", 'return {"found": False, "reason": "block-unreadable", "error": exception_text(exc, typed=False),'): 1,
    },
    "src/wiki/lane_search.py": {
        ("_TrackerReader._run", "raise _TrackerUnavailable(exception_text(exc)) from None"): 1,
        ("search", 'return {**base, "total": None, "items": [], "error": "query_invalid", "detail": exception_text(exc, typed=False)}'): 1,
    },
    # Backup: an exception that is NOT a database driver's (a file system refusal, a journal that cannot be opened, a member that
    # fails to decrypt) keeps its scrubbed words, with every held secret passed (ruling 2026-10-13: other links keep their words).
    # The migration command's console: ``MigrationRefused`` is this module's own refusal (fixed sentences naming a path or a class),
    # printed to the terminal of the person who ran it and stored nowhere; scrubbed with what the process holds all the same.
    "src/backup/country_migration.py": {
        ("main", 'print(f"Stopped: {exception_text(exc, typed=False)}", file=sys.stderr)'): 1,
    },
    "src/backup/export_folder.py": {
        ("allocate_export_folder", 'raise ExportFolderError(f"Cannot use destination {base}: {exception_text(exc, typed=False)}") from None'): 1,
        ("allocate_export_folder", "first = exception_text(exc, typed=False)"): 1,
    },
    "src/backup/merge.py": {
        ("_restore_ring_members", 'out["refused"].append({"name": name, "reason": f"write failed: {exception_text(exc, typed=False)}"})'): 1,
        ("merge_side_files", 'refused.append(f"{name}: {exception_text(exc, typed=False)}")'): 1,
    },
    "src/backup/runlog.py": {
        ("RunLog._open", 'self._disable("milestones", exception_text(exc))'): 1,
        ("RunLog._open", 'self._disable("beats", exception_text(exc))'): 1,
        ("RunLog._write", 'self._disable("beats" if beat else "milestones", exception_text(exc))'): 1,
    },
    # The repair's own refusals (``Declined``, ``salvage.SalvageRefused``) are sentences the code wrote, never a driver's words; they keep
    # them in ``reason_text`` and the log line, scrubbed (``_words_of``: ``exception_text``, then put back into the refusal itself), and
    # tests/test_refusal_detail_source.py reads what each is made of.
    "src/database/repair.py": {("run", "text = _words_of(refusal)"): 2},
    "src/backup/stream_backup.py": {("verify_stream_backup", "reason = exception_text(exc, passphrase, typed=False)"): 1},
    "src/backup/volume_job.py": {
        ("VolumeBackupManager._verify_after_write", '"reason": f"the volume set could not be re-read: {exception_text(exc, typed=False)}",'): 1,
        ("VolumeBackupManager.start_backup", "reason = exception_text(exc, passphrase, typed=False)"): 1,
    },
}


#: ``src/database``: the damage lane's classifiers and walks (``damage.py``, ``verify.py``, ``salvage.py``: each reads a
#: caught exception to CLASSIFY it, and what it records is ``failure_label``/``failure_text``/``corruption_of``, a class and a fixed label,
#: never the engine's words), the retry/lock walks in ``write.py``, the connect helper that hands the driver's exception back to its
#: caller to chain as the cause of WrongPassphraseError, the statement-deadline translation in ``maintenance.py`` (its ``from exc`` keeps the driver error as the cause
#: because the damage and storage classifiers read it; every sink of a chain goes through ``log_failure``/``record_text``/
#: ``record_traceback``, which apply the per-link driver rule), and ``session.info`` dictionaries (not logs). Read line by line; counted.
_DATABASE_CLASSIFIED: dict[str, dict[tuple[str, str], int]] = {
    'src/database/connect.py': {
        ('_try_open_encrypted', 'last_error[:] = [exc]'): 1,
    },
    'src/database/damage.py': {
        ('driver_error', 'cur = exc'): 1,
        ('failure_label', 'code = exc.errno if isinstance(exc, OSError) else None'): 1,
        ('corruption_of', 'driver = driver_error(exc)'): 1,
        ('failure_text', 'driver = driver_error(exc) or exc'): 2,
        ('failure_text', 'found = corruption_of(exc)'): 1,
        ('is_corruption', 'return corruption_of(exc) is not None'): 1,
        ('poisons_connection', 'driver = driver_error(exc)'): 1,
        ('poisons_connection', 'and not str(exc)'): 1,
        ('note_raw_driver_error', 'registry.note(key, exc, statement=statement, path=path)'): 1,
        ('note_raw_driver_error', 'if poisons_connection(exc, _dbapi_of(handle)) is not None:'): 1,
        ('DamageRegistry.note', 'found = corruption_of(exc)'): 1,
        ('diagnostics_member', 'return {"error": failure_label(exc)}  # the class only: the member rides the bundle, and what an exception says can be an engine\'s words'): 1,
        ('guard_raw_driver', 'note_raw_driver_error(handle, exc, engine=engine, file_key=file_key, statement=statement)'): 1,
        ('DamageRegistry._flush', "error = failure_label(exc)  # the class and the errno name: a drive's message names the path, and the record rides the bundle"): 1,
        ('DamageRegistry._job_main', '_LOG.warning("database damage: the record could not be written (%s)", failure_label(exc))'): 1,
        ('DamageRegistry._job_main', 'self._write_error = failure_label(exc)'): 1,
    },
    'src/database/fts.py': {
        ('fts_status', 'out["error"] = failure_text(exc)'): 3,
    },
    'src/database/fts_norm.py': {
        ('_normalize_sql', 'named = exc.args[0] if exc.args and exc.args[0] in ("jieba", "sudachipy") else "word-segmentation"'): 3,
    },
    'src/database/library_generation.py': {
        ('attach._stamp', 'connection_record.info[_KEY] = _GENERATION if taken is None else taken'): 1,
        ('_refuse', 'if valid(conn.connection.info.get(_KEY)):'): 1,
        ('attach._refuse_stale_checkout', 'if not valid(connection_record.info.get(_KEY)):'): 1,
    },
    'src/database/maintenance.py': {
        ('statement_deadline', 'interrupted = "interrupt" in str(exc).lower()'): 1,
        ('statement_deadline', ') from exc'): 2,
        ('statement_deadline', 'session.info[_DEADLINE_KEY] = deadline_at'): 1,
        ('statement_deadline', 'prev_deadline = session.info.get(_DEADLINE_KEY)'): 1,
        ('deadline_expired', 'at = session.info.get(_DEADLINE_KEY)'): 1,
        ('statement_deadline', 'session.info[_DEADLINE_KEY] = prev_deadline'): 1,
        ('statement_deadline', 'session.info.pop(_DEADLINE_KEY, None)'): 1,
    },
    'src/database/page_auth.py': {
        ('_Tally.not_read', 'if exc is not None and self.failure is None:'): 1,
        ('_Tally.not_read', 'self.failure = failure_label(exc)'): 1,
        ('_scan', 'tally.not_read(exc)'): 2,
        ('check_path', 'return _result(STATE_UNREADABLE, empty, failure=failure_label(exc))'): 1,
    },
    'src/database/pool_watch.py': {
        ('_on_invalidate', 'orig = getattr(exception, "orig", exception)'): 2,
    },
    # The repair reads its OWN refusals (``Declined``, ``salvage.SalvageRefused``: fixed sentences the code wrote, a code key and numbers) and
    # one salvage failure (``SalvageFailed``: a table or index name and the class and fixed label of the driver's error); ``refusal.detail``
    # reaches a record and a log only through ``exception_text``, and tests/test_refusal_detail_source.py reads what each refusal may be made of.
    'src/database/repair.py': {
        ('run', 'code = refusal.code'): 2,
        ('run', 'report.update(outcome="declined", reason=code, reason_text=text, **refusal.facts)'): 1,
        ('run', 'failure = f"{exc.where}: {exc.reason}" if isinstance(exc, salvage.SalvageFailed) else damage.failure_text(exc)'): 3,
        ('_copy_and_swap', 'report["failure"] = f"{exc.where}: {exc.reason}"'): 2,
        ('_swap', 'raise Declined("writer-busy", str(busy)) from busy'): 2,
        ('_swap', 'if refusal.code == "saved-during-the-copy":'): 1,
    },
    'src/database/salvage.py': {
        ('Salvage._is_corrupt', 'return damage.corruption_of(exc) is not None'): 1,
        ('Salvage._classify', 'return SalvageFailed(where, damage.failure_text(exc))'): 1,
        ('Salvage._raise_for_target', 'if str(exc).lower().startswith("interrupted"):'): 1,
        ('Salvage._raise_for_target', 'raise self._classify(where, exc) from None'): 1,
        ('Salvage.run', 'raise self._classify("the copy", exc) from None'): 1,
        ('Salvage._open_source', 'if self._is_corrupt(exc):'): 1,
        ('Salvage._open_source', 'raise SalvageRefused("cannot-open", f"the damaged file could not be opened for reading ({damage.failure_text(exc)})") from None'): 1,
        ('Salvage._read_schema', 'if self._is_corrupt(exc):'): 2,
        ('Salvage._read_schema', 'raise self._classify("the schema", exc) from None'): 2,
        ('Salvage._read_table_kinds', 'if self._is_corrupt(exc):'): 1,
        ('Salvage._create_plain_header', 'raise self._classify("the new file", exc) from None'): 1,
        ('Salvage._exec', 'self._raise_for_target(where, exc)'): 1,
        ('Salvage._bounds', 'if not self._is_corrupt(exc):'): 2,
        ('Salvage._bounds', 'raise self._classify(f"table {t.name}", exc) from None'): 2,
        ('Salvage._stream', 'if not self._is_corrupt(exc):'): 1,
        ('Salvage._stream', 'raise self._classify(f"table {t.name}", exc) from None'): 1,
        ('Salvage._flush', 'self._raise_for_target(f"table {t.name}", exc)'): 1,
        ('Salvage._probe', 'if not self._is_corrupt(exc):'): 1,
        ('Salvage._probe', 'raise self._classify(f"table {t.name}", exc) from None'): 1,
        ('Salvage._copy_one', 'if not self._is_corrupt(exc):'): 1,
        ('Salvage._copy_one', 'raise self._classify(f"table {t.name}", exc) from None'): 1,
        ('Salvage._copy_scan', 'if not self._is_corrupt(exc):'): 1,
        ('Salvage._copy_scan', 'raise self._classify(f"table {t.name}", exc) from None'): 1,
        ('Salvage._rebuild_search_index', 'self._raise_for_target("the search index", exc)'): 1,
        ('Salvage._finish', 'self._raise_for_target("the finished copy", exc)'): 1,
        ('Salvage._restore_counters', 'if self._is_corrupt(exc):'): 1,
        ('Salvage._orphan_groups', 'self._raise_for_target("the foreign key check", exc)'): 1,
        ('Salvage._single_key', 'self._raise_for_target("the foreign keys of a table", exc)'): 1,
        ('Salvage._raise_sequence', 'self._raise_for_target("the counter of a table", exc)'): 1,
        ('Salvage._id_above', 'self._raise_for_target("the highest id of a table that needs a stand-in row", exc)'): 1,
        ('Salvage._stand_in', 'self._raise_for_target("the columns of a table that needs a stand-in row", exc)'): 1,
        ('Salvage._stand_in', 'if "constraint" in str(exc).lower() or type(exc).__name__ == "IntegrityError":'): 1,
        ('Salvage._stand_in', 'self._raise_for_target("a stand-in row", exc)'): 1,
        ('Salvage._orphans', 'self._raise_for_target("the orphans", exc)'): 1,
        ('Salvage._create_indexes', 'raise SalvageFailed(f"index {name}", damage.failure_text(exc)) from None'): 1,
        ('Salvage._null_the_set_null_keys', 'if "constraint" in str(exc).lower() or type(exc).__name__ == "IntegrityError":'): 1,
        ('Salvage._null_the_set_null_keys', 'self._raise_for_target("the keys that set NULL", exc)'): 1,
        ('Salvage._highest_referenced', 'self._raise_for_target("the highest id the orphans refer to", exc)'): 1,
        ('Salvage._undo_stand_ins', 'self._raise_for_target("a stand-in row that was not needed", exc)'): 1,
        ('Salvage._create_rest', 'raise SalvageFailed(f"index {name}", damage.failure_text(exc)) from None'): 1,
        ('Salvage._orphans', 'self._raise_for_target("the list of columns of a table with orphans", exc)'): 1,
    },
    'src/database/session.py': {
        ('_mark_wrote', 'session.info[_WROTE_FLAG] = True'): 1,
        ('_clear_wrote', 'session.info.pop(_WROTE_FLAG, None)'): 1,
        ('release_idle_connection', 'if session.info.get(_WROTE_FLAG) or session.info.get(_WRITE_GATE_SESSION_FLAG):'): 2,
    },
    'src/database/verify.py': {
        ('classify_error', 'found = damage.corruption_of(exc)'): 1,
        ('classify_error', 'driver = damage.driver_error(exc) or exc'): 2,
        ('is_generic_error', 'if damage.corruption_of(exc) is not None:'): 1,
        ('is_generic_error', 'driver = damage.driver_error(exc)'): 1,
        ('_error_of', 'out: dict[str, Any] = {"error": classify_error(exc)}'): 1,
        ('_error_of', 'if out["error"][0] == VERDICT_UNCHECKED and is_generic_error(exc):'): 1,
        ('inspect_file', 'return _error_of(exc)'): 2,
        ('_read_table', 'verdict, reason = classify_error(exc)'): 1,
        ('_read_table', 'elif verdict == VERDICT_UNCHECKED and is_generic_error(exc):'): 1,
        ('_page_pass', 'verdict, reason = classify_error(exc)'): 1,
        ('_tag_pass', 'verdict, reason = classify_error(exc)'): 1,
    },
    'src/database/write.py': {
        ('_exc_chain', 'stack: list[BaseException | None] = [exc]'): 1,
        ('is_locked_error', 'for e in _exc_chain(exc):'): 1,
        ('is_integrity_error', 'return any(isinstance(e, types) for e in _exc_chain(exc))'): 1,
        ('run_write_with_retry', 'last_exc = exc'): 1,
    },
    'src/database/writer.py': {
        ('release_if_held', 'if session.info.pop(_SESSION_FLAG, False):'): 1,
        ('hold_write_window', 'session.info[_SESSION_FLAG] = True'): 1,
        ('_on_before_flush', 'session.info[_SESSION_FLAG] = True'): 1,
        ('_on_orm_execute', 'session.info[_SESSION_FLAG] = True'): 1,
        ('hold_write_window', 'if not session.info.get(_SESSION_FLAG):'): 1,
        ('_on_before_flush', 'if not session.info.get(_SESSION_FLAG):'): 1,
        ('_on_orm_execute', 'if not session.info.get(_SESSION_FLAG):'): 1,
        ('_on_after_transaction_end', 'if transaction.parent is None and session.info.pop(_SESSION_FLAG, False):'): 1,
    },
}
CLASSIFIED.update(_DATABASE_CLASSIFIED)
#: ``pool_watch``/``writer`` import ``traceback`` to print a stack of frames (the current thread's own), not an exception.
_DATABASE_NOT_RECORDS: dict[str, dict[str, int]] = {
    'src/database/pool_watch.py': {'the traceback module is imported': 2},
    'src/database/writer.py': {'the traceback module is imported': 1},
}
NOT_RECORDS.update(_DATABASE_NOT_RECORDS)
_MONITORING_CLASSIFIED: dict[str, dict[tuple[str, str], int]] = {
    'src/monitoring/boots.py': {  # _error_text is record_text (a driver by class, the paths tokenised, then cut)
        ('diagnostics_member', 'return {"error": _error_text(exc)}'): 1,
    },
    'src/monitoring/diagnostics_runs.py': {  # exc_line is record_text; tidy_error scrubs the whole text and cuts last (a driver by class only); a non-exception error is a string already written
        ('tidy_error', 'text = exc_line(error) if isinstance(error, BaseException) else str(error)'): 2,
        ('end_run', 'if error:'): 1,
        ('end_run', 'rec["error"] = tidy_error(error)'): 1,
        ('_append', '_LOG.debug("diagnostics runs: could not write the record: %s", tidy_error(err))'): 1,
        ('diagnostics_member', '"reason": tidy_error(exc_line(exc), MEMBER_REASON_CHARS),'): 1,
    },
    'src/monitoring/engine_text.py': {  # is_pool_timeout walks the chain by CLASS and returns a bool: no text of any link is read
        ('is_pool_timeout', 'link: BaseException | None = exc'): 1,
    },
    'src/monitoring/exit_evidence.py': {  # tidy_error (record_text underneath); the fatal trace is record_traceback
        ('arm_crash_trace', 'reason = tidy_error(exc, _ARM_REASON_CHARS)'): 1,
        ('note_fatal_exception', '_LOG.debug("could not record the fatal exception: %s", tidy_error(err))'): 1,
    },
    'src/monitoring/forensics.py': {  # _why/_why-like helpers go through tidy_error (record_text underneath)
        ('_why', 'return tidy_error(exc, _REASON_CHARS)  # an exception is written by ``exc_line``, which never raises'): 1,
        ('previous_session_report', 'out["earlier_unclean_ends"] = {"available": False, "reason": _why(exc)}'): 1,
        ('_exit_evidence_report', 'out["unavailable"] = _why(exc)'): 1,
    },
    'src/monitoring/integrity.py': {  # _budget_spent is a bool classifier (statement deadline expired and "interrupt" in the text); the text goes nowhere
        ('_budget_spent', 'return deadline_expired(session) and "interrupt" in str(exc).lower()'): 1,
        ('_scalar', 'if _budget_spent(session, exc):'): 1,
        ('corpus_integrity', 'if _budget_spent(session, exc):'): 2,
    },
    'src/monitoring/keyword_write_cost.py': {  # engine_text is record_text (a driver by class only): _cut_reason's text is composed by it
        ('keyword_write_cost', 'cut = _cut_reason(exc)'): 1,
    },
    'src/monitoring/machine_record.py': {  # _unavailable writes the class name and nothing else
        ('_build', 'out["app_version"] = _unavailable(exc)'): 1,
        ('_build', 'out["code"] = _unavailable(exc)'): 1,
        ('_process', 'out["started_at"] = _unavailable(exc)'): 1,
        ('_sqlcipher_version', 'return _unavailable(exc)'): 1,
        ('_libc', 'return _unavailable(exc)'): 1,
        ('_memory', 'out["reading_vs_now"] = _unavailable(exc)'): 1,
        ('_memory', 'out["available_now_mb"] = _unavailable(exc)'): 1,
        ('_allocator', 'return _unavailable(exc)'): 1,
        ('_environment', 'return _unavailable(exc)'): 1,
    },
    'src/monitoring/page_reading.py': {  # failure_label: the class and the errno name, never the message or the path (src/database/damage.py)
        ('_error', 'return failure_label(exc)'): 1,
        ('_wal_state', 'return None, _error(exc)'): 1,
        ('read_header', 'out["error"] = _error(exc)'): 1,
        ('from_connection', 'out["error"] = _error(exc)'): 1,
    },
    'src/monitoring/p0_validation.py': {  # _exception_text is record_text with the passphrase handed in
        ('_check_backup', 'verr = _exception_text(exc, passphrase)'): 1,
        ('_check_backup', 'err = _exception_text(exc, passphrase)'): 1,
        ('_check_backup', '"error": _exception_text(exc, passphrase),'): 1,
        ('_check_restore', 'f"the staged restore probe did not complete: {_exception_text(exc, passphrase)}",'): 1,
    },
    'src/monitoring/recursive_loop.py': {  # _failure_text is record_text, paths tokenised before the cut
        ('recursive_loop_report', 'row["error"] = _failure_text(exc)'): 2,
    },
    'src/monitoring/release_run.py': {  # _PhaseError.status/.partial are the phase's own fields (the text is record_text above); _is_pool_timeout is a classifier
        ('_run_phase', 'ph = run.end(exc.status if exc.status in PHASE_STATUSES else "error", why[:400], result=exc.partial)'): 3,
        ('_retrying', 'if delay is None or not _is_pool_timeout(exc) or ctx.stopping:'): 1,
    },
    'src/monitoring/release_run_fresh_restore.py': {  # _error_text is record_text with the passphrase handed in
        ('main', 'result["error"] = _error_text(exc, passphrase)'): 1,
    },
    'src/monitoring/storage.py': {  # failure_text is the damage lane's class-only label (never a part of the driver's message)
        ('storage_composition', 'out["reason"] = f"sqlite_master unreadable: {failure_text(exc)}"'): 1,
        ('storage_composition', 'f"compile flag in this SQLite/SQLCipher build, or the walk met a damaged page): {failure_text(exc)}"'): 1,
    },
    'src/monitoring/storage_events.py': {  # _label is the class and the errno NAME only; the "error" field is a label made by the caller (type(exc).__name__)
        ('_label', 'code = exc.errno if isinstance(exc, OSError) else None'): 1,
        ('_internal_failure', '_LAST_INTERNAL_FAILURE = f"{what}: {_label(exc)}"'): 1,
        ('note_checkpoint', '"error": error,'): 1,
        ('_flusher', '_internal_failure("the writer thread ended", exc)'): 1,
        ('flush', '_internal_failure("flush", exc)'): 1,
        ('record', '_internal_failure("record", exc)'): 1,
        ('update', '_internal_failure("update", exc)'): 1,
        ('end', '_internal_failure("end", exc)'): 1,
        ('run_started', '_internal_failure("run_started", exc)'): 1,
        ('run_facts', '_internal_failure("run_facts", exc)'): 1,
        ('free_bytes_of', '_internal_failure("free_bytes_of", exc)'): 1,
        ('run_ended', '_internal_failure("run_ended", exc)'): 1,
        ('run_refused', '_internal_failure("run_refused", exc)'): 1,
        ('run_part', '_internal_failure("run_part", exc)'): 1,
        ('note_checkpoint', '_internal_failure("note_checkpoint", exc)'): 1,
        ('note_open', '_internal_failure("note_open", exc)'): 1,
        ('note_pool_timeout', '_internal_failure("note_pool_timeout", exc)'): 1,
        ('diagnostics_member', 'return {"error": _label(exc)}'): 1,
        ('_read_file', 'return {}, None, f"unreadable ({_label(exc)})", True'): 1,
        ('_read_file', 'last = f"unreadable ({_label(exc)})"'): 1,
        ('_read_file', 'return {}, None, f"unreadable ({_label(exc)})", False'): 1,
        ('_read_file', 'how = "unreadable (not this journal)" if isinstance(exc, ValueError) else f"unreadable ({_label(exc)})"'): 1,
        ('_write', '_LAST_WRITE_FAILURE = _label(exc)'): 1,
        ('_flusher_loop', '_internal_failure("flusher", exc)'): 1,
    },
    'src/monitoring/ui_walk_playwright.py': {  # the import error is raised again as the cause of a refusal and never written to a record
        ('<module>', '_IMPORT_ERROR: Exception | None = _exc'): 1,
    },
    'src/monitoring/vitals_history.py': {  # _reason is the class plus an OSError's strerror (an OS word, never a driver's); _debug_failure goes through log_failure; _note_error stores only _reason
        ('_reason', 'if isinstance(exc, OSError) and exc.strerror:'): 1,
        ('_reason', 'reason += f": {exc.strerror}"'): 1,
        ('_note_error', '_ERRORS[f"last_{what}_error"] = {"at": _iso(time.time()), "error": _reason(exc)}'): 1,
        ('_slow_readings', '_debug_failure("vitals history: the data folder could not be read", err)'): 1,
        ('tick', '_note_error("tick", exc)'): 1,
        ('tick', '_debug_failure("vitals history tick failed", exc)'): 1,
        ('flush', '_debug_failure("vitals history flush failed", err)'): 1,
        ('diagnostics_member', 'return {"available": False, "error": _reason(exc)}'): 1,
        ('start', '_debug_failure("vitals history: could not read the previous file", err)'): 1,
        ('flush', '_note_error("flush", exc)'): 1,
    },
}
_MONITORING_NOT_RECORDS: dict[str, dict[str, int]] = {
    'src/monitoring/activity_ledger.py': {
        'getattr reaches name, a way round the scan of the log calls': 2,
    },
    # the traceback as raised is read at one line for two booleans (locked, interrupted) and never stored; the stored tail is record_traceback's
    'src/monitoring/errorlog.py': {
        'the traceback module is imported': 1,
        'format_exception() writes the traceback': 1,
        'sys.exc_info() reads the exception being handled': 5,
        'getattr reaches TRACEBACK_ATTRIBUTE, a way round the scan of the log calls': 1,
    },
    'src/monitoring/llm_bench.py': {
        'getattr reaches field, a way round the scan of the log calls': 1,
    },
    'src/monitoring/recursive_loop.py': {
        'getattr reaches fn_name, a way round the scan of the log calls': 1,
    },
    'src/monitoring/session_hwm.py': {
        'getattr reaches name, a way round the scan of the log calls': 1,
    },
    'src/monitoring/slowquery.py': {
        'conn.info is kept as a name, a log call the scan cannot read': 2,
    },
    'src/monitoring/ui_walk.py': {
        'r.error is kept as a name, a log call the scan cannot read': 1,
    },
    'src/monitoring/windows_locks.py': {
        'proc.info is kept as a name, a log call the scan cannot read': 2,
    },
}

#: ``src/api`` (R140). Every ``detail`` and every response or record field that carries a caught exception's text goes through
#: ``http_detail`` / ``record_text`` (the per-link rule: a database driver's error, or a wrapper that quotes one, is its class only; every
#: other exception keeps its words with the held passphrases taken out). What is left, line by line and counted: attributes of OUR OWN
#: typed refusals (``exc.status``, ``exc.state``, ``exc.report``, ``exc.i18n``/``vars``: fixed words the code wrote), callbacks that hand the
#: exception to the route's own response builder (read in that route's module), an exception stored to be re-raised on another thread, the
#: errno-only classifiers (``no_room_refusal``, ``strerror``), ``isinstance`` and ``__cause__`` type reads, the frontend-error REPORT body
#: (``err`` is a request model, not an exception; ``note_frontend_error`` scrubs it), ``_unreadable`` (logs through ``log_failure`` and
#: answers a fixed dict) and the unhandled-exception handler's non-driver branch (its own withheld sentence, pinned by
#: ``test_global_exception_handler_scrub``).
_API_CLASSIFIED: dict[str, dict[tuple[str, str], int]] = {
    'src/api/backup_v2.py': {
        ('_alt_call', 'raise HTTPException(status_code=exc.status, detail=http_detail(exc))'): 1,
    },
    'src/api/boot_sequence.py': {
        ('_timed', 'state = skipped.state'): 1,
    },
    'src/api/bulletin.py': {
        ('_scope_mismatch_detail', 'return {"reason": http_detail(exc), **exc.state}'): 1,
        ('narrate_edition', 'raise HTTPException(status_code=409, detail=_scope_mismatch_detail(exc))'): 1,
    },
    'src/api/database.py': {
        ('vacuum', 'raise HTTPException(status_code=507, detail=exc.report["detail"])'): 1,
    },
    'src/api/diagnostics/bundle.py': {
        ('_all_diagnostics_worker', 'error=_diag_runs.exc_line(exc),'): 1,
        ('all_diagnostics_volumes', 'if no_room_refusal(exc, "splitting the archive") is None:'): 1,
        ('all_diagnostics_volumes', 'f"written ({exc.strerror or type(exc).__name__}). The earlier set of files, if there "'): 1,
        ('_run_nondb_member_bounded._run', 'box["error"] = exc'): 1,
        ('_merged_member', 'cause = exc.__cause__ if isinstance(exc, HTTPException) else None'): 1,
        ('_write_all_diagnostics_zip', 'cause = exc.__cause__ if isinstance(exc, HTTPException) else None'): 1,
    },
    'src/api/diagnostics/keywords.py': {
        ('_keyword_parts', 'refusal = no_room_refusal(exc, "listing the parts")'): 1,
        ('keyword_log', 'raise HTTPException(status_code=exc.status, detail=http_detail(exc))'): 1,
    },
    'src/api/diagnostics/qualification_merge.py': {
        ('source_qualification_merge', 'return refuse(exc.i18n, **exc.vars)'): 2,
    },
    'src/api/diagnostics/system.py': {
        ('report_frontend_error', 'err.kind,'): 1,
        ('report_frontend_error', 'err.message,'): 1,
        ('report_frontend_error', 'source=err.source,'): 1,
        ('report_frontend_error', 'endpoint=err.endpoint,'): 1,
        ('report_frontend_error', 'lineno=err.lineno,'): 1,
        ('report_frontend_error', 'ui_lang=err.ui_lang,'): 1,
    },
    'src/api/heavy.py': {
        ('run_heavy', 'fl.error = exc'): 1,
        ('guarded_read', 'return on_timeout(exc)'): 1,
        ('guarded_read', 'return on_busy(exc)'): 1,
        ('run_heavy', 'if fl.error is not None:'): 1,
        ('run_heavy', 'raise fl.error'): 1,
    },
    'src/api/insights.py': {
        ('_deadlined', 'return on_timeout(exc)'): 1,
        ('_deadlined', 'return on_busy(exc)'): 1,
    },
    'src/api/llm.py': {
        ('bulk_llm._stream', 'if isinstance(res.error, LLMUnavailable):'): 1,
        ('bulk_llm._stream', 'assert res.error is not None  # a not-ok result always carries its error'): 1,
        ('bulk_llm._stream', '"error": http_detail(res.error, limit=200)})'): 1,
        ('bulk_llm._stream', '"aborted": True, "reason": http_detail(res.error, limit=200)})'): 1,
    },
    'src/api/main.py': {
        ('rate_limit_exceeded_handler', 'retry_after = getattr(exc, "retry_after", None)'): 1,
        ('rate_limit_exceeded_handler', 'limit = getattr(exc, "limit", None)'): 1,
        ('unhandled_exception_handler', 'f"internal error: {exc}",'): 1,
        ('monitor_requests', 'raise e'): 1,
        ('_serve', 'note_fatal_exception(exc)'): 1,
    },
    'src/api/osm_lane.py': {
        ('osm_view', 'return view(w, s, e, n)'): 1,
    },
    'src/api/startup_status.py': {
        ('set_startup', '_state["error"] = error'): 1,
    },
    'src/api/wiki_lane.py': {
        ('lane_status', 'return _unreadable("status", exc)'): 1,
        ('lane_analytics', 'return _unreadable("analytics", exc)'): 1,
        ('lane_divergence', 'return _unreadable("divergence", exc)'): 1,
        ('lane_attention', 'return _unreadable("attention", exc)'): 1,
        ('lane_counters_route', 'return _unreadable("counters", exc)'): 1,
        ('lane_places', 'return _unreadable("places", exc)'): 1,
        ('lane_sections', 'return _unreadable("sections", exc)'): 1,
        ('lane_changes', 'return _unreadable("changes", exc)'): 1,
        ('lane_revision_diff', 'return _unreadable("revision", exc)'): 1,
    },
}
_API_NOT_RECORDS: dict[str, dict[str, int]] = {
    'src/api/diagnostics_slots.py': {'getattr reaches function, a way round the scan of the log calls': 1},  # a module's function name
    'src/api/main.py': {'getattr reaches name, a way round the scan of the log calls': 1},  # a signal's name
    'src/api/search_filters.py': {'getattr reaches name, a way round the scan of the log calls': 1},  # a model field name
    'src/api/source_io.py': {'getattr reaches sort_key, a way round the scan of the log calls': 1},  # a model column name
}
CLASSIFIED.update(_API_CLASSIFIED)
NOT_RECORDS.update(_API_NOT_RECORDS)
CLASSIFIED.update(_MONITORING_CLASSIFIED)
NOT_RECORDS.update(_MONITORING_NOT_RECORDS)



#: ``raise HTTPException(...) from exc`` in ``src/api`` (R140): the chain rides the HTTPException the route answers with, and nothing logs
#: an HTTPException's chain (Starlette answers it; ``unhandled_exception_handler`` is for the exceptions that are NOT HTTPExceptions);
#: the exc_info sinks are read by ``test_exception_sinks_scrub``. The ``from`` is taken off the scanned source, line for line, so every
#: OTHER use of the exception on the raise (its detail) is still read.
_RAISE_FROM = re.compile(r"(?<=[)\w\]\"]) from (?:exc|e|err|ex|None)[ \t]*$", re.M)


def _api_chain_taken_off(rel: str, source: str) -> str:
    return _RAISE_FROM.sub("", source) if (rel.startswith("src/api/") or rel in _S5_MODULES) else source


#: Outside ``src/api`` a ``raise`` inside an ``except`` that chains the caught exception (``from exc``, or implicitly with no ``from``) hands
#: an ORDINARY exception's chain to whoever logs the new one (through ``record_traceback``, which reads every link), so the reading above
#: does not follow it. Instead the sites are COUNTED per module, an HTTPException raise among them: a new one fails here until its cause
#: has been read and the count raised, so a wrapper raised from a driver's error cannot arrive unseen. ``from None`` chains nothing.
_S5_CHAINED_RAISES: dict[str, int] = {
    "src/ai_layer/bench_batch.py": 2,
    "src/ai_layer/source_tags_job.py": 1,
    "src/ai_layer/triage_job.py": 1,
    "src/analytics/ir_eval.py": 2,
    "src/analytics/keyword_log_export.py": 3,
    "src/analytics/keyword_log_scan.py": 2,
    "src/analytics/watches.py": 1,
    "src/catalog/discover.py": 1,
    "src/catalog/qualification_integrity.py": 1,
    "src/catalog/qualification_merge.py": 12,
    "src/config/app_settings.py": 3,
    "src/custody/anchor.py": 2,
    "src/law/adapters/clml.py": 3,
    "src/llm/ollama.py": 10,
    "src/llm/ollama_lifecycle.py": 1,
    "src/llm/vllm_client.py": 5,
    "src/llm/vllm_lifecycle.py": 1,
    "src/safety/crypto.py": 4,
    "src/safety/settings.py": 1,
    "src/services/duckduckgo.py": 1,
    "src/stats/fdr.py": 1,
    "src/stats/fetch.py": 1,
    "src/utils/compression.py": 2,
    "src/verification/metadata.py": 1,
    "src/versioned/budget.py": 2,
}


def _chained_raises(source: str) -> int:
    seen = set()
    for handler in (n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ExceptHandler)):
        for r in ast.walk(handler):
            if isinstance(r, ast.Raise) and r.exc is not None and not (isinstance(r.cause, ast.Constant) and r.cause.value is None):
                seen.add(id(r))
    return len(seen)


def test_a_raise_that_chains_an_ordinary_exception_is_counted_not_skipped():
    found = {rel: n for rel in sorted(_S5_MODULES) if (n := _chained_raises((ROOT / rel).read_text(encoding="utf-8")))}
    assert found == _S5_CHAINED_RAISES
    assert _chained_raises("try:\n    pass\nexcept A as e:\n    raise B('x')\n") == 1, "an implicit chain is counted"
    assert _chained_raises("try:\n    pass\nexcept A as e:\n    raise HTTPException(400) from e\n") == 1, "an HTTPException is counted"
    assert _chained_raises("try:\n    pass\nexcept A as e:\n    raise B('x') from None\n") == 0


def _found(rel: str, source: str) -> list[str]:
    source = _api_chain_taken_off(rel, source)
    table = {k: v for k, v in KEPT.get(rel, {}).items() if v}
    lines = source.splitlines()
    tree = ast.parse(source)
    parent = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    nodes_by_line = {}
    for n in ast.walk(tree):
        if hasattr(n, 'lineno'):
            nodes_by_line.setdefault(n.lineno, n)
    allowed = dict(CLASSIFIED.get(rel, {}))
    out = []
    seen: dict[str, int] = {}
    for finding in _leaks(source, only_scrubbing=CALLS, words_kept=table or None, params=True):
        line, _, message = finding.partition(": ")
        if line.isdigit():
            key = (_enclosing_function(nodes_by_line[int(line)], parent) if int(line) in nodes_by_line else "", lines[int(line) - 1].strip())
            if allowed.get(key, 0) > 0:
                allowed[key] -= 1
                continue
        if message in NOT_RECORDS.get(rel, {}):
            seen[message] = seen.get(message, 0) + 1
            if seen[message] <= NOT_RECORDS[rel][message]:
                continue
        out.append(finding)
    out += [f"0: {m!r} expected {n} time(s), found {seen.get(m, 0)}" for m, n in NOT_RECORDS.get(rel, {}).items() if seen.get(m, 0) < n]
    out += [f"0: classifier line {k!r} expected but not found ({n} left)" for k, n in allowed.items() if n > 0]
    return out


@pytest.mark.parametrize("rel", MODULES)
def test_a_stored_or_served_record_names_the_class_and_not_the_words(rel):
    found = _found(rel, (ROOT / rel).read_text(encoding="utf-8"))
    assert found == [], f"{rel}: {found}"


def test_the_sweep_reads_the_whole_scheduler_and_wiki_trees():
    on_disk = {p.relative_to(ROOT).as_posix() for entry in ("src/scheduler", "src/wiki") for p in (ROOT / entry).rglob("*.py")}
    assert on_disk <= set(MODULES)
    assert len(on_disk) >= 20, "the directory glob found no module: the test would pass over nothing"


_HANDLER = "def f():\n    try:\n        pass\n    except Exception as exc:\n        {body}\n"


@pytest.mark.parametrize(
    "body",
    [
        "return {'reason': str(exc)}",
        "report.errors.append(str(exc))",
        "self._note('x', str(exc))",
        "msg = f'failed: {exc}'",
        "msg = f'{exc!s}'",
        "return repr(exc)",
        "return f'{type(exc).__name__}: {exc}'",
        "return '{}'.format(exc)",
        "return exception_text(exc)",
        "return {'e': exc}",
        "return str(getattr(exc, 'orig', exc))",
        "return exc.args[0]",
    ],
)
def test_the_strict_reading_flags_each_spelling_a_record_must_not_carry(body):
    assert _leaks(_HANDLER.format(body=body), only_scrubbing=CALLS), body


@pytest.mark.parametrize(
    "body",
    ["log_failure(_LOG, 'x', exc)", "return {'error': type(exc).__name__}", "return isinstance(exc, OSError)"],
)
def test_the_strict_reading_passes_the_class_and_the_log_failure_line(body):
    assert _leaks(_HANDLER.format(body=body), only_scrubbing=CALLS) == [], body


def test_a_chain_on_an_api_raise_is_not_a_use_but_its_detail_still_is():
    chained = "def f():\n    try:\n        g()\n    except Exception as exc:\n        raise HTTPException(status_code=400, detail=http_detail(exc)) from exc\n"
    assert _found("src/api/x.py", chained) == []
    leaking = chained.replace("http_detail(exc)", "str(exc)")
    assert _found("src/api/x.py", leaking), "the detail built from the exception is still reported"
    assert _found("src/backup/x.py", chained), "outside src/api the chain is still read as a use"


_API_RAISE = "def f():\n    try:\n        g()\n    except Exception as exc:\n        raise HTTPException(status_code=400, detail={detail}) from exc\n"


@pytest.mark.parametrize(
    "detail",
    [
        "str(exc)",
        'f"could not: {exc}"',
        'f"could not: {exc!r}"',
        '"could not: " + str(exc)',
        '"could not: %s" % exc',
        '"could not: {}".format(exc)',
        "repr(exc)",
        "str(exc)[:300]",
        "exc.args[0]",
        'f"{type(exc).__name__}: {exc}"',
        '{"reason": str(exc)}',
        "exception_text(exc, typed=False)",
    ],
)
def test_an_api_detail_built_from_an_exception_outside_the_helper_is_reported(detail):
    """R140's guard, with its negative controls: every spelling of an exception's text in a ``detail`` is a finding in ``src/api``."""
    assert _found("src/api/x.py", _API_RAISE.format(detail=detail)), detail


@pytest.mark.parametrize("detail", ["http_detail(exc)", 'http_detail(exc, "could not: ")', "http_detail(exc, limit=300)", '"a fixed sentence"'])
def test_an_api_detail_through_the_helper_or_fixed_is_not_a_finding(detail):
    assert _found("src/api/x.py", _API_RAISE.format(detail=detail)) == [], detail


def test_the_sweep_reads_every_module_of_src_api():
    read = {m for m in MODULES if m.startswith("src/api/")}
    on_disk = {p.relative_to(ROOT).as_posix() for p in (ROOT / "src/api").rglob("*.py")}
    assert on_disk <= read, sorted(on_disk - read)


# --- slice 5: the rest of src/ ----------------------------------------------------------------------------------------------------
# Every OTHER package is read like the ones above (a stored or served text from a caught exception is record_text's, or a line below with its reason).
_S5_CLASSIFIED: dict[str, dict[tuple[str, str], int]] = {
    'src/ai_layer/source_tags_job.py': {
        # outage_detail reads an exception through record_text (llm/backend.py); pinned by tests/test_outage_detail_scrub.py
        ('run_progressive_source_tags_job', 'f"{outage_detail(_why, exc, recovery=_fix)} — retrying in "'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('run_progressive_source_tags_job', 'if is_context_overflow(exc) and working_batch > 1:'): 1,
    },
    'src/ai_layer/triage_job.py': {
        # outage_detail reads an exception through record_text (llm/backend.py); pinned by tests/test_outage_detail_scrub.py
        ('run_progressive_triage_job', 'f"{outage_detail(_why, exc, recovery=_fix)} — retrying in "'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('run_progressive_triage_job', 'if is_context_overflow(exc) and working_batch > 1:'): 1,
    },
    'src/analytics/equivalence.py': {
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('QueryExpander.cap_facts', 'rec = self._capped.get(e.normalized)'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('QueryExpander.searched_siblings', 'rec = self._capped.get(e.normalized)'): 1,
    },
    'src/analytics/keyword_log_export.py': {
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('ZipJob.write', 'refusal = no_room_refusal(exc, "writing the archive")'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('ZipJob.write_parts', 'refusal = no_room_refusal(exc, "writing the parts")'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('finish_parts', 'refusal = no_room_refusal(exc, "writing the parts") if isinstance(exc, OSError) else None'): 1,
    },
    'src/analytics/keyword_log_scan.py': {
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('_refuse_when_the_disk_is_full', 'getattr(exc, "sqlite_errorcode", None) == _SQLITE_IOERR_WRITE'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('_refuse_when_the_disk_is_full', 'refusal = no_room_refusal(OSError(code, str(exc)), "ranking keywords")'): 1,
        # read for a keyword to CLASSIFY the failure; the text goes nowhere
        ('_refuse_when_the_disk_is_full', 'said = str(exc).lower()'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('no_room_refusal', 'code = getattr(exc, "errno", None)'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('scratch_file', 'refusal = no_room_refusal(exc, "creating its scratch file")'): 1,
    },
    'src/analytics/rollup_serve.py': {
        # the module's own stop signal: a reason word and a detail dict it wrote itself, no engine text
        ('_build_inmemory_and_swap', 'skip = {"reason": stop.reason, "at": time.time(), **stop.detail}'): 2,
    },
    'src/analytics/store.py': {
        # _skip_error writes engine_text (record_text); its body is pinned by tests/test_engine_text.py (the helper check)
        ('maybe_cleanup_keywords', 'tally["entity_status"] = _skip_error(exc)'): 1,
        # _skip_error writes engine_text (record_text); its body is pinned by tests/test_engine_text.py (the helper check)
        ('maybe_cleanup_keywords', 'tally["language"] = _skip_error(exc)'): 1,
        # _skip_error writes engine_text (record_text); its body is pinned by tests/test_engine_text.py (the helper check)
        ('maybe_cleanup_keywords', 'tally["prune"] = _skip_error(exc)'): 2,
    },
    'src/analytics/watches.py': {
        # the ValueError's detail is the HTTPException detail of the filter parser, or record_text's own output (search_filters does not use http_detail)
        ('_filters_blob', 'raise ValueError(getattr(exc, "detail", None) or record_text(exc))'): 1,
    },
    'src/catalog/discover_job.py': {
        # read for a keyword to CLASSIFY the failure; the text goes nowhere
        ('run_world_discovery', 'if "airplane" in str(exc):  # the kill switch raced the loop check'): 1,
    },
    'src/catalog/qualification_merge.py': {
        # hands the JSON error to the YAML reader, which records it through record_text(json_exc) and chains only the YAML error
        ('rows_from_export_bytes', 'return _rows_from_export_yaml(text, origin, json_exc)'): 1,
    },
    'src/config/kv_store.py': {
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('_ro_only_failure', 'return type(exc).__name__ == "OperationalError" and any(w in str(exc).lower() for w in _RO_ONLY_FAILURES)'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('is_damaged', 'return isinstance(exc, ValueError) or bool(getattr(exc, "damaged", False))'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('kv_get_json_checked', 'if isinstance(exc, FileNotFoundError) or "no such table" in str(exc).lower():'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('kv_get_json_checked', 'if not _ro_only_failure(ro_exc):'): 1,
        # read for a keyword to CLASSIFY the failure; the text goes nowhere
        ('kv_get_json_strict', 'if "no such table" in str(exc).lower():'): 1,
    },
    'src/custody/pending.py': {
        # an exception handed on in an object / a text already made by the caller from record_text; not made here
        ('_record', '"failed_at": _now_iso(), "error": str(error or "")[:300], "found_by": found_by,'): 1,
        # an exception handed on in an object / a text already made by the caller from record_text; not made here
        ('note_failed', 'source_id=source_id, error=error, found_by=found_by)])'): 1,
    },
    'src/diagnostics.py': {
        # _brief is record_text's first line (src/diagnostics.py)
        ('_check_database', 'r.line(FAIL, "Database", f"reachable but query failed: {_brief(exc)}")'): 1,
    },
    'src/entities/gazetteer_build.py': {
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('fetch_wikidata', '_reraise_refusal(exc)  # ... except a refusal by the transport or the kill switch'): 1,
    },
    'src/events/catalog.py': {
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_span_for', 'end = _span_end_date(start, e["end_month"], e["end_day"])'): 2,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_span_for', 'if not (e.get("end_month") and e.get("end_day") and e.get("month") and e.get("day")):'): 4,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_span_for', 'origin, until = e.get("origin_year"), e.get("until_year")'): 2,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_span_for', 'start = date(year, int(e["month"]), int(e["day"]))'): 2,
    },
    'src/events/dedup.py': {
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_when_display', 'return e.get("next_occurrence") or _when_key(e) or "—"'): 2,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_when_key', 'if e.get("month"):'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_when_key', 'if e.get("next_occurrence"):'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_when_key', 'return e.get("cadence") or ""'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_when_key', 'return e["next_occurrence"][5:7]  # MM'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_when_key', 'return f"{int(e[\'month\']):02d}"'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('fingerprint', 'return (_norm_title(e.get("title", "")), _when_key(e), (e.get("country") or "").upper())'): 3,
    },
    'src/geo/osm_downloads.py': {
        # kept to be re-raised on the caller's side: not written
        ('OsmDownloadManager._download', 'failure = exc'): 1,
    },
    'src/hazards/ingest.py': {
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('ingest_hazard_record', 'if not is_integrity_error(exc):'): 2,
    },
    'src/jobs/background.py': {
        # kept to be re-raised on the caller's side: not written
        ('BackgroundJob._run', 'failure = exc'): 1,
    },
    'src/law/corpus.py': {
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('upsert_law_corpus_article', 'if not is_integrity_error(exc):'): 1,
    },
    'src/law/track.py': {
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('track_document', 'if not is_integrity_error(exc):'): 2,
    },
    'src/llm/backend.py': {
        # an exception handed on in an object / a text already made by the caller from record_text; not made here
        ('outage_detail', 'text = str(error or "").strip()'): 1,
    },
    'src/llm/concurrency.py': {
        # an exception handed on in an object / a text already made by the caller from record_text; not made here
        ('run_concurrent', 'out.append(ConcurrentResult(ok=False, error=exc))'): 1,
        # an exception handed on in an object / a text already made by the caller from record_text; not made here
        ('run_concurrent', 'out[i] = ConcurrentResult(ok=False, error=exc)'): 1,
    },
    'src/llm/ollama.py': {
        # the SERVER'S OWN words of an HTTP status error (a response body or reason phrase, never a driver's or a held key); the exception is httpx's
        ('OllamaClient.generate', 'f"Ollama error for model {model!r}: {_http_error_text(exc)}"'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('OllamaClient.generate', 'if exc.response.status_code == 404:'): 1,
        # the SERVER'S OWN words of an HTTP status error (a response body or reason phrase, never a driver's or a held key); the exception is httpx's
        ('OllamaClient.pull', 'raise LLMError(f"Ollama error pulling {model!r}: {_http_error_text(exc)}")'): 1,
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('OllamaClient.remove', 'if exc.response.status_code == 404:'): 1,
        # the SERVER'S OWN words of an HTTP status error (a response body or reason phrase, never a driver's or a held key); the exception is httpx's
        ('OllamaClient.remove', 'raise LLMError(f"Ollama error removing {model!r}: {_http_error_text(exc)}")'): 1,
        # the SERVER'S OWN words of an HTTP status error (a response body or reason phrase, never a driver's or a held key); the exception is httpx's
        ('_http_error_text', 'line = _status_line(exc)'): 1,
        # the SERVER'S OWN words of an HTTP status error (a response body or reason phrase, never a driver's or a held key); the exception is httpx's
        ('_http_error_text', 'reason = _http_reason(exc)'): 1,
        # the SERVER'S OWN words of an HTTP status error (a response body or reason phrase, never a driver's or a held key); the exception is httpx's
        ('_http_reason', 'raw = exc.response.text or ""'): 1,
        # _status_line: httpx's HTTPStatusError status line and URL with the explainer line cut off; no driver and no key
        ('_status_line', 'text = str(exc)'): 1,
        # a parameter named error holding a text its caller made through record_text; not an exception here
        ('is_context_overflow', 'if error is None:'): 1,
        # read for a keyword to CLASSIFY the failure (callers pass the caught exception, triage_job and source_tags_job among them); the variable is followed by test_a_classification_read_of_the_exceptions_text_only_searches_it
        ('is_context_overflow', 'text = str(error).lower()'): 1,
    },
    'src/llm/vllm_client.py': {
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('VllmClient.generate', 'if exc.response.status_code == 404:'): 1,
        # the SERVER'S OWN words of an HTTP status error (a response body or reason phrase, never a driver's or a held key); the exception is httpx's
        ('VllmClient.generate', 'raise LLMError(f"vLLM error for model {model!r}: {_http_error_text(exc)}")'): 1,
    },
    'src/llm/vllm_lifecycle.py': {
        # an exception handed on in an object / a text already made by the caller from record_text; not made here
        ('record_install_attempt', '"error": (str(error)[:500] if error else None),'): 2,
        # an exception handed on in an object / a text already made by the caller from record_text; not made here
        ('run_install_job._journal', 'error=error,'): 1,
    },
    'src/markets/csv_feeds.py': {
        # read for a keyword to CLASSIFY the failure; the text goes nowhere
        ('classify_fetch_failure', 'low = str(exc).lower()'): 1,
        # classify_fetch_failure returns a verdict and a note whose exception text is record_text (markets/csv_feeds.py)
        ('import_feed', 'verdict, note, retryable = classify_fetch_failure(exc)'): 1,
    },
    'src/osm/view.py': {
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('parse_bbox', 'for v in (w, s, e, n):'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('parse_bbox', 'if not (w < e and s < n):'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('parse_bbox', 'return w, s, e, n'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('parse_bbox', 'w, e = max(-180.0, w), min(180.0, e)'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('view', 'cw, ch = (e - w) / CLUSTER_GRID, (n - s) / CLUSTER_GRID'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('view', 'out: dict[str, Any] = {"bbox": [w, s, e, n], "caps": caps()}'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('view', 'p = {"w": w, "s": s, "e": e, "n": n}'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('view', 'tol = (e - w) / SIMPLIFY_PX'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('view', 'w, s, e, n = parse_bbox(w, s, e, n)'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('view', 'want = (e - w) / CLUSTER_GRID'): 1,
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('view', '{"lv": lv, "x0": int((w + 180) // sz), "x1": int((e + 180) // sz),'): 1,
    },
    'src/safety/fetcher.py': {
        # a fixed sentence of that function, never the URL
        ('refuse_unlisted_host', 'raise RedirectRefused(str(exc)) from None  # a fixed sentence of that function, never the URL'): 1,
    },
    'src/safety/settings.py': {
        # classifies the exception (a bool, an errno, a status code, an enum): no text of it is written
        ('_read_raw_strict', 'raise refused(exc)'): 3,
    },
    'src/timemap/datediag.py': {
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('recall_probe._adjacent_to_a_date', 'or (e <= ks and _APPOS_BRIDGE.fullmatch(text, e, ks)))'): 2,
    },
    'src/timemap/dateextract.py': {
        # a variable named e that is not an exception (a dict / an east bound) in a file that also catches one elsewhere
        ('_extract._appositive_of_claimed', 'right_start = e + (len(text[e:]) - len(text[e:].lstrip(seps)))'): 3,
    },
    'src/weather/openmeteo.py': {
        # classify_fetch_failure returns a verdict and a note whose exception text is record_text (markets/csv_feeds.py)
        ('fetch_daily_slice', 'verdict, note, retryable = classify_fetch_failure(exc)'): 1,
    },
}
_S5_NOT_RECORDS: dict[str, dict[str, int]] = {
    'src/ai_layer/coordinator.py': {
        'getattr reaches m.enabled_key, a way round the scan of the log calls': 1,
    },
    'src/ai_layer/langdetect_llm.py': {
        'res.error is kept as a name, a log call the scan cannot read': 4,
    },
    'src/ai_layer/perception_extract.py': {
        'res.error is kept as a name, a log call the scan cannot read': 2,
    },
    'src/ai_layer/triage.py': {
        'getattr reaches f, a way round the scan of the log calls': 1,
    },
    'src/analytics/perception_eval.py': {
        'getattr reaches fld, a way round the scan of the log calls': 1,
    },
    'src/analytics/reindex_parallel.py': {
        'd.error is kept as a name, a log call the scan cannot read': 1,
    },
    'src/analytics/store.py': {
        'deriv.error is kept as a name, a log call the scan cannot read': 1,
    },
    'src/briefing/card.py': {
        'getattr reaches name, a way round the scan of the log calls': 2,
    },
    'src/briefing/registry.py': {
        'getattr reaches name, a way round the scan of the log calls': 1,
    },
    'src/catalog/qualification_merge.py': {
        'zlib.error is kept as a name, a log call the scan cannot read': 2,
    },
    'src/config/app_settings.py': {
        'getattr reaches _name, a way round the scan of the log calls': 2,
    },
    'src/geo/osm_downloads.py': {
        'e.error is kept as a name, a log call the scan cannot read': 5,
        'self.error is kept as a name, a log call the scan cannot read': 1,
    },
    'src/law/track.py': {
        'getattr reaches field, a way round the scan of the log calls': 1,
    },
    'src/markets/extract.py': {
        're.error is kept as a name, a log call the scan cannot read': 1,
    },
    'src/osm/completeness.py': {
        'row.error is kept as a name, a log call the scan cannot read': 1,
        'r.error is kept as a name, a log call the scan cannot read': 1,
    },
    'src/osm/history.py': {
        'self.error is kept as a name, a log call the scan cannot read': 1,
        'report.error is kept as a name, a log call the scan cannot read': 2,
        'r.error is kept as a name, a log call the scan cannot read': 1,
    },
    'src/osm/ingest.py': {
        'self.error is kept as a name, a log call the scan cannot read': 1,
        'report.error is kept as a name, a log call the scan cannot read': 2,
        "getattr reaches T.column_name('name'), a way round the scan of the log calls": 1,
    },
    'src/osm/reference_run.py': {
        'getattr reaches name, a way round the scan of the log calls': 2,
        'p.info is kept as a name, a log call the scan cannot read': 2,
    },
    'src/safety/crypto.py': {
        'struct.error is kept as a name, a log call the scan cannot read': 2,
    },
    'src/utils/access_log.py': {
        'sys.exc_info() reads the exception being handled': 1,
    },
    'src/versioned/budget.py': {
        'getattr reaches row.setting, a way round the scan of the log calls': 1,
    },
}
CLASSIFIED.update(_S5_CLASSIFIED)
NOT_RECORDS.update(_S5_NOT_RECORDS)


# --- ``withheld=`` is a FIXED sentence ----------------------------------------------------------------------------------------------
# ``exception_text``/``record_text``/``http_detail`` return ``withheld`` UNSCRUBBED exactly when the scrub fails, so a ``withheld`` made
# from the exception would write the words of the failure at the one moment nothing can check them.


def _withheld_values(source: str) -> list[ast.expr]:
    return [
        kw.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "withheld"
    ]


def _module_strings(source: str) -> dict[str, bool]:
    """Module-level names bound once to a PLAIN string literal (no f-string, no call, no concatenation): name -> True."""
    out: dict[str, bool] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    return out


def _imported_strings(source: str, name: str) -> bool:
    """``name`` imported ``from src.x import name``: it must be a plain string literal there, at module level."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src") and any((a.asname or a.name) == name for a in node.names):
            target = ROOT / (node.module.replace(".", "/") + ".py")
            if not target.exists():
                target = ROOT / node.module.replace(".", "/") / "__init__.py"
            real = next(a.name for a in node.names if (a.asname or a.name) == name)
            return target.exists() and _module_strings(target.read_text(encoding="utf-8")).get(real, False)
    return False


def _is_fixed(value: ast.expr, source: str = "") -> bool:
    """Default-deny: a string literal, or a NAME that resolves (in this module or the ``src`` module it is imported from) to a module-level
    PLAIN string literal. An UPPER_CASE spelling proves nothing: ``NOTE = f"{exc}"`` is a name too."""
    if isinstance(value, ast.Constant):
        return isinstance(value.value, str) or value.value is None
    if isinstance(value, ast.Name) and source:
        here = _module_strings(source)
        return here[value.id] if value.id in here else _imported_strings(source, value.id)
    return False


#: Where the value is only PASSED THROUGH the helpers' own signatures (the caller's fixed sentence, or the class name the scrub
#: itself derives): ``secret_scrub.py`` and nowhere else.
_WITHHELD_PASS_THROUGH = "src/monitoring/secret_scrub.py"


def test_every_withheld_argument_in_src_is_a_literal_or_a_module_constant():
    bad: list[str] = []
    seen = 0
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == _WITHHELD_PASS_THROUGH:
            continue
        text = path.read_text(encoding="utf-8")
        for value in _withheld_values(text):
            seen += 1
            if not _is_fixed(value, text):
                bad.append(f"{rel}:{value.lineno}: {ast.unparse(value)}")
    assert seen >= 8, f"the walk found {seen} withheld= sites, and 8 are known: a walk over nothing proves nothing"
    assert bad == [], "withheld= must be a fixed sentence (a literal or an UPPER_CASE constant), never made from the exception"


_CONTROL_SOURCE = (
    "from src.monitoring.secret_scrub import UNREADABLE_TEXT\n"
    "SENTENCE = 'its text is withheld'\n"
    "NOTE = f'{exc}'\n"
    "BUILT = 'a ' + str(exc)\n"
    "def f(sentence):\n    pass\n"
)


@pytest.mark.parametrize(
    "value, fixed",
    [
        ('"its text is withheld"', True),
        ("UNREADABLE_TEXT", True),
        ("SENTENCE", True),
        ("NOTE", False),  # an UPPER_CASE name bound to an f-string
        ("BUILT", False),  # ... to a concatenation
        ("UNKNOWN_CONSTANT", False),  # a name that resolves to nothing
        ('f"{type(exc).__name__}"', False),
        ("str(exc)", False),
        ("sentence", False),
        ('"a " + str(exc)', False),
        ('"{}".format(exc)', False),
    ],
)
def test_the_withheld_guard_tells_a_fixed_sentence_from_one_made_of_the_exception(value, fixed):
    (node,) = _withheld_values(f"http_detail(exc, withheld={value})")
    assert _is_fixed(node, _CONTROL_SOURCE) is fixed


# --- withheld=UNREADABLE_TEXT is kept where a route had it: pinned as exact sets -------------------------------------------------------


def _secret_carrying_http_detail_calls() -> dict[tuple[str, str], bool]:
    """(file, enclosing function, line text) -> whether the call names ``withheld=``, for every ``http_detail`` in src/api that is handed a
    secret (a third positional argument)."""
    found: dict[tuple[str, str], bool] = {}
    for path in sorted((ROOT / "src/api").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        parent = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "http_detail" and len(node.args) >= 3:
                fn = node
                while fn in parent and not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                    fn = parent[fn]
                name = fn.name if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) else ""
                key = (path.relative_to(ROOT).as_posix(), f"{name}:{node.lineno}")
                found[key] = any(k.arg == "withheld" for k in node.keywords)
    return found


def test_the_fixed_unreadable_text_sentence_is_kept_at_exactly_the_sites_that_had_it():
    """Both ways, by (file, function) with a count: a site that loses ``withheld=`` fails, and so does one that gains it unrecorded."""
    from collections import Counter

    calls = _secret_carrying_http_detail_calls()
    kept = Counter((rel, fn.split(":")[0]) for (rel, fn), has in calls.items() if has)
    assert kept == Counter(
        {
            ("src/api/diagnostics/p0.py", "p0_validation_start"): 1,
            ("src/api/diagnostics/release_run.py", "release_run_resume"): 1,
            ("src/api/diagnostics/release_run.py", "release_run_start"): 1,
            ("src/api/ingestion.py", "ingest_email_endpoint"): 1,
            ("src/api/safety.py", "encrypted_backup"): 1,
            ("src/api/unlock.py", "_close_after_checkpoint"): 1,
            ("src/api/unlock.py", "_file_opens_with"): 1,
            ("src/api/unlock.py", "_unlock_locked"): 1,
            ("src/api/unlock.py", "encrypt_db"): 1,
        }
    )
    lacking = Counter((rel, fn.split(":")[0]) for (rel, fn), has in calls.items() if not has)
    assert set(lacking) == {
        ("src/api/backup_v2.py", name)
        for name in ("_stage_upload", "import_queue_start", "restore_legacy_path", "volume_backup_restore", "volume_backup_start", "volume_backup_verify")
    } | {("src/api/diagnostics/release_run.py", "release_run_start"), ("src/api/ingestion.py", "_mailbox_pull_worker")}


# --- the helpers the api guard trusts BY NAME are pinned default-deny ------------------------------------------------------------------
# ``_err_str``, ``_all_diag_err_str``, ``_record_text`` and ``_restore_error`` are credited as scrubbing calls in every module. A rename or
# a body edit that stops them routing through the scrub would open every site that calls them, so each is held to two things: its body
# is ONE return of a call into the scrub (or into another pinned helper) and uses the exception nowhere else, and behaviourally a driver's
# words and a held passphrase planted in an exception never come out.

_PINNED = {
    # (file, qualified name) -> the callees its single return may be
    ("src/api/diagnostics/bundle.py", "_all_diag_err_str"): {"_record_text"},
    ("src/api/diagnostics/bundle.py", "_err_str"): {"_all_diag_err_str"},
    ("src/api/backup_v2.py", "_restore_error"): {"restore_failure_text"},
}


def _function(source: str, name: str) -> ast.FunctionDef:
    return next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name)


def _pinned_body_ok(source: str, name: str, allowed: set[str]) -> bool:
    """The function is its docstring, imports, and ONE ``return`` in which the exception is an argument of a call to an ``allowed`` scrub
    and is used nowhere else in the function (no ``str()``, f-string, attribute read, second return or copy)."""
    fn = _function(source, name)
    exc_param = fn.args.args[-1 if name == "_err_str" else (1 if name == "_restore_error" else 0)].arg
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)) and not isinstance(n, ast.ImportFrom | ast.Import)]
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return False
    uses = [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == exc_param]
    fed = [
        c
        for c in ast.walk(body[0])
        if isinstance(c, ast.Call)
        and getattr(c.func, "id", None) in allowed
        and any(isinstance(a, ast.Name) and a.id == exc_param for a in c.args)
    ]
    return len(uses) == 1 and len(fed) == 1


@pytest.mark.parametrize(("rel", "name"), sorted(_PINNED))
def test_a_helper_the_api_guard_trusts_by_name_is_still_one_call_into_the_scrub(rel, name):
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert _pinned_body_ok(source, name, _PINNED[(rel, name)]), f"{rel}:{name} no longer routes its exception straight into the scrub"


@pytest.mark.parametrize(
    "mutant",
    [
        "def _err_str(exc) -> str:\n    return str(exc)",
        "def _err_str(exc) -> str:\n    return f'{exc}'",
        "def _err_str(exc) -> str:\n    return _all_diag_err_str(exc) + str(exc)",
        "def _err_str(exc) -> str:\n    text = _all_diag_err_str(exc)\n    return text",
        "def _err_str(exc) -> str:\n    return repr(exc)",
        "_err_str = str",
    ],
)
def test_the_pin_fails_for_each_way_a_trusted_helper_can_start_returning_the_exception(mutant):
    try:
        ok = _pinned_body_ok(mutant, "_err_str", {"_all_diag_err_str"})
    except StopIteration:  # the name is gone: a rename the pin cannot miss, because the real read raises the same way
        ok = False
    assert ok is False


def test_the_trusted_helpers_never_return_a_drivers_words_or_a_held_passphrase(monkeypatch):
    import sqlite3

    from sqlalchemy.exc import OperationalError

    from src.api.backup_v2 import _restore_error
    from src.api.diagnostics.bundle import _all_diag_err_str
    from src.database import connect

    secret = "hunter2" + "Zq8Lm_tbl"
    monkeypatch.setattr(connect, "_passphrase", "kQ7!vLm-held-key")
    driver = OperationalError("SELECT 1 WHERE k = ?", (secret,), sqlite3.OperationalError(f"no such table: {secret}"))
    plain = ValueError("failed with kQ7!vLm-held-key inside")
    for exc in (driver, plain):
        outs = [_all_diag_err_str(exc), _all_diag_err_str(exc, typed=True), str(_restore_error("restore", exc).detail)]
        for out in outs:
            assert secret not in out and "kQ7!vLm-held-key" not in out, out


def test_the_record_text_alias_the_bundle_trusts_is_the_real_record_text():
    from src.api.diagnostics import bundle
    from src.monitoring import secret_scrub

    assert bundle._record_text is secret_scrub.record_text


def test_engine_text_and_bounded_error_never_return_a_drivers_words_or_a_held_passphrase(monkeypatch):
    """Both are credited as scrubbing calls by name (CALLS): each is held to the same two things as the api helpers."""
    import sqlite3

    from src.database import connect
    from src.llm.ollama import bounded_error
    from src.monitoring.engine_text import engine_text

    secret = "hunter2" + "Zq8Lm_tbl"
    monkeypatch.setattr(connect, "_passphrase", "kQ7!vLm-held-key")
    for exc in (sqlite3.OperationalError(f"no such table: {secret}"), ValueError("with kQ7!vLm-held-key inside")):
        for out in (engine_text(exc), engine_text(exc, 200, typed=True), bounded_error(exc, 200)):
            assert secret not in out and "kQ7!vLm-held-key" not in out, out


# --- an excused classification read is followed to where its text goes ---------------------------------------------------------------
# ``said = str(exc).lower()`` is excused by its exact line because the text is only searched for keywords; the scan does not follow the
# variable, so THIS test does: every load of it must be an operand of ``in``/``not in`` or the receiver of a search method.
_TEXT_READS = (
    ("src/analytics/keyword_log_scan.py", "_refuse_when_the_disk_is_full", "said"),
    ("src/markets/csv_feeds.py", "classify_fetch_failure", "low"),
    ("src/llm/ollama.py", "is_context_overflow", "text"),
)
_SEARCH_METHODS = {"startswith", "endswith", "find", "count", "index"}


@pytest.mark.parametrize(("rel", "func", "var"), _TEXT_READS, ids=[f"{r}:{v}" for r, _f, v in _TEXT_READS])
def test_a_classification_read_of_the_exceptions_text_only_searches_it(rel, func, var):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func)
    parent = {c: n for n in ast.walk(fn) for c in ast.iter_child_nodes(n)}
    loads = [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == var and isinstance(n.ctx, ast.Load)]
    assert loads, f"{rel}:{func} no longer reads {var!r}: drop the entry"
    for use in loads:
        up = parent.get(use)
        in_test = isinstance(up, ast.Compare) and all(isinstance(op, (ast.In, ast.NotIn)) for op in up.ops) and use in up.comparators
        call = parent.get(up)
        search = isinstance(up, ast.Attribute) and up.attr in _SEARCH_METHODS and isinstance(call, ast.Call) and call.func is up
        assert in_test or search, f"{rel}:{use.lineno} {var!r} (a caught exception's text) is used other than to search it"
