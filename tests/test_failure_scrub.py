"""A failed run's journal line, log line and served error carry no passphrase (src/backup/runlog.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE SINKS. A failed run writes the exception's text and its traceback into its run journal
(``data/run_logs/*.jsonl``) and logs it (``data/app_errors.jsonl`` rides the debug bundle), and
stores the text as the job's ``error`` (served by the status endpoint). The text is the engine's
own and may quote what it was handed, so every writer goes through ``runlog.failure_fields``: the
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
    monkeypatch.setattr("src.database.connect.get_passphrase", lambda: _CORPUS_PW)


# ---------------------------------------------------------------------------------------------- #
#  the helper
# ---------------------------------------------------------------------------------------------- #
def test_every_form_is_scrubbed_before_the_cut_and_the_cuts_say_what_they_protect():
    straddle = "x" * (runlog.FAILURE_MSG_KEEP - len(_PW) // 2) + _PW + " and more"
    out = runlog.failure_fields(RuntimeError(straddle), _PW)
    assert not _leaks(out["msg"] + out["traceback"], _PW, _CORPUS_PW)
    assert len(out["msg"]) <= runlog.FAILURE_MSG_KEEP and len(out["traceback"]) <= runlog.FAILURE_TRACEBACK_KEEP
    assert out["cls"] == "RuntimeError"
    # the process's own passphrase is always scrubbed, with or without being named
    out = runlog.failure_fields(_quoting(_CORPUS_PW))
    assert not _leaks(out["msg"] + out["traceback"], _CORPUS_PW)


def test_a_scrub_that_fails_or_leaves_a_form_withholds_the_text(monkeypatch):
    import src.monitoring.secret_scrub as ss

    monkeypatch.setattr(ss, "scrub_value", lambda value, needle: value)  # "succeeds", scrubs nothing
    out = runlog.failure_fields(_quoting(_PW), _PW)
    assert out["msg"] == runlog.FAILURE_WITHHELD and not _leaks(out["traceback"], _PW)

    def broken(*_a, **_k):
        raise RuntimeError("scrub broke")

    monkeypatch.setattr(ss, "scrub_value", broken)
    assert runlog.failure_fields(_quoting(_PW), _PW)["msg"] == runlog.FAILURE_WITHHELD
    assert runlog.scrub_secrets({"report": _PW}, _PW) == {"withheld": runlog.FAILURE_WITHHELD}


def test_the_recheck_reads_string_values_only_so_a_good_report_is_not_blanked(monkeypatch):
    """A passphrase form inside a report KEY, or a short numeric one that equals a count, is not text a
    secret was written into: ``scrub_value`` leaves both alone, and a recheck over ``json.dumps`` would
    turn the whole report into ``{"withheld": ...}`` and lose it."""
    monkeypatch.setattr("src.database.connect.get_passphrase", lambda: None)
    report = {"batch_id": 7, f"k{_PW}": 1, "imported": 12, "problems": ["fine"], "nested": {"n": 12}}
    assert runlog.scrub_secrets(report, _PW, "12") == report
    # and a string VALUE that holds the secret is still scrubbed, not withheld
    out = runlog.scrub_secrets({"a": f"x {_PW} y"}, _PW)
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
