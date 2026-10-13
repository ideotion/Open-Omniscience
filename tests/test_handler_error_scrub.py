"""A log handler that cannot write a record does not print the exception that was being logged (sink sweep, PR 2).

``logging.Handler.handleError`` prints the handler's own traceback to ``stderr``, and that traceback's ``__context__`` chain carries
the exception the code was handling when it logged: unscrubbed, so a driver error quoting the passphrase reaches the console (and
anything that captures it) even when the log line itself went through ``secret_scrub.log_failure``. ``secret_scrub`` replaces the
method once, at import, with one that writes a single line naming the classes involved.
"""

from __future__ import annotations

import io
import logging
import sys

import pytest

from src.monitoring import secret_scrub

_PW = "corpus'key\"two\\y"


class _Broken(io.StringIO):
    """A stream that fails the way a full disk does, with the secret in the failure's own words."""

    def write(self, s):  # noqa: ARG002
        raise OSError(f"no space left; the key was {_PW}")


def _driver_error() -> RuntimeError:
    return RuntimeError(f"driver said: {_PW}")


@pytest.fixture
def hooked():
    """The replacement in place (it is, from import) and put back the way it was found when the test ends."""
    secret_scrub._hook_handle_error()
    yield
    secret_scrub._hook_handle_error()


def _log_through_a_broken_handler(use_log_failure: bool, monkeypatch) -> str:
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    handler = logging.StreamHandler(_Broken())
    log = logging.getLogger("t.handler_error")
    log.propagate = False
    log.addHandler(handler)
    try:
        try:
            raise _driver_error()
        except RuntimeError as exc:
            if use_log_failure:
                secret_scrub.log_failure(log, "failed", exc, _PW)
            else:
                log.error("plain line")
    finally:
        log.removeHandler(handler)
    return err.getvalue()


@pytest.mark.parametrize("use_log_failure", [False, True])
def test_a_failing_handler_prints_a_class_only_line(hooked, monkeypatch, use_log_failure):
    out = _log_through_a_broken_handler(use_log_failure, monkeypatch)
    assert "OSError" in out and "StreamHandler" in out and "the record was not written" in out
    assert (
        _PW not in out
        and "Traceback" not in out
        and "RuntimeError" not in out
        and "driver said" not in out
    )


def test_without_the_replacement_the_stock_method_leaks_the_original(monkeypatch):
    """MUTATION TARGET: proves the cases above are not vacuous. With the stock method the same failure prints the handler's
    traceback and, in its context chain, the original exception quoting the passphrase."""
    assert secret_scrub._unhook_handle_error()
    try:
        out = _log_through_a_broken_handler(True, monkeypatch)
    finally:
        secret_scrub._hook_handle_error()
    assert _PW in out or "driver said" in out


def test_it_is_silent_when_raise_exceptions_is_off_and_never_raises(hooked, monkeypatch):
    monkeypatch.setattr(logging, "raiseExceptions", False)
    assert _log_through_a_broken_handler(False, monkeypatch) == ""
    monkeypatch.setattr(logging, "raiseExceptions", True)

    class _NoStderr:
        def write(self, s):
            raise OSError("stderr is gone")

    monkeypatch.setattr(sys, "stderr", _NoStderr())
    handler = logging.StreamHandler(_Broken())
    handler.handleError(logging.LogRecord("x", logging.ERROR, __file__, 1, "m", None, None))
    monkeypatch.setattr(sys, "stderr", None)
    handler.handleError(logging.LogRecord("x", logging.ERROR, __file__, 1, "m", None, None))


def test_the_hook_is_in_place_the_moment_the_module_is_imported():
    """MUTATION TARGET: the module-level ``_hook_handle_error()`` call. A fresh interpreter (the ``hooked`` fixture would put the
    replacement back in this process) must find ``Handler.handleError`` replaced right after the import and nothing else."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    code = (
        f"import sys\nsys.path.insert(0, {str(root)!r})\n"
        "import logging\n"
        "stock = logging.Handler.handleError\n"
        "import src.monitoring.secret_scrub as s\n"
        "assert logging.Handler.handleError is s._scrubbed_handle_error is not stock\n"
        "assert s._hook_handle_error() is False\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def _handler_classes(base=logging.Handler):
    for cls in base.__subclasses__():
        yield cls
        yield from _handler_classes(cls)


def _classes_defining_handle_error(source: str) -> list[str]:
    """Classes whose body defines ``handleError`` by ``def``, ``async def``, assignment (``handleError = lambda ...``) or annotated
    assignment."""
    import ast

    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            names = (
                [item.name]
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
                else [t.id for t in item.targets if isinstance(t, ast.Name)]
                if isinstance(item, ast.Assign)
                else [item.target.id]
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
                else []
            )
            if "handleError" in names:
                found.append(node.name)
    return found


@pytest.mark.parametrize(
    "body",
    [
        "def handleError(self, record): pass",
        "async def handleError(self, record): pass",
        "handleError = lambda self, record: None",
        "handleError: object = None",
    ],
)
def test_the_override_scan_sees_every_way_to_define_it(body):
    """MUTATION TARGET: a form dropped from ``_classes_defining_handle_error``."""
    assert _classes_defining_handle_error(f"class H:\n    {body}\n") == ["H"]
    assert _classes_defining_handle_error("class H:\n    def emit(self, record): pass\n") == []


def test_no_handler_in_src_overrides_handle_error():
    """A handler class that defines its own ``handleError`` would bypass the replacement. Read from the source, so a module that
    cannot be imported here (an optional dependency) is covered as well."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    own = []
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel != "src/monitoring/secret_scrub.py":
            own += [
                f"{rel}:{name}"
                for name in _classes_defining_handle_error(path.read_text(encoding="utf-8"))
            ]
    assert not own, own
