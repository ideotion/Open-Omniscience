"""ONE liveness probe, and never a signal on Windows (row 98).

On Windows ``os.kill(pid, 0)`` is ``TerminateProcess``: the uninstall watcher's wait for the server ended the server it was waiting
for, with no clean close, and against an ended process whose handle was still held the "test" kept succeeding, so the wait ran its
whole 120 s (the crypto_erase watcher tests hit their 60 s timeout on every Windows leg). ``src/pid_probe.py`` asks the process
object there instead; every caller goes through it, the watcher carrying its source and ``scripts/apply_update.py`` a pinned copy.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import ast
import builtins
import inspect
import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from src import pid_probe

REPO = Path(__file__).resolve().parents[1]


def _no_kill(*_a):
    raise AssertionError("os.kill on Windows terminates the process it was meant to test")


class _Win:
    """A kernel32 stand-in that records each call."""

    def __init__(self, handle, wait):
        self.calls: list = []
        self._handle, self._wait = handle, wait
        k32 = self

        class _F:
            def __init__(self, name, ret):
                self.name, self.ret = name, ret

            def __call__(self, *a):
                k32.calls.append((self.name, a))
                return self.ret

        self.OpenProcess = _F("open", handle)
        self.WaitForSingleObject = _F("wait", wait)
        self.CloseHandle = _F("close", 1)


@pytest.mark.parametrize(("handle", "wait", "expected"), [(7, 0x102, True), (7, 0, False), (0, None, False)])
def test_on_windows_the_probe_asks_the_process_object_and_never_signals(monkeypatch, handle, wait, expected):
    k32 = _Win(handle, wait)
    wintypes = types.SimpleNamespace(HANDLE=object, DWORD=object, BOOL=object)
    fake_ctypes = types.SimpleNamespace(WinDLL=lambda *_a, **_k: k32, wintypes=wintypes)
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)
    monkeypatch.setitem(sys.modules, "ctypes.wintypes", wintypes)
    monkeypatch.setattr(pid_probe, "os", types.SimpleNamespace(name="nt", kill=_no_kill))
    assert pid_probe.pid_alive(4242) is expected
    assert k32.calls[0] == ("open", (0x00100000, False, 4242))  # SYNCHRONIZE only: it may wait on the process, never end it
    if handle:
        assert k32.calls[1] == ("wait", (handle, 0)) and k32.calls[-1] == ("close", (handle,))


@pytest.mark.skipif(os.name != "posix", reason="the signal-0 branch is the POSIX one")
def test_on_posix_a_running_process_is_alive_and_an_ended_one_is_not_even_before_it_is_reaped():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert pid_probe.pid_alive(p.pid) is True
    finally:
        p.kill()
    if sys.platform.startswith("linux"):  # unreaped: a zombie still answers signal 0; /proc says Z
        import time

        for _ in range(100):
            if not pid_probe.pid_alive(p.pid):
                break
            time.sleep(0.02)
        assert pid_probe.pid_alive(p.pid) is False
    p.wait()
    assert pid_probe.pid_alive(p.pid) is False
    assert pid_probe.pid_alive(os.getpid()) is True


def test_the_probe_needs_nothing_but_os_so_the_watcher_can_carry_its_source():
    """The watcher runs with ``python -c`` after the environment is gone: the function may name no module global but ``os``."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(pid_probe.pid_alive)))
    fn = tree.body[0]
    local = {a.arg for a in fn.args.args} | {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    local |= {(al.asname or al.name).split(".")[0] for n in ast.walk(fn) if isinstance(n, (ast.Import, ast.ImportFrom)) for al in n.names}
    free = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)} - local - set(dir(builtins))
    assert free == {"os"}


def test_the_uninstall_watcher_waits_with_the_one_probe_and_never_signals_the_server():
    from src.safety.uninstall import _WATCHER_SRC

    probe = textwrap.dedent(inspect.getsource(pid_probe.pid_alive))
    assert probe in _WATCHER_SRC and "__PID_PROBE__" not in _WATCHER_SRC
    rest = _WATCHER_SRC.replace(probe, "")
    assert "os.kill(" not in rest, "the watcher must not signal the server outside the probe"
    assert "if not pid_alive(pid): break" in rest
    compile(_WATCHER_SRC, "watcher", "exec")


def test_the_update_helper_carries_a_byte_identical_copy():
    """``scripts/apply_update.py`` runs while the checkout is mid-swap and imports nothing from ``src``: its copy is pinned here."""
    tree = ast.parse((REPO / "scripts" / "apply_update.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "pid_alive")
    copy = ast.get_source_segment((REPO / "scripts" / "apply_update.py").read_text(encoding="utf-8"), fn)
    assert copy == textwrap.dedent(inspect.getsource(pid_probe.pid_alive)).rstrip("\n")


def test_no_module_probes_a_pid_with_signal_zero_outside_the_probe():
    """A new ``os.kill(pid, 0)`` reaching Windows would end the process it tests: every probe goes through ``src/pid_probe.py``.
    ``process_owner`` keeps its own, reached only after a Linux /proc read (it answers "unknown" before it on any other system)."""
    allowed = {"src/pid_probe.py", "scripts/apply_update.py", "src/safety/process_owner.py"}
    found = []
    for base in ("src", "scripts"):
        for path in (REPO / base).rglob("*.py"):
            rel = path.relative_to(REPO).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            for node in ast.walk(ast.parse(text)):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "kill"
                        and len(node.args) == 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == 0):
                    found.append(rel)
    assert set(found) <= allowed, sorted(set(found) - allowed)
