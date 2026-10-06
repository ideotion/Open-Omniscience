"""The volume job's own error handlers: every secret the job was handed is out of what they write.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A backup, a restore and a verify are each handed the passphrase (a restore a second one, the corpus's), and each catches
``Exception`` with it in scope. What a handler writes about the failure is the exception's own words: the status that
``GET /api/backup/v2/volumes/status`` serves and the task manager's job list reads, the log, and the run journal's message
and traceback. No message on that path names a passphrase today (every ``EncryptionError`` on the decrypt path is a
literal), which is the case the rule calls "no trigger today": no path that can carry a passphrase into an API response, a
log or a file is left to chance. So every text is scrubbed where it is made, and any cut is made after the scrub (a cut
text could split the secret and leave its half). These tests give the engine a message that DOES name the secrets, in the
exception and in the cause of a chain, and read everything the failure wrote: the status, every log record and every file
of the run journal. The helpers they write through are ``secret_scrub.scrubbed``, ``traceback_text`` and
``log_failure`` (tested in ``tests/test_secret_scrub.py``); the static walk that holds the next handler to the same rule is in
``tests/test_p0_validation.py`` (``_GUARDED_MODULES``).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import traceback
from pathlib import Path

import pytest

from src.backup import runlog
from src.backup.merge import MergeError, RestoreAborted, RestoreRefused
from src.backup.volume_job import VolumeBackupManager
from src.monitoring.secret_scrub import REDACTED
from tests.backup_helper import staged_artifact as _staged
from tests.test_volume_job import _own_the_machine, _wait

PASS = "kQ7!vLm-the-artifact-key"
CORPUS = "zR4#nPt-the-corpus-key"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch, caplog):
    """A run journal of the test's own to read, and a log that keeps the INFO line of a stopped restore."""
    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path / "run_logs")
    monkeypatch.setenv("OO_RUN_JOURNAL", "1")
    runlog._CURRENT = None
    caplog.set_level(logging.DEBUG, logger="src.backup.volume_job")
    yield
    cur = runlog._CURRENT
    if cur is not None:
        cur.end("test-teardown")
    runlog._CURRENT = None


def _journal(tmp_path: Path) -> list[dict]:
    """Every milestone and end record of every run the test wrote."""
    out: list[dict] = []
    for path in sorted((tmp_path / "run_logs").glob("*.jsonl")):
        if path.name.endswith(".beat.jsonl"):
            continue
        out += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


def _everything_written(mgr: VolumeBackupManager, caplog, tmp_path: Path) -> str:
    """The status an endpoint serves, every log record as a handler would format it, and every file of the run journal
    (the beats too), as one text: where a secret that got out would be."""
    records = [f"{r.getMessage()}\n{r.exc_text or ''}\n{r.exc_info!r}" for r in caplog.records]
    files = [p.read_text(encoding="utf-8") for p in sorted((tmp_path / "run_logs").glob("*.jsonl"))]
    return "\n".join([json.dumps(mgr.status(), default=str), *records, *files])


def _error_record(tmp_path: Path) -> dict:
    found = [r for r in _journal(tmp_path) if r["ev"] == "error"]
    assert len(found) == 1, found
    return found[0]


def _message_of(caplog, fragment: str) -> str:
    found = [r.getMessage() for r in caplog.records if fragment in r.getMessage()]
    assert len(found) == 1, found
    return found[0]


# --------------------------------------------------------------------------- #
# A backup
# --------------------------------------------------------------------------- #
def _backup_that_raises(tmp_path: Path, exc: BaseException) -> VolumeBackupManager:
    def fake(dest, pw, **k):
        raise exc

    mgr = VolumeBackupManager()
    mgr.start_backup(str(tmp_path / "d"), PASS, _backup_fn=fake)
    _wait(mgr)
    return mgr


