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
  * ``exit_evidence.arm_crash_trace`` writes its reason, and logs it, on a failure at boot.

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
)
_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log", "fatal"}
_TRACEBACK_CALLS = {"exception", "format_exc", "print_exc", "format_exception", "print_exception", "format_exception_only"}
#: The calls a handler's bound exception may be handed to: each writes it through the one scrub, or asks for its class.
#: ``forensics._why`` is ``tidy_error`` with the report's own cut.
_SCRUBBING_CALLS = {"tidy_error", "exc_line", "exception_text", "traceback_text", "log_failure", "type", "isinstance", "_why"}
#: Attributes of a caught exception that are not its text: its class, and the members of an exception group (which the
#: handler raises again, as they are, for the server to see).
_NOT_TEXT_ATTRIBUTES = {"__class__", "exceptions"}


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _leaks(source: str) -> list[str]:
    """The ways a module of the witnesses could print a failure raw: a log call asked for the traceback (``exc_info`` that is not
    the constant False/None, ``.exception()``, the ``traceback`` module, a ``**`` mapping a log call could carry ``exc_info`` in), and
    a handler's bound exception used anywhere but as an argument of a scrubbing call or of ``type()``/``isinstance()``."""
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
        if isinstance(node, ast.Call) and _call_name(node) in _LOG_METHODS and any(k.arg is None for k in node.keywords):
            out.append(f"{node.lineno}: a ** mapping handed to a log call can carry exc_info")
        if isinstance(node, ast.Attribute) and node.attr in {"exc_info"}:
            out.append(f"{node.lineno}: sys.exc_info() reads the exception being handled")
        if isinstance(node, ast.ExceptHandler) and node.name:
            for stmt in node.body:
                for use in ast.walk(stmt):
                    if not (isinstance(use, ast.Name) and use.id == node.name and isinstance(use.ctx, ast.Load)):
                        continue
                    call = parent.get(use)
                    if isinstance(call, ast.Call) and _call_name(call) in _SCRUBBING_CALLS and use in call.args:
                        continue
                    if isinstance(call, ast.Attribute) and call.attr in _NOT_TEXT_ATTRIBUTES:
                        continue
                    out.append(f"{use.lineno}: the caught exception {node.name!r} is used outside a scrubbing call")
    return out


@pytest.mark.parametrize("rel", _WITNESS_MODULES)
def test_the_modules_of_the_crash_witnesses_log_no_traceback_and_print_no_caught_exception_raw(rel):
    source = (ROOT / rel).read_text(encoding="utf-8")
    assert _leaks(source) == [], f"{rel}: {_leaks(source)}"


_FLAGGED = {
    "exc_info=True": "def f():\n    try:\n        go()\n    except OSError:\n        _LOG.debug('x', exc_info=True)\n",
    "exc_info a variable": "def f(e):\n    _LOG.debug('x', exc_info=e)\n",
    ".exception()": "def f():\n    try:\n        go()\n    except OSError:\n        _LOG.exception('x')\n",
    "traceback.format_exc": "def f():\n    return traceback.format_exc()\n",
    "sys.exc_info()": "def f():\n    return sys.exc_info()\n",
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
