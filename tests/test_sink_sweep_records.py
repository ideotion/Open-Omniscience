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
         "record_text", "record_traceback", "unicode_note", "is_driver_error","quotes_a_driver","is_locked_error","_is_integrity_error", "restore_failure_text", "is_corruption"}
MODULES = sorted(
    p.relative_to(ROOT).as_posix()
    for entry in ("src/scheduler", "src/wiki")
    for p in (ROOT / entry).rglob("*.py")
) + sorted(
    p.relative_to(ROOT).as_posix() for entry in ("src/backup", "src/ingest", "src/database") for p in (ROOT / entry).rglob("*.py")
) + sorted(
    p.relative_to(ROOT).as_posix() for p in (ROOT / "src/monitoring").rglob("*.py") if p.name != "secret_scrub.py"
) + ["src/api/unlock.py"]

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

#: Operator-facing text that nothing stores: the unlock answer and the start-up status the lock screen shows, a dump lookup's HTTP
#: answer, a tracker error that only reaches ``log_failure``, a malformed-query refusal. The words are scrubbed (``exception_text``);
#: a record written from the same function is not in this table.
_UNLOCK_DETAIL = "detail=exception_text("
KEPT: dict[str, dict[tuple[str, str], int]] = {
    "src/api/unlock.py": {
        # One WARNING line (the class and the scrubbed FIRST line, never the statement or a trailing line): the log, not a record.
        ("_close_after_checkpoint", 'said = exception_text(exc, passphrase, typed=False, withheld="its text is withheld")'): 1,
        ("_finish_unlock", 'set_startup("ready", "", error=exception_text(exc, typed=False))'): 1,
        ("_finish_unlock._upkeep", 'set_startup("ready", "", error=exception_text(exc, typed=False))'): 1,
        ("_file_opens_with", _UNLOCK_DETAIL): 1,
        ("_unlock_locked", _UNLOCK_DETAIL): 1,
        (
            "encrypt_db",
            "raise HTTPException(status_code=400, detail=exception_text(exc, body.passphrase, typed=False, withheld=UNREADABLE_TEXT)) from None",
        ): 1,
    },
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
    'src/monitoring/keyword_write_cost.py': {  # engine_text is record_text (a driver by class only)
        ('_cut_reason', 'return f"stopped before the sample finished, by the {why} ({engine_text(exc)})"'): 1,
        ('keyword_write_cost', 'cut = _cut_reason(exc)'): 1,
        ('keyword_write_cost', '_LOG.debug("keyword write cost unavailable: %s", engine_text(exc, typed=True))'): 1,
        ('keyword_write_cost', 'out["reason"] = f"unreadable: {engine_text(exc, 200)}"'): 1,
        ('_write_rate', 'out[key] = {"available": False, "reason": f"stopped by the {why} ({engine_text(exc)})"}'): 1,
        ('_write_rate', 'out[key] = {"available": False, "reason": f"unreadable: {engine_text(exc, 160)}"}'): 1,
    },
    'src/monitoring/llm_bench.py': {  # bounded_error scrubs through record_text before its cut (no database call can raise in the bench)
        ('_one_call', '"error": bounded_error(exc, 200),'): 1,
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

CLASSIFIED.update(_MONITORING_CLASSIFIED)
NOT_RECORDS.update(_MONITORING_NOT_RECORDS)



def _found(rel: str, source: str) -> list[str]:
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
