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
    ("all_diagnostics_volumes", "raise HTTPException(status_code=507, detail=http_detail(exc)) from exc"): (
        1,
        "a VolumeRoomError, whose text diagnostics_volumes composes from sizes and the drive; the answer goes to the local page",
    ),
    ("all_diagnostics_volumes", "raise HTTPException(status_code=500, detail=http_detail(exc) or type(exc).__name__) from exc"): (
        2,
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
_SCRUBBING_CALLS = {"tidy_error", "exc_line", "exception_text", "record_text", "http_detail", "record_traceback", "traceback_text", "log_failure", "type", "isinstance", "_why"}


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


#: The calls that hand a failure's WORDS (the held passphrase out) to the person who just asked; only :data:`_SWEEP_WORDS_KEPT` sites may.
_WORDS_KEPT_CALLS = frozenset({"exception_text", "_scope_mismatch_detail", "_words_of"})


def _enclosing_function(node: ast.AST, parent: dict) -> str:
    """The QUALIFIED name of the innermost function (``Class.method``, ``outer.inner``): a bare name would let a line moved into another
    class's method of the same name hide behind the allowance written for the first."""
    names: list[str] = []
    in_function = False
    while node in parent:
        node = parent[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
            in_function = in_function or not isinstance(node, ast.ClassDef)
    return ".".join(reversed(names)) if in_function else "<module>"


#: Parameter names read as a caught exception when ``params`` is on.
_EXC_PARAMS = frozenset({"exc", "exception", "error", "err", "exc_value", "e", "ex", "cause"})


def _leaks(
    source: str,
    *,
    handlers: bool = True,
    also_scrubbing: frozenset[str] | set[str] = frozenset(),
    only_scrubbing: frozenset[str] | set[str] | None = None,
    words_kept: dict[tuple[str, str], int] | None = None,
    params: bool = False,
) -> list[str]:
    """The ways a module of the witnesses could print a failure raw: a log call asked for the traceback (``exc_info`` that is not
    the constant False/None, ``.exception()``, the ``traceback`` module however it is imported, ``exc_info()`` however it is
    imported, a ``**`` mapping a log call could carry ``exc_info`` in, a log method reached through ``getattr`` or kept in a name),
    and a handler's bound exception used anywhere but as an argument of a scrubbing call or of ``type()``/``isinstance()``.

    ``only_scrubbing`` is the STRICT reading the bulletin sweep uses: the calls named there are the only ones that may be handed the
    exception (``_SCRUBBING_CALLS`` and ``also_scrubbing`` are not consulted), and ``log_failure`` takes it as its THIRD argument, where
    the exception goes, never as the first words (``log_failure(_LOG, exc, exc)`` writes the unscrubbed words into the line).

    ``params`` (default False) reads a function's PARAMETER named like an exception (:data:`_EXC_PARAMS`: ``exc``, ``exception``, ``error``,
    ``err``, ``exc_value``) as bound for the whole function, like a handler's name, so ``__exit__(self, exc_type, exc, tb)`` building a
    record from ``exc`` is read.

    ``words_kept`` (only with ``only_scrubbing``) names the few sites where the person who just asked is told the failure's words: keyed by
    (the function the call stands in, the call's line text) with the NUMBER of uses it excuses, like :data:`_BUNDLE_ALLOWED`. The same text
    copied into another function, or one more use in the same function, is reported, and so is an allowance that no longer matches a use,
    so the table cannot outlive the code it excuses. Without a table (``None``) a call of :data:`_WORDS_KEPT_CALLS` is reported like any
    other use of the exception."""
    tree = ast.parse(source)
    lines = source.splitlines()
    parent = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    out: list[str] = []
    kept_hits: dict[tuple[str, str], int] = {}
    counted: set[int] = set()
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
        bound: list[tuple[str, list[ast.stmt]]] = []
        if handlers and isinstance(node, ast.ExceptHandler) and node.name:
            bound.append((node.name, node.body))
        if params and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            bound.extend((a.arg, node.body) for a in [*args.posonlyargs, *args.args, *args.kwonlyargs] if a.arg in _EXC_PARAMS)
        for bound_name, bound_body in bound:
            for stmt in bound_body:
                for use in ast.walk(stmt):
                    if not (isinstance(use, ast.Name) and use.id == bound_name and isinstance(use.ctx, ast.Load)):
                        continue
                    call = parent.get(use)
                    if (
                        words_kept is not None
                        and isinstance(call, ast.Call)
                        and (_call_name(call) in _WORDS_KEPT_CALLS or (_call_name(call) == "record_text" and "record_text" not in (only_scrubbing or ())))
                        and use in call.args
                    ):
                        if id(use) not in counted:  # a handler inside a handler is walked twice
                            counted.add(id(use))
                            key = (_enclosing_function(call, parent), lines[call.lineno - 1].strip())
                            kept_hits[key] = kept_hits.get(key, 0) + 1
                        continue
                    allowed = (_SCRUBBING_CALLS | also_scrubbing) if only_scrubbing is None else only_scrubbing
                    if isinstance(call, ast.Call) and _call_name(call) in allowed and use in call.args:
                        if only_scrubbing is not None and _call_name(call) == "log_failure" and call.args.index(use) != 2:
                            out.append(f"{use.lineno}: the caught exception {bound_name!r} is handed to log_failure as its words, not as the failure")
                        continue
                    if _is_not_the_text_of_the_failure(use, parent):
                        continue
                    out.append(f"{use.lineno}: the caught exception {bound_name!r} is used outside a scrubbing call")
    if words_kept is not None:
        for key in sorted(kept_hits.keys() | words_kept.keys()):
            got, excused = kept_hits.get(key, 0), words_kept.get(key, 0)
            if got != excused:
                out.append(f"0: the failure's words are kept {got} time(s) at {key!r} and the table excuses {excused}")
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
    """The directory is globbed again HERE, apart from the expression that built the list, so a filter added to that expression (a module
    left out) is a failure of this test and not a quiet gap."""
    on_disk = {p.relative_to(ROOT).as_posix() for p in (ROOT / "src" / "bulletin").glob("*.py")}
    assert on_disk <= set(_SWEEP_MODULES), sorted(on_disk - set(_SWEEP_MODULES))
    assert len(on_disk) >= 15, "the directory glob found no module: the test would pass over nothing"
    assert {"src/api/bulletin.py", "src/briefing/card_audit.py", "src/briefing/card_audit_diff.py"} <= set(_SWEEP_MODULES), "the routes and the card audit are read too"


#: STRICT: a record of these modules keeps the exception's CLASS (``type``) and a log line goes through ``log_failure``; nothing else
#: may be handed a caught exception, except where the person who just asked is told the words (the scrub keeps the sentence and takes
#: the held passphrase out of it): the evidence plan's folder check (a route's refusal goes through ``http_detail``, R140, which is a
#: scrubbing call here: a driver's error is its class, any other keeps its scrubbed words). Each such site is a line of
#: :data:`_SWEEP_WORDS_KEPT`, keyed like :data:`_BUNDLE_ALLOWED`: a record written from one of those functions (``edition["x"] =
#: exception_text(exc)``) is a line the table does not hold.
_SWEEP_CALLS = {"type", "isinstance", "log_failure", "http_detail"}
_SWEEP_WORDS_KEPT: dict[str, dict[tuple[str, str], int]] = {
    # The scope-mismatch refusal is composed by the module's own helper (its fixed words and the two scopes), answered and not saved.
    "src/api/bulletin.py": {
        ("narrate_edition", "raise HTTPException(status_code=409, detail=_scope_mismatch_detail(exc)) from None"): 1,
    },
    # The folder the operator just chose cannot be written: the plan is answered to them and not saved.
    "src/bulletin/evidence.py": {("evidence_plan", 'out["destination_error"] = record_text(exc, limit=300, typed=True)'): 1},
    # The refusal of a diff the operator asked for; the exception is the module's own ``CardAuditDiffError`` (fixed words, a file name and
    # the class). Nothing in src calls it yet.
    "src/briefing/card_audit_diff.py": {
        ("diff_latest_card_audits", 'return {"available": False, "reason": record_text(exc), "saved_runs": names}'): 1
    },
}


def _sweep_leaks(rel: str, source: str) -> list[str]:
    """What the sweep reports for ``source`` read as module ``rel``: the ONE reading both the parametrized sweep and the snippet tests use,
    so loosening the sweep's own call (``also_scrubbing`` for ``only_scrubbing``, a wider allowance) fails a snippet test."""
    return _leaks(source, only_scrubbing=_SWEEP_CALLS, words_kept=_SWEEP_WORDS_KEPT.get(rel))


@pytest.mark.parametrize("rel", _SWEEP_MODULES)
def test_the_bulletin_its_routes_and_the_card_audit_log_no_traceback_and_keep_no_caught_exception_raw(rel):
    found = _sweep_leaks(rel, (ROOT / rel).read_text(encoding="utf-8"))
    assert found == [], f"{rel}: {found}"


_HANDLER = "def f():\n    try:\n        pass\n    except Exception as exc:\n        {body}\n"


@pytest.mark.parametrize(
    ("snippet", "flagged"),
    [
        (_HANDLER.format(body="log_failure(_LOG, 'x', exc)"), False),
        (_HANDLER.format(body="return {'error': type(exc).__name__}"), False),
        (_HANDLER.format(body="log_failure(_LOG, exc, exc)"), True),
        (_HANDLER.format(body="return {'error': exception_text(exc)}"), True),
        (_HANDLER.format(body="return {'error': traceback_text(exc)}"), True),
        (_HANDLER.format(body="return {'error': str(exc)[:12]}"), True),
    ],
    ids=["log_failure", "class", "exc-as-words", "exception_text", "traceback_text", "cut-words"],
)
def test_the_strict_reading_flags_what_a_record_must_not_carry(snippet, flagged):
    assert bool(_sweep_leaks("src/bulletin/cards.py", snippet)) is flagged


@pytest.mark.parametrize(
    ("rel", "body"),
    [
        # a module with no table: the words are not kept anywhere
        ("src/bulletin/cards.py", "raise HTTPException(status_code=400, detail=exception_text(exc, typed=False)) from None"),
        # the same words written into a RECORD of a module that does keep some: not a line the table holds
        ("src/api/bulletin.py", "edition['gate_error'] = exception_text(exc)"),
        ("src/bulletin/evidence.py", "out['archive_error'] = exception_text(exc, limit=300)"),
        ("src/briefing/card_audit_diff.py", "return {'available': False, 'reason': record_text(exc)}"),
    ],
    ids=["no-table", "record-in-api", "record-in-evidence", "record-in-diff"],
)
def test_the_words_kept_table_excuses_lines_not_modules(rel, body):
    found = _sweep_leaks(rel, _HANDLER.format(body=body))
    assert any("excuses 0" in f or "used outside a scrubbing call" in f for f in found), found


def test_an_allowance_that_no_longer_matches_a_use_is_reported():
    """The table cannot outlive the code it excuses: the source of a module is read with its excused line turned into a class."""
    source = (ROOT / "src/bulletin/evidence.py").read_text(encoding="utf-8")
    assert 'out["destination_error"] = record_text' in source
    found = _sweep_leaks("src/bulletin/evidence.py", source.replace('out["destination_error"] = record_text', 'out["destination_error"] = type'))
    assert any("kept 0 time(s)" in f and "table excuses 1" in f for f in found), found


def test_a_second_use_in_a_function_the_table_excuses_once_is_reported():
    line = 'out["destination_error"] = record_text(exc, limit=300, typed=True)'
    source = (ROOT / "src/bulletin/evidence.py").read_text(encoding="utf-8")
    assert source.count(line) == 1
    assert _sweep_leaks("src/bulletin/evidence.py", source) == []
    twice = _sweep_leaks("src/bulletin/evidence.py", source.replace(line, line + "\n" + " " * 12 + line, 1))
    assert any("kept 2 time(s)" in f and "table excuses 1" in f for f in twice), twice
    other = _sweep_leaks("src/bulletin/evidence.py", source.replace(line, line + "\n" + " " * 12 + 'out["again"] = exception_text(exc)', 1))
    assert any("again" in f and "excuses 0" in f for f in other), other


#: The modules whose ``diagnostics_member`` a slot runs and that no other list above reads (the vitals and runs producers are in
#: :data:`_WITNESS_MODULES`). The slot net scrubs what reaches the ZIP; this reads what the producer does with a caught failure on
#: the way (a log line, a traceback, the exception's words handed on), which the net does not see.
_SLOT_PRODUCER_MODULES = (
    "src/monitoring/session_hwm.py",
    "src/database/damage.py",
    "src/monitoring/boots.py",
    "src/monitoring/storage_events.py",
)
#: What each may hand a caught exception to: ``failure_label`` is the class and the errno name, never the message; ``_error_text`` is
#: ``exception_text`` with the paths tokenised and then cut; ``note_raw_driver_error`` hands the exception to the damage registry, which
#: keeps ``corruption_of``'s fixed label or ``failure_label`` (the registry's own tests hold that); the storage-events journal's ``_label``
#: is the class and the errno name, and its ``_internal_failure`` keeps that label and logs the failure through ``log_failure``.
_SLOT_PRODUCER_SCRUBS = {
    "src/database/damage.py": {"failure_label", "note_raw_driver_error"},
    "src/monitoring/boots.py": {"_error_text"},
    "src/monitoring/storage_events.py": {"_label", "_internal_failure"},
}
#: A line the guard reports in these modules that is not a leak, with why. Keyed like :data:`_BUNDLE_ALLOWED`: by (the module, the
#: function the line stands in, the line's text) with the NUMBER of hits it excuses. The same text copied into another function (a raw
#: use dressed as an allowed line), or a second use in the same one, is reported, and so is an allowance that no longer matches a hit
#: or matches fewer than it counts: the table cannot outlive the code it excuses.
_SLOT_PRODUCER_ALLOWED: dict[tuple[str, str, str], tuple[int, str]] = {
    ("src/monitoring/session_hwm.py", "_holders_view", "read = getattr(pool, name, None)"): (
        1,
        "reads a counter off the connection pool by a name from the module's own tuple of counter names, not a log method",
    ),
}


def _slot_producer_hits(rel: str, source: str) -> dict[tuple[str, str], list[str]]:
    """The hits of the guard on one slot producer, grouped by (the function they stand in, the text of their line)."""
    lines = source.splitlines()
    owner = _qualified_names(ast.parse(source))
    out: dict[tuple[str, str], list[str]] = {}
    for hit in _leaks(source, also_scrubbing=_SLOT_PRODUCER_SCRUBS.get(rel, set())):
        number = int(hit.split(":", 1)[0])
        out.setdefault((owner.get(number, "<module>"), lines[number - 1].strip()), []).append(hit)
    return out


def _slot_producer_not_excused(rel: str, got: dict[tuple[str, str], list[str]]) -> dict[tuple[str, str], list[str]]:
    """The hits the table does not excuse: a line it does not name in that function of that module, or more hits than it counts."""
    return {
        k: v
        for k, v in got.items()
        if (rel, *k) not in _SLOT_PRODUCER_ALLOWED or len(v) > _SLOT_PRODUCER_ALLOWED[(rel, *k)][0]
    }


@pytest.mark.parametrize("rel", _SLOT_PRODUCER_MODULES)
def test_the_slot_producers_log_no_traceback_and_print_no_caught_exception_raw(rel):
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert _slot_producer_not_excused(rel, _slot_producer_hits(rel, source)) == {}, rel


@pytest.mark.parametrize("rel", _SLOT_PRODUCER_MODULES)
def test_a_raw_use_planted_in_a_slot_producer_is_reported(rel):
    source = (ROOT / rel).read_text(encoding="utf-8")
    for planted in (
        "\n\ndef _planted():\n    try:\n        go()\n    except OSError as exc:\n        return {'error': str(exc)}\n",
        "\n\ndef _planted():\n    _LOG.debug('x', exc_info=True)\n",
    ):
        assert _slot_producer_not_excused(rel, _slot_producer_hits(rel, source + planted)), rel


def test_every_allowance_for_a_slot_producer_still_stands_where_it_is_written_as_often_as_it_is_counted():
    stale = {}
    for (rel, fn, text), (count, _why) in _SLOT_PRODUCER_ALLOWED.items():
        found = len(_slot_producer_hits(rel, (ROOT / rel).read_text(encoding="utf-8")).get((fn, text), []))
        if found != count:
            stale[(rel, fn, text)] = (count, found)
    assert stale == {}, "an allowance that no longer matches the code: (counted, found)"


def test_an_allowed_slot_producer_line_copied_into_another_function_or_used_twice_is_still_reported():
    """The table excuses a line where it stands, as often as it counts: not wherever its text appears (a raw use dressed as the
    allowed line), and not a second time in the function that is allowed one."""
    (rel, fn, line), (count, _why) = next(iter(_SLOT_PRODUCER_ALLOWED.items()))
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert count == 1 and source.count(line) == 1, "the case below doubles a line the table counts once"
    # the text is allowed, the function is not
    planted = source + f"\n\ndef _planted(pool, name):\n    {line}\n"
    got = _slot_producer_hits(rel, planted)
    assert ("_planted", line) in got and _slot_producer_not_excused(rel, got) == {("_planted", line): got[("_planted", line)]}
    # the function is allowed, a second use of the text in it is not
    at = source.index(line)
    indent = source[source.rindex("\n", 0, at) + 1 : at]
    doubled = source.replace(line, line + "\n" + indent + line, 1)
    got = _slot_producer_hits(rel, doubled)
    assert len(got[(fn, line)]) == 2 and _slot_producer_not_excused(rel, got) == {(fn, line): got[(fn, line)]}
    assert _slot_producer_not_excused(rel, _slot_producer_hits(rel, source)) == {}
    # the line MOVED into a method of another class that has the allowed function's name is not the allowed place
    start = source.rindex("\n", 0, at) + 1
    moved = source.replace(source[start : at + len(line)], f"{indent}pass", 1)
    moved += f"\n\nclass _Elsewhere:\n    def {fn}(self, pool, name):\n        {line}\n"
    got = _slot_producer_hits(rel, moved)
    assert (f"_Elsewhere.{fn}", line) in got
    assert _slot_producer_not_excused(rel, got) == {(f"_Elsewhere.{fn}", line): got[(f"_Elsewhere.{fn}", line)]}


def test_the_module_of_every_built_slot_is_read_by_the_log_guard():
    """A slot added later is guarded without anyone remembering to list it: its module must be in one of the two lists."""
    from src.api import diagnostics_slots as slots

    built = {s.target.split(":", 1)[0].replace(".", "/") + ".py" for s in slots.SLOTS if slots.module_in_build(s)}
    unguarded = built - set(_WITNESS_MODULES) - set(_SLOT_PRODUCER_MODULES)
    assert unguarded == set(), f"a built slot's module the log guard does not read: {sorted(unguarded)}"


#: The two helpers :data:`_SLOT_PRODUCER_SCRUBS` excuses BY NAME for ``storage_events.py``. The exemption trusts the name, so a body that
#: later handed the message on (``str(exc)``, ``exc.args``, an f-string, an alias, a traceback, a number that is really a path) would be
#: excused without a test failing: this reads the BODIES, default-deny. ``param`` is the parameter that holds the caught exception,
#: ``calls`` the calls it may be a positional argument of, ``stores`` the only names the body may bind.
_CLASS_ONLY_HELPERS: dict[str, dict] = {
    "_label": {"param": "exc", "calls": frozenset({"type", "isinstance"}), "stores": frozenset({"name", "code", "named"})},
    "_internal_failure": {
        "param": "exc",
        "calls": frozenset({"_label", "log_failure"}),
        "stores": frozenset({"_INTERNAL_FAILURES", "_LAST_INTERNAL_FAILURE"}),
    },
}
#: What the bodies lean on, with how many times each name is bound at MODULE scope: the helpers once (their own ``def``), the two
#: imports once, and the builtins the bodies call never, so a module-level ``_label = repr`` or ``type = ...`` is reported.
_CLASS_ONLY_BINDINGS = {"_label": 1, "_internal_failure": 1, "log_failure": 1, "errno": 1, "type": 0, "isinstance": 0, "str": 0, "repr": 0}
#: Ways to reach the exception being handled without naming it: the traceback module, ``sys.exc_info()``, ``sys.exception()``.
_EXC_ROUTES = frozenset({"traceback", "exc_info", "exception", "format_exc", "print_exc", "format_exception", "last_value"})


def _bound_at_module_scope(tree: ast.Module) -> dict[str, int]:
    """How many times each name is bound at module scope: defs, classes, imports, assignment targets, loop and ``with`` targets, walrus
    targets and ``except ... as`` names, not entering a function, lambda or class body."""
    counts: dict[str, int] = {}

    def bind(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bind(node.name)
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.Import):
            for a in node.names:
                bind((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                bind(a.asname or a.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bind(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bind(node.id)
        stack.extend(ast.iter_child_nodes(node))
    return counts


def _ways_a_helper_uses_its_exception(source: str) -> dict[str, list[str]]:
    """For each helper of :data:`_CLASS_ONLY_HELPERS` in ``storage_events.py``'s source: what its body does with the exception that is
    not one of the allowed shapes, as ``line: text`` (or a sentence). Default-deny: the exception parameter may appear only as a
    positional argument of an allowed call, or as ``.errno`` on the right of a plain assignment whose name is then only used as the
    operand of ``isinstance(..., int)`` or ``errno.errorcode.get(...)``; no other name may be bound, nothing may be defined or
    imported inside, and nothing may reach the exception being handled by another road (``traceback``, ``sys.exc_info()``)."""
    tree = ast.parse(source)
    lines = source.splitlines()
    out: dict[str, list[str]] = {}

    def at(node: ast.AST) -> str:
        return f"{getattr(node, 'lineno', 0)}: {lines[getattr(node, 'lineno', 1) - 1].strip()}"

    bound = _bound_at_module_scope(tree)
    for name, want in _CLASS_ONLY_BINDINGS.items():
        if bound.get(name, 0) != want:
            out.setdefault("<module>", []).append(f"{name} is bound {bound.get(name, 0)} times at module scope, expected {want}")
    for name, rule in _CLASS_ONLY_HELPERS.items():
        param, calls, stores = rule["param"], rule["calls"], rule["stores"]
        defs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
        if len(defs) != 1:
            out.setdefault(name, []).append(f"defined {len(defs)} times at module level")
            continue
        fn = defs[0]
        bad = out.setdefault(name, [])
        args = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs)]
        if param not in args:
            bad.append(f"the exception parameter {param!r} is not a parameter of {name} (found {args})")
        if fn.args.defaults or any(d is not None for d in fn.args.kw_defaults):
            # a default can rebind a name the body relies on (``type=str``, ``_label=repr``) without a store anywhere in the body
            bad.append(f"{at(fn)} (a parameter default: the helpers take none, and a default can stand in for a name the body calls)")
        if fn.decorator_list:
            bad.append(f"{name} is decorated")
        parents = {child: node for node in ast.walk(fn) for child in ast.iter_child_nodes(node)}
        tainted: set[str] = set()
        uses = 0
        for node in ast.walk(fn):
            if isinstance(node, (ast.Lambda, ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef)) or (
                isinstance(node, ast.FunctionDef) and node is not fn
            ):
                bad.append(f"{at(node)} (defines or imports inside the body)")
            if isinstance(node, ast.ExceptHandler) and node.name:
                bad.append(f"{at(node)} (binds the handled exception)")
            if isinstance(node, ast.Name) and node.id in _EXC_ROUTES or isinstance(node, ast.Attribute) and node.attr in _EXC_ROUTES:
                bad.append(f"{at(node)} (reaches the handled exception another way)")
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id not in stores:
                bad.append(f"{at(node)} (binds {node.id!r})")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == param:
                up = node
                while not isinstance(up, ast.stmt):
                    up = parents[up]
                if node.attr == "errno" and isinstance(up, ast.Assign) and len(up.targets) == 1 and isinstance(up.targets[0], ast.Name):
                    tainted.add(up.targets[0].id)
                    uses += 1
                else:
                    bad.append(at(node))
                continue
            if isinstance(node, ast.Name) and node.id == param and isinstance(node.ctx, ast.Load):
                uses += 1
                up2 = parents.get(node)
                if isinstance(up2, ast.Attribute):
                    continue  # judged on the attribute above
                if isinstance(up2, ast.Call) and node in up2.args and isinstance(up2.func, ast.Name) and up2.func.id in calls:
                    continue
                bad.append(at(node))
        if param in args and uses == 0:
            bad.append(f"the exception parameter {param!r} is never used")
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and node.id in tainted and isinstance(node.ctx, ast.Load):
                up3 = parents.get(node)
                is_int_test = (
                    isinstance(up3, ast.Call) and isinstance(up3.func, ast.Name) and up3.func.id == "isinstance"
                    and len(up3.args) == 2 and up3.args[0] is node and ast.unparse(up3.args[1]) == "int"
                )
                is_name_lookup = isinstance(up3, ast.Call) and ast.unparse(up3.func) == "errno.errorcode.get" and up3.args == [node]
                if not (is_int_test or is_name_lookup):
                    bad.append(f"{at(node)} (the errno value is used for something other than a type test or a name lookup)")
        if not bad:
            del out[name]
    return out


def test_the_storage_events_helpers_the_log_guard_excuses_by_name_hand_on_the_class_and_never_the_message():
    """MUTATION TARGET: the bodies of ``_label`` and ``_internal_failure``. The slot-producer guard counts a call to either as a
    scrub, so what makes them one is read here."""
    source = (ROOT / "src/monitoring/storage_events.py").read_text(encoding="utf-8")
    assert _ways_a_helper_uses_its_exception(source) == {}
    assert set(_CLASS_ONLY_HELPERS) == _SLOT_PRODUCER_SCRUBS["src/monitoring/storage_events.py"], "the table and this check name the same helpers"


def _swap(old: str, new: str):
    def apply(source: str) -> str:
        assert source.count(old) == 1, f"the mutation target moved: {old!r}"
        return source.replace(old, new)

    return apply


def _whole_label(new_def: str):
    def apply(source: str) -> str:
        # bounded by the parser, not by a guessed delimiter (tests/test_source_slicing_discipline.py counts the hand-rolled slices)
        (fn,) = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_label"]
        lines = source.splitlines(keepends=True)
        return "".join(lines[: fn.lineno - 1]) + new_def + "".join(lines[fn.end_lineno :])

    return apply


_FAILURE_LINE = '    _LAST_INTERNAL_FAILURE = f"{what}: {_label(exc)}"\n'
_PLANTED_BODIES = {
    "str-as-name": _swap("    name = type(exc).__name__\n", "    name = str(exc)\n"),
    "fstring-of-exc": _swap('    return f"{name} {named}" if named else name\n', '    return f"{name}: {exc}"\n'),
    "args-fallback": _swap("    code = exc.errno if isinstance(exc, OSError) else None\n", "    code = exc.errno if isinstance(exc, OSError) else exc.args\n"),
    "repr-fallback": _swap(
        "    named = errno.errorcode.get(code) if isinstance(code, int) else None\n",
        "    named = errno.errorcode.get(code) if isinstance(code, int) else repr(exc)\n",
    ),
    "stored-raw": _swap(_FAILURE_LINE, '    _LAST_INTERNAL_FAILURE = f"{what}: {exc}"\n'),
    "aliased": _swap(_FAILURE_LINE, '    held = exc\n    _LAST_INTERNAL_FAILURE = f"{what}: {_label(held)}"\n'),
    "traceback-logged": _swap(
        '    log_failure(_LOG, f"storage events: {what}", exc, level=logging.DEBUG)\n',
        '    _LOG.debug("storage events: %s", what, exc_info=exc)\n    log_failure(_LOG, f"storage events: {what}", exc, level=logging.DEBUG)\n',
    ),
    "renamed-parameter": _whole_label("def _label(err: BaseException) -> str:\n    return str(err)\n"),
    "traceback-module": _swap(_FAILURE_LINE, '    _LAST_INTERNAL_FAILURE = f"{what}: {traceback.format_exc()}"\n'),
    "sys-exception": _swap(_FAILURE_LINE, '    _LAST_INTERNAL_FAILURE = f"{what}: {sys.exception()}"\n'),
    "errno-as-text": _swap('    return f"{name} {named}" if named else name\n', '    return f"{name} {exc.errno}"\n'),
    "errno-value-escapes": _swap('    return f"{name} {named}" if named else name\n', '    return f"{name} {named} {code}"\n'),
    "shadowed-type": _swap("    name = type(exc).__name__\n", "    type = lambda e: str(e)\n    name = type(exc)\n"),
    "default-rebinds-type": _swap("def _label(exc: BaseException) -> str:\n", "def _label(exc: BaseException, type=str) -> str:\n"),
    "default-rebinds-label": _swap(
        "def _internal_failure(what: str, exc: BaseException) -> None:\n", "def _internal_failure(what: str, exc: BaseException, _label=repr) -> None:\n"
    ),
    "keyword-default-rebinds-label": _swap(
        "def _internal_failure(what: str, exc: BaseException) -> None:\n", "def _internal_failure(what: str, exc: BaseException, *, _label=repr) -> None:\n"
    ),
    # a POSITIONAL-ONLY default sits in the same ``defaults`` list as the others; planted so the guard on it is held by a test and not by the reading
    "positional-only-default-rebinds-type": _swap("def _label(exc: BaseException) -> str:\n", "def _label(exc: BaseException, type=str, /) -> str:\n"),
    "positional-only-default-rebinds-label": _swap(
        "def _internal_failure(what: str, exc: BaseException) -> None:\n", "def _internal_failure(what: str, exc: BaseException, _label=repr, /) -> None:\n"
    ),
    "module-level-rebind": lambda source: source + "\n_label = repr\n",
    "module-level-type": lambda source: source + "\ntype = lambda e: str(e)\n",
}


@pytest.mark.parametrize("planted", sorted(_PLANTED_BODIES))
def test_a_helper_that_starts_handing_on_the_message_is_reported(planted):
    source = (ROOT / "src/monitoring/storage_events.py").read_text(encoding="utf-8")
    found = _ways_a_helper_uses_its_exception(_PLANTED_BODIES[planted](source))
    assert found, f"{planted}: not reported"


def _qualified_names(tree: ast.AST) -> dict[int, str]:
    """For every line of a function, the dotted name of the innermost function that holds it (``outer.inner``,
    ``Class.method``): a class is part of the name, so a method of another class that happens to share a
    function's name is a different owner."""
    owner: dict[int, str] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                for line in range(child.lineno, (child.end_lineno or child.lineno) + 1):
                    owner[line] = name
                walk(child, name)
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{prefix}.{child.name}" if prefix else child.name)
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
        "raise HTTPException(status_code=500, detail=http_detail(exc) or type(exc).__name__) from exc",
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


def test_a_words_kept_line_moved_to_another_class_with_the_same_method_name_is_reported():
    """The allowance is keyed by the QUALIFIED function: ``B.run`` does not inherit what was written for ``A.run``."""
    text = (
        "class {cls}:\n    def run(self):\n        try:\n            pass\n        except Exception as exc:\n"
        "            return exception_text(exc, typed=False)\n"
    )
    line = "return exception_text(exc, typed=False)"
    table = {("A.run", line): 1}
    assert _leaks(text.format(cls="A"), only_scrubbing={"type", "isinstance", "log_failure"}, words_kept=table) == []
    moved = _leaks(text.format(cls="B"), only_scrubbing={"type", "isinstance", "log_failure"}, words_kept=table)
    assert any("'B.run'" in m for m in moved) and any("'A.run'" in m for m in moved), moved
