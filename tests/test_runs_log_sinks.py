"""The places the runs recorder and the crash witnesses LOG a failure, and the reasons they keep, carry neither the passphrase nor
a traceback that prints it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A debug line written with ``exc_info=True`` prints the exception's message, and the cause and the context chain after it ("During
handling of the above exception..."): the engine's words, unscrubbed, to every handler of the root logger (the console at
``LOG_LEVEL=DEBUG``) and to the error journal the debug bundle carries. The three places this PR adds or rewrites that run INSIDE a
handler of another failure are the ones that matter, because the other failure is the one that has the words:

  * ``diagnostics_runs._append`` runs inside the handler of the build's own failure (``end_run`` is called from
    ``except BaseException`` in the worker);
  * ``exit_evidence.note_fatal_exception`` runs inside the handler of the exception that ends the server;
  * ``exit_evidence.arm_crash_trace`` writes its reason, and logs it, on a failure at boot;
  * ``bundle._write_all_diagnostics_zip``'s two journal-write warnings and ``_bundle_exclusive_window``'s failed claim, which run in a
    build that may itself be inside the handler of another failure (a handler's exception chains the one it ran in as its context).

Each is run here with the passphrase and a key statement in the failure it runs inside, and every record any handler formats is
searched. A source-level guard then holds the whole set of modules of the crash witnesses to the same rule, with the cases it must
flag written out so that a guard that stopped reading anything fails.
"""

from __future__ import annotations

import ast
import json
import logging
import sys
from pathlib import Path

import pytest

from src.monitoring import diagnostics_runs as r
from src.monitoring import exit_evidence as ee

SECRET = "correct horse's battery"
STATEMENT = "PRAGMA key = 'k3y-zzzz-abcd'"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "diagnostics").mkdir()
    r.reset_for_tests()
    yield tmp_path
    r.reset_for_tests()


def _held(monkeypatch, secret: str = SECRET) -> None:
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", secret)


def _everything_a_handler_would_write(caplog) -> str:
    """Each record as a handler formats it: the message AND the traceback ``exc_info`` carries, which is where the chain prints."""
    fmt = logging.Formatter("%(levelname)s %(name)s %(message)s")
    return "\n".join(fmt.format(rec) for rec in caplog.records)


def _none_of_it(text: str) -> None:
    for leaked in (SECRET, "correct horse", "battery", "k3y-zzzz", "abcd'"):
        assert leaked not in text, leaked


# --------------------------------------------------------------------------- #
#  the three places that run inside the handler of another failure
# --------------------------------------------------------------------------- #
def test_a_record_that_cannot_be_written_logs_its_reason_and_not_the_failure_the_build_died_of(_data, monkeypatch, caplog):
    """``end_run`` -> ``_append`` runs in the handler of the build's failure, so the OSError of a full drive has that failure as its
    context: a logged traceback prints the build's message, with the engine's statement in it, through ``__context__``."""
    _held(monkeypatch)
    rid = r.begin_run("f.zip", profile="full")

    def full_drive():
        raise OSError(28, f"No space left on device ({SECRET})")

    monkeypatch.setattr(r, "_path", full_drive)
    caplog.set_level(logging.DEBUG)
    try:
        try:
            raise RuntimeError(f"the build failed on {SECRET} [SQL: {STATEMENT}]")
        except BaseException:
            assert r.end_run(rid, outcome="failed", seconds=1.0, error="x") is False
    finally:
        caplog.set_level(logging.WARNING)
    mine = [rec for rec in caplog.records if "could not write the record" in rec.getMessage()]
    assert len(mine) == 1, [rec.getMessage() for rec in caplog.records]
    assert mine[0].exc_info is None and mine[0].exc_text is None, "no traceback rides the record"
    assert "OSError" in mine[0].getMessage(), "the reason is named"
    _none_of_it(_everything_a_handler_would_write(caplog))


def test_a_fatal_exception_that_cannot_be_recorded_logs_its_reason_and_not_the_fatal_exception(_data, monkeypatch, caplog):
    _held(monkeypatch)

    def unwritable():
        raise PermissionError(13, f"denied for {SECRET}")

    monkeypatch.setattr(ee, "crash_trace_path", unwritable)
    caplog.set_level(logging.DEBUG)
    try:
        try:
            raise MemoryError(f"ended the server on {SECRET} [SQL: {STATEMENT}]")
        except MemoryError as exc:
            ee.note_fatal_exception(exc)
    finally:
        caplog.set_level(logging.WARNING)
    mine = [rec for rec in caplog.records if "could not record the fatal exception" in rec.getMessage()]
    assert len(mine) == 1, [rec.getMessage() for rec in caplog.records]
    assert mine[0].exc_info is None and "PermissionError" in mine[0].getMessage()
    _none_of_it(_everything_a_handler_would_write(caplog))


def test_a_crash_trace_that_cannot_be_armed_logs_and_returns_the_one_scrubbed_reason(_data, monkeypatch, caplog):
    import faulthandler

    _held(monkeypatch)
    monkeypatch.setattr(ee, "_TRACE_HANDLE", None)

    def refuses(*args, **kwargs):
        raise OSError(f"cannot dump to {_data}/diagnostics/x for {SECRET} [SQL: {STATEMENT}]")

    monkeypatch.setattr(faulthandler, "enable", refuses)
    caplog.set_level(logging.DEBUG)
    try:
        out = ee.arm_crash_trace()
    finally:
        caplog.set_level(logging.WARNING)
    assert out["armed"] is False
    _none_of_it(json.dumps(out))
    assert str(_data) not in out["reason"] and len(out["reason"]) <= ee._ARM_REASON_CHARS
    mine = [rec for rec in caplog.records if "could not arm the crash trace" in rec.getMessage()]
    assert len(mine) == 1 and mine[0].exc_info is None
    assert out["reason"] in mine[0].getMessage(), "the log says what the return value says"
    _none_of_it(_everything_a_handler_would_write(caplog))


def test_a_failed_claim_of_the_machine_logs_the_scrubbed_failure_and_no_raw_traceback(_data, monkeypatch, caplog):
    import src.api.diagnostics as d
    import src.scheduler.runner as R

    _held(monkeypatch)

    def wedged(*args, **kwargs):
        raise RuntimeError(f"the scheduler is wedged on {SECRET} [SQL: {STATEMENT}]")

    monkeypatch.setattr(R, "exclusive_window", wedged)
    caplog.set_level(logging.DEBUG)
    try:
        try:
            raise OSError(f"the build was already failing on {SECRET}")
        except OSError:
            with d._bundle_exclusive_window() as claim:
                assert claim == {"held": False, "reason": "could not claim the machine"}
    finally:
        caplog.set_level(logging.WARNING)
    mine = [rec for rec in caplog.records if "could not claim the machine" in rec.getMessage()]
    assert len(mine) == 1 and mine[0].exc_info is None, [rec.getMessage() for rec in caplog.records]
    assert "RuntimeError" in mine[0].getMessage(), "the failure is named"
    for leaked in (SECRET, "correct horse", "battery"):
        assert leaked not in _everything_a_handler_would_write(caplog), leaked


