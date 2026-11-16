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


@pytest.mark.parametrize(
    ("handle", "wait", "last_error", "expected"),
    [
        (7, 0x102, 0, True),  # WAIT_TIMEOUT: running
        (7, 0, 0, False),  # WAIT_OBJECT_0: ended
        (7, 0xFFFFFFFF, 0, True),  # WAIT_FAILED: no answer, so running (a wait has a deadline; a wrong "ended" erases)
        (0, None, 87, False),  # ERROR_INVALID_PARAMETER: no such process
        (0, None, 5, True),  # ERROR_ACCESS_DENIED: it exists
    ],
)
def test_on_windows_the_probe_asks_the_process_object_and_never_signals(monkeypatch, handle, wait, last_error, expected):
    k32 = _Win(handle, wait)
    wintypes = types.SimpleNamespace(HANDLE=object, DWORD=object, BOOL=object)
    fake_ctypes = types.SimpleNamespace(WinDLL=lambda *_a, **_k: k32, wintypes=wintypes, get_last_error=lambda: last_error)
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


def _signal_zero_calls(text: str) -> int:
    """``kill(x, 0)``, ``kill(x, SIG_DFL)`` (0 on Windows too) or ``kill(x, <a name>)``, as ``os.kill`` or a bare ``kill``; a call that
    signals the process itself (``os.getpid()``) is not a probe of another process."""
    n = 0
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call) or len(node.args) != 2:
            continue
        f = node.func
        if not ((isinstance(f, ast.Attribute) and f.attr == "kill") or (isinstance(f, ast.Name) and f.id == "kill")):
            continue
        target, sig = node.args
        if isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute) and target.func.attr == "getpid":
            continue
        zero = isinstance(sig, ast.Constant) and sig.value == 0
        dfl = isinstance(sig, ast.Attribute) and sig.attr == "SIG_DFL"
        if zero or dfl or isinstance(sig, ast.Name):
            n += 1
    return n


#: Every place allowed to send signal 0, with its count. ``process_owner`` reaches its one only after a Linux /proc read (on any
#: other system it answers "unknown" first); the probe and its pinned copy are the probe.
_ALLOWED = {"src/pid_probe.py": 1, "scripts/apply_update.py": 1, "src/safety/process_owner.py": 1}


def test_no_module_probes_a_pid_with_signal_zero_outside_the_probe():
    """A new ``os.kill(pid, 0)`` reaching Windows would end the process it tests: every probe goes through ``src/pid_probe.py``."""
    found = {}
    for base in ("src", "scripts"):
        for path in (REPO / base).rglob("*.py"):
            n = _signal_zero_calls(path.read_text(encoding="utf-8", errors="replace"))
            if n:
                found[path.relative_to(REPO).as_posix()] = n
    assert found == _ALLOWED


def test_the_ratchet_sees_the_spellings_of_signal_zero():
    assert _signal_zero_calls("import os\nos.kill(p, 0)") == 1
    assert _signal_zero_calls("import os, signal\nos.kill(p, signal.SIG_DFL)") == 1
    assert _signal_zero_calls("from os import kill\nkill(p, 0)") == 1
    assert _signal_zero_calls("import os\nsig = 0\nos.kill(p, sig)") == 1
    assert _signal_zero_calls("import os, signal\nos.kill(p, signal.SIGTERM)") == 0
    assert _signal_zero_calls("import os\nos.kill(os.getpid(), signum)") == 0


@pytest.mark.parametrize("pid", [0, -1, 2**32 + 5, None, "12"])
def test_what_is_not_a_process_id_is_no_process(pid):
    """0 and negatives name process GROUPS on POSIX, and a DWORD would wrap 2**32 + 5 to pid 5."""
    assert pid_probe.pid_alive(pid) is False


def test_an_install_without_the_probes_source_refuses_the_uninstall_and_erases_nothing(monkeypatch):
    """The watcher carries the probe as source; without it it could not wait for the server, so nothing is started."""
    from src.safety import uninstall as U

    started = []
    monkeypatch.setattr(U, "_WATCHER_SRC", U._WATCHER_SRC.replace(textwrap.dedent(inspect.getsource(pid_probe.pid_alive)), "__PID_PROBE__\n"))
    monkeypatch.setattr(U.subprocess, "Popen", lambda *a, **k: started.append(a))
    with pytest.raises(RuntimeError, match="liveness probe"):
        U._default_spawn({"launchers": [], "venv": None}, 4242)
    assert started == []
