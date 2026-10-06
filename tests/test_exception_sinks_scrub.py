"""Two more files an exception ends in carry the passphrases the process holds out of it (2026-10-06).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The debug bundle carries the crash trace, the run journal and the import's status file, and an engine's error can quote the
statement that held a key. The server's fatal exception (``exit_evidence.note_fatal_exception``, an exception that escaped the
server's loop and is ending the process) and the newsletter import's failure (the journal's ``error`` line, the status the API
serves and the state file the job keeps) wrote what they caught as it made its message. Each now takes the held passphrases
out BEFORE the cut that keeps the end of a traceback, and writes the exception's class and none of its words when the scrub
cannot run.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.backup import runlog
from src.database.models import Base
from src.ingest import import_job
from src.monitoring import exit_evidence as ee
from src.monitoring import secret_scrub as S

PASS = "Qv9#k'L-72mZpx"
SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture(autouse=True)
def _held(monkeypatch):
    monkeypatch.setenv("OO_DB_PASSPHRASE", PASS)
    monkeypatch.setattr("src.database.connect._passphrase", None)


# --------------------------------------------------------------------------- #
#  The exception that ends the server
# --------------------------------------------------------------------------- #
@pytest.fixture
def trace(monkeypatch, tmp_path):
    path = tmp_path / "crash_trace.log"
    monkeypatch.setattr(ee, "crash_trace_path", lambda: path)
    return path


def test_the_fatal_exception_is_written_without_the_passphrase(trace):
    try:
        raise RuntimeError(f"near 'PRAGMA key = ''{PASS.replace(chr(39), chr(39) * 2)}''': syntax error")
    except RuntimeError as exc:
        ee.note_fatal_exception(exc)
    text = trace.read_text(encoding="utf-8")
    assert PASS not in text and PASS.replace("'", "''") not in text
    assert text.startswith("Uncaught exception ended the server at ") and f"RuntimeError: near 'PRAGMA key = ''{S.REDACTED}''" in text


def test_the_fatal_exception_is_scrubbed_before_it_is_cut(trace):
    """MUTATION TARGET: the cut of the traceback before the scrub. The file keeps the END of the traceback, so a passphrase the
    cut runs through leaves its tail behind, which is no shape of it and which no scrub then recognises."""
    cut_at = 4
    try:
        raise RuntimeError(PASS + "z" * (7999 - len(PASS) + cut_at))
    except RuntimeError as exc:
        ee.note_fatal_exception(exc)
    text = trace.read_text(encoding="utf-8")
    assert PASS[cut_at:] not in text and PASS not in text and "zzzz" in text


def test_the_fatal_exception_keeps_the_end_of_the_traceback_and_no_more_than_the_bound(trace):
    """MUTATION TARGET: the cut left out. The file is carried by the debug bundle and the exception can be as long as an engine
    makes it: the last 8,000 characters are kept, where the exception's own words end."""
    try:
        raise RuntimeError("x" * 50_000 + "THE-END")
    except RuntimeError as exc:
        ee.note_fatal_exception(exc)
    text = trace.read_text(encoding="utf-8")
    assert "THE-END" in text and len(text) < 8_200 and text.count("x") < 8_000