@pytest.mark.parametrize("event", ["begin", "end"])
def test_a_journal_that_cannot_be_written_logs_the_failure_without_a_traceback_and_the_run_goes_on(
    _data, monkeypatch, caplog, tmp_path, event
):
    """The journal is a diagnostic aid: ENOSPC on its disk degrades the run to unjournaled. The warning is written through
    ``log_failure`` (no ``exc_info``), at both places that write a journal line, because the handler may run inside the handler
    of another failure. (The write is made to fail by the line that makes the text: a drive that refuses writes, such as
    /dev/full, is read back whole by the fold at the end of the run and is no fixture for it.)"""
    import io
    import json
    import types
    import zipfile

    import src.api.diagnostics as d
    from src.api.diagnostics import bundle as bundle_module

    _held(monkeypatch)
    real_json = bundle_module.json

    def dumps(obj, *args, **kwargs):
        if isinstance(obj, dict) and obj.get("event") == event:
            raise OSError(28, f"No space left on device ({SECRET})")
        return real_json.dumps(obj, *args, **kwargs)

    monkeypatch.setattr(bundle_module, "json", types.SimpleNamespace(**{**vars(json), "dumps": dumps}))
    caplog.set_level(logging.DEBUG)
    members = [("a.json", lambda: {"x": 1}), ("b.json", lambda: {"y": 2})]
    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w") as z:
            d._write_all_diagnostics_zip(members, z, journal_path=tmp_path / "run.journal.jsonl")
        names = zipfile.ZipFile(io.BytesIO(buf.getvalue())).namelist()
    finally:
        caplog.set_level(logging.WARNING)
    assert "a.json" in names and "b.json" in names, "the bundle is still written"
    mine = [rec for rec in caplog.records if "journal write failed" in rec.getMessage()]
    assert len(mine) == 1, [rec.getMessage() for rec in caplog.records]
    assert mine[0].exc_info is None and mine[0].exc_text is None
    assert "OSError" in mine[0].getMessage()
    for leaked in (SECRET, "correct horse", "battery"):
        assert leaked not in _everything_a_handler_would_write(caplog), leaked


# --------------------------------------------------------------------------- #
#  the member's own "could not be read"
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seam", ["_read_lines_marked", "_runs_view"])
def test_a_member_that_could_not_be_read_gives_a_reason_free_of_the_passphrase_and_the_key_statement_cut_after(
    _data, monkeypatch, seam
):
    """``diagnostics_member``'s reason is served by ``GET /runs`` and written into the zip. The exception carries the passphrase and a
    key statement whose literal OPENS 20 characters before the reason's cut and closes after it, so a reason built as
    ``f"{type(exc).__name__}: {exc}"[:200]``, or cut before the scrub, keeps the opening of the literal, and one that is not
    scrubbed keeps the passphrase."""
    _held(monkeypatch)
    literal = "'k3y-" + "z" * 60 + "'"
    statement = " PRAGMA key = "
    # the quote that opens the literal is the 181st character of the reason's text ("RuntimeError: " leads), 20 before the cut at
    # 200, and the literal ends after it: a cut made before the scrub keeps ``'k3y-zzzz...`` with no closing quote, which no pattern
    # of a key statement recognises
    pad = "x" * (r.MEMBER_REASON_CHARS - 20 - len("RuntimeError: ") - len(statement))
    text = f"{pad}{statement}{literal} then {SECRET} and more words after the cut"
    reason_text = f"RuntimeError: {text}"
    assert reason_text.index(literal) == r.MEMBER_REASON_CHARS - 20
    assert reason_text.index(literal) + len(literal) > r.MEMBER_REASON_CHARS

    def boom(*args, **kwargs):
        raise RuntimeError(text)

    if seam == "_read_lines_marked":
        monkeypatch.setattr(r, "_read_lines_marked", boom)
    else:
        monkeypatch.setattr(r, "_runs_view", boom)
    doc = r.diagnostics_member()
    assert doc["available"] is False and doc["reason"].startswith("RuntimeError: "), doc
    _none_of_it(doc["reason"])
    assert "k3y-" not in doc["reason"] and len(doc["reason"]) <= r.MEMBER_REASON_CHARS
    assert "***redacted***" in doc["reason"], "the key statement was named, not dropped: the test reached the scrub"


def test_a_member_whose_failure_holds_a_unicode_error_gives_the_fixed_words(_data, monkeypatch):
    from src.monitoring.secret_scrub import UNICODE_WITHHELD

    def boom(*args, **kwargs):
        raise UnicodeEncodeError("ascii", "café", 3, 4, "ordinal not in range(128)")

    monkeypatch.setattr(r, "_runs_view", boom)
    doc = r.diagnostics_member()
    assert UNICODE_WITHHELD in doc["reason"] and "xe9" not in doc["reason"] and "position" not in doc["reason"]


# --------------------------------------------------------------------------- #
#  held_shapes() hands its result to a caller, never to a module
# --------------------------------------------------------------------------- #
_ALLOWED_HOLDERS = {
    # (module, name): why it holds the passphrase or its shapes
    ("src.database.connect", "_passphrase"): "the key the open store was unlocked with",
    ("src.monitoring.secret_scrub", "_HELD_FORMS"): "the one cache of the scrub, emptied by forget_held()",
}


def _holders(shapes: tuple[str, ...]) -> set[tuple[str, str]]:
    """Every module-level name under ``src`` whose value is one of the shapes, or a container (two levels deep) of them."""
    wanted = set(shapes)

    def carries(value, depth=0) -> bool:
        if isinstance(value, str):
            return value in wanted
        if depth >= 2:
            return False
        if isinstance(value, dict):
            return any(carries(k, depth + 1) or carries(v, depth + 1) for k, v in list(value.items()))
        if isinstance(value, (tuple, list, set, frozenset)):
            return any(carries(v, depth + 1) for v in list(value))
        return False

    found: set[tuple[str, str]] = set()
    for name, mod in list(sys.modules.items()):
        if not name.startswith("src.") or mod is None:
            continue
        for attr, value in list(vars(mod).items()):
            if not attr.startswith("__") and carries(value):
                found.add((name, attr))
    return found


