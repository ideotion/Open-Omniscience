"""A crash of the app leaves no core dump that holds the passphrase (2026-10-06, the release-candidate thread).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``src/monitoring/core_guard.py`` holds a process that holds the passphrase to a core limit of exactly 1, soft and hard,
and where the hard limit is already 0 (a launcher's ``ulimit -c 0``) makes it non-dumpable instead. WHY 1 AND NOT 0 is
measured (kernel 6.18.44, a piped handler against a file pattern): a piped handler is handed a FULL dump at 0, and
nothing at exactly 1, where the kernel aborts the dump itself; a shell cannot set 1 at all. What these tests hold, in
three layers because each can fail on its own:

  * the LOGIC, against a fake kernel that behaves as a process without CAP_SYS_RESOURCE meets the real one (a limit that
    can only be lowered, a dumpable flag that can be refused), so every branch runs on every machine, whatever limit the
    harness happens to run under;
  * the KERNEL, in real child processes (the limit as ``getrlimit`` reads it, inherited by a grandchild, the dumpable flag
    reset by ``exec``, and, where this machine's core pattern writes a file in the working directory, a real SIGSEGV
    that leaves no file beside a control that does);
  * the WIRING: the entry points that can hold the passphrase call the guard before they read it, ``set_passphrase``
    and the import of the store module are the net under one that forgot, no launcher sets a limit of its own (it
    could not set the value, and a ``ulimit -c 0`` there would make the in-process call fail), and nothing offers an
    opt-out.

``tests/conftest.py`` stubs ``core_guard.engage`` for the rest of the suite (a process that engaged is never raised
again, and hundreds of tests set a throwaway passphrase), so the real function is taken here at collection.
"""

from __future__ import annotations

import ast
import builtins
import io
import json
import os
import re
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.monitoring import core_guard as G
from tests.js_source_helper import python_function_source

#: The real function, taken at collection (see the module docstring).
_ENGAGE = G.engage
_ROOT = Path(__file__).resolve().parents[1]
_POSIX = pytest.mark.skipif(sys.platform == "win32", reason="there is no per-process core limit on Windows")
_LINUX = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="prctl(PR_SET_DUMPABLE) is Linux")


def _harness_limit() -> tuple[int, int] | None:
    try:
        import resource
    except ImportError:
        return None
    return resource.getrlimit(resource.RLIMIT_CORE)


_HARNESS = _harness_limit()
#: The limit can be set in a child only where the harness's own hard limit is not already 0 (a limit is only lowered).
_SETTABLE = pytest.mark.skipif(
    _HARNESS is None or _HARNESS[1] == 0, reason="the harness itself runs with a hard core limit of 0: it cannot be set"
)


# --------------------------------------------------------------------------- #
#  The logic, against a fake kernel
# --------------------------------------------------------------------------- #
class _Kernel:
    """What the guard talks to, as a process without CAP_SYS_RESOURCE meets it: one core limit that can only be lowered
    (a refusal is the ``ValueError`` ``resource`` raises) and the dumpable flag, which the kernel may refuse to change (a
    sandbox). One process, so ``exec`` resetting the flag is not modelled: the real kernel tests below do."""

    RLIMIT_CORE = 4
    RLIM_INFINITY = -1

    def __init__(self, soft: int = 0, hard: int = -1, dumpable: int = 1, *, can_set_dumpable: bool = True,
                 oserror: bool = False) -> None:
        self.soft, self.hard, self.dumpable = soft, hard, dumpable
        self.can_set_dumpable, self.oserror = can_set_dumpable, oserror
        self.set_calls: list[tuple[int, int]] = []
        self.prctl_calls: list[tuple[int, int]] = []

    def getrlimit(self, which: int) -> tuple[int, int]:
        assert which == self.RLIMIT_CORE, "the guard asked for a limit that is not the core limit"
        return self.soft, self.hard

    def setrlimit(self, which: int, limits: tuple[int, int]) -> None:
        assert which == self.RLIMIT_CORE, "the guard set a limit that is not the core limit"
        self.set_calls.append(limits)
        if self.oserror:
            raise OSError(1, "Operation not permitted")
        soft, hard = limits

        def size(v: int) -> float:
            return float("inf") if v == self.RLIM_INFINITY else v

        if size(hard) > size(self.hard):
            raise ValueError("not allowed to raise maximum limit")
        if size(soft) > size(hard):
            raise ValueError("current limit exceeds maximum limit")
        self.soft, self.hard = soft, hard

    def prctl(self, option: int, arg: int = 0) -> int:
        self.prctl_calls.append((option, arg))
        if option == G._PR_GET_DUMPABLE:
            return self.dumpable
        if option == G._PR_SET_DUMPABLE:
            if not self.can_set_dumpable:
                return -1
            self.dumpable = arg
            return 0
        raise AssertionError(f"the guard asked the kernel for something else: prctl({option})")

    def asked_not_to_be_dumped(self) -> bool:
        return any(opt == G._PR_SET_DUMPABLE for opt, _ in self.prctl_calls)


@pytest.fixture
def kernel(monkeypatch) -> _Kernel:
    k = _Kernel()
    monkeypatch.setattr(G, "_resource", lambda: k)
    monkeypatch.setattr(G, "_prctl", k.prctl)
    monkeypatch.setattr(G, "_read_pattern", lambda: "core")
    return k


