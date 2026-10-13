"""A failed run's journal line, log line and served error carry no passphrase (src/backup/runlog.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE SINKS. A failed run writes the exception's text and its traceback into its run journal
(``data/run_logs/*.jsonl``) and logs it (``data/app_errors.jsonl`` rides the debug bundle), and
stores the text as the job's ``error`` (served by the status endpoint). The text is the engine's
own and may quote what it was handed, so every writer goes through ``secret_scrub`` (``exception_text``, ``traceback_text``, ``scrubbed_value``): the
secrets are taken out in every form the code writes (as typed, SQL ''-doubled, JSON-escaped, repr)
BEFORE the cut, the result is checked once more, and a text that cannot be checked is withheld whole.
The log lines are written from those fields, never with ``exc_info`` or ``_LOG.exception``.

One test per writer, because each reaches the sink by its own branch: the volume backup, the volume
restore (two secrets), the volume verify, the newsletter import, and ``runlog.run`` itself.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from src.backup import runlog
from src.backup.volume_job import VolumeBackupManager

_PW = "pa'ss\"w;rd\\x"
_CORPUS_PW = "corpus'key\"two\\y"


def _forms(secret: str) -> list[str]:
    return [secret, secret.replace("'", "''"), json.dumps(secret)[1:-1], repr(secret)[1:-1]]


def _leaks(text: str, *secrets: str) -> list[str]:
    return [f for s in secrets for f in _forms(s) if f in text]


def _everything_written(caplog) -> str:
    """The journal files of the run, every log record (message and any attached traceback) and the
    saved queue state: what a debug bundle would carry."""
    parts = [caplog.text] + [str(r.exc_info) for r in caplog.records if r.exc_info]
    for p in runlog.run_logs_dir().glob("*.jsonl"):
        parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _quoting(secret: str, *more: str) -> RuntimeError:
    """An exception whose text quotes the secret the way an engine would, in several forms."""
    return RuntimeError("driver said: " + " | ".join(_forms(secret) + [m for s in more for m in _forms(s)]))


@pytest.fixture(autouse=True)
def _own_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("src.database.connect._passphrase", _CORPUS_PW)  # the passphrase the unlocked session holds


# ---------------------------------------------------------------------------------------------- #
#  the helper
# ---------------------------------------------------------------------------------------------- #
def _fields(exc, *secrets):
    """What ``runlog.run`` journals for a failure: the one scrub (``secret_scrub``), then the cut."""
    from src.monitoring.secret_scrub import exception_text, traceback_text

    return {
        "cls": type(exc).__name__,
        "msg": exception_text(exc, *secrets, typed=False, limit=runlog.FAILURE_MSG_KEEP),
        "traceback": traceback_text(exc, *secrets)[-runlog.FAILURE_TRACEBACK_KEEP :],
    }


def test_every_form_is_scrubbed_before_the_cut_and_the_cuts_say_what_they_protect():
    straddle = "x" * (runlog.FAILURE_MSG_KEEP - len(_PW) // 2) + _PW + " and more"
    out = _fields(RuntimeError(straddle), _PW)
    assert not _leaks(out["msg"] + out["traceback"], _PW, _CORPUS_PW)
    assert len(out["msg"]) <= runlog.FAILURE_MSG_KEEP and len(out["traceback"]) <= runlog.FAILURE_TRACEBACK_KEEP
    assert out["cls"] == "RuntimeError"
    # the process's own passphrase is always scrubbed, with or without being named
    out = _fields(_quoting(_CORPUS_PW))
    assert not _leaks(out["msg"] + out["traceback"], _CORPUS_PW)


def test_a_scrub_that_cannot_run_withholds_the_text(monkeypatch):
    import src.monitoring.secret_scrub as ss

    monkeypatch.setattr(ss, "_forms_now", lambda secrets: None)  # what the process holds cannot be read
    out = _fields(_quoting(_PW), _PW)
    assert "withheld" in out["msg"] and not _leaks(out["msg"] + out["traceback"], _PW)
    assert ss.scrubbed_value({"report": _PW}, _PW) == {"report": ss.UNREADABLE_TEXT}


def test_a_report_is_scrubbed_in_its_string_values_only_so_a_good_report_is_not_blanked(monkeypatch):
    """A passphrase form inside a report KEY, or a short numeric one that equals a count, is not text a
    secret was written into: the walk leaves both alone, and it would not turn the whole report into a
    withheld marker and lose it."""
    from src.monitoring.secret_scrub import scrubbed_value

    monkeypatch.setattr("src.database.connect._passphrase", None)
    report = {"batch_id": 7, f"k{_PW}": 1, "imported": 12, "problems": ["fine"], "nested": {"n": 12}}
    assert scrubbed_value(report, _PW, "12") == report
    # and a string VALUE that holds the secret is still scrubbed, not withheld
    out = scrubbed_value({"a": f"x {_PW} y"}, _PW)
    assert _PW not in json.dumps(out) and out["a"].startswith("x ")


# ---------------------------------------------------------------------------------------------- #
#  one test per writer
# ---------------------------------------------------------------------------------------------- #
def test_a_failed_volume_backup_writes_no_passphrase_to_the_journal_the_log_or_the_error(tmp_path, caplog):
    def fail(*_a, **_k):
        raise _quoting(_PW, _CORPUS_PW)

    mgr = VolumeBackupManager()
    with caplog.at_level(logging.DEBUG):
        mgr._run_backup(tmp_path / "drive", _PW, True, 0.1, [], False, fail)
    st = mgr.status()
    assert st["state"] == "error" and "driver said" in (st.get("error") or "")
    assert not _leaks(json.dumps(st) + _everything_written(caplog), _PW, _CORPUS_PW)
    assert not any(r.exc_info for r in caplog.records), "a raw traceback was logged"


def test_a_stopped_newsletter_free_backup_is_served_whole_even_if_the_passphrase_is_a_word_in_it(tmp_path):
    """The two sentences are the server's own fixed text; the page matches them whole, so scrubbing them
    for a passphrase that is a word in the sentence would redact the match and leave the user a broken
    notice (and a passphrase that is only a class name is not a leak: the sentence holds no user text)."""
    from src.backup.newsletter_export import MESSAGE_OTHER, MESSAGE_SPACE, NewsletterFilterRefused

    for refusal, said in (
        (NewsletterFilterRefused("there is not enough free space for the rewrite", space=True), MESSAGE_SPACE),
        (NewsletterFilterRefused("OSError", space=False), MESSAGE_OTHER.format(reason="OSError")),
    ):
        def fail(*_a, _r=refusal, **_k):
            raise _r

        mgr = VolumeBackupManager()
        mgr._run_backup(tmp_path / "drive", "newsletters", True, 0.1, [], False, fail)
        st = mgr.status()
        assert st["state"] == "error"
        assert st["error"] == said


def test_a_failed_volume_restore_writes_no_passphrase_of_either_kind(tmp_path, caplog):
    def fail(*_a, **_k):
        raise _quoting(_PW, _CORPUS_PW)

    mgr = VolumeBackupManager()
    with caplog.at_level(logging.DEBUG):
        mgr._run_restore(tmp_path / "set", _PW, False, _CORPUS_PW, fail)
    st = mgr.status()
    assert st["state"] == "error"
    assert not _leaks(json.dumps(st) + _everything_written(caplog), _PW, _CORPUS_PW)
    assert not any(r.exc_info for r in caplog.records)


def test_a_failed_volume_verify_writes_no_passphrase_to_the_log_or_the_error(tmp_path, caplog):
    def fail(*_a, **_k):
        raise _quoting(_PW)

    mgr = VolumeBackupManager()
    with caplog.at_level(logging.DEBUG):
        mgr._run_verify(tmp_path / "set", _PW, fail)
    st = mgr.status()
    assert st["state"] == "error" and "driver said" in (st.get("error") or "")
    assert not _leaks(json.dumps(st) + _everything_written(caplog), _PW)
    assert not any(r.exc_info for r in caplog.records)


def test_a_failed_newsletter_import_writes_no_passphrase_to_the_journal_or_the_error(tmp_path, caplog):
    from src.ingest.import_job import NewsletterImportManager

    def factory():
        raise _quoting(_CORPUS_PW)

    mgr = NewsletterImportManager()
    with caplog.at_level(logging.DEBUG):
        mgr._run([], factory)
    st = mgr.status()
    assert st.get("state") == "error"
    assert not _leaks(json.dumps(st, default=str) + _everything_written(caplog), _CORPUS_PW)


def test_a_run_block_that_raises_journals_the_failure_scrubbed(tmp_path, caplog):
    with pytest.raises(RuntimeError), runlog.run("verify", label="x", dest=str(tmp_path)):
        raise _quoting(_CORPUS_PW)
    journal = "\n".join(p.read_text(encoding="utf-8") for p in Path(runlog.run_logs_dir()).glob("*.jsonl"))
    assert "driver said" in journal, "the failure is still journalled"
    assert not _leaks(journal, _CORPUS_PW)


# ---------------------------------------------------------------------------------------------- #
#  the persisted import report
# ---------------------------------------------------------------------------------------------- #
def _report_quoting(secret: str) -> dict:
    """A report as the restore builds it: engine check text in ``verification`` and ``problems``."""
    quoted = " | ".join(_forms(secret))
    return {
        "batch_id": 7,
        "imported": 12,
        "verification": {"integrity": f"database said: {quoted}"},
        "problems": [f"row 3: {quoted}", "fine"],
        "refused": f"driver: {quoted}",
    }


def _report_files() -> str:
    from src.backup.import_reports import _reports_dir

    return "\n".join(p.read_text(encoding="utf-8") for p in _reports_dir().glob("*.json"))


def test_a_persisted_report_carries_no_passphrase_in_any_form():
    from src.backup.import_reports import persist_import_report

    path = persist_import_report("restore", _report_quoting(_PW), run_id="r1", secrets=(_PW,))
    text = path.read_text(encoding="utf-8")
    assert not _leaks(text, _PW, _CORPUS_PW)
    data = json.loads(text)
    assert data["batch_id"] == 7 and data["imported"] == 12 and data["problems"][1] == "fine"
    # the process's own passphrase is taken out too, without being named
    persist_import_report("restore", _report_quoting(_CORPUS_PW), run_id="r2")
    assert not _leaks(_report_files(), _CORPUS_PW)


def test_an_annotation_carries_no_passphrase_either(tmp_path):
    from src.backup.import_reports import annotate_import_report, persist_import_report

    path = persist_import_report("restore", {"batch_id": 1}, run_id="r3")
    annotate_import_report(path, {"import_run": {"label": f"folder {_PW}"}}, secrets=(_PW,))
    text = path.read_text(encoding="utf-8")
    assert not _leaks(text, _PW) and "import_run" in text


def test_a_report_that_cannot_be_checked_is_withheld_not_written(monkeypatch):
    import src.monitoring.secret_scrub as ss
    from src.backup.import_reports import persist_import_report

    monkeypatch.setattr(ss, "_forms_now", lambda secrets: None)  # what the process holds cannot be read
    path = persist_import_report("restore", _report_quoting(_PW), run_id="r4", secrets=(_PW,))
    text = path.read_text(encoding="utf-8")
    assert not _leaks(text, _PW) and "withheld" in text


def test_the_import_queue_hands_its_passphrase_to_the_report_writers(tmp_path):
    from src.backup.import_queue import ImportQueueManager

    mgr = ImportQueueManager()
    mgr._passphrase = _PW
    item = {"id": "i1", "summary": {"report": {**_report_quoting(_PW), "held": True}}}
    mgr._persist_held_report(item, {"label": "next"})
    assert _report_files() and not _leaks(_report_files(), _PW)


# ---------------------------------------------------------------------------------------------- #
#  the legacy restore path, the restore's refusal branches, the run's own secrets
# ---------------------------------------------------------------------------------------------- #
def test_a_failed_legacy_restore_logs_and_serves_no_passphrase(tmp_path, caplog, monkeypatch):
    from fastapi import HTTPException

    import src.api.backup_v2 as v2

    f = tmp_path / "b.oo"
    f.write_bytes(b"x")
    monkeypatch.setattr(v2, "check_memory_before_staging", lambda: None)

    class _Staged:
        staging_dir = tmp_path / "stg"

    monkeypatch.setattr(v2, "_stage_upload", lambda data, pw: _Staged())
    monkeypatch.setattr(v2, "_apply_restore_selection", lambda *a, **k: None)
    monkeypatch.setattr(v2, "cleanup_staging", lambda s: None)

    def boom(*_a, **_k):
        raise _quoting(_PW, _CORPUS_PW)

    monkeypatch.setattr(v2, "run_restore", boom)
    with caplog.at_level(logging.DEBUG), pytest.raises(HTTPException) as hit:
        v2.restore_legacy_path(str(f), _PW)
    assert not _leaks(str(hit.value.detail) + _everything_written(caplog), _PW, _CORPUS_PW)
    assert not any(r.exc_info for r in caplog.records), "a raw traceback was logged"


def test_the_restore_refusal_and_stop_branches_scrub_what_they_journal_log_and_serve(tmp_path, caplog):
    from src.backup.merge import RestoreAborted, RestoreRefused

    for exc_type, state in ((RestoreRefused, "error"), (RestoreAborted, "cancelled")):

        def fail(*_a, _t=exc_type, **_k):
            raise _t("said: " + " | ".join(_forms(_PW) + _forms(_CORPUS_PW)))

        mgr = VolumeBackupManager()
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            mgr._run_restore(tmp_path / "set", _PW, False, _CORPUS_PW, fail)
        st = mgr.status()
        assert st["state"] == state
        assert not _leaks(json.dumps(st) + _everything_written(caplog), _PW, _CORPUS_PW)


def test_a_run_given_secrets_scrubs_them_and_never_writes_them_to_the_header(tmp_path):
    with pytest.raises(RuntimeError), runlog.run("verify", label="x", dest=str(tmp_path), secrets=(_PW,)):
        raise _quoting(_PW)
    journal = "\n".join(p.read_text(encoding="utf-8") for p in Path(runlog.run_logs_dir()).glob("*.jsonl"))
    assert "driver said" in journal and not _leaks(journal, _PW)


# ---------------------------------------------------------------------------------------------- #
#  the cuts are the stated ones, at every site
# ---------------------------------------------------------------------------------------------- #
def _journalled_error() -> dict:
    """The one ``error`` milestone the run journals hold."""
    rows = [
        json.loads(line)
        for p in runlog.run_logs_dir().glob("*.jsonl")
        if not p.name.endswith(".beat.jsonl")
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    errors = [r for r in rows if r.get("ev") == "error"]
    assert len(errors) == 1, [p.name for p in runlog.run_logs_dir().glob('*')]
    return errors[0]


def test_the_volume_job_cuts_a_failure_at_the_stated_numbers_not_at_literals_of_its_own(tmp_path, monkeypatch):
    """The cuts were literals (2000, 8000) beside the constants that state what they protect; a number
    that stays says what it protects, so the job's journal lines follow the constants. The constants are
    made small here: a literal left in the job would keep its old length and fail these bounds, and the
    message and the traceback are each long enough to be cut, so the bounds are met by cutting."""
    from src.backup.newsletter_export import MESSAGE_SPACE, NewsletterFilterRefused

    monkeypatch.setattr(runlog, "FAILURE_MSG_KEEP", 120)
    monkeypatch.setattr(runlog, "FAILURE_TRACEBACK_KEEP", 300)
    long_text = "driver said: " + "q" * 400

    def fail(*_a, **_k):
        raise RuntimeError(long_text)

    def refuse(*_a, **_k):
        # the refusal carries the server's own fixed sentence (its text argument is not served), which is
        # longer than the message cut: the case means something only while that stays true
        raise NewsletterFilterRefused(long_text, space=True)

    assert len(MESSAGE_SPACE) > 120, "the newsletter-free case no longer has a message longer than the cut"
    # (name, how it is run, the bound on the error the job SERVES: the refusal is served whole by design)
    cases = {
        "backup": (lambda m: m._run_backup(tmp_path / "drive", _PW, True, 0.1, [], False, fail), 120),
        "newsletter-free backup": (
            lambda m: m._run_backup(tmp_path / "drive", "newsletters", True, 0.1, [], False, refuse),
            None,
        ),
        "restore": (lambda m: m._run_restore(tmp_path / "set", _PW, False, _CORPUS_PW, fail), 120),
    }
    for name, (run, served_bound) in cases.items():
        for p in runlog.run_logs_dir().glob("*.jsonl"):
            p.unlink()
        mgr = VolumeBackupManager()
        run(mgr)
        err = _journalled_error()
        assert 0 < len(err["msg"]) <= 120, f"{name}: the message is not cut at FAILURE_MSG_KEEP ({len(err['msg'])})"
        assert 0 < len(err["traceback"]) <= 300, f"{name}: the traceback is not cut at FAILURE_TRACEBACK_KEEP"
        served = mgr.status().get("error") or ""
        if served_bound is None:
            assert served == MESSAGE_SPACE, f"{name}: the refusal is served whole"
        else:
            assert 0 < len(served) <= served_bound, f"{name}: the served error is not cut at FAILURE_MSG_KEEP"