def test_no_module_keeps_the_shapes_the_scrubs_recheck_and_the_torn_start_reader_were_handed(_data, monkeypatch):
    """``held_shapes`` is the first function of ``secret_scrub`` that hands every raw shape of every held passphrase to a caller. It
    stores nothing; the callers keep the tuple in a local. Run every caller, then read every module's globals: the only names that
    hold a shape are the ones listed (the key itself, and the scrub's own cache that ``forget_held`` empties)."""
    from src.monitoring.secret_scrub import held_shapes

    _held(monkeypatch)
    shapes = held_shapes()
    assert shapes and len(shapes) > 8
    r.scrubbed_text("nothing of the key here", one_line=True)
    r.scrubbed_text("a\r\nb", file_text=True)
    r.held_forms()
    r.without_a_torn_start("Traceback (most recent call last):\n  x")
    r.tidy_error(RuntimeError("failed"))
    assert _holders(shapes) <= set(_ALLOWED_HOLDERS), sorted(_holders(shapes) - set(_ALLOWED_HOLDERS))


def test_the_holder_scan_sees_a_module_that_caches_the_shapes(_data, monkeypatch):
    """Negative space: a future caller that keeps the result in a module name must be seen by the scan above."""
    from src.monitoring.secret_scrub import held_shapes

    _held(monkeypatch)
    shapes = held_shapes()
    monkeypatch.setattr(r, "_CACHED", shapes, raising=False)
    monkeypatch.setattr(r, "_CACHED_AS_LIST", list(shapes), raising=False)
    assert {("src.monitoring.diagnostics_runs", "_CACHED"), ("src.monitoring.diagnostics_runs", "_CACHED_AS_LIST")} <= _holders(shapes)


# --------------------------------------------------------------------------- #
#  the vitals recorder: four debug lines that ran with exc_info, and the reason it keeps
# --------------------------------------------------------------------------- #
@pytest.fixture
def _vitals(monkeypatch):
    from src.monitoring import vitals_history as v

    v.reset_for_tests()
    monkeypatch.setattr(v, "_fast_readings", lambda: {})
    monkeypatch.setattr(v, "_slow_readings", lambda _now: {})
    monkeypatch.setattr(v, "_busiest", lambda _avail: ([], None))
    yield v
    v.reset_for_tests()


def _the_failing_engine():
    return RuntimeError(f"the engine said {SECRET} and its statement")


def _no_passphrase_in(text: str) -> None:
    """``log_failure`` takes out the passphrase the process holds (a key statement is the runs scrub's business, not its)."""
    for leaked in (SECRET, "correct horse", "battery"):
        assert leaked not in text, leaked


def _inside_another_failure(call) -> None:
    """The recorder's lines run on the liveness thread, where an unrelated handler may be on the stack: its exception is the
    ``__context__`` of whatever the recorder meets."""
    try:
        raise _the_failing_engine()
    except RuntimeError:
        call()


def _only_the_vitals_records(caplog) -> list[logging.LogRecord]:
    return [rec for rec in caplog.records if rec.name == "src.monitoring.vitals_history"]


def test_a_tick_that_fails_logs_the_failure_scrubbed_with_no_traceback_on_the_record(_data, _vitals, monkeypatch, caplog):
    v = _vitals
    _held(monkeypatch)
    v.start()

    def broken():
        raise _the_failing_engine()

    monkeypatch.setattr(v, "_fast_readings", broken)
    caplog.set_level(logging.DEBUG)
    _inside_another_failure(lambda: v.tick(now=1_699_999_200.0))
    mine = [rec for rec in _only_the_vitals_records(caplog) if "tick failed" in rec.getMessage()]
    assert len(mine) == 1, [rec.getMessage() for rec in caplog.records]
    assert mine[0].exc_info is None and mine[0].exc_text is None
    _no_passphrase_in(_everything_a_handler_would_write(caplog))
    assert v.diagnostics_member()["errors"]["last_tick_error"]["error"] == "RuntimeError", "the member keeps the class and no words"


def test_a_flush_that_fails_logs_the_failure_scrubbed_with_no_traceback_on_the_record(_data, _vitals, monkeypatch, caplog):
    v = _vitals
    _held(monkeypatch)
    v.start()

    def broken():
        raise _the_failing_engine()

    monkeypatch.setattr(v, "_state_doc", broken)
    caplog.set_level(logging.DEBUG)
    _inside_another_failure(v.flush)
    mine = [rec for rec in _only_the_vitals_records(caplog) if "flush failed" in rec.getMessage()]
    assert len(mine) == 1, [rec.getMessage() for rec in caplog.records]
    assert mine[0].exc_info is None and mine[0].exc_text is None
    _no_passphrase_in(_everything_a_handler_would_write(caplog))


def test_a_data_folder_that_cannot_be_read_logs_the_failure_scrubbed_with_no_traceback_on_the_record(_data, monkeypatch, caplog):
    from src.monitoring import vitals_history as v

    v.reset_for_tests()
    _held(monkeypatch)

    def gone():
        raise _the_failing_engine()

    monkeypatch.setattr(v, "data_dir", gone)
    monkeypatch.setattr(v, "_count_readings", lambda: {})
    caplog.set_level(logging.DEBUG)
    try:
        _inside_another_failure(lambda: v._slow_readings(10_000_000.0))
    finally:
        v.reset_for_tests()
    mine = [rec for rec in _only_the_vitals_records(caplog) if "data folder could not be read" in rec.getMessage()]
    assert len(mine) == 1, [rec.getMessage() for rec in caplog.records]
    assert mine[0].exc_info is None and mine[0].exc_text is None
    _no_passphrase_in(_everything_a_handler_would_write(caplog))


def test_a_previous_file_that_cannot_be_read_logs_the_failure_scrubbed_with_no_traceback_on_the_record(_data, _vitals, monkeypatch, caplog):
    v = _vitals
    _held(monkeypatch)

    def broken():
        raise _the_failing_engine()

    monkeypatch.setattr(v, "_load", broken)
    caplog.set_level(logging.DEBUG)
    _inside_another_failure(v.start)
    mine = [rec for rec in _only_the_vitals_records(caplog) if "could not read the previous file" in rec.getMessage()]
    assert len(mine) == 1, [rec.getMessage() for rec in caplog.records]
    assert mine[0].exc_info is None and mine[0].exc_text is None
    _no_passphrase_in(_everything_a_handler_would_write(caplog))