def test_the_limit_is_one_and_never_zero():
    """MUTATION TARGET. 0 leaves a piped handler a full dump (measured: 6,545,408 bytes of a bare interpreter); 1 is the
    one value the kernel refuses to dump at."""
    assert G.CORE_LIMIT == 1


def test_engage_holds_the_limit_at_exactly_one_soft_and_hard(kernel):
    got = _ENGAGE()
    assert (kernel.soft, kernel.hard) == (1, 1)
    assert got["mechanism"] == "rlimit" and got["soft"] == got["hard"] == 1 and got["inherited_by_children"] is True
    assert kernel.set_calls == [(1, 1)]
    assert not kernel.asked_not_to_be_dumped(), "the limit held, so nothing weaker was asked for"


@pytest.mark.parametrize("start", [(0, -1), (-1, -1), (0, 1 << 20), (4096, 4096), (2, 2), (1, -1)])
def test_every_limit_that_can_be_lowered_is_set_to_the_guard(kernel, start):
    """The usual desktop (soft 0, hard unlimited) and the others a launcher leaves, among them 2 (a piped handler is
    handed the full dump at 2) and a soft 1 under an unlimited hard limit (a process could raise that one again)."""
    kernel.soft, kernel.hard = start
    assert _ENGAGE()["mechanism"] == "rlimit" and (kernel.soft, kernel.hard) == (1, 1)


def test_a_process_already_held_to_the_guard_is_left_alone(kernel):
    kernel.soft = kernel.hard = 1
    got = _ENGAGE()
    assert got["mechanism"] == "rlimit" and kernel.set_calls == [] and not kernel.asked_not_to_be_dumped()


def test_a_hard_limit_of_zero_makes_the_process_not_dumpable_instead(kernel):
    kernel.soft = kernel.hard = 0  # `ulimit -c 0`, which sets both
    got = _ENGAGE()
    assert kernel.set_calls == [(1, 1)], "the limit was tried first"
    assert got["mechanism"] == "dumpable" and got["dumpable"] == 0 and (got["soft"], got["hard"]) == (0, 0)
    assert got["inherited_by_children"] is False, "the flag does not survive an exec: a child must engage itself"


def test_an_oserror_from_the_limit_is_taken_like_the_refusal_of_a_hard_zero(kernel):
    kernel.oserror = True
    got = _ENGAGE()
    assert got["mechanism"] == "dumpable" and kernel.dumpable == 0


def test_strict_refuses_where_only_the_weaker_guard_is_possible_and_tries_nothing_weaker(kernel):
    """MUTATION TARGET. The OSM reference run's children hold the passphrase from their first instruction and only an
    rlimit is inherited, so a strict caller is refused rather than given the fallback."""
    kernel.soft = kernel.hard = 0
    with pytest.raises(G.CoreGuardError) as err:
        _ENGAGE(strict=True)
    assert str(err.value) == G._REFUSED and "cannot be limited" in str(err.value)
    assert not kernel.asked_not_to_be_dumped() and kernel.dumpable == 1


def test_strict_passes_where_the_limit_can_be_set(kernel):
    assert _ENGAGE(strict=True)["mechanism"] == "rlimit"


@pytest.fixture
def windows(monkeypatch):
    """A fake Windows process: an error mode and the C runtime's abort flags that the three calls read and change, so the
    logic runs in every CI job. ``state`` holds what the process has; ``calls`` what was asked of it."""
    state = {"mode": 0, "abort": 0x3}  # default: the fault dialog is on and abort() reports (_WRITE_ABORT_MSG | _CALL_REPORTFAULT)
    calls: list[tuple] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(G, "_resource", lambda: None)
    monkeypatch.setattr(G, "_prctl", lambda *a, **k: None)
    monkeypatch.setattr(G, "_read_pattern", lambda: None)
    monkeypatch.setattr(G, "_win_error_mode", lambda: state["mode"])

    def set_mode(mode):
        calls.append(("SetErrorMode", mode))
        state["mode"] = mode

    def abort_flags(flags=0, mask=0):
        before = state["abort"]
        if mask:
            calls.append(("_set_abort_behavior", flags, mask))
            state["abort"] = (before & ~mask) | (flags & mask)
        return before

    monkeypatch.setattr(G, "_win_set_error_mode", set_mode)
    monkeypatch.setattr(G, "_win_abort_flags", abort_flags)
    return state, calls


def test_on_windows_engage_keeps_a_crash_from_windows_error_reporting_with_both_settings(windows):
    """MUTATION TARGETS: either call removed. A process with no core limit to set is otherwise left to LocalDumps and the report
    queue; the error mode is inherited by a child, the runtime's report of an abort() is not."""
    state, calls = windows
    state["mode"] = 0x8001  # another bit the process already had stays
    out = _ENGAGE()
    assert state["mode"] == 0x8001 | 0x0002, "SEM_NOGPFAULTERRORBOX is ORed in, nothing else is touched"
    assert state["abort"] == 0x1, "_CALL_REPORTFAULT is cleared, the abort message stays"
    assert out["mechanism"] == "error-mode" and out["inherited_by_children"] is True
    assert out["win_nogpfault"] is True and out["win_abort_reportfault"] is False
    assert [c[0] for c in calls] == ["SetErrorMode", "_set_abort_behavior"]