def test_a_failed_backup_writes_no_passphrase_to_its_status_its_log_or_its_journal(tmp_path, caplog):
    mgr = _backup_that_raises(tmp_path, RuntimeError(f"could not seal the set with {PASS} on this drive"))
    st = mgr.status()
    assert st["state"] == "error"
    assert st["error"] == f"could not seal the set with {REDACTED} on this drive"
    assert PASS not in _everything_written(mgr, caplog, tmp_path)
    record = _error_record(tmp_path)
    assert record["cls"] == "RuntimeError"
    assert record["msg"] == f"could not seal the set with {REDACTED} on this drive"
    assert f"RuntimeError: could not seal the set with {REDACTED}" in record["traceback"]
    assert f"RuntimeError: could not seal the set with {REDACTED}" in _message_of(caplog, "volume backup failed")


def test_a_failed_backup_scrubs_the_cause_of_a_chain_in_the_log_and_the_journal(tmp_path, caplog):
    try:
        try:
            raise ValueError(f"the key {PASS} did not open the header")
        except ValueError as inner:
            raise RuntimeError("the volume could not be written") from inner
    except RuntimeError as outer:
        mgr = _backup_that_raises(tmp_path, outer)
    assert PASS not in _everything_written(mgr, caplog, tmp_path)
    for text in (_error_record(tmp_path)["traceback"], _message_of(caplog, "volume backup failed")):
        assert f"ValueError: the key {REDACTED} did not open the header" in text
        assert "RuntimeError: the volume could not be written" in text


def test_a_failed_backup_cuts_the_journal_message_after_the_scrub_and_not_before_it(tmp_path, caplog):
    """The message is cut at 2000 characters. Cut first and a secret that straddles the cut would leave its first half in
    the journal, which no scrub of the whole secret would find."""
    lead = "x" * 1995
    mgr = _backup_that_raises(tmp_path, RuntimeError(lead + PASS + " and then some"))
    msg = _error_record(tmp_path)["msg"]
    assert msg == (lead + REDACTED + " and then some")[:2000]
    assert PASS[:5] not in msg and PASS not in _everything_written(mgr, caplog, tmp_path)


def test_a_failed_backup_cuts_the_journal_traceback_after_the_scrub_and_not_before_it(tmp_path, caplog):
    """The traceback keeps its last 8000 characters. The message below ends 10 characters after the secret does, so an
    unscrubbed tail would start 10 characters before the secret's end and leave its last 10 characters in the journal."""
    mgr = _backup_that_raises(tmp_path, RuntimeError(PASS + "y" * 7989))
    tail = _error_record(tmp_path)["traceback"]
    assert len(tail) <= 8000 and tail.rstrip().endswith("y" * 100)
    assert PASS[-10:] not in tail and PASS not in _everything_written(mgr, caplog, tmp_path)


def test_a_destination_that_cannot_be_made_names_no_passphrase_and_carries_no_cause(tmp_path, monkeypatch):
    dest = tmp_path / "sets"
    real_mkdir = Path.mkdir

    def refuse(self, *args, **kwargs):
        if self == dest:
            raise OSError(f"the volume refused the key {PASS}")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", refuse)
    mgr = VolumeBackupManager()
    with pytest.raises(ValueError) as caught:
        mgr.start_backup(str(dest), PASS)
    assert str(caught.value) == f"Cannot use destination {dest}: the volume refused the key {REDACTED}"
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert PASS not in "".join(traceback.format_exception(caught.value))
    assert not mgr.status()["running"], "a refused start leaves nothing running"


# --------------------------------------------------------------------------- #
# A restore, through the injected engine (every handler at the end of the runner)
# --------------------------------------------------------------------------- #
def _restore_that_raises(tmp_path: Path, exc: BaseException) -> VolumeBackupManager:
    src = tmp_path / "src"
    src.mkdir()

    def fake(s, pw):
        raise exc

    mgr = VolumeBackupManager()
    mgr.start_restore(str(src), PASS, corpus_passphrase=CORPUS, _restore_fn=fake)
    _wait(mgr)
    return mgr


_FAILURES = {
    "a failure of the engine": (RuntimeError(f"unlock failed: {PASS}, then {CORPUS}"), "error"),
    "a merge refusal": (MergeError(f"refusing: {PASS} and {CORPUS} do not match this corpus"), "error"),
    "a constraint clash the classifier describes": (
        sqlite3.IntegrityError(f"UNIQUE constraint failed: notes.{PASS}, notes.{CORPUS}"),
        "error",
    ),
    "a refusal before the swap": (RestoreRefused(f"another job holds the corpus ({PASS}, {CORPUS})"), "error"),
    "a stop by the operator": (RestoreAborted(f"stopped before the swap ({PASS}, {CORPUS})"), "cancelled"),
}