@pytest.mark.parametrize(("level", "formatted"), [(logging.INFO, 0), (logging.DEBUG, 1)])
def test_a_failing_tick_formats_and_scrubs_its_failure_only_when_debug_is_on(_data, _vitals, monkeypatch, caplog, level, formatted):
    """``log_failure`` formats the traceback and runs every held shape over it before the logger asks its level; the recorder asks
    first, so a tick that fails on every pass costs nothing at INFO."""
    v = _vitals
    v.start()
    calls: list[str] = []
    monkeypatch.setattr(v, "log_failure", lambda log, what, exc, *a, **k: calls.append(what))

    def broken():
        raise _the_failing_engine()

    monkeypatch.setattr(v, "_fast_readings", broken)
    caplog.set_level(level, logger="src.monitoring.vitals_history")
    v.tick(now=1_699_999_200.0)
    assert len(calls) == formatted, calls


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (OSError(28, "No space left on device", f"/home/someone/{SECRET}/vitals.json"), "OSError: No space left on device"),
        (OSError(f"no errno, only {SECRET}"), "OSError"),
        (_the_failing_engine(), "RuntimeError"),
        (UnicodeDecodeError("utf-8", b"\xff", 0, 1, f"bad byte near {SECRET}"), "UnicodeDecodeError"),
    ],
)
def test_the_reason_the_vitals_recorder_keeps_is_the_class_and_the_systems_own_reason_and_never_the_message(exc, expected):
    """``_reason`` is one of the two calls the guard above lets a vitals handler hand its exception to, so it is pinned here."""
    from src.monitoring import vitals_history as v

    got = v._reason(exc)
    assert got == expected
    _none_of_it(got)


# --------------------------------------------------------------------------- #
#  the unattended-run log: three WARNING lines that were written with exc_info
# --------------------------------------------------------------------------- #
def _the_one_record(caplog, fragment: str) -> logging.LogRecord:
    mine = [rec for rec in caplog.records if rec.name == "src.monitoring.expedition" and fragment in rec.getMessage()]
    assert len(mine) == 1, [rec.getMessage() for rec in caplog.records]
    assert mine[0].exc_info is None and mine[0].exc_text is None, "no traceback rides the record"
    return mine[0]


def test_an_expedition_file_that_cannot_be_written_logs_the_failure_scrubbed_with_no_traceback_on_the_record(
    _data, monkeypatch, caplog
):
    from src.monitoring import expedition as ex

    _held(monkeypatch)

    def refused(*args, **kwargs):
        raise OSError(28, f"No space left on device ({SECRET})")

    monkeypatch.setattr(ex.os, "replace", refused)
    caplog.set_level(logging.DEBUG)
    _inside_another_failure(lambda: ex._write({"armed": True}))
    assert "OSError" in _the_one_record(caplog, "could not persist expedition.json").getMessage()
    _no_passphrase_in(_everything_a_handler_would_write(caplog))


def test_an_event_that_cannot_be_recorded_logs_the_failure_scrubbed_with_no_traceback_on_the_record(_data, monkeypatch, caplog):
    from src.monitoring import expedition as ex

    _held(monkeypatch)

    def unreadable():
        raise RuntimeError(f"the state said {SECRET}")

    monkeypatch.setattr(ex, "_read", unreadable)
    caplog.set_level(logging.DEBUG)
    _inside_another_failure(lambda: ex.record_event("armed", "x"))
    assert "RuntimeError" in _the_one_record(caplog, "expedition event not recorded").getMessage()
    _no_passphrase_in(_everything_a_handler_would_write(caplog))


def test_a_refresh_that_fails_logs_the_failure_scrubbed_with_no_traceback_on_the_record(_data, monkeypatch, caplog):
    from src.monitoring import expedition as ex

    _held(monkeypatch)

    def broken(*args, **kwargs):
        raise RuntimeError(f"the counters said {SECRET}")

    monkeypatch.setattr(ex, "_series_window", broken)
    caplog.set_level(logging.DEBUG)
    _inside_another_failure(lambda: ex.refresh(object()))
    assert "RuntimeError" in _the_one_record(caplog, "expedition refresh failed").getMessage()
    _no_passphrase_in(_everything_a_handler_would_write(caplog))