def test_on_windows_status_says_which_of_the_two_settings_is_missing(windows):
    state, _ = windows
    assert G.status()["mechanism"] == "none"
    state["mode"] = 0x0002
    out = G.status()
    assert out["mechanism"] == "none" and out["win_nogpfault"] is True and out["win_abort_reportfault"] is True
    state["mode"], state["abort"] = 0, 0x1
    out = G.status()
    assert out["mechanism"] == "none" and out["win_nogpfault"] is False and out["win_abort_reportfault"] is False


def test_on_windows_a_process_already_held_is_left_alone_and_strict_passes(windows):
    state, calls = windows
    _ENGAGE()
    calls.clear()
    assert _ENGAGE(strict=True)["mechanism"] == "error-mode" and calls == []


def test_on_windows_strict_refuses_when_the_settings_cannot_be_made(windows, monkeypatch):
    monkeypatch.setattr(G, "_win_set_error_mode", lambda mode: None)
    with pytest.raises(G.CoreGuardError):
        _ENGAGE(strict=True)
    assert _ENGAGE()["mechanism"] == "none", "not strict: it never raises, and the status says nothing held"


def test_the_windows_calls_are_nothing_off_windows():
    if sys.platform == "win32":
        pytest.skip("this is the control for the other systems")
    assert G._win_error_mode() is None and G._win_abort_flags() is None
    G._win_set_error_mode(2)  # never raises, touches nothing
    assert "win_nogpfault" not in G.status()


def test_a_system_that_refuses_both_says_none_and_raises_only_when_strict(kernel):
    kernel.soft = kernel.hard = 0
    kernel.can_set_dumpable = False  # a sandbox that filters prctl
    got = _ENGAGE()
    assert got["mechanism"] == "none" and got["dumpable"] == 1 and got["inherited_by_children"] is False
    with pytest.raises(G.CoreGuardError):
        _ENGAGE(strict=True)


def test_a_system_with_no_core_limit_to_set_is_unsupported(monkeypatch):
    monkeypatch.setattr(G, "_resource", lambda: None)  # Windows: no ``resource`` module
    monkeypatch.setattr(G, "_prctl", lambda *a, **k: None)
    monkeypatch.setattr(G, "_read_pattern", lambda: None)
    got = _ENGAGE()
    assert got["mechanism"] == "unsupported" and got["soft"] is None and got["handler"] is None
    with pytest.raises(G.CoreGuardError):
        _ENGAGE(strict=True)


@pytest.mark.parametrize(
    ("soft", "hard", "dumpable", "mechanism"),
    [
        (1, 1, 1, "rlimit"),
        (1, 1, 0, "rlimit"),  # both: the limit is the one a child inherits, so it is the one named
        (0, 0, 0, "dumpable"),
        (0, -1, 0, "dumpable"),
        (1, -1, 1, "none"),  # a soft limit alone is one a process can raise again
        (2, 2, 1, "none"),  # 2 lets a piped handler have the full dump
        (0, 0, 1, "none"),  # the usual advice: leaves a piped handler a full dump
        (-1, -1, 1, "none"),
    ],
)
def test_the_mechanism_is_what_the_kernel_holds_and_not_what_was_asked(kernel, soft, hard, dumpable, mechanism):
    """MUTATION TARGET. The boot record says which guard a session ran under, so it is read from the kernel."""
    kernel.soft, kernel.hard, kernel.dumpable = soft, hard, dumpable
    assert G.status()["mechanism"] == mechanism


def test_status_names_an_unlimited_limit_and_carries_exactly_the_fields_of_the_record(kernel):
    got = G.status()
    assert got["soft"] == 0 and got["hard"] == "unlimited"
    assert set(got) == {"mechanism", "soft", "hard", "dumpable", "inherited_by_children", "handler", "platform"}
    assert got["handler"] == "file" and got["platform"] == sys.platform


def test_a_dumpable_reading_the_call_failed_to_take_is_unread_and_not_minus_one(kernel):
    kernel.dumpable = -1  # prctl's own failure
    assert G.status()["dumpable"] is None


@pytest.mark.parametrize(
    ("pattern", "word"),
    [
        ("core", "file"),
        ("/var/crash/core.%e.%p", "file"),
        ("|/usr/lib/systemd/systemd-coredump %P %u %g %s %t %c %h", "systemd-coredump"),
        ("|/usr/share/apport/apport -p%p -s%s -c%c -d%d -P%P -u%u -g%g -- %E", "apport"),
        ("|/usr/libexec/abrt-hook-ccpp %s %c %p %u %g %t %P %I %h", "abrt-hook-ccpp"),
        ("|", "unreadable"),
        ("| ", "unreadable"),
        (None, None),
    ],
)
def test_the_handler_is_one_word_and_never_a_path_or_an_argument(monkeypatch, pattern, word):
    monkeypatch.setattr(G, "_read_pattern", lambda: pattern)
    assert G.pattern_handler() == word
    assert word is None or "/" not in word