@pytest.mark.parametrize("failure", sorted(_FAILURES))
def test_a_failed_restore_writes_neither_passphrase_to_its_status_its_log_or_its_journal(tmp_path, caplog, failure):
    exc, state = _FAILURES[failure]
    mgr = _restore_that_raises(tmp_path, exc)
    st = mgr.status()
    assert st["state"] == state
    written = _everything_written(mgr, caplog, tmp_path)
    assert PASS not in written and CORPUS not in written
    assert REDACTED in written, "the texts are scrubbed, not dropped"
    if state == "error":
        assert REDACTED in st["error"]
    else:
        assert st["error"] is None and REDACTED in st["progress"]["detail"]


def test_a_failed_restore_journals_a_scrubbed_message_and_traceback_and_keeps_the_words_around_the_secrets(
    tmp_path, caplog
):
    mgr = _restore_that_raises(tmp_path, RuntimeError(f"unlock failed: {PASS}, then {CORPUS}"))
    record = _error_record(tmp_path)
    assert record["cls"] == "RuntimeError"
    assert record["msg"] == f"unlock failed: {REDACTED}, then {REDACTED}"
    assert f"RuntimeError: unlock failed: {REDACTED}, then {REDACTED}" in record["traceback"]
    assert f"RuntimeError: unlock failed: {REDACTED}, then {REDACTED}" in _message_of(caplog, "volume restore failed")
    assert mgr.status()["error"].count(REDACTED) == 2


def test_a_merge_refusal_keeps_its_own_message_with_the_secrets_out(tmp_path):
    mgr = _restore_that_raises(tmp_path, MergeError(f"refusing: {PASS} does not match"))
    assert mgr.status()["error"] == f"refusing: {REDACTED} does not match"


def test_a_refused_restore_cuts_its_detail_after_the_scrub_and_not_before_it(tmp_path, caplog):
    """The detail the journal ends the run with is cut at 500 characters; the status carries the whole scrubbed text."""
    lead = "x" * 497
    mgr = _restore_that_raises(tmp_path, RestoreRefused(lead + CORPUS + " is held"))
    ended = [r for r in _journal(tmp_path) if r.get("outcome") == "refused" or r.get("ev") == "end"]
    detail = " ".join(str(r.get("detail", "")) for r in ended)
    assert (lead + REDACTED)[:500] in detail
    assert CORPUS[:4] not in detail and CORPUS not in _everything_written(mgr, caplog, tmp_path)
    assert mgr.status()["error"] == lead + REDACTED + " is held"


# --------------------------------------------------------------------------- #
# A restore, through the whole runner (the courtesy handlers and the file placement)
# --------------------------------------------------------------------------- #
def _restore_through_the_runner(monkeypatch, tmp_path: Path, *, pause=None, resume=None, place=None):
    """A restore with the engine's merge stubbed to succeed, so that what fails is the one thing the test names."""
    import src.backup.artifact as artifact_mod
    import src.backup.folder_backup as fb_mod
    import src.backup.merge as merge_mod
    import src.scheduler.runner as sched_mod

    staged = _staged(tmp_path / "staging")
    if place is not None:
        staged.file_members = [{"name": "blobs/wiki_dumps/x", "category": "wiki_dumps", "rel": "x"}]
        monkeypatch.setattr(fb_mod, "place_artifact_file_members", place)
    monkeypatch.setattr(sched_mod, "pause_for_exclusive_operation", pause or (lambda timeout=10.0: True))
    monkeypatch.setattr(sched_mod, "resume_after_exclusive_operation", resume or (lambda was_paused: None))
    _own_the_machine(monkeypatch, False)
    monkeypatch.setattr(artifact_mod, "read_volume_backup", lambda *a, **k: staged)
    monkeypatch.setattr(artifact_mod, "cleanup_staging", lambda s: None)
    monkeypatch.setattr(merge_mod, "run_restore", lambda *a, **k: {"committed": True})
    src = tmp_path / "src"
    src.mkdir()
    mgr = VolumeBackupManager()
    mgr.start_restore(str(src), PASS, corpus_passphrase=CORPUS)
    _wait(mgr)
    return mgr