# --------------------------------------------------------------------------- #
#  the modules of the crash witnesses log no traceback and print no exception raw
# --------------------------------------------------------------------------- #
#: The modules this PR creates or rewrites for the crash witnesses and the runs, each read whole.
_WITNESS_MODULES = (
    "src/monitoring/diagnostics_runs.py",
    "src/monitoring/exit_evidence.py",
    "src/monitoring/forensics.py",
    "src/monitoring/session_history.py",
    "src/monitoring/build_marker.py",
    "src/monitoring/chronology.py",
    "src/api/diagnostics/runs.py",
    "src/monitoring/vitals_history.py",
    "src/monitoring/expedition.py",
)
#: Calls a module of the list above may hand a caught exception to besides the common ones, each with what it writes: the vitals
#: recorder's ``_reason`` is the exception's class and the operating system's own reason, never its message ("Never its message,
#: which can name a path or carry text a user typed"), ``_note_error`` writes only that, and ``_debug_failure`` is ``log_failure`` behind a
#: check that DEBUG is on (tested below).
_EXTRA_SCRUBBING_CALLS = {
    "src/monitoring/vitals_history.py": {"_reason", "_note_error", "_debug_failure"},
    # ``exception_text`` on the refusal's words, then the run's own state dict (no exception text).
    "src/api/bulletin.py": {"_scope_mismatch_detail"},
}
#: The bundle writer is read whole, like the witnesses, with its own two scrubbing helpers added: ``_all_diag_err_str`` is
#: ``exception_text(limit=300)`` and ``_err_str`` its older spelling. What the guard still reports there is each LINE below, with the
#: reason it stands. A line is allowed in the FUNCTION it stands in and as many times as the table counts: the same text copied into
#: another function (a raw use dressed as an allowed line), or a second hit in the same one, is reported; an allowance that no longer
#: matches a hit, or matches fewer than it counts, fails, so the table cannot outlive the code it excuses.
_BUNDLE_SCRUBS = {"_all_diag_err_str", "_err_str"}
#: Keyed by (the function the line stands in, the line's text) with the NUMBER of hits the guard reports on it: the same line
#: copied into another function, or a second use in the same one, is a hit the table does not excuse.
_BUNDLE_ALLOWED: dict[tuple[str, str], tuple[int, str]] = {
    ("all_diagnostics_volumes", ") from exc"): (
        2,
        "the closing line of a raise whose own detail is a fixed sentence: the cause chain rides the HTTPException the route answers "
        "with, and nothing logs an HTTPException's chain (the member handlers write it through _all_diag_err_str)",
    ),
    ("all_diagnostics_volume_download", ") from exc"): (
        1,
        "the same closing line, in the download route of one volume",
    ),
    ("all_diagnostics_volumes", "raise HTTPException(status_code=507, detail=str(exc)) from exc"): (
        2,
        "a VolumeRoomError, whose text diagnostics_volumes composes from sizes and the drive; the answer goes to the local page",
    ),
    ("all_diagnostics_volumes", "raise HTTPException(status_code=500, detail=str(exc) or type(exc).__name__) from exc"): (
        4,
        "the error of splitting a FINISHED zip on disk, answered to the local page, which puts its own translated sentence before it: "
        "no engine and no passphrase in the path (_ensure_volume_set reads a zip and writes volumes). If an engine ever enters it, "
        "this allowance is wrong",
    ),
    ("all_diagnostics_volumes", 'if no_room_refusal(exc, "splitting the archive") is None:'): (
        1,
        "no_room_refusal reads errno and nothing else (keyword_log_scan)",
    ),
    ("all_diagnostics_volumes", 'f"written ({exc.strerror or type(exc).__name__}). The earlier set of files, if there "'): (
        1,
        "the operating system's own reason (\"No space left on device\"), never the message, which carries the path",
    ),
    ("_run_nondb_member_bounded._run", 'box["error"] = exc'): (
        1,
        "stored for the caller's side to re-raise, where the per-member handler writes it through _all_diag_err_str",
    ),
    ("_merged_member", "cause = exc.__cause__ if isinstance(exc, HTTPException) else None"): (
        1,
        "the cause is asked its type (isinstance) or handed to _all_diag_err_str, and the HTTPException itself is not read",
    ),
    ("_write_all_diagnostics_zip", "cause = exc.__cause__ if isinstance(exc, HTTPException) else None"): (
        1,
        "the same, in the build's per-member handler",
    ),
}
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log", "fatal"}
_TRACEBACK_CALLS = {
    "exception",
    "format_exc",
    "print_exc",
    "format_exception",
    "print_exception",
    "format_exception_only",
    "exc_info",
}
#: The calls a handler's bound exception may be handed to: each writes it through the one scrub, or asks for its class.
#: ``forensics._why`` is ``tidy_error`` with the report's own cut.
_SCRUBBING_CALLS = {"tidy_error", "exc_line", "exception_text", "traceback_text", "log_failure", "type", "isinstance", "_why"}


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _is_not_the_text_of_the_failure(use: ast.Name, parent: dict[ast.AST, ast.AST]) -> bool:
    """``exc.__class__`` (its class), ``len(exc.exceptions)`` (a count) and ``raise exc.exceptions[0]`` (the member, raised again as
    it is for the server to see). ``[str(x) for x in exc.exceptions]`` and ``str(exc.exceptions[0])`` are its text, and are not."""
    attr = parent.get(use)
    if not isinstance(attr, ast.Attribute):
        return False
    if attr.attr == "__class__":
        return True
    if attr.attr != "exceptions":
        return False
    up = parent.get(attr)
    if isinstance(up, ast.Call) and _call_name(up) == "len" and attr in up.args:
        return True
    return isinstance(up, ast.Subscript) and up.value is attr and isinstance(parent.get(up), ast.Raise)


def _leaks(
    source: str,
    *,
    handlers: bool = True,
    also_scrubbing: frozenset[str] | set[str] = frozenset(),
    only_scrubbing: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """The ways a module of the witnesses could print a failure raw: a log call asked for the traceback (``exc_info`` that is not
    the constant False/None, ``.exception()``, the ``traceback`` module however it is imported, ``exc_info()`` however it is
    imported, a ``**`` mapping a log call could carry ``exc_info`` in, a log method reached through ``getattr`` or kept in a name),
    and a handler's bound exception used anywhere but as an argument of a scrubbing call or of ``type()``/``isinstance()``.

    ``only_scrubbing`` is the STRICT reading the bulletin sweep uses: the calls named there are the only ones that may be handed the
    exception (``_SCRUBBING_CALLS`` and ``also_scrubbing`` are not consulted), and ``log_failure`` takes it as its THIRD argument, where
    the exception goes, never as the first words (``log_failure(_LOG, exc, exc)`` writes the unscrubbed words into the line)."""
    tree = ast.parse(source)
    parent = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    out: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "exc_info"
            and not (isinstance(node.value, ast.Constant) and node.value.value in (False, None))
        ):
            out.append(f"{node.value.lineno}: a log call asked for the traceback (exc_info)")
        if isinstance(node, ast.Call) and _call_name(node) in _TRACEBACK_CALLS:
            out.append(f"{node.lineno}: {_call_name(node)}() writes the traceback")
        if isinstance(node, ast.Call) and any(k.arg is None for k in node.keywords) and _call_name(node) in _LOG_METHODS | {None}:
            out.append(f"{node.lineno}: a ** mapping handed to a log call can carry exc_info")
        if (
            isinstance(node, ast.Call)
            and _call_name(node) == "getattr"
            and len(node.args) >= 2
            and not (isinstance(node.args[1], ast.Constant) and node.args[1].value not in _LOG_METHODS | _TRACEBACK_CALLS)
        ):
            out.append(f"{node.lineno}: getattr reaches {ast.unparse(node.args[1])}, a way round the scan of the log calls")
        if isinstance(node, ast.Attribute) and node.attr == "exc_info":
            out.append(f"{node.lineno}: sys.exc_info() reads the exception being handled")
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and node.attr in _LOG_METHODS
            and not (isinstance(parent.get(node), ast.Call) and parent[node].func is node)
        ):
            out.append(f"{node.lineno}: {ast.unparse(node)} is kept as a name, a log call the scan cannot read")
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "traceback" for a in node.names):
            out.append(f"{node.lineno}: the traceback module is imported")
        if isinstance(node, ast.ImportFrom) and (
            (node.module or "").split(".")[0] == "traceback" or any(a.name in _TRACEBACK_CALLS for a in node.names)
        ):
            out.append(f"{node.lineno}: a traceback function is imported by name")
        if handlers and isinstance(node, ast.ExceptHandler) and node.name:
            for stmt in node.body:
                for use in ast.walk(stmt):
                    if not (isinstance(use, ast.Name) and use.id == node.name and isinstance(use.ctx, ast.Load)):
                        continue
                    call = parent.get(use)
                    allowed = (_SCRUBBING_CALLS | also_scrubbing) if only_scrubbing is None else only_scrubbing
                    if isinstance(call, ast.Call) and _call_name(call) in allowed and use in call.args:
                        if only_scrubbing is not None and _call_name(call) == "log_failure" and call.args.index(use) != 2:
                            out.append(f"{use.lineno}: the caught exception {node.name!r} is handed to log_failure as its words, not as the failure")
                        continue
                    if _is_not_the_text_of_the_failure(use, parent):
                        continue
                    out.append(f"{use.lineno}: the caught exception {node.name!r} is used outside a scrubbing call")
    return out