# --------------------------------------------------------------------------- #
#  The kernel, in real child processes
# --------------------------------------------------------------------------- #
def _child(body: str, cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    code = "import json, os, resource, signal, subprocess, sys\nfrom src.monitoring import core_guard as g\n" + body
    environ = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(_ROOT), environ.get("PYTHONPATH", "")) if p)
    environ.pop("OO_DB_PASSPHRASE", None)
    environ.update(env)
    return subprocess.run([sys.executable, "-c", code], cwd=cwd, env=environ, capture_output=True, text=True, timeout=120,
                          check=False)


def _json(proc: subprocess.CompletedProcess[str]) -> dict:
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


_LIMIT = "list(resource.getrlimit(resource.RLIMIT_CORE))"
_GRANDCHILD_LIMIT = "import resource, json; print(json.dumps(list(resource.getrlimit(resource.RLIMIT_CORE))))"


@_POSIX
@_SETTABLE
def test_a_real_process_is_held_to_one_byte_soft_and_hard(tmp_path):
    out = _json(_child(f"got = g.engage()\nprint(json.dumps({{'limit': {_LIMIT}, 'status': got}}))\n", tmp_path))
    assert out["limit"] == [1, 1], "the kernel's own reading, not the guard's"
    assert out["status"]["mechanism"] == "rlimit" and out["status"]["inherited_by_children"] is True


@_POSIX
@_SETTABLE
def test_a_child_of_a_held_process_is_held_with_no_code_of_its_own(tmp_path):
    """An rlimit is inherited through fork and exec: the LLM server, a worker and the restore child are covered the
    moment they exist (and a child cannot raise the hard limit it inherited)."""
    body = (
        "g.engage()\n"
        f"kid = subprocess.run([sys.executable, '-c', {_GRANDCHILD_LIMIT!r}], capture_output=True, text=True)\n"
        "print(kid.stdout.strip())\n"
    )
    assert json.loads(_child(body, tmp_path).stdout.strip().splitlines()[-1]) == [1, 1]


@_LINUX
def test_a_real_process_with_a_hard_limit_of_zero_is_made_not_dumpable_and_a_strict_caller_is_refused(tmp_path):
    body = (
        "resource.setrlimit(resource.RLIMIT_CORE, (0, 0))\n"
        "try:\n"
        "    g.engage(strict=True)\n"
        "    strict = 'held'\n"
        "except g.CoreGuardError:\n"
        "    strict = 'refused'\n"
        "after_strict = g.status()['dumpable']\n"
        "got = g.engage()\n"
        f"print(json.dumps({{'strict': strict, 'after_strict': after_strict, 'status': got, 'limit': {_LIMIT}}}))\n"
    )
    out = _json(_child(body, tmp_path))
    assert out["strict"] == "refused" and out["after_strict"] == 1, "a strict caller is refused and nothing weaker is tried"
    assert out["limit"] == [0, 0]
    assert out["status"]["mechanism"] == "dumpable" and out["status"]["dumpable"] == 0


@_LINUX
def test_the_dumpable_flag_does_not_survive_an_exec_and_a_child_that_engages_gets_it_back(tmp_path):
    """The reason the entry points that can hold the passphrase call the guard themselves, and say so in the record."""
    kid = (
        "import json; from src.monitoring import core_guard as g; "
        "bare = g.status(); g.engage(); print(json.dumps([bare['dumpable'], bare['mechanism'], g.status()['dumpable']]))"
    )
    body = (
        "resource.setrlimit(resource.RLIMIT_CORE, (0, 0))\n"
        "g.engage()\n"
        "mine = g.status()['dumpable']\n"
        f"kid = subprocess.run([sys.executable, '-c', {kid!r}], capture_output=True, text=True)\n"
        "print(json.dumps({'mine': mine, 'kid': json.loads(kid.stdout.strip().splitlines()[-1])}))\n"
    )
    out = _json(_child(body, tmp_path))
    assert out["mine"] == 0
    assert out["kid"] == [1, "none", 0], "reset by the exec, until the child asks again"


def _writes_a_file_called_core_here() -> bool:
    """This machine's core pattern is the kernel's own ``core``: a dump is a file in the crashed process's working
    directory, where a test can see it. A piped handler or an absolute pattern writes where it cannot, and a test of
    "no dump" there would pass whatever the guard did."""
    return G._read_pattern() == "core"


def _crash(tmp_path: Path, name: str, prelude: str) -> tuple[subprocess.CompletedProcess[str], list[Path]]:
    cwd = tmp_path / name
    cwd.mkdir()
    proc = _child(prelude + "os.kill(os.getpid(), signal.SIGSEGV)\n", cwd)
    return proc, sorted(cwd.glob("core*"))


