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


def test_the_hook_is_idempotent_and_in_place_at_import():
    assert logging.Handler.handleError is secret_scrub._scrubbed_handle_error
    assert secret_scrub._hook_handle_error() is False


def _handler_classes(base=logging.Handler):
    for cls in base.__subclasses__():
        yield cls
        yield from _handler_classes(cls)


def test_no_handler_in_src_overrides_handle_error():
    """A handler class that defines its own ``handleError`` would bypass the replacement."""
    import importlib
    import pkgutil

    import src

    for mod in pkgutil.walk_packages(src.__path__, "src."):
        try:
            importlib.import_module(mod.name)
        except Exception:  # noqa: BLE001, S112 - an optional dependency missing; the source read below still covers the file
            continue
    own = [
        c
        for c in _handler_classes()
        if c.__module__.startswith("src.") and "handleError" in vars(c)
    ]
    assert not own, own