@pytest.mark.parametrize("rel", _WITNESS_MODULES)
def test_the_modules_of_the_crash_witnesses_log_no_traceback_and_print_no_caught_exception_raw(rel):
    source = (ROOT / rel).read_text(encoding="utf-8")
    extra = _EXTRA_SCRUBBING_CALLS.get(rel, set())
    assert _leaks(source, also_scrubbing=extra) == [], f"{rel}: {_leaks(source, also_scrubbing=extra)}"


#: Every module of the bulletin, its routes and the card audit, which ride the diagnostics bundle or answer the operator: no log call
#: asks for a traceback and no record carries a caught exception's words (``tests/test_bulletin_sink_sites.py`` drives each site with a
#: held passphrase). The bulletin directory is READ, not listed, so a module added to it is held to the rule from its first commit.
_SWEEP_MODULES = (
    "src/briefing/card_audit.py",
    "src/briefing/card_audit_diff.py",
    "src/api/bulletin.py",
    *sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "src" / "bulletin").glob("*.py")),
)


def test_the_sweep_reads_the_whole_bulletin_directory():
    names = {rel for rel in _SWEEP_MODULES if rel.startswith("src/bulletin/")}
    assert {"src/bulletin/facts.py", "src/bulletin/sections.py", "src/bulletin/narration_job.py", "src/bulletin/gate.py"} <= names, names
    assert {"src/api/bulletin.py", "src/briefing/card_audit.py", "src/briefing/card_audit_diff.py"} <= set(_SWEEP_MODULES), "the routes and the card audit are read too"


#: STRICT: a record of these modules keeps the exception's CLASS (``type``) and a log line goes through ``log_failure``; nothing else
#: may be handed a caught exception, except where the person who just asked is told the words (the scrub keeps the sentence and takes
#: the held passphrase out of it): a route's refusal, the evidence plan's folder check, a translator's refused frame.
_SWEEP_CALLS = {"type", "isinstance", "log_failure"}
_SWEEP_WORDS_KEPT = {
    "src/api/bulletin.py": {"exception_text", "_scope_mismatch_detail"},
    "src/bulletin/evidence.py": {"exception_text"},
    "src/bulletin/i18n.py": {"exception_text"},
    "src/briefing/card_audit_diff.py": {"exception_text"},
}


@pytest.mark.parametrize("rel", _SWEEP_MODULES)
def test_the_bulletin_its_routes_and_the_card_audit_log_no_traceback_and_keep_no_caught_exception_raw(rel):
    allowed = _SWEEP_CALLS | _SWEEP_WORDS_KEPT.get(rel, set())
    found = _leaks((ROOT / rel).read_text(encoding="utf-8"), only_scrubbing=allowed)
    assert found == [], f"{rel}: {found}"


@pytest.mark.parametrize(
    ("snippet", "flagged"),
    [
        ("def f():\n    try:\n        pass\n    except Exception as exc:\n        log_failure(_LOG, 'x', exc)\n", False),
        ("def f():\n    try:\n        pass\n    except Exception as exc:\n        return {'error': type(exc).__name__}\n", False),
        ("def f():\n    try:\n        pass\n    except Exception as exc:\n        log_failure(_LOG, exc, exc)\n", True),
        ("def f():\n    try:\n        pass\n    except Exception as exc:\n        return {'error': exception_text(exc)}\n", True),
        ("def f():\n    try:\n        pass\n    except Exception as exc:\n        return {'error': traceback_text(exc)}\n", True),
        ("def f():\n    try:\n        pass\n    except Exception as exc:\n        return {'error': str(exc)[:12]}\n", True),
    ],
    ids=["log_failure", "class", "exc-as-words", "exception_text", "traceback_text", "cut-words"],
)
def test_the_strict_reading_flags_what_a_record_must_not_carry(snippet, flagged):
    assert bool(_leaks(snippet, only_scrubbing=_SWEEP_CALLS)) is flagged


#: The modules whose ``diagnostics_member`` a slot runs and that no other list above reads (the vitals and runs producers are in
#: :data:`_WITNESS_MODULES`). The slot net scrubs what reaches the ZIP; this reads what the producer does with a caught failure on
#: the way (a log line, a traceback, the exception's words handed on), which the net does not see.
_SLOT_PRODUCER_MODULES = (
    "src/monitoring/session_hwm.py",
    "src/database/damage.py",
    "src/monitoring/boots.py",
)
#: What each may hand a caught exception to: ``failure_label`` is the class and the errno name, never the message; ``_error_text`` is
#: ``exception_text`` with the paths tokenised and then cut; ``note_raw_driver_error`` hands the exception to the damage registry, which
#: keeps ``corruption_of``'s fixed label or ``failure_label`` (the registry's own tests hold that).
_SLOT_PRODUCER_SCRUBS = {
    "src/database/damage.py": {"failure_label", "note_raw_driver_error"},
    "src/monitoring/boots.py": {"_error_text"},
}
#: A line the guard reports in these modules that is not a leak, with why. A table entry that no longer matches a hit fails below.
_SLOT_PRODUCER_ALLOWED = {
    ("src/monitoring/session_hwm.py", "read = getattr(pool, name, None)"): (
        "reads a counter off the connection pool by a name from the module's own tuple of counter names, not a log method"
    ),
}


def _slot_producer_hits(rel: str, source: str) -> list[tuple[str, str]]:
    lines = source.splitlines()
    got = []
    for hit in _leaks(source, also_scrubbing=_SLOT_PRODUCER_SCRUBS.get(rel, set())):
        text = lines[int(hit.split(":", 1)[0]) - 1].strip()
        if (rel, text) not in _SLOT_PRODUCER_ALLOWED:
            got.append((text, hit))
    return got


@pytest.mark.parametrize("rel", _SLOT_PRODUCER_MODULES)
def test_the_slot_producers_log_no_traceback_and_print_no_caught_exception_raw(rel):
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert _slot_producer_hits(rel, source) == [], rel


@pytest.mark.parametrize("rel", _SLOT_PRODUCER_MODULES)
def test_a_raw_use_planted_in_a_slot_producer_is_reported(rel):
    source = (ROOT / rel).read_text(encoding="utf-8")
    for planted in (
        "\n\ndef _planted():\n    try:\n        go()\n    except OSError as exc:\n        return {'error': str(exc)}\n",
        "\n\ndef _planted():\n    _LOG.debug('x', exc_info=True)\n",
    ):
        assert _slot_producer_hits(rel, source + planted), rel