@_LINUX
@_SETTABLE
def test_a_real_crash_leaves_no_core_file_where_the_same_crash_unguarded_does(tmp_path):
    """MUTATION TARGET. A control first: with the limit raised to its maximum an unguarded SIGSEGV writes a file here, or
    nothing can be observed and the test says so instead of passing. Then the guarded crash writes none, and neither does
    a process that only asked the kernel not to dump it (the fallback), under the same unlimited limit."""
    if not _writes_a_file_called_core_here():
        pytest.skip("this machine's core pattern does not write a file in the working directory: no dump to observe")
    raise_limit = "lim = resource.getrlimit(resource.RLIMIT_CORE)[1]\nresource.setrlimit(resource.RLIMIT_CORE, (lim, lim))\n"
    control, dumps = _crash(tmp_path, "control", raise_limit)
    assert control.returncode == -signal.SIGSEGV
    if not dumps:
        pytest.skip("an unguarded crash wrote no core file here (a size cap or a sandbox): nothing to compare against")
    guarded, left = _crash(tmp_path, "guarded", "g.engage()\n")
    assert guarded.returncode == -signal.SIGSEGV, "the crash is real: it is the dump that is not"
    assert left == [], f"the guarded process left {[p.name for p in left]}"
    weaker, left = _crash(tmp_path, "dumpable", raise_limit + "g._prctl(g._PR_SET_DUMPABLE, 0)\n")
    assert weaker.returncode == -signal.SIGSEGV and left == [], "a process asked not to be dumped leaves no file"


# --- the net under the entry points -------------------------------------- #
_STORE = "from src.database import connect as c\n"


@_POSIX
@_SETTABLE
def test_a_process_that_comes_to_hold_a_passphrase_from_the_environment_is_held_when_the_store_module_is_imported(tmp_path):
    out = _json(_child(f"before = {_LIMIT}\n{_STORE}print(json.dumps({{'before': before, 'after': {_LIMIT}}}))\n", tmp_path,
                       OO_DB_PASSPHRASE="a-passphrase-from-the-launcher"))
    assert out["after"] == [1, 1]


@_POSIX
@_SETTABLE
def test_a_process_that_holds_none_is_left_as_it_was(tmp_path):
    out = _json(_child(f"before = {_LIMIT}\n{_STORE}print(json.dumps({{'before': before, 'after': {_LIMIT}}}))\n", tmp_path))
    assert out["after"] == out["before"], "importing the store module must not hold a process that holds no key"


@_POSIX
@_SETTABLE
def test_set_passphrase_holds_the_process_before_it_holds_the_key_and_clearing_it_holds_nothing(tmp_path):
    """MUTATION TARGET. The net under an entry point that forgot to ask: only a non-empty passphrase engages, and it does
    before the process holds the key."""
    body = (
        _STORE
        + "from src.monitoring import core_guard as g\n"
        + f"seen = {{'start': {_LIMIT}}}\n"
        + "c.set_passphrase(None)\n"
        + f"seen['none'] = {_LIMIT}\n"
        + "c.set_passphrase('')\n"
        + f"seen['empty'] = {_LIMIT}\n"
        + "orig = g.engage\n"
        + "def spy(**kw):\n"
        + "    seen['held_when_asked'] = c.get_passphrase()\n"
        + "    return orig(**kw)\n"
        + "g.engage = spy\n"
        + "c.set_passphrase('a typed passphrase')\n"
        + f"seen['typed'] = {_LIMIT}\n"
        + "print(json.dumps(seen))\n"
    )
    out = _json(_child(body, tmp_path))
    assert out["none"] == out["start"] and out["empty"] == out["start"]
    assert out["typed"] == [1, 1]
    assert out["held_when_asked"] is None, "engaged after the key was already held"


