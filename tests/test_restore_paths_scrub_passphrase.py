"""The single-file restore's route and the import queue write what they caught with the passphrase taken out.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The route layer's ``restore_legacy_path`` and the import queue's run loop both hold the passphrase and catch
``Exception``. Two things come out of them: a LOG RECORD (``restore_legacy_path``'s ``legacy restore failed``; the queue's
``import item ... failed`` and the two warnings beside it), which the error log in the debug bundle keeps with a traceback
tail; and, in the queue, the item's ``error``, which the status route serves, the task manager shows, and
``import_queue.json`` keeps on the drive. The queue is also the one recorder of the route layer's RESPONSE text: a legacy
item raises the route's own ``HTTPException`` (``decryption failed: {exc}``, ``could not read {path}: {exc}``), and the
queue stores its text. So the responses to a caller stay outside the rule (they are the caller's own), and the recorder of
one scrubs what it records, where it records it. No message on those paths names the passphrase today; these tests give
the engine one that does.

``errorlog.note_http_error`` is the other recorder the diagnostics bundle keeps of an error RESPONSE, and it records the
status, the method and the path: a last test pins that no caller hands it a ``detail``.

The static walk that holds the next handler in these modules to the same rule is in ``tests/test_p0_validation.py``
(``_GUARDED_MODULES``).
"""

from __future__ import annotations

import ast
import contextlib
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.backup.import_queue import ImportQueueManager
from src.monitoring.secret_scrub import REDACTED

PASS = "kQ7!vLm-the-artifact-key"
SRC = Path(__file__).resolve().parents[1] / "src"


# --------------------------------------------------------------------------- #
# The single-file restore's route
# --------------------------------------------------------------------------- #
@pytest.fixture()
def route(monkeypatch, tmp_path, caplog):
    """``restore_legacy_path`` with the artifact read stubbed (it decrypts), the staging a no-op and no run journal: the
    handler under test is the ``except Exception`` that logs."""
    from src.api import backup_v2 as r
    from src.backup import runlog

    @contextlib.contextmanager
    def no_journal(*a, **k):
        yield None

    monkeypatch.setattr(runlog, "run", no_journal)
    monkeypatch.setattr(r, "read_artifact", lambda data, passphrase=None: SimpleNamespace(corpus_path=tmp_path / "c.db"))
    monkeypatch.setattr(r, "cleanup_staging", lambda staged: None)
    legacy = tmp_path / "old.bak"
    legacy.write_bytes(b"read_artifact is stubbed")
    caplog.set_level(logging.DEBUG, logger="api.backup_v2")
    return r, legacy


def test_a_failed_legacy_restore_logs_its_failure_with_the_passphrase_out_and_still_answers_500(route, monkeypatch, caplog):
    r, legacy = route

    def boom(*a, **k):
        raise RuntimeError(f"the merge could not open the corpus with {PASS}")

    monkeypatch.setattr(r, "run_restore", boom)
    with pytest.raises(HTTPException) as caught:
        r.restore_legacy_path(str(legacy), PASS)
    assert caught.value.status_code == 500, "the caller still gets its JSON 500 (P0-3)"
    records = [rec for rec in caplog.records if rec.name == "api.backup_v2"]
    assert len(records) == 1, [rec.getMessage() for rec in records]
    record = records[0]
    assert record.levelno == logging.ERROR
    assert record.exc_info is None and record.exc_text is None, "a record carrying exc_info prints the message again"
    message = record.getMessage()
    assert PASS not in message
    assert f"legacy restore failed: RuntimeError: the merge could not open the corpus with {REDACTED}" in message
    assert "Traceback (most recent call last)" in message, "the traceback is still in the record, as text"


def test_a_legacy_restore_without_a_passphrase_logs_the_failure_as_it_is(route, monkeypatch, caplog):
    r, legacy = route

    def boom(*a, **k):
        raise RuntimeError("the merge could not open the corpus")

    monkeypatch.setattr(r, "run_restore", boom)
    with pytest.raises(HTTPException):
        r.restore_legacy_path(str(legacy), None)
    assert "legacy restore failed: RuntimeError: the merge could not open the corpus" in caplog.records[-1].getMessage()


# --------------------------------------------------------------------------- #
# The import queue
# --------------------------------------------------------------------------- #
@pytest.fixture()
def queue(tmp_path, monkeypatch, caplog):
    import src.scheduler.runner as R

    monkeypatch.setattr(R, "pause_for_exclusive_operation", lambda *a, **k: True)
    monkeypatch.setattr(R, "resume_after_exclusive_operation", lambda *a, **k: None)
    caplog.set_level(logging.DEBUG, logger="src.backup.import_queue")
    return ImportQueueManager(state_path=tmp_path / "q.json")