def test_every_allowance_for_a_slot_producer_still_stands_where_it_is_written():
    stale = []
    for (rel, text), _why in _SLOT_PRODUCER_ALLOWED.items():
        source = (ROOT / rel).read_text(encoding="utf-8")
        lines = source.splitlines()
        hits = [lines[int(h.split(":", 1)[0]) - 1].strip() for h in _leaks(source, also_scrubbing=_SLOT_PRODUCER_SCRUBS.get(rel, set()))]
        if text not in hits:
            stale.append((rel, text))
    assert stale == [], "an allowance that matches no hit any more"


def test_the_module_of_every_built_slot_is_read_by_the_log_guard():
    """A slot added later is guarded without anyone remembering to list it: its module must be in one of the two lists."""
    from src.api import diagnostics_slots as slots

    built = {s.target.split(":", 1)[0].replace(".", "/") + ".py" for s in slots.SLOTS if slots.module_in_build(s)}
    unguarded = built - set(_WITNESS_MODULES) - set(_SLOT_PRODUCER_MODULES)
    assert unguarded == set(), f"a built slot's module the log guard does not read: {sorted(unguarded)}"


def _qualified_names(tree: ast.AST) -> dict[int, str]:
    """For every line of a function, the dotted name of the innermost function that holds it (``outer.inner``)."""
    owner: dict[int, str] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                for line in range(child.lineno, (child.end_lineno or child.lineno) + 1):
                    owner[line] = name
                walk(child, name)
            else:
                walk(child, prefix)

    walk(tree, "")
    return owner


def _bundle_hits(source: str) -> dict[tuple[str, str], list[str]]:
    """The hits of the full guard on the bundle writer, grouped by (the function they stand in, the text of their line)."""
    lines = source.splitlines()
    owner = _qualified_names(ast.parse(source))
    out: dict[tuple[str, str], list[str]] = {}
    for hit in _leaks(source, also_scrubbing=_BUNDLE_SCRUBS):
        number = int(hit.split(":", 1)[0])
        out.setdefault((owner.get(number, "<module>"), lines[number - 1].strip()), []).append(hit)
    return out


def _not_excused(got: dict[tuple[str, str], list[str]]) -> dict[tuple[str, str], list[str]]:
    """The hits the table does not excuse: a line it does not name in that function, or more hits than it counts."""
    return {k: v for k, v in got.items() if k not in _BUNDLE_ALLOWED or len(v) > _BUNDLE_ALLOWED[k][0]}


def test_the_bundle_writer_logs_no_traceback_and_prints_no_caught_exception_raw_but_the_lines_it_states():
    got = _bundle_hits((ROOT / "src/api/diagnostics/bundle.py").read_text(encoding="utf-8"))
    assert _not_excused(got) == {}


def test_every_line_the_bundle_writer_is_allowed_still_stands_there_as_often_as_it_is_counted():
    got = _bundle_hits((ROOT / "src/api/diagnostics/bundle.py").read_text(encoding="utf-8"))
    stale = {k: (n, len(got.get(k, []))) for k, (n, _why) in _BUNDLE_ALLOWED.items() if len(got.get(k, [])) != n}
    assert stale == {}, "an allowance that no longer matches the code: (counted, found)"


def test_a_raw_use_planted_in_the_bundle_writer_is_not_one_of_the_lines_it_is_allowed():
    source = (ROOT / "src/api/diagnostics/bundle.py").read_text(encoding="utf-8")
    planted = source + "\n\ndef _planted():\n    try:\n        go()\n    except OSError as exc:\n        _LOG.warning('x %s', exc)\n"
    assert _not_excused(_bundle_hits(planted)), "the full guard does not see a raw use added to the bundle writer"
    planted = source + "\n\ndef _planted():\n    _LOG.warning('x', exc_info=True)\n"
    assert _not_excused(_bundle_hits(planted))


def test_an_allowed_line_copied_into_another_handler_is_still_reported():
    """The table excuses a line where it stands, not wherever its text appears (the allowed 500 detail copied into a member
    handler survived a guard keyed by text alone)."""
    source = (ROOT / "src/api/diagnostics/bundle.py").read_text(encoding="utf-8")
    for line in (
        "raise HTTPException(status_code=500, detail=str(exc) or type(exc).__name__) from exc",
        'box["error"] = exc',
        "cause = exc.__cause__ if isinstance(exc, HTTPException) else None",
    ):
        # The planted text must BE an allowed text (else the case passes because the text is unknown, whatever the function is).
        assert any(text == line for (_fn, text) in _BUNDLE_ALLOWED), f"not an allowed line: {line}"
        planted = source + f"\n\ndef _planted():\n    try:\n        go()\n    except OSError as exc:\n        {line}\n"
        got = _bundle_hits(planted)
        assert ("_planted", line) in got and _not_excused(got) == {("_planted", line): got[("_planted", line)]}, line
    # and a second use, the SAME text, in the function that is allowed one: the count, not the text, reports it
    anchor = "re-raised on the caller's side below\n            box[\"error\"] = exc\n"
    assert source.count(anchor) == 1
    doubled = source.replace(anchor, anchor + "            box[\"error\"] = exc\n")
    key = ("_run_nondb_member_bounded._run", 'box["error"] = exc')
    assert _not_excused(_bundle_hits(doubled)) == {key: _bundle_hits(doubled)[key]} and len(_bundle_hits(doubled)[key]) == 2
    assert not _not_excused(_bundle_hits(source))


def test_the_traceback_only_reading_ignores_how_a_handler_uses_its_exception():
    body = "def f():\n    try:\n        go()\n    except OSError as exc:\n        return str(exc)\n"
    assert _leaks(body) and _leaks(body, handlers=False) == []
    assert _leaks("def f():\n    _LOG.debug('x', exc_info=True)\n", handlers=False), "a traceback is flagged in either reading"