@_POSIX
def test_the_command_line_lists_what_a_crash_left_and_nothing_about_this_commands_own_limits(tmp_path):
    proc = subprocess.run([sys.executable, "-m", "src.monitoring.core_guard"], cwd=tmp_path, capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": os.pathsep.join(p for p in (str(_ROOT), os.environ.get("PYTHONPATH", "")) if p)},
                          timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr[-1000:]
    assert set(json.loads(proc.stdout)) == {"handler", "places", "dumps"}


# --------------------------------------------------------------------------- #
#  What a crash left behind: the lister
# --------------------------------------------------------------------------- #
def _file(path: Path, size: int, when: datetime) -> None:
    path.write_bytes(b"x" * size)
    os.utime(path, (when.timestamp(), when.timestamp()))


@pytest.fixture
def machine(monkeypatch, tmp_path):
    """A machine whose only places are the ones the test makes: no ``/var/crash``, no store, no cores directory."""
    monkeypatch.setattr(G, "_PLACES", ())
    monkeypatch.setattr(G, "_read_pattern", lambda: "core")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return cwd


def test_the_lister_names_each_dump_by_file_size_and_date_under_a_label_and_never_a_path(machine, tmp_path):
    data = tmp_path / "home" / "someone" / "data"
    data.mkdir(parents=True)
    old, new = datetime(2026, 10, 1, 8, 7, 0, tzinfo=UTC), datetime(2026, 10, 4, 8, 7, 12, tzinfo=UTC)
    _file(data / "core", 120, old)
    _file(data / "core.4242", 300, new)
    _file(data / "vgcore.9", 5, old)
    _file(data / "python.core", 7, old)
    _file(data / "notes.txt", 9, new)  # not a dump
    (data / "core.d").mkdir()  # a directory with a dump's name is not one
    (data / "core.link").symlink_to(data / "notes.txt")  # nor is a link, and it is not followed
    got = G.list_core_dumps({"data directory": data})
    names = [d["name"] for d in got["dumps"]]
    assert names == ["core.4242", "core", "python.core", "vgcore.9"] or names[0] == "core.4242"
    assert set(names) == {"core", "core.4242", "vgcore.9", "python.core"}
    by = {d["name"]: d for d in got["dumps"]}
    assert by["core.4242"] == {"where": "data directory", "name": "core.4242", "bytes": 300, "modified": "2026-10-04T08:07:12Z"}
    assert by["core"]["bytes"] == 120 and by["core"]["modified"] == "2026-10-01T08:07:00Z"
    assert [d["modified"] for d in got["dumps"]] == sorted((d["modified"] for d in got["dumps"]), reverse=True), "newest first"
    place = next(p for p in got["places"] if p["where"] == "data directory")
    assert place == {"where": "data directory", "readable": True, "files": 4, "bytes": 120 + 300 + 5 + 7}
    assert str(tmp_path) not in json.dumps(got), "a path names a user and a home"


def test_the_lister_opens_nothing_and_reads_no_content(machine, monkeypatch, tmp_path):
    """MUTATION TARGET. Names, sizes and dates come from the directory entry: a dump holds the passphrase, so no byte of
    one is read, and ``open`` is the only way to read one."""
    data = tmp_path / "data"
    data.mkdir()
    _file(data / "core", 50, datetime(2026, 10, 1, tzinfo=UTC))

    def refuse(*a, **k):
        raise AssertionError("the lister opened a file")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(io, "open", refuse)
    monkeypatch.setattr(os, "open", refuse)
    got = G.list_core_dumps({"data directory": data})
    assert [d["name"] for d in got["dumps"]] == ["core"]


def test_a_directory_that_cannot_be_listed_is_not_readable_and_never_empty(machine, monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    real = os.scandir

    def scandir(path):
        if Path(path) == data:
            raise PermissionError(13, "Permission denied")
        return real(path)

    monkeypatch.setattr(os, "scandir", scandir)
    got = G.list_core_dumps({"data directory": data})
    place = next(p for p in got["places"] if p["where"] == "data directory")
    assert place == {"where": "data directory", "readable": False, "files": 0, "bytes": 0}
    assert any(p["where"] == "working directory" and p["readable"] for p in got["places"]), "the others are still read"


def test_the_directory_a_file_pattern_writes_to_is_listed_and_a_pipe_has_none(machine, monkeypatch, tmp_path):
    cores = tmp_path / "cores"
    cores.mkdir()
    _file(cores / "core.python3.4242", 80, datetime(2026, 10, 3, tzinfo=UTC))
    _file(cores / "unrelated.bin", 80, datetime(2026, 10, 3, tzinfo=UTC))
    monkeypatch.setattr(G, "_read_pattern", lambda: str(cores / "core.%e.%p"))
    got = G.list_core_dumps()
    assert [(d["where"], d["name"]) for d in got["dumps"]] == [("core-pattern directory", "core.python3.4242")]
    monkeypatch.setattr(G, "_read_pattern", lambda: "|/usr/lib/systemd/systemd-coredump %P")
    assert G._pattern_places() == [] and not any(p["where"] == "core-pattern directory" for p in G.list_core_dumps()["places"])
    monkeypatch.setattr(G, "_read_pattern", lambda: "core")  # relative: written where the process ran, not here
    assert G._pattern_places() == [] and not any(p["where"] == "core-pattern directory" for p in G.list_core_dumps()["places"])
    monkeypatch.setattr(G, "_read_pattern", lambda: None)
    assert G._pattern_places() == []


def test_the_places_a_crash_can_leave_a_dump_are_the_four_named_with_the_files_each_holds():
    """MUTATION TARGET: a place dropped from the table. On a machine that has no ``/cores`` the walk below cannot see it go."""
    assert [(label, directory, glob) for label, directory, glob in G._PLACES] == [
        ("crash-report directory", "/var/crash", "*.crash"),
        ("crash-report directory", "/var/crash", "core*"),
        ("systemd-coredump store", "/var/lib/systemd/coredump", "core.*"),
        ("cores directory", "/cores", "core.*"),
    ]


def test_a_pattern_reader_that_raises_does_not_break_the_status(kernel, monkeypatch):
    """MUTATION TARGET: the guard around the handler read in ``status``: it is on every boot record and never the thing that stops
    a boot."""
    def broken():
        raise RuntimeError("the pattern could not be read")

    monkeypatch.setattr(G, "pattern_handler", broken)
    got = G.status()
    assert got["handler"] is None and got["mechanism"] == "none" and got["platform"] == sys.platform


def test_the_places_of_a_real_machine_are_the_labelled_ones_and_only_those_that_exist(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    got = G.list_core_dumps()
    labels = {"working directory", "crash-report directory", "systemd-coredump store", "cores directory",
              "core-pattern directory", "crash-dump directory"}
    assert {p["where"] for p in got["places"]} <= labels
    assert set(got) == {"handler", "places", "dumps"}
    assert all(set(d) == {"where", "name", "bytes", "modified"} for d in got["dumps"])


# --------------------------------------------------------------------------- #
#  The record
# --------------------------------------------------------------------------- #
@pytest.fixture
def ledger(monkeypatch, tmp_path):
    from src.monitoring import session_history as sh

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    # the other boot readings are other tests' business, and resolving them here would leave their state behind
    monkeypatch.setattr(sh, "_boot_memory_budget", lambda: {})
    monkeypatch.setattr(sh, "_boot_allocator", lambda: {})
    monkeypatch.setattr(sh, "_boot_rollup_mode", lambda: "auto")
    sh._reset_for_tests()
    yield sh
    sh._reset_for_tests()


def test_a_boot_record_names_the_guard_this_session_ran_under_compactly(ledger, monkeypatch):
    """MUTATION TARGET. A session that ended in a native crash says whether it could have left a dump."""
    said = {"mechanism": "rlimit", "soft": 1, "hard": 1, "dumpable": 1, "inherited_by_children": True,
            "handler": "systemd-coredump", "platform": "linux"}
    monkeypatch.setattr(G, "status", lambda: dict(said))
    rec = ledger.record_boot(None)
    assert rec["core_guard"] == {k: v for k, v in said.items() if k != "platform"}
    assert ledger.read_records()[0]["core_guard"] == rec["core_guard"], "written to the ledger, not only returned"


def test_a_guard_reading_that_cannot_be_taken_says_so_and_never_breaks_a_boot(ledger, monkeypatch):
    def boom():
        raise RuntimeError("no reading")

    monkeypatch.setattr(G, "status", boom)
    rec = ledger.record_boot(None)
    assert rec["kind"] == "boot" and rec["core_guard"] == {"error": "RuntimeError"}
    assert ledger.read_records()[0]["session_id"] == rec["session_id"]


def test_a_boot_record_carries_the_guard_this_process_really_holds(ledger):
    rec = ledger.record_boot(None)
    assert rec["core_guard"]["mechanism"] in {"rlimit", "dumpable", "none", "unsupported"}
    assert set(rec["core_guard"]) == {"mechanism", "soft", "hard", "dumpable", "inherited_by_children", "handler"}


# --------------------------------------------------------------------------- #
#  The wiring
# --------------------------------------------------------------------------- #
def _source(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_the_server_engages_the_guard_before_anything_else_it_does():
    """MUTATION TARGET. The key of an unlocked store is in this process's memory from the first thing it does: the guard
    comes before the crash trace, the seeding (which opens the store) and the server."""
    serve = python_function_source(_source("src/api/main.py"), "_serve")
    at = serve.index("guard_process()")
    assert at < serve.index("import uvicorn") < serve.index("arm_crash_trace()")
    assert at < serve.index("init_db()") and at < serve.index("uvicorn.run(")
    handler = serve[at:serve.index("arm_crash_trace()")]
    assert "except Exception" in handler, "a guard that cannot be engaged must not stop the app from starting"


def test_a_server_not_started_by_serve_guards_the_process_when_its_lifespan_starts_and_before_the_boot_record():
    """MUTATION TARGET. ``python -m uvicorn src.api.main:app`` (the encrypted click-through's start) never runs ``_serve``, and the
    first thing the lifespan does that can hold a key is the unlock a request brings. The boot record names the mechanism that
    held, so the guard comes before it is written."""
    life = python_function_source(_source("src/api/main.py"), "lifespan")
    at = life.index("guard_process()")
    assert at < life.index("record_session_start()") and at < life.index("capture_previous()")
    assert "except Exception" in life[at:life.index("record_session_start()")], "a guard that cannot be engaged never blocks startup"


def test_the_lifespan_calls_the_guard_before_the_boot_record_when_the_app_really_starts(monkeypatch, tmp_path):
    """The wiring above read off the source, run: the guard is called, and before the boot record is written."""
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.monitoring import forensics
    from src.monitoring import secret_scrub as S

    calls: list[str] = []
    real = forensics.record_session_start
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(S, "guard_process", lambda: calls.append("guard"))
    monkeypatch.setattr(forensics, "record_session_start", lambda *a, **k: (calls.append("boot"), real(*a, **k))[1])
    with TestClient(app):
        pass
    assert "guard" in calls and "boot" in calls and calls.index("guard") < calls.index("boot"), calls


def test_the_store_module_guards_the_process_when_it_comes_to_hold_a_passphrase_and_where_it_hands_a_key_to_the_engine():
    """MUTATION TARGET. The net: at import when the environment hands it one, in ``set_passphrase`` before the key is held, and
    at each place the module gives a key to the engine (a key typed into a request reaches the engine before it is held)."""
    src = _source("src/database/connect.py")
    tree = ast.parse(src)
    read = next(n for n in tree.body if isinstance(n, ast.AnnAssign) and ast.unparse(n.target) == "_passphrase")
    gate = next(n for n in tree.body if isinstance(n, ast.If) and ast.unparse(n.test) == "_passphrase")
    assert gate.lineno > read.lineno and [ast.unparse(s) for s in gate.body] == ["_guard_the_key()"]
    setter = python_function_source(src, "set_passphrase")
    assert setter.index("if p:") < setter.index("_guard_the_key()") < setter.index("_passphrase = p or None")
    body = python_function_source(src, "_guard_the_key")
    assert "from src.monitoring.secret_scrub import guard_process" in body and "suppress(Exception)" in body
    key = python_function_source(src, "_apply_key")
    assert key.index("_guard_the_key()") < key.index("passphrase_bytes(key)") < key.index("PRAGMA key")
    attach = python_function_source(src, "reencrypt_plain_to")
    assert attach.index("_guard_the_key()") < attach.index("passphrase_bytes(key)") < attach.index("ATTACH DATABASE")


def test_the_encrypt_command_guards_the_process_before_it_reads_the_passphrase():
    """MUTATION TARGET. The command line tool reads the passphrase with ``getpass`` and gives it to the whole-corpus export."""
    main = python_function_source(_source("scripts/encrypt_db.py"), "main")
    assert main.index("guard_process()") < main.index("input(") < main.index("getpass.getpass(")


@_POSIX
@_SETTABLE
def test_a_key_typed_into_a_request_is_given_to_the_engine_only_after_the_process_is_held(tmp_path):
    """MUTATION TARGET. The read of the core-limit head (2026-10-06): a server not started by ``_serve`` opens the store with the
    typed key (``connect(path, key=...)``) BEFORE ``set_passphrase`` holds it, and the first engage was in ``set_passphrase``, so
    the key derivation and the open ran under whatever limit the shell gave. Here nothing holds a key at any point: the process
    is only handed one, and is held by the time the engine has it."""
    pytest.importorskip("sqlcipher3")
    body = (
        _STORE
        + f"seen = {{'start': {_LIMIT}}}\n"
        + "orig = c._sql_literal_escape\n"
        + "def spy(value):\n"
        + f"    seen['when_the_engine_had_it'] = {_LIMIT}\n"
        + "    return orig(value)\n"
        + "c._sql_literal_escape = spy\n"
        + "c.connect(os.path.join(os.getcwd(), 'store.db'), key='a typed passphrase').close()\n"
        + f"seen['after'] = {_LIMIT}\n"
        + "seen['held'] = c.get_passphrase()\n"
        + "print(json.dumps(seen))\n"
    )
    out = _json(_child(body, tmp_path))
    assert out["held"] is None, "the key was never held: this is the order a typed key takes before the unlock accepts it"
    assert out["when_the_engine_had_it"] == [1, 1] and out["after"] == [1, 1], out


@_POSIX
@_SETTABLE
def test_the_encrypt_tools_attach_key_is_given_to_the_engine_only_after_the_process_is_held(tmp_path):
    """MUTATION TARGET. ``reencrypt_plain_to`` is handed the key directly, against a plaintext source that no ``PRAGMA key``
    has looked at."""
    pytest.importorskip("sqlcipher3")
    body = (
        _STORE
        + "import sqlite3\n"
        + "plain = os.path.join(os.getcwd(), 'plain.db')\n"
        + "k = sqlite3.connect(plain); k.execute('CREATE TABLE t(x)'); k.commit(); k.close()\n"
        + f"start = {_LIMIT}\n"
        + "c.reencrypt_plain_to(plain, os.path.join(os.getcwd(), 'enc.db'), 'a typed passphrase')\n"
        + f"print(json.dumps({{'start': start, 'after': {_LIMIT}, 'held': c.get_passphrase()}}))\n"
    )
    out = _json(_child(body, tmp_path))
    assert out["held"] is None and out["after"] == [1, 1], out


def test_the_restore_child_engages_the_guard_before_it_reads_the_passphrase():
    main = python_function_source(_source("src/monitoring/release_run_fresh_restore.py"), "main")
    assert main.index("engage()") < main.index('env_secret("OO_DB_PASSPHRASE")')


def test_the_osm_reference_run_requires_the_inherited_limit_before_the_run_reads_the_passphrase():
    main = python_function_source(_source("scripts/osm_reference_run.py"), "main")
    assert main.index("engage(strict=True)") < main.index("R.run(")
    assert "except CoreGuardError" in main and "refused: core dumps cannot be limited" in main


def test_the_guard_imports_nothing_but_the_standard_library_and_never_the_store():
    """It is the first call an entry point makes and ``connect`` calls it: a third-party import here would run before the
    guard, and an import of the store would be a cycle."""
    tree = ast.parse(Path(G.__file__).read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
    assert names <= set(sys.stdlib_module_names), sorted(names - set(sys.stdlib_module_names))


def test_no_launcher_sets_a_core_limit_of_its_own_and_nothing_offers_an_opt_out():
    """A shell cannot set the one value that works (bash's ``ulimit -c 1`` is 1024 bytes, dash's 512), and a ``ulimit -c 0``
    in a launcher makes the in-process call fail for ever. An opt-out would be a way to turn the protection off that the
    people it protects would never find."""
    launchers = [*(_ROOT / "scripts").glob("*.sh"), *(_ROOT / "scripts").glob("*.cmd"), *_ROOT.glob("install*.sh"),
                 *_ROOT.glob("install*.ps1"), *_ROOT.glob("*.desktop")]
    assert launchers, "the launchers were not found"
    offenders = [p.name for p in launchers if re.search(r"\bulimit\s+(-\w*c\w*|-\w+\s+-c)\b|LimitCORE", p.read_text(encoding="utf-8"))]
    assert not offenders, f"a launcher sets a core limit: {offenders}"
    named = []
    for base in (_ROOT / "src", _ROOT / "scripts"):
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in {".py", ".sh", ".cmd", ".ps1", ".js"}:
                named += [f"{p.relative_to(_ROOT)}: {m}" for m in re.findall(r"OO_[A-Z_]*CORE[A-Z_]*", p.read_text(encoding="utf-8", errors="ignore"))]
    assert not named, f"an environment variable that could switch the guard off: {named}"