def _drain(mgr, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if mgr.status()["state"] != "running":
            return mgr.status()
        time.sleep(0.02)
    raise AssertionError(f"queue never finished: {mgr.status()['state']}")


def _everything(queue, tmp_path, caplog) -> str:
    """The status the route serves, the state file on the drive and every log record of the queue, as one text: where a
    passphrase that got out would be."""
    records = [f"{r.getMessage()}\n{r.exc_text or ''}\n{r.exc_info!r}" for r in caplog.records]
    return "\n".join([json.dumps(queue.status(), default=str), (tmp_path / "q.json").read_text(encoding="utf-8"), *records])


def _message_of(caplog, fragment: str) -> logging.LogRecord:
    found = [r for r in caplog.records if fragment in r.getMessage()]
    assert len(found) == 1, [r.getMessage()[:120] for r in caplog.records]
    return found[0]


def test_an_item_that_fails_naming_the_passphrase_is_served_persisted_and_logged_without_it(
    queue, monkeypatch, tmp_path, caplog
):
    def boom(item, *, hold=False):
        raise RuntimeError(f"the key {PASS} did not open {item['path']}")

    monkeypatch.setattr(queue, "_run_corpus", boom)
    queue.start([{"kind": "corpus", "path": "/b/1"}], passphrase=PASS)
    st = _drain(queue)
    assert st["items"][0]["state"] == "error"
    assert st["items"][0]["error"] == f"the key {REDACTED} did not open /b/1"
    assert PASS not in _everything(queue, tmp_path, caplog)
    record = _message_of(caplog, "import item 0-corpus failed")
    assert record.levelno == logging.ERROR and record.exc_info is None
    assert f"RuntimeError: the key {REDACTED} did not open /b/1" in record.getMessage()


def test_the_route_layers_response_text_is_scrubbed_where_the_queue_records_it(queue, monkeypatch, tmp_path, caplog):
    """A legacy item raises the route's own ``HTTPException``: its detail and the cause it was raised from."""

    def response(path, passphrase, **k):
        try:
            raise ValueError(f"the cause names {PASS}")
        except ValueError as cause:
            raise HTTPException(status_code=400, detail=f"decryption failed: {PASS}") from cause

    monkeypatch.setattr("src.api.backup_v2.restore_legacy_path", response)
    queue.start([{"kind": "legacy", "path": "/b/old.bak"}], passphrase=PASS)
    st = _drain(queue)
    assert st["items"][0]["error"] == f"400: decryption failed: {REDACTED}"
    assert PASS not in _everything(queue, tmp_path, caplog)
    message = _message_of(caplog, "import item 0-legacy failed").getMessage()
    assert f"ValueError: the cause names {REDACTED}" in message, "the chain is kept, with the secret out of it"


def test_an_item_stopped_mid_merge_keeps_its_scrubbed_text_and_logs_the_info_line_without_the_passphrase(
    queue, monkeypatch, tmp_path, caplog
):
    def stopped(item, *, hold=False):
        queue._stop.set()
        raise RuntimeError(f"stopped while reading with {PASS}")

    monkeypatch.setattr(queue, "_run_corpus", stopped)
    queue.start([{"kind": "corpus", "path": "/b/1"}], passphrase=PASS)
    st = _drain(queue)
    assert st["items"][0]["state"] == "stopped"
    assert st["items"][0]["error"] == f"stopped while reading with {REDACTED}"
    record = _message_of(caplog, "stopped mid-merge")
    assert record.levelno == logging.INFO
    assert record.getMessage() == f"import item 0-corpus stopped mid-merge: stopped while reading with {REDACTED}"
    assert PASS not in _everything(queue, tmp_path, caplog)


def test_the_hold_decision_and_the_group_bookkeeping_log_their_failures_with_the_passphrase_out(
    queue, monkeypatch, tmp_path, caplog
):
    """Two warnings in the loop that holds the key; neither can fail an import, and neither may carry the passphrase."""

    def decide(idx, item):
        raise RuntimeError(f"the hold decision read {PASS}")

    def after(item, summary):
        raise RuntimeError(f"the bookkeeping read {PASS}")

    monkeypatch.setattr(queue, "_decide_hold", decide)
    monkeypatch.setattr(queue, "_after_item", after)
    monkeypatch.setattr(queue, "_run_corpus", lambda item, *, hold=False: {})
    queue.start([{"kind": "corpus", "path": "/b/1"}], passphrase=PASS)
    st = _drain(queue)
    assert st["items"][0]["state"] == "done", "neither warning may cost the import"
    for fragment, said in (("hold decision for 0-corpus", "the hold decision read"), ("bookkeeping failed after item 0-corpus", "the bookkeeping read")):
        record = _message_of(caplog, fragment)
        assert record.levelno == logging.WARNING and record.exc_info is None
        assert f"RuntimeError: {said} {REDACTED}" in record.getMessage()
    assert PASS not in _everything(queue, tmp_path, caplog)


def test_a_queue_started_without_a_passphrase_records_an_error_as_it_was_raised(queue, monkeypatch):
    def boom(item, *, hold=False):
        raise RuntimeError("the set is damaged")

    monkeypatch.setattr(queue, "_run_corpus", boom)
    queue.start([{"kind": "corpus", "path": "/b/1"}])
    assert _drain(queue)["items"][0]["error"] == "the set is damaged"


# --------------------------------------------------------------------------- #
# The recorder of an error response in the debug bundle
# --------------------------------------------------------------------------- #
def test_no_caller_hands_the_http_error_log_a_response_text():
    """``errorlog.note_http_error(method, path, status, *, detail=None)`` can keep 200 characters of a response's text, and
    the route layer's ``HTTPException`` details (``decryption failed: {exc}``) are texts that could name a passphrase. The
    one caller (the request middleware) passes the status alone, and a caller that passed a ``detail``, a ``**kwargs`` that
    could carry one, or a fourth positional would turn the routes' responses into a recorded text no scrub sees."""
    calls = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name == "note_http_error":
                calls.append((path.relative_to(SRC).as_posix(), node.lineno, node))
    assert any(where == "api/main.py" for where, _, _ in calls), "the walk must find the middleware's call, not nothing"
    for where, line, node in calls:
        assert all(kw.arg not in (None, "detail") for kw in node.keywords), f"{where}:{line} passes a detail or **kwargs"
        assert len(node.args) <= 3, f"{where}:{line} passes more than method, path and status"