def test_a_pause_that_names_the_secrets_is_logged_with_them_out_and_never_aborts_the_restore(
    tmp_path, monkeypatch, caplog
):
    def pause(timeout=10.0):
        raise RuntimeError(f"the scheduler refused {PASS} and {CORPUS}")

    mgr = _restore_through_the_runner(monkeypatch, tmp_path, pause=pause)
    assert mgr.status()["state"] == "done"
    written = _everything_written(mgr, caplog, tmp_path)
    assert PASS not in written and CORPUS not in written
    record = next(r for r in caplog.records if "pausing background collection" in r.getMessage())
    assert record.levelno == logging.WARNING
    assert f"RuntimeError: the scheduler refused {REDACTED} and {REDACTED}" in record.getMessage()


def test_a_resume_that_names_the_secrets_is_logged_with_them_out_and_never_costs_the_restore(
    tmp_path, monkeypatch, caplog
):
    def resume(was_paused):
        raise RuntimeError(f"the scheduler refused {CORPUS} and {PASS}")

    mgr = _restore_through_the_runner(monkeypatch, tmp_path, resume=resume)
    assert mgr.status()["state"] == "done"
    written = _everything_written(mgr, caplog, tmp_path)
    assert PASS not in written and CORPUS not in written
    record = next(r for r in caplog.records if "resuming background collection" in r.getMessage())
    assert record.levelno == logging.WARNING
    assert f"RuntimeError: the scheduler refused {REDACTED} and {REDACTED}" in record.getMessage()


def test_a_failed_file_placement_reports_and_logs_with_the_secrets_out_and_the_restore_stays_done(
    tmp_path, monkeypatch, caplog
):
    def place(*args, **kwargs):
        raise OSError(f"the drive refused {CORPUS} and {PASS} while placing the files")

    mgr = _restore_through_the_runner(monkeypatch, tmp_path, place=place)
    st = mgr.status()
    assert st["state"] == "done", "a good merge is not thrown away over a file copy"
    placed = st["summary"]["report"]["file_members"]
    assert placed["placed"] == 0
    assert placed["error"] == f"the drive refused {REDACTED} and {REDACTED} while placing the files"
    written = _everything_written(mgr, caplog, tmp_path)
    assert PASS not in written and CORPUS not in written
    record = next(r for r in caplog.records if "placing the artifact's large files failed" in r.getMessage())
    assert record.levelno == logging.WARNING and REDACTED in record.getMessage()


# --------------------------------------------------------------------------- #
# A verify
# --------------------------------------------------------------------------- #
def _verify_that_raises(tmp_path: Path, exc: BaseException, passphrase: str | None) -> VolumeBackupManager:
    src = tmp_path / "set"
    src.mkdir()

    def fake(s, pw):
        raise exc

    mgr = VolumeBackupManager()
    mgr.start_verify(str(src), passphrase, _verify_fn=fake)
    _wait(mgr)
    return mgr


def test_a_failed_verify_writes_no_passphrase_to_its_status_or_its_log(tmp_path, caplog):
    mgr = _verify_that_raises(tmp_path, RuntimeError(f"every volume refused {PASS}"), PASS)
    st = mgr.status()
    assert st["state"] == "error" and st["error"] == f"every volume refused {REDACTED}"
    assert PASS not in _everything_written(mgr, caplog, tmp_path)
    assert f"RuntimeError: every volume refused {REDACTED}" in _message_of(caplog, "volume verify failed")


def test_a_verify_given_no_passphrase_leaves_its_error_as_the_engine_wrote_it(tmp_path, caplog):
    mgr = _verify_that_raises(tmp_path, RuntimeError("the signature does not match"), None)
    st = mgr.status()
    assert st["state"] == "error" and st["error"] == "the signature does not match"
    assert "RuntimeError: the signature does not match" in _message_of(caplog, "volume verify failed")