def test_a_fatal_exception_that_cannot_be_checked_writes_its_class_and_none_of_its_words(trace, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the scrub broke")

    monkeypatch.setattr(S, "_forms_now", broken)  # the scrub cannot run: ``traceback_text`` never raises and writes the class
    try:
        raise RuntimeError(f"near {PASS}")
    except RuntimeError as exc:
        ee.note_fatal_exception(exc)
    text = trace.read_text(encoding="utf-8")
    assert "RuntimeError: its text is withheld" in text and PASS not in text


# --------------------------------------------------------------------------- #
#  The newsletter import's failure
# --------------------------------------------------------------------------- #
@pytest.fixture
def failed_import(monkeypatch, tmp_path):
    """A newsletter import whose ingest raises an error naming ``PASS``: a function that runs it to its end and returns
    ``(manager, directory)``."""
    monkeypatch.setattr(runlog, "run_logs_dir", lambda: tmp_path / "run_logs")
    monkeypatch.setenv("OO_RUN_JOURNAL", "1")
    runlog._CURRENT = None

    def boom(*args, **kwargs):
        raise RuntimeError(f"the store refused the key: PRAGMA key = '{PASS.replace(chr(39), chr(39) * 2)}'")

    monkeypatch.setattr(import_job, "ingest_emails", boom)

    def run():
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
        Base.metadata.create_all(engine)
        folder = tmp_path / "nl"
        folder.mkdir()
        (folder / "1.eml").write_bytes(b"From: N <n@x.test>\nSubject: S\nMessage-ID: <m1@x.test>\n\nbody\n")
        mgr = import_job.NewsletterImportManager(state_path=tmp_path / "import_state.json")
        mgr.start(str(folder), _session_factory=sessionmaker(bind=engine, future=True, autoflush=False))
        if mgr._thread is not None:
            mgr._thread.join(10)
        return mgr, tmp_path

    yield run
    runlog._CURRENT = None


def test_a_failed_newsletter_import_keeps_its_error_without_the_passphrase_in_the_status_the_state_file_and_the_journal(failed_import):
    """MUTATION TARGET: any of the three kept as the exception made it."""
    mgr, tmp_path = failed_import()
    status = mgr.status()
    assert status["state"] == "error"
    assert status["error"] == f"the store refused the key: PRAGMA key = '{S.REDACTED}'"
    kept = [tmp_path / "import_state.json", *sorted((tmp_path / "run_logs").glob("*.jsonl"))]
    assert len(kept) >= 2
    for path in kept:
        text = path.read_text(encoding="utf-8")
        assert PASS not in text and PASS.replace("'", "''") not in text, path.name
    errors = [
        json.loads(line)
        for path in (tmp_path / "run_logs").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("ev") == "error"
    ]
    assert len(errors) == 1 and errors[0]["cls"] == "RuntimeError"
    assert errors[0]["msg"] == f"the store refused the key: PRAGMA key = '{S.REDACTED}'" and "RuntimeError: the store refused" in errors[0]["traceback"]


def test_a_newsletter_import_error_that_cannot_be_checked_is_kept_as_its_class_alone(failed_import, monkeypatch):
    """MUTATION TARGET: the words kept when the scrub cannot run."""

    def broken(*args, **kwargs):
        raise RuntimeError("the scrub broke")

    monkeypatch.setattr(import_job, "scrubbed", broken)
    monkeypatch.setattr(runlog, "scrubbed", broken)
    mgr, tmp_path = failed_import()
    assert mgr.status()["error"] == "RuntimeError: its text is withheld"
    for path in [tmp_path / "import_state.json", *(tmp_path / "run_logs").glob("*.jsonl")]:
        assert PASS not in path.read_text(encoding="utf-8"), path.name


# --------------------------------------------------------------------------- #
#  The next one
# --------------------------------------------------------------------------- #
#: What turns an exception into text with the ``traceback`` module.
_FORMATTERS = frozenset({"format_exception", "format_exc", "print_exc", "print_exception", "format_exception_only"})
#: The modules of ``src/`` that format an exception themselves, each with why the text carries no passphrase. Held to zero
#: slack both ways: a module that starts to format one has to go through ``secret_scrub.traceback_text`` or be named here
#: with its reason, and an entry that no longer formats one has to come out. Found by a sweep of ``src/`` on 2026-10-06 that
#: turned up the fatal exception's record and the newsletter import's journal line (fixed above) beside ``runlog.run``.
_FORMATS_ITS_OWN = {
    "monitoring/secret_scrub.py": "the helpers themselves: traceback_text and log_failure format the exception and take every secret out of the text they return",
    "monitoring/errorlog.py": "the error journal's handler scrubs the traceback of every record it keeps, with the held passphrases, before it cuts it",
}


def _formats_an_exception(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "traceback":
                name = func.attr
            else:
                name = func.id if isinstance(func, ast.Name) else ""
            if name in _FORMATTERS:
                lines.append(node.lineno)
    return lines


def test_no_module_formats_an_exception_as_text_without_the_scrubbing_helpers_or_a_reason():
    """The next ``traceback.format_exception`` in a handler is how the next file keeps an engine's error as it made its message,
    and nothing else would see it: the static guard reads the functions that hold the passphrase, and the sweep that found the
    two sinks above was a grep. MUTATION TARGET: a module added to ``src/`` that formats an exception, or an entry left in."""
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        lines = _formats_an_exception(ast.parse(path.read_text(encoding="utf-8")))
        if lines:
            found[path.relative_to(SRC).as_posix()] = lines
    assert set(found) == set(_FORMATS_ITS_OWN), (
        f"format an exception, neither through the helpers nor listed: {sorted(set(found) - set(_FORMATS_ITS_OWN))}; "
        f"listed but no longer formatting one (take them out): {sorted(set(_FORMATS_ITS_OWN) - set(found))}"
    )
    assert all(len(reason) > 40 for reason in _FORMATS_ITS_OWN.values()), "a reason, not a placeholder"