_FLAGGED = {
    "exc_info=True": "def f():\n    try:\n        go()\n    except OSError:\n        _LOG.debug('x', exc_info=True)\n",
    "exc_info a variable": "def f(e):\n    _LOG.debug('x', exc_info=e)\n",
    ".exception()": "def f():\n    try:\n        go()\n    except OSError:\n        _LOG.exception('x')\n",
    "traceback.format_exc": "def f():\n    return traceback.format_exc()\n",
    "sys.exc_info()": "def f():\n    return sys.exc_info()\n",
    "exc_info() imported by name": "from sys import exc_info\n\n\ndef f():\n    return exc_info()\n",
    "exc_info imported by name, never called": "from sys import exc_info as where\n",
    "traceback.print_exc": "def f():\n    traceback.print_exc()\n",
    "traceback.format_exception": "def f(e):\n    return traceback.format_exception(e)\n",
    "traceback.print_exception": "def f(e):\n    traceback.print_exception(e)\n",
    "traceback.format_exception_only": "def f(e):\n    return traceback.format_exception_only(e)\n",
    "import traceback": "import traceback\n",
    "import traceback as tb": "import traceback as tb\n",
    "from traceback import format_tb": "from traceback import format_tb\n",
    "_LOG.info with a ** mapping": "def f(k):\n    _LOG.info('x', **k)\n",
    "_LOG.warning with a ** mapping": "def f(k):\n    _LOG.warning('x', **k)\n",
    "_LOG.warn with a ** mapping": "def f(k):\n    _LOG.warn('x', **k)\n",
    "_LOG.error with a ** mapping": "def f(k):\n    _LOG.error('x', **k)\n",
    "_LOG.critical with a ** mapping": "def f(k):\n    _LOG.critical('x', **k)\n",
    "_LOG.fatal with a ** mapping": "def f(k):\n    _LOG.fatal('x', **k)\n",
    "_LOG.log with a ** mapping": "def f(k):\n    _LOG.log(10, 'x', **k)\n",
    "_LOG.warn with exc_info": "def f():\n    _LOG.warn('x', exc_info=True)\n",
    "_LOG.critical with exc_info": "def f():\n    _LOG.critical('x', exc_info=True)\n",
    "_LOG.fatal with exc_info": "def f():\n    _LOG.fatal('x', exc_info=True)\n",
    "_LOG.error with exc_info": "def f():\n    _LOG.error('x', exc_info=True)\n",
    "_LOG.log with exc_info": "def f():\n    _LOG.log(10, 'x', exc_info=True)\n",
    "a log method reached through getattr": "def f(k):\n    getattr(_LOG, 'debug')(**k)\n",
    "a log method reached through getattr, no **": "def f():\n    getattr(_LOG, 'exception')('x')\n",
    "a log method kept in a name": "def f(k):\n    emit = _LOG.debug\n    emit('x', **k)\n",
    "a log method of a logger from getattr, kept in a name": (
        "def f(k):\n    fn = logging.getLogger('a').debug\n    fn('x', **k)\n"
    ),
    "a log method of an attribute, kept in a name": "def f(self, k):\n    emit = self._log.debug\n    emit('x', **k)\n",
    "a log method looked up with a name that is not a constant": "def f(name, k):\n    fn = getattr(_LOG, name)\n    fn('x', **k)\n",
    "a log method looked up by a constant name": "def f(k):\n    fn = getattr(_LOG, 'warning')\n    fn('x', **k)\n",
    "the exception method kept in a name": "def f():\n    fn = _LOG.exception\n    fn('x')\n",
    "a traceback function reached through getattr": "def f(e):\n    return getattr(traceback, 'format_exc')()\n",
    "sys.exc_info kept in a name": "def f():\n    g = sys.exc_info\n    return g()\n",
    "the members of a group, stringified whole": (
        "def f():\n    try:\n        go()\n    except BaseExceptionGroup as exc:\n        return str(exc.exceptions)\n"
    ),
    "a log method kept in a name, then asked for the traceback": "def f():\n    emit = _LOG.debug\n    emit('x', exc_info=True)\n",
    "exc_info() called, its import out of sight": "def f():\n    return exc_info()\n",
    "a ** into a call that is not a name": "def f(k):\n    pick()(**k)\n",
    "the members of a group, as text": (
        "def f():\n    try:\n        go()\n    except BaseExceptionGroup as exc:\n        return [str(x) for x in exc.exceptions]\n"
    ),
    "a member of a group, as text": (
        "def f():\n    try:\n        go()\n    except BaseExceptionGroup as exc:\n        return str(exc.exceptions[0])\n"
    ),
    "the members of a group, handed on": (
        "def f():\n    try:\n        go()\n    except BaseExceptionGroup as exc:\n        return exc.exceptions\n"
    ),
    "a ** mapping": "def f(k):\n    _LOG.debug('x', **k)\n",
    "str(exc)": "def f():\n    try:\n        go()\n    except OSError as exc:\n        return str(exc)\n",
    "an f-string of exc": "def f():\n    try:\n        go()\n    except OSError as exc:\n        return f'bad {exc}'\n",
    "exc.args": "def f():\n    try:\n        go()\n    except OSError as exc:\n        return exc.args\n",
    "exc as an extra argument": "def f():\n    try:\n        go()\n    except OSError as exc:\n        _LOG.debug('x %s', exc)\n",
    "a scrubbing call that is not given exc itself": (
        "def f():\n    try:\n        go()\n    except OSError as exc:\n        return tidy_error(str(exc))\n"
    ),
}
_ALLOWED = {
    "exc_info=False": "def f():\n    _LOG.debug('x', exc_info=False)\n",
    "exc_info=None": "def f():\n    _LOG.debug('x', exc_info=None)\n",
    "tidy_error(exc)": "def f():\n    try:\n        go()\n    except OSError as exc:\n        return tidy_error(exc, 200)\n",
    "log_failure(log, what, exc)": "def f():\n    try:\n        go()\n    except OSError as exc:\n        log_failure(_LOG, 'x', exc)\n",
    "a log method called on the spot": "def f():\n    _LOG.debug('x')\n    _LOG.warning('y %s', 1)\n",
    "a count of the members of a group": (
        "def f():\n    try:\n        go()\n    except BaseExceptionGroup as exc:\n        return len(exc.exceptions)\n"
    ),
    "a single member of a group, raised again as it is": (
        "def f():\n    try:\n        go()\n    except BaseExceptionGroup as exc:\n"
        "        if len(exc.exceptions) == 1:\n            raise exc.exceptions[0] from None\n        raise\n"
    ),
    "getattr for something that is not a log method": "def f(e):\n    return getattr(e, 'errno', None)\n",
    "a module that imports from secret_scrub": "from src.monitoring.secret_scrub import traceback_text\n",
    "exc.__class__.__name__": "def f():\n    try:\n        go()\n    except OSError as exc:\n        return exc.__class__.__name__\n",
    "type(exc).__name__": "def f():\n    try:\n        go()\n    except OSError as exc:\n        return type(exc).__name__\n",
    "a handler that binds nothing": "def f():\n    try:\n        go()\n    except OSError:\n        _LOG.debug('x')\n",
}


@pytest.mark.parametrize("name", sorted(_FLAGGED))
def test_the_guard_flags_each_way_a_failure_is_printed_raw(name):
    assert _leaks(_FLAGGED[name]), f"the guard does not see: {name}"


@pytest.mark.parametrize("name", sorted(_ALLOWED))
def test_the_guard_lets_the_calls_that_scrub_through(name):
    assert _leaks(_ALLOWED[name]) == [], name
